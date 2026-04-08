"""Expert install command — discovery, validation, DB writes, scaffolding.

Implements `pearscarf install <source>`, `pearscarf expert list`, and
`pearscarf expert inspect <name>`. The install command runs an 8-stage
validation pipeline before writing any DB rows; if any blocking stage
fails, nothing is registered.

Source detection follows the rules from the architecture spec:

    ./local-path        → local   (no pip — package must already be on sys.path)
    git+https://...     → git     (pip install git+...)
    https://github.com  → git     (pip install git+https://...)
    bare-name           → pypi    (pip install bare-name)
"""

from __future__ import annotations

import importlib
import importlib.metadata
import importlib.util
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import click
import yaml

from pearscarf.indexing.registry import base_entity_types
from pearscarf.storage import store


# --- Source detection ---


@dataclass
class InstallSource:
    method: str  # "local" | "git" | "pypi"
    raw: str
    pip_arg: str | None = None  # what to pass to pip; None for local
    local_path: Path | None = None  # set when method == "local"


def detect_source(source: str) -> InstallSource:
    """Classify an install source string into local / git / pypi."""
    s = source.strip()

    # Local path
    if s.startswith("./") or s.startswith("../") or s.startswith("~/") or s.startswith("/"):
        return InstallSource(
            method="local",
            raw=source,
            local_path=Path(s).expanduser().resolve(),
        )

    # Git URL with explicit prefix
    if s.startswith("git+"):
        return InstallSource(method="git", raw=source, pip_arg=s)

    # GitHub URL without prefix
    if "github.com" in s:
        return InstallSource(method="git", raw=source, pip_arg=f"git+{s}")

    # PyPI bare name
    return InstallSource(method="pypi", raw=source, pip_arg=s)


# --- Validation pipeline ---


@dataclass
class ValidationContext:
    source: InstallSource
    package_name: str = ""
    package_dir: Path | None = None
    manifest: dict = field(default_factory=dict)
    failures: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    pip_installed: bool = False  # True iff Stage 1 actually ran pip install successfully


@dataclass
class StageResult:
    ok: bool
    message: str = ""
    blocking: bool = True


def _stage(name: str) -> None:
    click.echo(click.style(f"  → {name}", fg="cyan"))


def _ok(detail: str = "") -> StageResult:
    if detail:
        click.echo(click.style(f"    ok — {detail}", fg="green"))
    else:
        click.echo(click.style("    ok", fg="green"))
    return StageResult(ok=True)


def _fail(detail: str, blocking: bool = True) -> StageResult:
    color = "red" if blocking else "yellow"
    label = "fail" if blocking else "warn"
    click.echo(click.style(f"    {label} — {detail}", fg=color))
    return StageResult(ok=False, message=detail, blocking=blocking)


def stage_pip_install(ctx: ValidationContext) -> StageResult:
    _stage("Stage 1 — pip install")
    if ctx.source.method == "local":
        # Local installs don't go through pip — the package must already be on
        # sys.path (typically because it lives under experts/, which pearscarf
        # adds to sys.path on startup).
        return _ok("local — pip skipped")

    cmd = [sys.executable, "-m", "pip", "install", ctx.source.pip_arg]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        return _fail(f"pip install failed:\n{proc.stderr.strip()}")
    ctx.pip_installed = True
    return _ok("pip install succeeded")


def stage_locate_package(ctx: ValidationContext) -> StageResult:
    _stage("Stage 2 — package locatable")

    if ctx.source.method == "local":
        # For local installs we trust the path. The package_name is taken from
        # the manifest (in stage 3) — for now we just verify the directory
        # exists and stash it on the context.
        path = ctx.source.local_path
        if path is None or not path.is_dir():
            return _fail(f"local path is not a directory: {ctx.source.raw}")
        ctx.package_dir = path
        # Provisional name from directory; refined in stage 3 from the manifest.
        ctx.package_name = path.name
        return _ok(f"local path resolved → {path}")

    # pip-installed: use importlib.metadata to find the package
    name_guess = ctx.source.raw.split("/")[-1].split("@")[0]
    if name_guess.startswith("git+"):
        name_guess = name_guess.replace("git+", "")
    try:
        dist = importlib.metadata.distribution(name_guess)
    except importlib.metadata.PackageNotFoundError:
        return _fail(
            f"package '{name_guess}' not found via importlib.metadata. "
            f"Did pip install actually deliver this package?"
        )

    ctx.package_name = dist.metadata["Name"]
    spec = importlib.util.find_spec(ctx.package_name)
    if not spec or not spec.submodule_search_locations:
        return _fail(f"package '{ctx.package_name}' has no importable directory")
    ctx.package_dir = Path(next(iter(spec.submodule_search_locations)))
    return _ok(f"package '{ctx.package_name}' at {ctx.package_dir}")


_SEMVER = re.compile(r"^\d+\.\d+\.\d+$")


def stage_manifest(ctx: ValidationContext) -> StageResult:
    _stage("Stage 3 — manifest valid")
    assert ctx.package_dir is not None

    manifest_path = ctx.package_dir / "manifest.yaml"
    if not manifest_path.is_file():
        return _fail(f"manifest.yaml missing at {manifest_path}")

    try:
        data = yaml.safe_load(manifest_path.read_text()) or {}
    except yaml.YAMLError as exc:
        return _fail(f"manifest.yaml not valid YAML: {exc}")

    required = ["name", "version", "source_type", "record_types", "connector"]
    missing = [f for f in required if not data.get(f)]
    if missing:
        return _fail(f"manifest missing required field(s): {', '.join(missing)}")

    name = data["name"]
    version = data["version"]
    record_types = data["record_types"]

    if not _SEMVER.match(str(version)):
        return _fail(f"manifest version '{version}' is not semver X.Y.Z")

    # name should match the directory name (local) or the dist name (pip)
    if name != ctx.package_name:
        return _fail(
            f"manifest name '{name}' does not match package name '{ctx.package_name}'"
        )

    if not isinstance(record_types, list) or not record_types:
        return _fail("manifest record_types must be a non-empty list")
    if not all(isinstance(rt, str) and rt for rt in record_types):
        return _fail("manifest record_types must contain non-empty strings")

    ctx.manifest = data
    return _ok(f"name={name} version={version} source_type={data['source_type']}")


def _check_file_nonempty(path: Path, label: str) -> str | None:
    if not path.is_file():
        return f"{label} missing at {path}"
    if path.stat().st_size == 0:
        return f"{label} is empty"
    return None


def stage_knowledge(ctx: ValidationContext) -> StageResult:
    _stage("Stage 4 — knowledge contract")
    assert ctx.package_dir is not None
    knowledge = ctx.package_dir / "knowledge"

    for label, rel in [("knowledge/extraction.md", "extraction.md"),
                        ("knowledge/agent.md", "agent.md")]:
        err = _check_file_nonempty(knowledge / rel, label)
        if err:
            return _fail(err)

    for entry in ctx.manifest.get("new_entity_types") or []:
        if isinstance(entry, dict):
            type_name = entry.get("name")
        else:
            type_name = entry
        if not type_name:
            return _fail("new_entity_types entry missing 'name'")
        err = _check_file_nonempty(
            knowledge / "entities" / f"{type_name.lower()}.md",
            f"knowledge/entities/{type_name.lower()}.md",
        )
        if err:
            return _fail(err)

    return _ok("agent.md, extraction.md, and entity files present")


def stage_connector(ctx: ValidationContext) -> StageResult:
    _stage("Stage 5 — connector contract")
    assert ctx.package_dir is not None

    connector_rel = ctx.manifest.get("connector", "connector/agent.py")
    connector_path = ctx.package_dir / connector_rel
    if not connector_path.is_file():
        return _fail(f"connector file missing at {connector_path}")

    # Derive module name from package + connector relative path
    module_no_ext = Path(connector_rel).with_suffix("")
    module_name = f"{ctx.package_name}." + module_no_ext.as_posix().replace("/", ".")

    try:
        module = importlib.import_module(module_name)
    except Exception as exc:  # noqa: BLE001
        return _fail(f"connector import failed: {exc}")

    start_fn = getattr(module, "start", None)
    if start_fn is None or not callable(start_fn):
        return _fail(f"{module_name} has no callable start function")

    return _ok(f"{module_name}.start is callable")


def stage_conflicts(ctx: ValidationContext) -> StageResult:
    _stage("Stage 6 — conflict checks")

    source_type = ctx.manifest["source_type"]
    name = ctx.manifest["name"]
    record_types = ctx.manifest["record_types"]

    installed = store.list_registered_experts()
    others = [e for e in installed if e["name"] != name]

    for e in others:
        if e["source_type"] == source_type:
            return _fail(
                f"source_type '{source_type}' already registered by '{e['name']}'"
            )

    # Build record_type → expert map for collision check
    rt_map: dict[str, str] = {}
    for e in others:
        for rt in store.list_entity_types_for_expert(e["name"]):
            pass  # entity types — checked separately below
        # Need record_types per other expert; refetch from their manifest via importlib
        spec = importlib.util.find_spec(e["package_name"])
        if spec and spec.submodule_search_locations:
            other_dir = Path(next(iter(spec.submodule_search_locations)))
            other_manifest = other_dir / "manifest.yaml"
            if other_manifest.is_file():
                try:
                    other_data = yaml.safe_load(other_manifest.read_text()) or {}
                    for rt in other_data.get("record_types") or []:
                        rt_map[rt] = e["name"]
                except yaml.YAMLError:
                    pass

    for rt in record_types:
        if rt in rt_map:
            return _fail(
                f"record_type '{rt}' already claimed by '{rt_map[rt]}'"
            )

    # New entity type collisions: against base types and against installed entity types
    existing_entity_types: set[str] = set()
    for et in store.list_all_entity_types():
        if et["expert_name"] == name:
            continue  # this expert's own previous registration — allowed (upsert)
        existing_entity_types.add(et["type_name"].lower())

    base_types = base_entity_types()
    for entry in ctx.manifest.get("new_entity_types") or []:
        type_name = entry.get("name") if isinstance(entry, dict) else entry
        if not type_name:
            continue
        lower = type_name.lower()
        if lower in base_types:
            return _fail(
                f"new_entity_type '{type_name}' collides with base entity type"
            )
        if lower in existing_entity_types:
            return _fail(
                f"new_entity_type '{type_name}' collides with an installed entity type"
            )

    return _ok("no conflicts")


def stage_identifier_patterns(ctx: ValidationContext) -> StageResult:
    _stage("Stage 7 — identifier patterns")

    declared_types = {
        (entry.get("name") if isinstance(entry, dict) else entry).lower()
        for entry in (ctx.manifest.get("new_entity_types") or [])
        if entry
    }
    valid_types = base_entity_types() | declared_types

    for entry in ctx.manifest.get("identifier_patterns") or []:
        if not isinstance(entry, dict):
            return _fail(f"identifier_patterns entry must be a mapping: {entry!r}")

        has_pattern = bool(entry.get("pattern"))
        has_field = bool(entry.get("field"))
        if has_pattern == has_field:
            return _fail(
                f"identifier pattern must declare exactly one of 'pattern' or 'field': {entry!r}"
            )

        if has_pattern:
            try:
                re.compile(entry["pattern"])
            except re.error as exc:
                return _fail(f"identifier pattern regex invalid: {exc}")

        entity_type = (entry.get("entity_type") or "").lower()
        if entity_type not in valid_types:
            return _fail(
                f"identifier pattern entity_type '{entry.get('entity_type')}' "
                f"is neither a base type nor declared by this expert"
            )

        scope = entry.get("scope")
        if scope not in ("global", "source"):
            return _fail(f"identifier pattern scope must be 'global' or 'source', got '{scope}'")

    return _ok("identifier patterns valid")


def stage_eval(ctx: ValidationContext) -> StageResult:
    _stage("Stage 8 — eval dataset (non-blocking)")
    assert ctx.package_dir is not None
    eval_dir = ctx.package_dir / "eval"

    missing = []
    for rel in ["seed.md", "ground_truth.json", "data"]:
        if not (eval_dir / rel).exists():
            missing.append(f"eval/{rel}")
    if missing:
        return _fail(f"missing: {', '.join(missing)}", blocking=False)
    return _ok("eval dataset present")


_STAGES = [
    stage_pip_install,
    stage_locate_package,
    stage_manifest,
    stage_knowledge,
    stage_connector,
    stage_conflicts,
    stage_identifier_patterns,
    stage_eval,
]


def run_validation(source: InstallSource) -> ValidationContext:
    """Run all 8 stages. Always returns the context — check `ctx.failures`.

    The context is returned even on failure so callers can inspect
    `ctx.pip_installed` to decide whether to roll back the pip step.
    """
    ctx = ValidationContext(source=source)
    for stage in _STAGES:
        result = stage(ctx)
        if not result.ok:
            if result.blocking:
                ctx.failures.append(result.message)
                return ctx
            ctx.warnings.append(result.message)
    return ctx


def _guess_package_name(source: InstallSource) -> str:
    """Best-effort name extraction for rollback when stage 2 didn't get to set it."""
    if source.method == "local":
        return ""
    raw = source.raw
    if raw.startswith("git+"):
        raw = raw[4:]
    return raw.split("/")[-1].split("@")[0].replace(".git", "")


def rollback_pip_install(ctx: ValidationContext) -> None:
    """Run `pip uninstall -y` if Stage 1 successfully installed the package.

    No-op for local installs and for pip installs that never reached the
    success branch of Stage 1. Print rollback status either way so the
    operator knows what state the env is in.
    """
    if not ctx.pip_installed:
        return

    package = ctx.package_name or _guess_package_name(ctx.source)
    if not package:
        click.echo(click.style(
            "  rollback skipped: could not determine package name to uninstall",
            fg="yellow",
        ))
        return

    click.echo()
    click.echo(click.style(f"  rolling back: pip uninstall {package}", fg="yellow"))
    proc = subprocess.run(
        [sys.executable, "-m", "pip", "uninstall", "-y", package],
        capture_output=True,
        text=True,
    )
    if proc.returncode == 0:
        click.echo(click.style(f"  uninstalled {package}", fg="yellow"))
    else:
        click.echo(click.style(
            f"  pip uninstall failed: {proc.stderr.strip()}",
            fg="red",
        ))


# --- DB writes + scaffolding ---


def _resolve_install_method(source: InstallSource) -> str:
    return source.method  # "local" | "git" | "pypi"


def write_registration(ctx: ValidationContext) -> None:
    """Write expert + entity_types + identifier_patterns rows in one transaction."""
    entity_types: list[dict] = []
    for entry in ctx.manifest.get("new_entity_types") or []:
        type_name = entry.get("name") if isinstance(entry, dict) else entry
        if not type_name:
            continue
        entity_types.append({
            "type_name": type_name,
            "knowledge_path": f"knowledge/entities/{type_name.lower()}.md",
        })

    identifier_patterns: list[dict] = []
    for entry in ctx.manifest.get("identifier_patterns") or []:
        identifier_patterns.append({
            "pattern_or_field": entry.get("pattern") or entry.get("field") or "",
            "entity_type": entry["entity_type"],
            "scope": entry["scope"],
        })

    store.write_full_registration(
        name=ctx.manifest["name"],
        version=ctx.manifest["version"],
        source_type=ctx.manifest["source_type"],
        package_name=ctx.package_name,
        install_method=_resolve_install_method(ctx.source),
        enabled=True,
        entity_types=entity_types,
        identifier_patterns=identifier_patterns,
    )


_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_ENV_DIR = _REPO_ROOT / "env"
_GITIGNORE = _REPO_ROOT / ".gitignore"


def scaffold_credentials(ctx: ValidationContext) -> Path | None:
    """Copy <package>/.env.example → env/.<name>.env. Returns target path or None."""
    assert ctx.package_dir is not None
    example = ctx.package_dir / ".env.example"
    if not example.is_file():
        return None

    _ENV_DIR.mkdir(exist_ok=True)
    target = _ENV_DIR / f".{ctx.manifest['name']}.env"
    if target.exists():
        click.echo(f"  credentials file already exists at {target} — left untouched")
        return target

    shutil.copy2(example, target)

    # Make sure env/ is gitignored
    if _GITIGNORE.is_file():
        gi = _GITIGNORE.read_text()
        if "env/" not in gi.split("\n"):
            with _GITIGNORE.open("a") as f:
                if not gi.endswith("\n"):
                    f.write("\n")
                f.write("env/\n")

    click.echo(click.style(f"  credentials scaffolded → {target}", fg="green"))
    click.echo(f"  edit this file before starting the expert.")
    return target


def prompt_entity_type_approval(
    ctx: ValidationContext, assume_yes: bool
) -> bool:
    """If the manifest declares new entity types, ask the operator to approve."""
    new_types = [
        (entry.get("name") if isinstance(entry, dict) else entry)
        for entry in (ctx.manifest.get("new_entity_types") or [])
    ]
    new_types = [t for t in new_types if t]
    if not new_types:
        return True

    click.echo()
    click.echo(click.style("New entity types declared by this expert:", fg="yellow"))
    for t in new_types:
        click.echo(f"  • {t}")
    click.echo(
        "These types will be added to the world schema and become available "
        "to every expert. This decision affects all future installs."
    )

    if assume_yes:
        click.echo("  --yes/-y supplied; accepting without prompt.")
        return True

    return click.confirm("Approve adding these entity types?", default=False)


# --- Click commands ---


@click.command("install")
@click.argument("source")
@click.option("-y", "--yes", "assume_yes", is_flag=True, default=False,
              help="Skip the new entity types approval prompt (for non-interactive installs)")
def install_command(source: str, assume_yes: bool) -> None:
    """Install an expert from a local path, git URL, or PyPI name."""
    src = detect_source(source)
    click.echo(f"Installing from {click.style(src.method, fg='cyan')}: {src.raw}\n")

    ctx = run_validation(src)

    if ctx.failures:
        rollback_pip_install(ctx)
        click.echo()
        click.echo(click.style("Install failed.", fg="red"))
        raise SystemExit(1)

    if not prompt_entity_type_approval(ctx, assume_yes):
        rollback_pip_install(ctx)
        click.echo(click.style("Install cancelled — entity types not approved.", fg="red"))
        raise SystemExit(1)

    try:
        write_registration(ctx)
    except Exception as exc:
        rollback_pip_install(ctx)
        click.echo()
        click.echo(click.style(f"DB write failed, install rolled back: {exc}", fg="red"))
        raise SystemExit(1)

    click.echo()
    click.echo(click.style(
        f"✓ {ctx.manifest['name']} v{ctx.manifest['version']} installed.",
        fg="green",
    ))

    scaffold_credentials(ctx)

    if ctx.warnings:
        click.echo()
        for w in ctx.warnings:
            click.echo(click.style(f"  warning: {w}", fg="yellow"))

    # Reset the registry so the next call picks up the new DB row
    from pearscarf.indexing.registry import reset_registry
    reset_registry()


@click.command("list")
def expert_list_command() -> None:
    """List installed experts."""
    rows = store.list_registered_experts()
    if not rows:
        click.echo(
            "No experts registered in the DB. Default experts under "
            "experts/ are loaded from disk via the registry fallback."
        )
        return

    click.echo(f"{'name':20s}  {'source_type':12s}  {'version':10s}  {'enabled':8s}  install")
    click.echo("-" * 70)
    for r in rows:
        enabled = "yes" if r["enabled"] else "no"
        click.echo(
            f"{r['name']:20s}  {r['source_type']:12s}  {r['version']:10s}  "
            f"{enabled:8s}  {r['install_method']}"
        )


@click.command("inspect")
@click.argument("name")
def expert_inspect_command(name: str) -> None:
    """Show full detail for an installed expert."""
    row = store.get_registered_expert(name)
    if not row:
        click.echo(f"No expert registered with name '{name}'.")
        raise SystemExit(1)

    click.echo(click.style(f"{row['name']} v{row['version']}", fg="cyan"))
    click.echo(f"  source_type:   {row['source_type']}")
    click.echo(f"  package_name:  {row['package_name']}")
    click.echo(f"  install:       {row['install_method']}")
    click.echo(f"  enabled:       {row['enabled']}")
    click.echo(f"  installed_at:  {row['installed_at']}")

    # Resolve package directory via importlib
    try:
        spec = importlib.util.find_spec(row["package_name"])
    except Exception:
        spec = None
    if spec and spec.submodule_search_locations:
        package_dir = Path(next(iter(spec.submodule_search_locations)))
        click.echo(f"  package_dir:   {package_dir}")
    else:
        click.echo("  package_dir:   (unresolved)")

    entity_types = store.list_entity_types_for_expert(name)
    click.echo()
    click.echo(f"Entity types ({len(entity_types)}):")
    for et in entity_types:
        click.echo(f"  • {et['type_name']} → {et['knowledge_path']}")

    patterns = store.list_identifier_patterns_for_expert(name)
    click.echo()
    click.echo(f"Identifier patterns ({len(patterns)}):")
    for p in patterns:
        click.echo(
            f"  • [{p['scope']}] {p['entity_type']} ← {p['pattern_or_field']}"
        )

    cred_path = _ENV_DIR / f".{name}.env"
    click.echo()
    if cred_path.is_file():
        click.echo(f"Credentials: {cred_path}")
    else:
        click.echo(f"Credentials: (none — expected at {cred_path})")
