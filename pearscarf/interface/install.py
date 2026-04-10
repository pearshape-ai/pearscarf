"""Expert install command — discovery, validation, DB writes, scaffolding.

Implements `pearscarf install <source>`, `pearscarf expert list`, and
`pearscarf expert inspect <name>`. The install command runs a 7-stage
validation pipeline before writing any DB rows; if any blocking stage
fails, nothing is registered.

Local path only for MVP. Git URL and PyPI installs are post-MVP.
"""

from __future__ import annotations

import importlib
import importlib.util
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import click
import yaml

from pearscarf.indexing.registry import base_entity_types
from pearscarf.storage import store


# --- Source detection ---


@dataclass
class InstallSource:
    method: str  # "local" only for MVP
    raw: str
    local_path: Path | None = None


def detect_source(source: str) -> InstallSource:
    """Classify an install source string. Only local paths are supported for MVP."""
    s = source.strip()

    # Reject non-local sources with a clear message
    if s.startswith("git+") or "github.com" in s:
        raise SystemExit(
            f"Git URL installs are not supported in this version.\n"
            f"Clone the repo into experts/ and use: pearscarf install ./experts/<name>"
        )
    if not (s.startswith("./") or s.startswith("../") or s.startswith("~/") or s.startswith("/")):
        raise SystemExit(
            f"PyPI installs are not supported in this version.\n"
            f"Place the package in experts/ and use: pearscarf install ./experts/{s}"
        )

    return InstallSource(
        method="local",
        raw=source,
        local_path=Path(s).expanduser().resolve(),
    )


# --- Validation pipeline ---


@dataclass
class ValidationContext:
    source: InstallSource
    package_name: str = ""
    package_dir: Path | None = None
    manifest: dict = field(default_factory=dict)
    failures: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


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


def stage_locate_package(ctx: ValidationContext) -> StageResult:
    _stage("Stage 1 — package locatable")
    path = ctx.source.local_path
    if path is None or not path.is_dir():
        return _fail(f"local path is not a directory: {ctx.source.raw}")
    ctx.package_dir = path
    ctx.package_name = path.name
    return _ok(f"local path resolved → {path}")


_SEMVER = re.compile(r"^\d+\.\d+\.\d+$")


def stage_manifest(ctx: ValidationContext) -> StageResult:
    _stage("Stage 2 — manifest valid")
    assert ctx.package_dir is not None

    manifest_path = ctx.package_dir / "manifest.yaml"
    if not manifest_path.is_file():
        return _fail(f"manifest.yaml missing at {manifest_path}")

    try:
        data = yaml.safe_load(manifest_path.read_text()) or {}
    except yaml.YAMLError as exc:
        return _fail(f"manifest.yaml not valid YAML: {exc}")

    required = ["name", "version", "source_type", "record_types"]
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
    _stage("Stage 3 — knowledge contract")
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
    _stage("Stage 4 — entry points")
    assert ctx.package_dir is not None

    # Check ingester entry point (new manifests use "ingester", legacy use "connector")
    ingester_rel = ctx.manifest.get("ingester") or ctx.manifest.get("connector")
    if ingester_rel:
        ingester_path = ctx.package_dir / ingester_rel
        if not ingester_path.is_file():
            return _fail(f"ingester file missing at {ingester_path}")
        module_no_ext = Path(ingester_rel).with_suffix("")
        module_name = f"{ctx.package_name}." + module_no_ext.as_posix().replace("/", ".")
        try:
            module = importlib.import_module(module_name)
        except Exception as exc:  # noqa: BLE001
            return _fail(f"ingester import failed: {exc}")
        start_fn = getattr(module, "start", None)
        if start_fn is None or not callable(start_fn):
            return _fail(f"{module_name} has no callable start function")

    # Check tools entry point (optional)
    tools_rel = ctx.manifest.get("tools")
    if tools_rel:
        tools_path = ctx.package_dir / tools_rel
        if not tools_path.is_file():
            return _fail(f"tools file missing at {tools_path}")
        module_no_ext = Path(tools_rel).with_suffix("")
        module_name = f"{ctx.package_name}." + module_no_ext.as_posix().replace("/", ".")
        try:
            module = importlib.import_module(module_name)
        except Exception as exc:  # noqa: BLE001
            return _fail(f"tools import failed: {exc}")
        get_tools_fn = getattr(module, "get_tools", None)
        if get_tools_fn is None or not callable(get_tools_fn):
            return _fail(f"{module_name} has no callable get_tools function")

    if not ingester_rel and not tools_rel:
        return _fail("manifest declares neither 'ingester' nor 'tools' — at least one is required")

    return _ok("entry points valid")


def stage_conflicts(ctx: ValidationContext) -> StageResult:
    _stage("Stage 5 — conflict checks")

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

    # Build record_type → expert map for collision check.
    # Read each other expert's record_types from its on-disk manifest via importlib.
    rt_map: dict[str, str] = {}
    for e in others:
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
    for et in store.list_entity_types_for_enabled_experts():
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
    _stage("Stage 6 — identifier patterns")

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
    _stage("Stage 7 — eval dataset (non-blocking)")
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
    stage_locate_package,
    stage_manifest,
    stage_knowledge,
    stage_connector,
    stage_conflicts,
    stage_identifier_patterns,
    stage_eval,
]


def run_validation(source: InstallSource) -> ValidationContext:
    """Run all 7 validation stages. Always returns the context — check `ctx.failures`."""
    ctx = ValidationContext(source=source)
    for stage in _STAGES:
        result = stage(ctx)
        if not result.ok:
            if result.blocking:
                ctx.failures.append(result.message)
                return ctx
            ctx.warnings.append(result.message)
    return ctx


# --- DB writes + scaffolding ---


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
        install_method="local",
        enabled=True,
        entity_types=entity_types,
        identifier_patterns=identifier_patterns,
    )


_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_ENV_DIR = _REPO_ROOT / "env"
_GITIGNORE = _REPO_ROOT / ".gitignore"


# --- Pre-startup credential check ---
#
# Convention for `.env.example`:
#   KEY=        → required, operator must fill in
#   KEY=value   → optional with a working default; check skips it
# The check requires every "required" var to have a non-empty value in
# the operator's env file.


@dataclass
class CredentialError:
    expert_name: str
    var_name: str
    env_path: Path
    reason: str


def _parse_env_file(path: Path) -> dict[str, str]:
    """Parse a `KEY=VALUE` env file. Returns {key: value} (no expansion, no quotes)."""
    if not path.is_file():
        return {}
    result: dict[str, str] = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        result[key.strip()] = value.strip()
    return result


def check_expert_credentials(expert) -> list[CredentialError]:
    """Verify the operator has filled in every required env var for an expert.

    Required vars are detected from the expert's `.env.example` file —
    any var with an empty value in the example is required. The
    operator's file at `env/.<name>.env` must contain a non-empty value
    for each. Vars with non-empty defaults in the example are skipped.
    """
    errors: list[CredentialError] = []
    example_path = expert.path / ".env.example"
    if not example_path.is_file():
        return errors  # expert declares no credentials

    example_vars = _parse_env_file(example_path)
    target_path = _ENV_DIR / f".{expert.name}.env"

    if not target_path.is_file():
        # The whole credentials file is missing — flag every required var
        for key, example_value in example_vars.items():
            if example_value:
                continue
            errors.append(CredentialError(
                expert_name=expert.name,
                var_name=key,
                env_path=target_path,
                reason="credentials file missing — copy .env.example and fill in",
            ))
        return errors

    operator_vars = _parse_env_file(target_path)

    for key, example_value in example_vars.items():
        if example_value:
            # Optional var with a default — skip
            continue
        operator_value = operator_vars.get(key)
        if operator_value is None:
            errors.append(CredentialError(
                expert_name=expert.name,
                var_name=key,
                env_path=target_path,
                reason="missing from env file",
            ))
            continue
        if not operator_value:
            errors.append(CredentialError(
                expert_name=expert.name,
                var_name=key,
                env_path=target_path,
                reason="empty",
            ))

    return errors


def check_credentials_for_enabled_experts() -> list[CredentialError]:
    """Run credential checks against every currently enabled expert."""
    from pearscarf.indexing.registry import get_registry

    errors: list[CredentialError] = []
    for expert in get_registry().enabled_experts():
        errors.extend(check_expert_credentials(expert))
    return errors


def enforce_credentials_or_exit() -> None:
    """Run the credential check and exit with a clear report on any failure.

    Called by `psc run` and `psc discord` before starting any expert.
    """
    errors = check_credentials_for_enabled_experts()
    if not errors:
        return

    click.echo(click.style(
        "Credential check failed. The following expert credentials are missing or unfilled:",
        fg="red",
    ))
    click.echo()

    by_expert: dict[str, list[CredentialError]] = {}
    for err in errors:
        by_expert.setdefault(err.expert_name, []).append(err)

    for name, expert_errors in by_expert.items():
        env_path = expert_errors[0].env_path
        click.echo(click.style(f"  {name}", fg="cyan") + f"  → {env_path}")
        for err in expert_errors:
            click.echo(f"    {click.style(err.var_name, fg='yellow')}: {err.reason}")
        click.echo()

    click.echo("Edit the env file(s) above and try again.")
    raise SystemExit(1)


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
    """Install an expert from a local folder path."""
    src = detect_source(source)
    click.echo(f"Installing from {click.style(src.method, fg='cyan')}: {src.raw}\n")

    ctx = run_validation(src)

    if ctx.failures:
        click.echo()
        click.echo(click.style("Install failed.", fg="red"))
        raise SystemExit(1)

    if not prompt_entity_type_approval(ctx, assume_yes):
        click.echo(click.style("Install cancelled — entity types not approved.", fg="red"))
        raise SystemExit(1)

    try:
        write_registration(ctx)
    except Exception as exc:
        click.echo()
        click.echo(click.style(f"DB write failed: {exc}", fg="red"))
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
    _reset_runtime_registry()


@click.command("list")
def expert_list_command() -> None:
    """List installed experts (every version, including disabled)."""
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
    """Show full detail for the currently enabled version of an expert."""
    row = store.get_enabled_expert(name)
    if not row:
        click.echo(f"No enabled expert registered with name '{name}'.")
        history = store.list_versions_of_expert(name)
        if history:
            click.echo(f"  ({len(history)} historical row(s) found — see 'psc expert list'.)")
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

    entity_types = store.list_entity_types_for_expert_id(row["id"])
    click.echo()
    click.echo(f"Entity types ({len(entity_types)}):")
    for et in entity_types:
        click.echo(f"  • {et['type_name']} → {et['knowledge_path']}")

    patterns = store.list_identifier_patterns_for_expert_id(row["id"])
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


# --- Lifecycle commands ---


def _reset_runtime_registry() -> None:
    """Drop the cached registry so the next process call sees fresh DB state."""
    from pearscarf.indexing.registry import reset_registry
    reset_registry()


@click.command("disable")
@click.argument("name")
def expert_disable_command(name: str) -> None:
    """Disable the currently enabled version of an expert (reversible)."""
    row = store.get_enabled_expert(name)
    if not row:
        click.echo(f"No enabled expert named '{name}'.")
        raise SystemExit(1)

    store.disable_enabled_expert(name)
    _reset_runtime_registry()
    click.echo(click.style(
        f"✓ {name} v{row['version']} disabled. Reversible via 'psc expert enable {name}'.",
        fg="yellow",
    ))
    click.echo("  (graph data is untouched.)")


@click.command("enable")
@click.argument("name")
def expert_enable_command(name: str) -> None:
    """Re-enable the most recently installed disabled version of an expert."""
    if store.get_enabled_expert(name):
        click.echo(f"{name} is already enabled.")
        return

    row = store.enable_latest_disabled_expert(name)
    if not row:
        click.echo(f"No disabled version of '{name}' found to enable.")
        raise SystemExit(1)

    _reset_runtime_registry()
    click.echo(click.style(
        f"✓ {name} v{row['version']} enabled.", fg="green"
    ))


@click.command("uninstall")
@click.argument("name")
@click.option("-y", "--yes", "assume_yes", is_flag=True, default=False,
              help="Skip the confirmation prompt")
def expert_uninstall_command(name: str, assume_yes: bool) -> None:
    """Uninstall an expert. Removes all DB rows. Graph data is preserved."""
    rows = store.list_versions_of_expert(name)
    if not rows:
        click.echo(f"No expert named '{name}' registered.")
        raise SystemExit(1)

    enabled = next((r for r in rows if r["enabled"]), None)
    summary_version = (enabled or rows[0])["version"]

    click.echo(f"This will uninstall '{name}' v{summary_version} "
               f"and remove {len(rows)} DB row(s).")
    click.echo("  Graph data (entities, fact edges) is preserved.")

    if not assume_yes and not click.confirm("Proceed?", default=False):
        click.echo("Cancelled.")
        return

    removed = store.delete_expert_cascade(name)
    _reset_runtime_registry()

    click.echo(click.style(
        f"✓ {name} uninstalled ({removed} row(s) removed). "
        f"Graph data preserved.",
        fg="green",
    ))


def _read_manifest_version(package_name: str) -> tuple[str | None, Path | None]:
    """Read a package's manifest.yaml and return (version, package_dir).

    Resolves the package via importlib so it works for local packages
    on sys.path.
    """
    try:
        spec = importlib.util.find_spec(package_name)
    except Exception:
        return None, None
    if not spec or not spec.submodule_search_locations:
        return None, None
    package_dir = Path(next(iter(spec.submodule_search_locations)))
    manifest_path = package_dir / "manifest.yaml"
    if not manifest_path.is_file():
        return None, package_dir
    try:
        data = yaml.safe_load(manifest_path.read_text()) or {}
    except yaml.YAMLError:
        return None, package_dir
    return str(data.get("version") or ""), package_dir


@click.command("update")
@click.argument("name")
@click.option("-y", "--yes", "assume_yes", is_flag=True, default=False,
              help="Skip the new entity types approval prompt")
def expert_update_command(name: str, assume_yes: bool) -> None:
    """Update an installed expert to the latest on-disk version."""
    current = store.get_enabled_expert(name)
    if not current:
        click.echo(f"No enabled expert named '{name}'.")
        raise SystemExit(1)

    package_name = current["package_name"]

    # Read the on-disk manifest version
    new_version, package_dir = _read_manifest_version(package_name)
    if new_version is None:
        click.echo(click.style(
            f"Could not read manifest version for {package_name}.",
            fg="red",
        ))
        raise SystemExit(1)

    if new_version == current["version"]:
        click.echo(f"{name} is already at version {new_version}. Nothing to do.")
        return

    click.echo(f"Detected new version: {current['version']} → {new_version}")

    # Re-validate the package
    assert package_dir is not None
    src = InstallSource(method="local", raw=str(package_dir),
                        local_path=package_dir)
    ctx = run_validation(src)
    if ctx.failures:
        click.echo()
        click.echo(click.style("Update failed validation. Old version remains active.", fg="red"))
        raise SystemExit(1)

    if not prompt_entity_type_approval(ctx, assume_yes):
        click.echo(click.style(
            "Update cancelled — entity types not approved. Old version remains active.",
            fg="red",
        ))
        raise SystemExit(1)

    # Step 4: write_full_registration handles "disable old enabled row, insert new"
    # in a single transaction.
    try:
        write_registration(ctx)
    except Exception as exc:
        click.echo(click.style(
            f"DB write failed: {exc}. Old version remains active.", fg="red"
        ))
        raise SystemExit(1)

    _reset_runtime_registry()
    click.echo()
    click.echo(click.style(
        f"✓ {name} updated: v{current['version']} → v{new_version}.",
        fg="green",
    ))
    click.echo(f"  Old row preserved as historical record (enabled=false).")
