"""Expert registry — discovers installed experts and exposes runtime lookups.

The registry has three discovery paths, run in order on startup:

1. **Internal experts** — packages bundled with pearscarf itself
   (e.g. `pearscarf.records`). Always registered, no DB row, no install
   pipeline. The list lives in `_INTERNAL_EXPERTS` below.
2. **DB-registered experts** — operator-installed experts whose rows
   live in the `experts` table. Resolved by `importlib` from the package
   name in each row.
3. **Filesystem experts** — fallback when the DB has no rows; scans
   `<repo>/experts/` for subdirectories with `manifest.yaml`.

The registry then serves the runtime needs of the indexer:

* `get(source_type)` / `get_by_record_type(record_type)` — find the expert
  responsible for a given source or record type
* `core_prompt()` — Layer 1 of the extraction prompt (cached)
* `schema_fragment()` — Layer 2 entity types, including any new types
  declared by registered experts (cached)
* `agent_factory(expert_name)` — placeholder for the LLM agent factory,
  wired up in a follow-up

Discovery happens on first use of `get_registry()` and the result is
held in a module-level singleton for the lifetime of the process.
"""

from __future__ import annotations

import importlib
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

# Internal experts bundled with pearscarf itself. These are always
# registered on startup, regardless of DB state. They have no row in
# the `experts` table and don't go through the install pipeline.
_INTERNAL_EXPERTS: tuple[str, ...] = ("pearscarf.records",)


@dataclass
class Expert:
    """An installed expert package, materialised from its manifest."""

    name: str
    version: str
    source_type: str
    description: str
    path: Path
    knowledge_dir: Path | None
    extraction_path: Path | None
    ingester_path: Path | None
    ingester_module: str
    tools_module: str = ""
    new_entity_types: list[dict] = field(default_factory=list)
    record_types: list[str] = field(default_factory=list)
    enabled: bool = True
    relevancy_check: str = ""  # "skip" | "required" | "" (not declared)

    def start(self, ctx: Any) -> threading.Thread | None:
        """Import the ingester entry point and call its start(ctx).

        Returns whatever the module returns — typically a polling thread,
        or None if no ingester is declared.
        """
        if not self.ingester_module:
            return None
        module = importlib.import_module(self.ingester_module)
        start_fn = getattr(module, "start", None)
        if start_fn is None:
            return None
        return start_fn(ctx)


class Registry:
    """In-memory expert registry. Built once by scanning experts/."""

    def __init__(self, experts_dir: Path) -> None:
        self._experts_dir = experts_dir
        self._by_source: dict[str, Expert] = {}
        self._by_name: dict[str, Expert] = {}
        self._by_record_type: dict[str, Expert] = {}
        self._connects: dict[str, Any] = {}
        # Python module path for each internal expert, resolved during
        # `_load_internal`. Used by startup to importlib-load the package
        # and call its `get_handler(ctx)` factory. Presence in this map
        # means the expert is internal; absence means it's external.
        self._internal_packages: dict[str, str] = {}
        self._core_cache: dict[str, str] | None = None
        self._schema_cache: str | None = None
        self._load()

    # --- Discovery ---

    def _load(self) -> None:
        """Load experts. Internal first; then DB rows, falling back to filesystem."""
        self._load_internal()
        rows = self._db_rows()
        if rows:
            self._load_from_db(rows)
            return
        self._load_from_filesystem()

    def _load_internal(self) -> None:
        """Register internal experts bundled with pearscarf core.

        These have no `experts` row and don't go through `psc install`.
        Manifest lives at `<package>/manifest.yaml`; package is resolved
        via importlib so editable / installed pearscarf both work.
        """
        import importlib.util

        for package_name in _INTERNAL_EXPERTS:
            try:
                spec = importlib.util.find_spec(package_name)
            except Exception as exc:  # noqa: BLE001
                print(f"[registry] internal {package_name}: find_spec failed: {exc}")
                continue
            if not spec or not spec.submodule_search_locations:
                print(f"[registry] internal {package_name}: package not found")
                continue

            package_dir = Path(next(iter(spec.submodule_search_locations)))
            manifest_path = package_dir / "manifest.yaml"
            if not manifest_path.is_file():
                print(f"[registry] internal {package_name}: manifest missing at {manifest_path}")
                continue

            try:
                expert = self._parse_manifest(package_dir, manifest_path)
            except Exception as exc:  # noqa: BLE001
                print(f"[registry] internal {package_name}: failed to parse manifest: {exc}")
                continue

            self._register(expert)
            self._internal_packages[expert.name] = package_name

    def _db_rows(self) -> list[dict]:
        """Return enabled expert rows from the DB. Empty list on any failure.

        Disabled rows are historical — only one row per name is enabled
        at a time, and that's the one the registry loads.
        """
        try:
            from pearscarf.storage.store import list_registered_experts

            return list_registered_experts(enabled_only=True)
        except Exception:
            # DB unavailable or schema not yet migrated — fall back to scan.
            return []

    def _load_from_db(self, rows: list[dict]) -> None:
        """Load each registered expert by resolving its package via importlib."""
        import importlib.util

        for row in rows:
            package_name = row["package_name"]
            try:
                spec = importlib.util.find_spec(package_name)
            except Exception as exc:
                print(f"[registry] {row['name']}: find_spec failed: {exc}")
                continue
            if not spec or not spec.submodule_search_locations:
                print(f"[registry] {row['name']}: package '{package_name}' not found")
                continue

            package_dir = Path(next(iter(spec.submodule_search_locations)))
            manifest_path = package_dir / "manifest.yaml"
            if not manifest_path.is_file():
                print(f"[registry] {row['name']}: manifest missing at {manifest_path}")
                continue

            try:
                expert = self._parse_manifest(package_dir, manifest_path)
            except Exception as exc:  # noqa: BLE001
                print(f"[registry] {row['name']}: failed to parse manifest: {exc}")
                continue

            expert.enabled = bool(row.get("enabled", True))
            self._register(expert)

    def _load_from_filesystem(self) -> None:
        """Scan experts/ for subdirs containing manifest.yaml."""
        if not self._experts_dir.is_dir():
            return
        for child in sorted(self._experts_dir.iterdir()):
            if not child.is_dir():
                continue
            manifest_path = child / "manifest.yaml"
            if not manifest_path.is_file():
                continue
            try:
                expert = self._parse_manifest(child, manifest_path)
            except Exception as exc:  # noqa: BLE001
                # Bad manifest — skip the package, don't crash startup
                print(f"[registry] failed to load {child.name}: {exc}")
                continue
            self._register(expert)

    def _parse_manifest(self, package_dir: Path, manifest_path: Path) -> Expert:
        data: dict[str, Any] = yaml.safe_load(manifest_path.read_text()) or {}

        name = data.get("name")
        source_type = data.get("source_type")
        if not name or not source_type:
            raise ValueError("manifest missing required field: name or source_type")

        # All paths come from the manifest. No conventions. Each path is
        # relative to the package dir; absent means the expert doesn't have it.
        knowledge_dir = self._resolve_path(package_dir, data.get("knowledge"))
        extraction_path = self._resolve_path(package_dir, data.get("extraction"), must_exist=True)
        ingester_path = self._resolve_path(package_dir, data.get("ingester"))

        ingester_module = self._module_for(name, data.get("ingester"))
        tools_module = self._module_for(name, data.get("tools"))

        return Expert(
            name=str(name),
            version=str(data.get("version", "0.0.0")),
            source_type=str(source_type),
            description=str(data.get("description", "")),
            path=package_dir,
            knowledge_dir=knowledge_dir,
            extraction_path=extraction_path,
            ingester_path=ingester_path,
            ingester_module=ingester_module,
            tools_module=tools_module,
            new_entity_types=list(data.get("new_entity_types") or []),
            record_types=[str(rt) for rt in (data.get("record_types") or [])],
            relevancy_check=str(data.get("relevancy_check") or ""),
        )

    @staticmethod
    def _resolve_path(
        package_dir: Path, rel: str | None, *, must_exist: bool = False
    ) -> Path | None:
        """Resolve a manifest-declared relative path against the package dir.

        When `must_exist` is True, returns None if the resolved path doesn't
        point at a file on disk — used for entries (e.g. `extraction`) that
        downstream consumers treat as "present iff non-None."
        """
        if not rel:
            return None
        resolved = (package_dir / rel).resolve()
        if must_exist and not resolved.is_file():
            return None
        return resolved

    @staticmethod
    def _module_for(name: str, rel: str | None) -> str:
        """Compute the dotted Python module path for a manifest entry-point file."""
        if not rel:
            return ""
        no_ext = Path(rel).with_suffix("")
        return f"{name}." + no_ext.as_posix().replace("/", ".")

    def _register(self, expert: Expert) -> None:
        self._by_source[expert.source_type] = expert
        self._by_name[expert.name] = expert
        for rt in expert.record_types:
            self._by_record_type[rt] = expert

    # --- Public lookups ---

    def get(self, source_type: str) -> Expert | None:
        """Find an expert by its source_type (e.g. 'gmail')."""
        return self._by_source.get(source_type)

    def get_by_name(self, name: str) -> Expert | None:
        """Find an expert by its package name (e.g. 'gmailscarf')."""
        return self._by_name.get(name)

    def get_by_record_type(self, record_type: str) -> Expert | None:
        """Find the expert that owns a given record type (e.g. 'email' → gmailscarf)."""
        return self._by_record_type.get(record_type)

    def all(self) -> list[Expert]:
        """All registered experts, sorted by name."""
        return [self._by_name[n] for n in sorted(self._by_name)]

    def enabled_experts(self) -> list[Expert]:
        """Experts that should be started by `pearscarf run`.

        Filters by the `enabled` flag. Filesystem-loaded experts default
        to enabled=True; DB-loaded experts honor the `enabled` column on
        the experts table.
        """
        return [e for e in self.all() if e.enabled]

    # --- Connect cache ---

    def register_connect(self, record_type: str, connect: Any) -> None:
        """Cache a connect instance by record_type.

        Called at startup after loading each expert's tools module.
        The ingest tool looks up connects by record_type to delegate
        record processing to the right expert.
        """
        self._connects[record_type] = connect

    def get_connect(self, record_type: str) -> Any | None:
        """Look up the cached connect instance for a record_type."""
        return self._connects.get(record_type)

    def internal_package(self, expert_name: str) -> str | None:
        """Python module path if `expert_name` is an internal expert, else None.

        Resolved during `_load_internal` from `_INTERNAL_EXPERTS`. Startup
        uses this to import the package and call its `get_handler(ctx)`
        factory; absence means the expert is external (its lifecycle is
        the polling-Consumer / agent-bot path, not push-driven init).
        """
        return self._internal_packages.get(expert_name)

    # --- Prompt assembly ---

    def _core_parts(self) -> dict[str, str]:
        """Load core prompt components. Cached on first call."""
        if self._core_cache is None:
            from pearscarf.knowledge import KNOWLEDGE_DIR

            core = KNOWLEDGE_DIR / "core"
            self._core_cache = {
                "intro": (core / "extraction.md").read_text(),
                "normalization": (core / "normalization.md").read_text(),
                "fact_structure": (core / "fact_structure.md").read_text(),
                "fact_labels": "## Fact Edge Labels\n\n" + (core / "facts.md").read_text(),
                "ignore": (core / "ignore.md").read_text(),
                "output_format": (core / "output_format.md").read_text(),
            }
        return self._core_cache

    def schema_fragment(self) -> str:
        """Entity type definitions + normalization rules.

        Reads base entity types from pearscarf/knowledge/core/entities/
        plus any types declared by installed experts. Appends entity
        normalization rules so "what to look for" and "how to name them"
        are together.
        """
        if self._schema_cache is None:
            from pearscarf.knowledge import KNOWLEDGE_DIR

            entities_dir = KNOWLEDGE_DIR / "core" / "entities"
            parts: list[str] = ["## Entity Types\n"]
            for entity_file in sorted(entities_dir.glob("*.md")):
                parts.append(entity_file.read_text())

            for expert in self.all():
                if expert.knowledge_dir is None:
                    continue
                for entry in expert.new_entity_types:
                    type_name = entry.get("name") if isinstance(entry, dict) else None
                    if not type_name:
                        continue
                    md_path = expert.knowledge_dir / "entities" / f"{type_name.lower()}.md"
                    if md_path.is_file():
                        parts.append(md_path.read_text())

            # Deployment-vocab entity types — declared per-deployment in
            # vocab.yaml (loaded via DEPLOYMENT_VOCAB_PATH). Rendered with
            # the same `**name**\n<description>` shape as core / expert
            # entity files. Empty vocab (no DEPLOYMENT_VOCAB_PATH) is a
            # no-op — backward-compatible with deployments that don't set it.
            from pearscarf.deployment_vocab import get_vocab

            for vt in get_vocab().entity_types:
                desc = (vt.description or "").strip()
                parts.append(f"**{vt.name}**\n{desc}\n" if desc else f"**{vt.name}**\n")

            # Normalization follows entity types
            parts.append(self._core_parts()["normalization"])

            self._schema_cache = "\n".join(parts)
        return self._schema_cache

    # --- Extraction prompt composition ---

    def compose_prompt(self, record: dict) -> str:
        """Compose the extraction system prompt for a given record.

        Order:
            1. Intro
            2. Entity types + normalization
            3. Fact structure
            4. Fact edge labels
            5. What to ignore
            6. Output format
            7. Source-specific guidance (expert's extraction.md)
        """
        from pearscarf.knowledge import load

        record_type = record.get("type", "")

        if record_type == "ingest":
            template = load("seed_guidance")
            return template.replace(
                "{{deployment_entity_sections}}",
                self._render_deployment_section_seed(),
            )

        core = self._core_parts()
        parts: list[str] = [
            core["intro"],
            self.schema_fragment(),
            core["fact_structure"],
            core["fact_labels"],
            core["ignore"],
            core["output_format"],
        ]

        expert = self.get_by_record_type(record_type)
        if expert and expert.extraction_path is not None:
            parts.append(expert.extraction_path.read_text())

        return "\n\n".join(parts)

    # --- Deployment-vocab prompt rendering ---

    def _render_deployment_section_seed(self) -> str:
        """Render the deployment-vocab entity-type sections for seed prompts.

        Replaces the `{{deployment_entity_sections}}` placeholder in
        `seed_guidance.md`. Produces one bullet per declared entity type;
        the bullet names the corresponding `## <plural>` section the
        operator's seed file is expected to use. Returns the empty string
        when no deployment vocab is loaded — backward-compatible with
        deployments that don't set `DEPLOYMENT_VOCAB_PATH`.
        """
        from pearscarf.deployment_vocab import get_vocab

        types = get_vocab().entity_types
        if not types:
            return ""
        lines = []
        for t in types:
            desc = f" — {t.description.strip()}" if t.description else ""
            lines.append(
                f"**`## {t.section_name}`** — one `{t.name}` per line: "
                f"`name | description`. Each line creates a `{t.name}` "
                f"entity (Neo4j label `:{t.name[0].upper() + t.name[1:]}`)"
                f"{desc}"
            )
        return "\n".join(lines)

    # --- Future hook ---

    def agent_factory(self, expert_name: str) -> Callable | None:
        """Return a callable that creates the LLM agent for an expert.

        Placeholder — wired up in a follow-up that introduces
        registry-driven CLI startup. Returns None today.
        """
        return None


# --- Module-level singleton ---


_registry: Registry | None = None


def get_registry() -> Registry:
    """Return the process-wide registry, building it on first call."""
    global _registry
    if _registry is None:
        from pearscarf.config import EXPERTS_DIR

        _registry = Registry(Path(EXPERTS_DIR))
    return _registry


def reset_registry() -> None:
    """Drop the cached registry. Used by tests that need a clean slate."""
    global _registry, _base_entity_types_cache
    _registry = None
    _base_entity_types_cache = None


def compose_prompt(record: dict) -> str:
    """Convenience: delegates to the process-wide registry."""
    return get_registry().compose_prompt(record)


# --- Base entity types (Layer 2 source of truth) ---


_base_entity_types_cache: set[str] | None = None


def base_entity_types() -> set[str]:
    """Lowercased base entity type names declared by core/entities/*.md.

    The file set is static after startup, so the result is cached for the
    process lifetime. `reset_registry()` clears the cache.
    """
    global _base_entity_types_cache
    if _base_entity_types_cache is None:
        from pearscarf.knowledge import KNOWLEDGE_DIR

        entities_dir = KNOWLEDGE_DIR / "core" / "entities"
        _base_entity_types_cache = {p.stem.lower() for p in entities_dir.glob("*.md")}
    return _base_entity_types_cache
