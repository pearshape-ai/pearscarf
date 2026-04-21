from __future__ import annotations

import os
import sys

import click

from pearscarf import __version__

# Reset terminal to sane mode immediately on import.
# This fixes stale raw mode left by a previous crashed session.
os.system("stty sane 2>/dev/null")


def _print_version(ctx: click.Context, _param: click.Parameter, value: bool) -> None:
    if not value or ctx.resilient_parsing:
        return
    click.echo(f"PearScarf v{__version__}")
    ctx.exit()


@click.group()
@click.option("--version", is_flag=True, callback=_print_version, expose_value=False, is_eager=True, help="Show version and exit.")
def cli() -> None:
    """pearscarf: Operational infrastructure that grows itself."""


@cli.command()
@click.option("--poll", is_flag=True, default=False,
              help="Start all enabled expert connectors (each requires its own credentials)")
def run(poll: bool) -> None:
    """Start the full system: worker + experts + REPL."""
    from pearscarf.interface.repl import SessionRepl
    from pearscarf.interface.startup import start_system, stop_system

    click.echo(f"PearScarf v{__version__}")

    def log_fn(msg: str) -> None:
        sys.stdout.write(msg + "\r\n")
        sys.stdout.flush()

    components = start_system(poll=poll, log_fn=log_fn)

    repl = SessionRepl(components.bus)
    try:
        repl.run()
    finally:
        stop_system(components)


@cli.command()
@click.option("--poll", is_flag=True, default=False,
              help="Start all enabled expert connectors (each requires its own credentials)")
def discord(poll: bool) -> None:
    """Run the full system with Discord as the frontend."""
    from pearscarf.interface.discord_bot import run_bot

    run_bot(poll=poll)


@cli.command()
def chat() -> None:
    """Start a direct chat with the worker agent (no session bus)."""
    from pearscarf.agents.base import BaseAgent
    from pearscarf.tools import registry

    registry.discover()
    agent = BaseAgent(
        tool_registry=registry,
        on_tool_call=lambda name, args: click.echo(f"  -> {name}({args})"),
    )
    click.echo("pearscarf chat — direct mode (type 'exit' or Ctrl+C to quit)\n")

    try:
        while True:
            user_input = click.prompt("you", prompt_suffix=" > ")
            if user_input.strip().lower() in ("exit", "quit"):
                break
            response = agent.run(user_input)
            click.echo(f"\nagent > {response}\n")
    except (KeyboardInterrupt, EOFError):
        click.echo("\nbye.")


@cli.group()
def expert() -> None:
    """Expert agent utilities."""


# Install + lifecycle commands live in interface/install.py — registered here.
from pearscarf.interface.install import (
    expert_disable_command,
    expert_enable_command,
    expert_inspect_command,
    expert_list_command,
    expert_uninstall_command,
    expert_update_command,
    install_command,
)

cli.add_command(install_command)
cli.add_command(expert_update_command)
expert.add_command(expert_list_command)
expert.add_command(expert_inspect_command)
expert.add_command(expert_disable_command)
expert.add_command(expert_enable_command)
expert.add_command(expert_uninstall_command)


@expert.command()
@click.option("--auth", is_flag=True, help="Run Gmail OAuth flow for API-based access.")
def gmail(auth: bool) -> None:
    """Gmail expert — OAuth setup."""
    if auth:
        from gmailscarf.gmail_connect import run_oauth_flow

        run_oauth_flow()
        return

    click.echo(
        "Standalone interactive Gmail mode is offline during the expert "
        "encapsulation rework. Run 'psc run --poll-email' to start the "
        "Gmail connector instead. Use 'psc expert gmail --auth' to set up "
        "OAuth credentials."
    )


@expert.command("linear")
def linear() -> None:
    """Linear expert — standalone mode for direct interaction."""
    click.echo(
        "Standalone interactive Linear mode is offline during the expert "
        "encapsulation rework. Run 'psc run --poll-linear' to start the "
        "Linear connector instead."
    )


@expert.command("ingest")
@click.option("--seed", type=click.Path(exists=True), default=None, help="Ingest a seed file (.md)")
@click.option("--record", type=click.Path(exists=True), default=None, help="Ingest a JSON record file")
@click.option("--type", "record_type", type=str, default=None, help="Record type (e.g. 'email', 'linear_issue', 'github_pr')")
def ingest(seed: str | None, record: str | None, record_type: str | None) -> None:
    """Ingest expert — file-based data entry. Standalone interactive mode without flags."""
    from pearscarf.bus import MessageBus
    from pearscarf.expert_context import build_context
    from pearscarf.experts.ingest import create_ingest_expert

    def on_tool_call(name, args):
        click.echo(click.style(f"  [tool] {name}", fg="cyan") + f"({args})")

    def on_text(text):
        click.echo(click.style("  [thinking] ", fg="yellow") + text)

    def on_tool_result(name, result):
        preview = result[:200] + "..." if len(result) > 200 else result
        click.echo(click.style(f"  [result] {name}", fg="green") + f": {preview}")

    import importlib

    from pearscarf.indexing.registry import get_registry

    bus = MessageBus()
    registry = get_registry()

    # Standalone command — not connected to a running psc instance.
    # Must load expert connects in-process so the ingest tool can
    # delegate record processing. Duplicates the connect-loading from
    # start_system(); ideally this command would talk to the running
    # system's bus instead.
    for expert in registry.enabled_experts():
        if not expert.tools_module:
            continue
        try:
            tools_mod = importlib.import_module(expert.tools_module)
            expert_ctx = build_context(expert.name, bus, expert_version=expert.version)
            connect = tools_mod.get_tools(expert_ctx)
            for rt in expert.record_types:
                registry.register_connect(rt, connect)
        except Exception as exc:
            click.echo(f"  {expert.name} tools failed: {exc}")

    ctx = build_context("ingest_expert", bus)
    agent = create_ingest_expert(
        ctx=ctx,
        on_tool_call=on_tool_call,
        on_text=on_text,
        on_tool_result=on_tool_result,
    )

    # Seed mode — non-interactive
    if seed:
        message = f"Ingest seed file: {seed}"
        response = agent.run(message)
        click.echo(response)
        return

    # Record mode — non-interactive
    if record:
        if not record_type:
            raise click.UsageError("--type is required when using --record")
        message = f"Ingest {record_type} records from: {record}"
        response = agent.run(message)
        click.echo(response)
        return

    # Interactive mode — fallthrough
    click.echo("Ingest expert — standalone (type 'exit' or Ctrl+C to quit)\n")

    try:
        while True:
            user_input = click.prompt("you", prompt_suffix=" > ")
            if user_input.strip().lower() in ("exit", "quit"):
                break
            response = agent.run(user_input)
            click.echo(f"\n{click.style('expert', fg='magenta')} > {response}\n")
    except (KeyboardInterrupt, EOFError):
        click.echo("\nbye.")


@cli.command("gmail")
@click.option("--auth", is_flag=True, help="Run Gmail OAuth flow for API-based access.")
def gmail_shortcut(auth: bool) -> None:
    """Gmail utilities (shortcut for 'expert gmail')."""
    if auth:
        from gmailscarf.gmail_connect import run_oauth_flow

        run_oauth_flow()
        return
    click.echo("Usage: pearscarf gmail --auth")


@cli.group("eval", invoke_without_command=True)
@click.option("--dataset", type=click.Path(exists=True), default=None, help="Path to eval dataset directory")
@click.pass_context
def eval_cmd(ctx, dataset: str | None) -> None:
    """Run evaluation. Use subcommands (er, facts) or run all."""
    ctx.ensure_object(dict)
    ctx.obj["dataset"] = dataset
    if ctx.invoked_subcommand is None:
        if not dataset:
            raise click.UsageError("--dataset is required")
        from pearscarf.eval.runner import run_graph_eval
        run_graph_eval(dataset)


@eval_cmd.command("er")
@click.option("--dataset", type=click.Path(exists=True), default=None, help="Path to eval dataset directory")
@click.option("--verbose", "-v", is_flag=True, help="Show per-entity surface form diagnostics")
@click.option("--debug", "-d", is_flag=True, help="Dump LLM prompts/responses to data/debug/")
@click.option("--debug-dir", type=click.Path(), default=None, help="Custom debug output folder")
@click.pass_context
def eval_er(ctx, dataset: str | None, verbose: bool, debug: bool, debug_dir: str | None) -> None:
    """Run entity resolution eval only."""
    ds = dataset or ctx.obj.get("dataset")
    if not ds:
        raise click.UsageError("--dataset is required")
    from pearscarf.eval.runner import run_er_eval
    d = debug_dir or ("data/debug" if debug else None)
    run_er_eval(ds, verbose=verbose, debug_dir=d)


@eval_cmd.command("facts")
@click.option("--dataset", type=click.Path(exists=True), default=None, help="Path to eval dataset directory")
@click.option("--verbose", "-v", is_flag=True, help="Show missing and extra facts")
@click.option("--debug", "-d", is_flag=True, help="Dump LLM prompts/responses to data/debug/")
@click.option("--debug-dir", type=click.Path(), default=None, help="Custom debug output folder")
@click.pass_context
def eval_facts(ctx, dataset: str | None, verbose: bool, debug: bool, debug_dir: str | None) -> None:
    """Run fact extraction eval only. Includes curator processing."""
    ds = dataset or ctx.obj.get("dataset")
    if not ds:
        raise click.UsageError("--dataset is required")
    from pearscarf.eval.runner import run_facts_eval
    d = debug_dir or ("data/debug" if debug else None)
    run_facts_eval(ds, verbose=verbose, debug_dir=d)


@cli.group(invoke_without_command=True)
@click.pass_context
def mcp(ctx):
    """MCP server management."""
    if ctx.invoked_subcommand is None:
        click.echo("Use 'psc mcp start', 'psc mcp status', or 'psc mcp keys'.")


@mcp.command("start")
def mcp_start():
    """Run MCP server standalone in the foreground."""
    from pearscarf.mcp.mcp_server import MCPServer
    MCPServer().run_foreground()


@mcp.command("status")
def mcp_status():
    """Show MCP server info."""
    from pearscarf.config import MCP_HOST, MCP_PORT
    from pearscarf.storage.store import list_mcp_keys
    from pearscarf.storage.db import init_db
    init_db()
    keys = list_mcp_keys()
    active = sum(1 for k in keys if not k["revoked"])
    click.echo(f"  Bind: {MCP_HOST}:{MCP_PORT}")
    click.echo(f"  Tools: 10")
    click.echo(f"  Keys: {active} active, {len(keys)} total")


@mcp.command("test")
@click.argument("entity_name")
def mcp_test(entity_name: str):
    """Smoke test: call all three primitive tools against an entity name."""
    import json
    from pearscarf.query import context_query
    from pearscarf.storage.db import init_db
    init_db()

    click.echo(f"Testing against: {entity_name}\n")

    # find_entity
    click.echo("--- find_entity ---")
    results = context_query.find_entity(entity_name)
    if not results:
        click.echo(f"  Not found: {entity_name}")
        return
    entity = results[0]
    click.echo(f"  {entity['name']} ({entity['type']}, id={entity['id']})")

    # get_facts
    click.echo("\n--- get_facts ---")
    facts = context_query.get_facts(entity["id"])
    click.echo(f"  {len(facts)} fact(s)")
    for f in facts[:5]:
        click.echo(f"  [{f.get('edge_label', '?')}/{f.get('fact_type', '?')}] {f.get('fact', '')}")

    # get_connections
    click.echo("\n--- get_connections ---")
    conns = context_query.get_connections(entity["id"], max_depth=1)
    nodes = [n for n in conns.get("nodes", []) if n.get("type") != "day"]
    click.echo(f"  {len(nodes)} connection(s)")
    for n in nodes[:5]:
        click.echo(f"  {n['name']} ({n['type']})")

    # get_conflicts
    click.echo("\n--- get_conflicts (global) ---")
    conflicts = context_query.get_conflicts()
    click.echo(f"  {len(conflicts)} conflict(s)")
    for c in conflicts[:3]:
        click.echo(f"  {c['entity_name']}: {c['fact_a']} vs {c['fact_b']}")

    # get_entity_context (chronological)
    click.echo("\n--- get_entity_context (chronological) ---")
    facts_chrono = context_query.get_facts(entity["id"])
    facts_chrono.sort(key=lambda f: f.get("source_at", ""))
    click.echo(f"  {len(facts_chrono)} fact(s)")

    # get_entity_context (clustered)
    click.echo("\n--- get_entity_context (clustered) ---")
    clustered: dict[str, list] = {}
    for f in facts_chrono:
        clustered.setdefault(f.get("edge_label", "?"), []).append(f)
    for label, lf in clustered.items():
        click.echo(f"  {label}: {len(lf)} fact(s)")

    # get_current_state
    click.echo("\n--- get_current_state ---")
    affiliations = context_query.get_facts(entity["id"], edge_label="AFFILIATED", include_stale=False)
    click.echo(f"  {len(affiliations)} affiliation(s)")
    for a in affiliations[:5]:
        click.echo(f"  [{a.get('fact_type', '?')}] {a.get('fact', '')}")

    # get_open_commitments
    click.echo("\n--- get_open_commitments ---")
    commitments = context_query.get_facts(entity["id"], edge_label="ASSERTED", fact_type="commitment", include_stale=False)
    commitments = [c for c in commitments if c.get("valid_until")]
    click.echo(f"  {len(commitments)} open commitment(s)")
    for c in commitments[:3]:
        click.echo(f"  {c.get('fact', '')} (until: {c.get('valid_until', '?')})")

    # get_open_blockers
    click.echo("\n--- get_open_blockers ---")
    blockers = context_query.get_facts(entity["id"], edge_label="ASSERTED", fact_type="blocker", include_stale=False)
    click.echo(f"  {len(blockers)} blocker(s)")
    for b in blockers[:3]:
        click.echo(f"  {b.get('fact', '')}")

    # get_recent_activity
    click.echo("\n--- get_recent_activity (30 days) ---")
    from datetime import datetime, timezone, timedelta
    since_30d = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    transitions = context_query.get_facts(entity["id"], edge_label="TRANSITIONED", since=since_30d)
    comms = context_query.get_communications(entity["id"], since=since_30d)
    click.echo(f"  {len(transitions)} transition(s), {len(comms)} communication(s)")


@mcp.group("keys")
def mcp_keys():
    """Manage MCP API keys."""


@mcp_keys.command("list")
def mcp_keys_list():
    """List all MCP API keys."""
    from pearscarf.storage.store import list_mcp_keys
    from pearscarf.storage.db import init_db
    init_db()
    keys = list_mcp_keys()
    if not keys:
        click.echo("No keys.")
        return
    for k in keys:
        status = "revoked" if k["revoked"] else "active"
        last = k["last_used_at"] or "never"
        click.echo(f"  {k['id']}  {k['name']}  {status}  created: {k['created_at']}  last used: {last}")


@mcp_keys.command("create")
@click.option("--name", required=True, help="Human-readable key name")
def mcp_keys_create(name):
    """Create a new MCP API key."""
    from pearscarf.storage.store import create_mcp_key
    from pearscarf.storage.db import init_db
    init_db()
    result = create_mcp_key(name)
    click.echo(f"Key created: {result['id']}")
    click.echo(f"Name: {result['name']}")
    click.echo(f"Key: {result['raw_key']}")
    click.echo("Save this key — it will not be shown again.")


@mcp_keys.command("revoke")
@click.argument("key_id")
def mcp_keys_revoke(key_id):
    """Revoke an MCP API key."""
    from pearscarf.storage.store import revoke_mcp_key
    from pearscarf.storage.db import init_db
    init_db()
    if revoke_mcp_key(key_id):
        click.echo(f"Key {key_id} revoked.")
    else:
        click.echo(f"Key {key_id} not found or already revoked.")


@cli.group(invoke_without_command=True)
@click.pass_context
def indexer(ctx) -> None:
    """Indexer — extracts entities and facts from records into the knowledge graph."""
    if ctx.invoked_subcommand is None:
        click.echo("Use 'psc indexer start' to run.")


@indexer.command("start")
def indexer_start() -> None:
    """Start the indexer in the foreground."""
    from pearscarf.indexing.indexer import Indexer
    click.echo("Indexer starting...")
    Indexer().run_foreground()


@cli.group(invoke_without_command=True)
@click.pass_context
def curator(ctx) -> None:
    """Curator agent — processes indexed records for graph quality."""
    if ctx.invoked_subcommand is None:
        click.echo("Use 'psc curator start' to run or 'psc curator status' to inspect.")


@curator.command("start")
def curator_start() -> None:
    """Start the curator in the foreground."""
    from pearscarf.curation.curator import Curator
    click.echo("Curator starting...")
    c = Curator()
    c.run_foreground()


@curator.command("status")
def curator_status() -> None:
    """Show curator queue status."""
    from pearscarf.storage.db import _get_conn, init_db
    from pearscarf.config import CURATOR_CLAIM_TIMEOUT
    init_db()
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS c FROM curator_queue WHERE claimed_at IS NULL"
        ).fetchone()
        unclaimed = row["c"] if row else 0

        row = conn.execute(
            "SELECT COUNT(*) AS c FROM curator_queue WHERE claimed_at IS NOT NULL"
        ).fetchone()
        claimed = row["c"] if row else 0

        row = conn.execute(
            "SELECT MIN(queued_at) AS oldest FROM curator_queue WHERE claimed_at IS NULL"
        ).fetchone()
        oldest = row["oldest"] if row else None

        row = conn.execute(
            "SELECT COUNT(*) AS c FROM curator_queue "
            "WHERE claimed_at IS NOT NULL "
            "AND claimed_at < now() - interval '%s seconds'",
            (CURATOR_CLAIM_TIMEOUT,),
        ).fetchone()
        timed_out = row["c"] if row else 0
    click.echo(f"  Unclaimed:  {unclaimed}")
    click.echo(f"  Claimed:    {claimed}")
    click.echo(f"  Timed out:  {timed_out}")
    if oldest:
        click.echo(f"  Oldest:     {oldest}")

    # Graph-derived metrics
    from datetime import datetime, timezone
    from pearscarf.storage import graph
    eligible = len(graph.get_inferred_multi_source_edges())
    today = graph.utc_to_local_date(datetime.now(timezone.utc).isoformat())
    expired = len(graph.get_expired_commitments(today))
    click.echo(f"  Upgrade eligible: {eligible}")
    click.echo(f"  Expired pending:  {expired}")


@cli.group(invoke_without_command=True)
@click.pass_context
def queue(ctx) -> None:
    """Inspect the curator queue."""
    if ctx.invoked_subcommand is not None:
        return
    from pearscarf.storage.db import _get_conn, init_db
    init_db()
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS c FROM curator_queue WHERE claimed_at IS NULL"
        ).fetchone()
        unclaimed = dict(row).get("c", 0) if row else 0

        row = conn.execute(
            "SELECT COUNT(*) AS c FROM curator_queue WHERE claimed_at IS NOT NULL"
        ).fetchone()
        claimed = dict(row).get("c", 0) if row else 0

        row = conn.execute(
            "SELECT MIN(queued_at) AS oldest FROM curator_queue WHERE claimed_at IS NULL"
        ).fetchone()
        oldest = dict(row).get("oldest") if row else None
    click.echo(f"  Unclaimed: {unclaimed}")
    click.echo(f"  Claimed:   {claimed}")
    if oldest:
        click.echo(f"  Oldest:    {oldest}")


@queue.command("list")
def queue_list() -> None:
    """List curator queue entries (up to 20)."""
    from pearscarf.storage.db import _get_conn, init_db
    init_db()
    with _get_conn() as conn:
        rows = conn.execute(
            "SELECT record_id, queued_at, claimed_at FROM curator_queue "
            "ORDER BY queued_at LIMIT 20"
        ).fetchall()
    if not rows:
        click.echo("Queue is empty.")
        return
    for r in rows:
        claimed = f"  claimed: {r['claimed_at']}" if r["claimed_at"] else "  unclaimed"
        click.echo(f"  {r['record_id']}  queued: {r['queued_at']}{claimed}")


@queue.command("clear")
@click.option("--confirm", is_flag=True, help="Required to actually clear the queue")
def queue_clear(confirm: bool) -> None:
    """Delete all unclaimed entries from the curator queue."""
    if not confirm:
        click.echo("Use --confirm to clear unclaimed queue entries.")
        return
    from pearscarf.storage.db import _get_conn, init_db
    init_db()
    with _get_conn() as conn:
        result = conn.execute("DELETE FROM curator_queue WHERE claimed_at IS NULL")
        conn.commit()
        click.echo(f"Cleared {result.rowcount} unclaimed entries.")


@cli.command("query")
@click.argument("tool_name")
@click.option("--name", default=None, help="Entity name (for find_entity)")
@click.option("--entity-name", default=None, help="Entity name (for entity-scoped tools)")
@click.option("--edge-label", default=None, help="AFFILIATED, ASSERTED, or TRANSITIONED")
@click.option("--fact-type", default=None, help="Fact type filter")
@click.option("--include-stale", is_flag=True, help="Include stale facts")
@click.option("--since", default=None, help="ISO datetime filter")
@click.option("--entity-a", default=None, help="First entity (for get_relationship)")
@click.option("--entity-b", default=None, help="Second entity (for get_relationship)")
@click.option("--before-date", default=None, help="ISO date (for get_open_commitments)")
@click.option("--entity-type", default=None, help="person, company, project, event")
def query_cmd(tool_name, **kwargs):
    """Call a context_query tool directly. No MCP auth needed."""
    import json as json_mod
    from pearscarf.query import context_query
    from pearscarf.storage.db import init_db
    init_db()

    try:
        if tool_name == "find_entity":
            result = context_query.find_entity(
                kwargs["name"] or kwargs["entity_name"] or "",
                entity_type=kwargs.get("entity_type"),
            )
        elif tool_name == "get_facts":
            matches = context_query.find_entity(kwargs["entity_name"] or "")
            if not matches:
                click.echo(json_mod.dumps({"error": "not_found", "name": kwargs["entity_name"]}))
                return
            result = context_query.get_facts(
                matches[0]["id"],
                edge_label=kwargs.get("edge_label"),
                fact_type=kwargs.get("fact_type"),
                include_stale=kwargs.get("include_stale", False),
                since=kwargs.get("since"),
            )
        elif tool_name == "get_connections":
            matches = context_query.find_entity(kwargs["entity_name"] or "")
            if not matches:
                click.echo(json_mod.dumps({"error": "not_found"}))
                return
            labels = [kwargs["edge_label"]] if kwargs.get("edge_label") else None
            result = context_query.get_connections(
                matches[0]["id"], include_stale=kwargs.get("include_stale", False),
                edge_labels=labels,
            )
        elif tool_name == "get_relationship":
            ma = context_query.find_entity(kwargs["entity_a"] or "")
            mb = context_query.find_entity(kwargs["entity_b"] or "")
            if not ma or not mb:
                click.echo(json_mod.dumps({"error": "not_found"}))
                return
            result = context_query.get_path(ma[0]["id"], mb[0]["id"])
        elif tool_name == "get_conflicts":
            eid = None
            if kwargs.get("entity_name"):
                matches = context_query.find_entity(kwargs["entity_name"])
                eid = matches[0]["id"] if matches else None
            result = context_query.get_conflicts(entity_id=eid)
        elif tool_name == "vector_search":
            result = context_query.vector_search(kwargs["name"] or kwargs["entity_name"] or "")
        else:
            click.echo(f"Unknown tool: {tool_name}")
            return

        click.echo(json_mod.dumps(result, indent=2, default=str))
    except Exception as exc:
        click.echo(f"Error: {exc}")


@cli.command("integration-test")
def integration_test():
    """Smoke test: call all context_query tools and validate response shapes."""
    from pearscarf.query import context_query
    from pearscarf.storage.db import init_db
    init_db()

    passed = 0
    failed = 0

    def _check(name, result, required_keys):
        nonlocal passed, failed
        if isinstance(result, dict):
            for k in required_keys:
                if k not in result:
                    click.echo(f"  FAIL {name}: missing key '{k}'")
                    failed += 1
                    return
        count = len(result) if isinstance(result, list) else result.get("count", len(result))
        click.echo(f"  PASS {name} ({count} items)")
        passed += 1

    # find_entity
    entities = context_query.find_entity("")
    _check("find_entity", entities, [])

    if entities:
        eid = entities[0]["id"]
        ename = entities[0]["name"]

        _check("get_facts", context_query.get_facts(eid), [])
        _check("get_connections", context_query.get_connections(eid), ["nodes", "edges"])
        _check("get_conflicts", context_query.get_conflicts(), [])
        _check("get_communications", context_query.get_communications(eid), [])

        from pearscarf.storage import graph
        from datetime import datetime, timezone
        today = graph.utc_to_local_date(datetime.now(timezone.utc).isoformat())
        _check("get_facts_for_day", context_query.get_facts_for_day(today), [])
        _check("vector_search", context_query.vector_search(ename), [])
        _check("get_path", context_query.get_path(eid, eid), ["path", "direct_facts"])
    else:
        click.echo("  SKIP — no entities in graph, seed data first")

    click.echo(f"\n  {passed} passed, {failed} failed")


@cli.command("erase-all")
def erase_all() -> None:
    """Wipe all system state: Postgres records, Neo4j graph, Qdrant vectors."""
    from pearscarf.storage import vectorstore
    from pearscarf.storage.db import _get_conn, close_pool, init_db
    from pearscarf.storage.neo4j_client import close as neo4j_close, get_session

    init_db()

    # Count
    with get_session() as session:
        node_count = session.run("MATCH (n) RETURN count(n) AS c").single()["c"]
        rel_count = session.run("MATCH ()-[r]->() RETURN count(r) AS c").single()["c"]

    try:
        vc = vectorstore._get_client()
        vector_count = vc.get_collection(vectorstore.COLLECTION_NAME).points_count
    except Exception:
        vector_count = 0

    with _get_conn() as conn:
        row = conn.execute("SELECT count(*) AS c FROM records").fetchone()
        records_count = dict(row).get("c", 0) if row else 0

    if node_count + vector_count + records_count == 0:
        click.echo("Nothing to do — all stores are empty.")
        return

    click.echo("This will DELETE:")
    click.echo(f"  Postgres:  {records_count} records")
    click.echo(f"  Neo4j:     {node_count} nodes, {rel_count} relationships")
    click.echo(f"  Qdrant:    {vector_count} vectors")
    click.echo()

    if not click.confirm("Continue?", default=False):
        click.echo("Aborted.")
        return

    # Wipe Neo4j
    with get_session() as session:
        session.run("MATCH (n) DETACH DELETE n")
    click.echo(f"Deleted {node_count} nodes and {rel_count} relationships from Neo4j.")

    # Wipe Qdrant
    try:
        from qdrant_client.models import Distance, VectorParams
        vc = vectorstore._get_client()
        vc.delete_collection(vectorstore.COLLECTION_NAME)
        vc.create_collection(
            collection_name=vectorstore.COLLECTION_NAME,
            vectors_config=VectorParams(size=vectorstore.VECTOR_SIZE, distance=Distance.COSINE),
        )
        vectorstore._client = None
        click.echo(f"Deleted {vector_count} vectors from Qdrant (collection recreated).")
    except Exception as exc:
        click.echo(f"Warning: Qdrant clear failed: {exc}")

    # Wipe Postgres
    from pearscarf.storage.store import list_typed_tables
    typed_tables = list_typed_tables()
    import re
    with _get_conn() as conn:
        for t in typed_tables:
            if re.match(r"^[a-z0-9_]+$", t):
                conn.execute(f"TRUNCATE {t} CASCADE")
        conn.execute("TRUNCATE curator_queue, records CASCADE")
        conn.commit()
    click.echo(f"Deleted {records_count} records from Postgres.")
    if typed_tables:
        click.echo(f"  Truncated {len(typed_tables)} typed table(s): {', '.join(typed_tables)}")

    click.echo("\nDone. All system state erased.")
    close_pool()
    neo4j_close()


import pearscarf.interface.cli_memory  # noqa: F401 — registers memory command group

if __name__ == "__main__":
    cli()
