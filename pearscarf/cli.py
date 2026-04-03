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
@click.option("--poll-email", is_flag=True, default=False,
              help="Enable email polling loop (requires Gmail OAuth credentials)")
@click.option("--poll-linear", is_flag=True, default=False,
              help="Enable Linear issue polling loop (requires LINEAR_API_KEY)")
def run(poll_email: bool, poll_linear: bool) -> None:
    """Start the full system: worker + experts + REPL."""
    from pearscarf.agents.runner import AgentRunner
    from pearscarf.agents.worker import create_worker_agent
    from pearscarf.bus import MessageBus
    from pearscarf.experts.gmail import create_gmail_expert_for_runner, start_email_polling
    from pearscarf.experts.linear import create_linear_expert_for_runner, start_issue_polling
    from pearscarf.experts.retriever import create_retriever_for_runner
    from pearscarf.indexer import Indexer
    from pearscarf.repl import SessionRepl

    click.echo(f"PearScarf v{__version__}")

    bus = MessageBus()

    # Start Gmail expert runner
    gmail_factory, gmail_manager, mcp_client = create_gmail_expert_for_runner(bus=bus)
    gmail_runner = AgentRunner("gmail_expert", gmail_factory, bus)
    gmail_runner.start()
    sys.stdout.write("Gmail expert started.\r\n")
    sys.stdout.flush()

    # Start email polling if requested
    if poll_email:
        if not mcp_client:
            raise SystemExit(
                "Email polling requires Gmail OAuth credentials.\n"
                "Set GMAIL_CLIENT_ID, GMAIL_CLIENT_SECRET, and GMAIL_REFRESH_TOKEN in .env.\n"
                "Run 'pearscarf gmail --auth' to set up OAuth."
            )
        start_email_polling(bus, mcp_client)
        sys.stdout.write("Email polling started.\r\n")
        sys.stdout.flush()

    # Start Linear expert runner (if configured)
    linear_factory, linear_client = create_linear_expert_for_runner(bus=bus)
    linear_runner = None
    if linear_factory:
        linear_runner = AgentRunner("linear_expert", linear_factory, bus)
        linear_runner.start()
        sys.stdout.write("Linear expert started.\r\n")
        sys.stdout.flush()

        if poll_linear:
            start_issue_polling(bus, linear_client)
            sys.stdout.write("Linear polling started.\r\n")
            sys.stdout.flush()
    elif poll_linear:
        raise SystemExit(
            "Linear polling requires LINEAR_API_KEY.\n"
            "Set LINEAR_API_KEY in .env."
        )

    # Start Retriever expert runner
    retriever_factory = create_retriever_for_runner(bus=bus)
    retriever_runner = AgentRunner("retriever", retriever_factory, bus)
    retriever_runner.start()
    sys.stdout.write("Retriever started.\r\n")
    sys.stdout.flush()

    # Start Worker runner
    def worker_factory(session_id: str):
        return create_worker_agent(bus=bus, session_id=session_id)

    worker_runner = AgentRunner("worker", worker_factory, bus)
    worker_runner.start()
    sys.stdout.write("Worker agent started.\r\n")
    sys.stdout.flush()

    # Start Indexer
    indexer = Indexer()
    indexer.start()
    sys.stdout.write("Indexer started.\r\n")
    sys.stdout.flush()

    # Start MCP server
    from pearscarf.mcp_server import MCPServer
    from pearscarf.config import MCP_PORT
    mcp_srv = MCPServer()
    mcp_srv.start()
    sys.stdout.write(f"MCP server started on port {MCP_PORT}.\r\n")
    sys.stdout.flush()

    # Run REPL in main thread
    repl = SessionRepl(bus)
    try:
        repl.run()
    finally:
        mcp_srv.stop()
        indexer.stop()
        retriever_runner.stop()
        worker_runner.stop()
        if linear_runner:
            linear_runner.stop()
        gmail_runner.stop()
        if gmail_manager:
            gmail_manager.close()


@cli.command()
@click.option("--poll-email", is_flag=True, default=False,
              help="Enable email polling loop (requires Gmail OAuth credentials)")
@click.option("--poll-linear", is_flag=True, default=False,
              help="Enable Linear issue polling loop (requires LINEAR_API_KEY)")
def discord(poll_email: bool, poll_linear: bool) -> None:
    """Run the full system with Discord as the frontend."""
    from pearscarf.discord_bot import run_bot

    run_bot(poll_email=poll_email, poll_linear=poll_linear)


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


@expert.command()
@click.option("--login", is_flag=True, help="Open a visible browser to log into Gmail.")
@click.option("--auth", is_flag=True, help="Run Gmail OAuth flow for API-based access.")
def gmail(login: bool, auth: bool) -> None:
    """Gmail expert — login, OAuth setup, or direct standalone mode."""
    if auth:
        from pearscarf.experts.gmail import run_oauth_flow

        run_oauth_flow()
        return

    from pearscarf.experts.gmail import create_gmail_expert
    from pearscarf.experts.gmail import login as gmail_login

    if login:
        gmail_login(headed=True)
        return

    def on_tool_call(name, args):
        click.echo(click.style(f"  [tool] {name}", fg="cyan") + f"({args})")

    def on_text(text):
        click.echo(click.style("  [thinking] ", fg="yellow") + text)

    def on_tool_result(name, result):
        preview = result[:200] + "..." if len(result) > 200 else result
        click.echo(click.style(f"  [result] {name}", fg="green") + f": {preview}")

    agent, manager = create_gmail_expert(
        on_tool_call=on_tool_call,
        on_text=on_text,
        on_tool_result=on_tool_result,
    )

    click.echo("Gmail expert — standalone (type 'exit' or Ctrl+C to quit)\n")

    try:
        while True:
            user_input = click.prompt("you", prompt_suffix=" > ")
            if user_input.strip().lower() in ("exit", "quit"):
                break
            response = agent.run(user_input)
            click.echo(f"\n{click.style('expert', fg='magenta')} > {response}\n")
    except (KeyboardInterrupt, EOFError):
        click.echo("\nbye.")
    finally:
        manager.close()


@expert.command("linear")
def linear() -> None:
    """Linear expert — standalone mode for direct interaction."""
    from pearscarf.experts.linear import create_linear_expert_for_runner
    from pearscarf.linear_client import LinearClient
    from pearscarf.config import LINEAR_API_KEY

    if not LINEAR_API_KEY:
        raise SystemExit("LINEAR_API_KEY is not set in .env.")

    from pearscarf.experts.linear import _create_linear_client
    from pearscarf.prompts import load as load_prompt
    from pearscarf.tools import ToolRegistry
    from pearscarf.agents.expert import ExpertAgent

    client = _create_linear_client()

    from pearscarf.experts.linear import (
        LinearListIssuesTool, LinearGetIssueTool, LinearCreateIssueTool,
        LinearUpdateIssueTool, LinearAddCommentTool, LinearSearchIssuesTool,
        SaveIssueTool,
    )

    registry = ToolRegistry()
    registry.register(LinearListIssuesTool(client))
    registry.register(LinearGetIssueTool(client))
    registry.register(LinearCreateIssueTool(client))
    registry.register(LinearUpdateIssueTool(client))
    registry.register(LinearAddCommentTool(client))
    registry.register(LinearSearchIssuesTool(client))
    registry.register(SaveIssueTool())

    def on_tool_call(name, args):
        click.echo(click.style(f"  [tool] {name}", fg="cyan") + f"({args})")

    def on_text(text):
        click.echo(click.style("  [thinking] ", fg="yellow") + text)

    def on_tool_result(name, result):
        preview = result[:200] + "..." if len(result) > 200 else result
        click.echo(click.style(f"  [result] {name}", fg="green") + f": {preview}")

    agent = ExpertAgent(
        domain="linear",
        domain_prompt=load_prompt("linear"),
        tool_registry=registry,
        on_tool_call=on_tool_call,
        on_text=on_text,
        on_tool_result=on_tool_result,
    )

    click.echo("Linear expert — standalone (type 'exit' or Ctrl+C to quit)\n")

    try:
        while True:
            user_input = click.prompt("you", prompt_suffix=" > ")
            if user_input.strip().lower() in ("exit", "quit"):
                break
            response = agent.run(user_input)
            click.echo(f"\n{click.style('expert', fg='magenta')} > {response}\n")
    except (KeyboardInterrupt, EOFError):
        click.echo("\nbye.")


@expert.command("ingest")
@click.option("--seed", type=click.Path(exists=True), default=None, help="Ingest a seed file (.md)")
@click.option("--record", type=click.Path(exists=True), default=None, help="Ingest a JSON record file")
@click.option("--type", "record_type", type=click.Choice(["email", "issue", "issue_change"]), default=None, help="Record type (required with --record)")
def ingest(seed: str | None, record: str | None, record_type: str | None) -> None:
    """Ingest expert — file-based data entry. Standalone interactive mode without flags."""
    from pearscarf.experts.ingest import create_ingest_expert

    def on_tool_call(name, args):
        click.echo(click.style(f"  [tool] {name}", fg="cyan") + f"({args})")

    def on_text(text):
        click.echo(click.style("  [thinking] ", fg="yellow") + text)

    def on_tool_result(name, result):
        preview = result[:200] + "..." if len(result) > 200 else result
        click.echo(click.style(f"  [result] {name}", fg="green") + f": {preview}")

    agent = create_ingest_expert(
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
        from pearscarf.experts.gmail import run_oauth_flow

        run_oauth_flow()
        return
    click.echo("Usage: pearscarf gmail --auth")


@cli.command("extract-test")
@click.argument("record_ids", nargs=-1)
def extract_test(record_ids: tuple[str, ...]) -> None:
    """Run extraction prompt against emails (no writes). Pass record IDs or omit for all relevant."""
    from pearscarf.extract_test import run_extraction

    run_extraction(list(record_ids) if record_ids else None)


@cli.command("eval")
@click.option("--dataset", required=True, type=click.Path(exists=True), help="Path to eval dataset directory")
@click.option("--verbose", "-v", is_flag=True, help="Print record content, expected and extracted entities/facts per record")
def eval_cmd(dataset: str, verbose: bool) -> None:
    """Run graph-based eval: ingest, index, query graph, score."""
    from pearscarf.eval_runner import run_graph_eval

    run_graph_eval(dataset, verbose=verbose)


@cli.group(invoke_without_command=True)
@click.pass_context
def mcp(ctx):
    """MCP server management."""
    if ctx.invoked_subcommand is None:
        click.echo("Use 'psc mcp start', 'psc mcp status', or 'psc mcp keys'.")


@mcp.command("start")
def mcp_start():
    """Run MCP server standalone in the foreground."""
    from pearscarf.mcp_server import MCPServer
    MCPServer().run_foreground()


@mcp.command("status")
def mcp_status():
    """Show MCP server info."""
    from pearscarf.config import MCP_HOST, MCP_PORT
    from pearscarf.store import list_mcp_keys
    from pearscarf.db import init_db
    init_db()
    keys = list_mcp_keys()
    active = sum(1 for k in keys if not k["revoked"])
    click.echo(f"  Bind: {MCP_HOST}:{MCP_PORT}")
    click.echo(f"  Tools: 7 (find_entity, get_facts, get_connections, get_relationship, get_conflicts, get_entity_context, get_current_state)")
    click.echo(f"  Keys: {active} active, {len(keys)} total")


@mcp.command("test")
@click.argument("entity_name")
def mcp_test(entity_name: str):
    """Smoke test: call all three primitive tools against an entity name."""
    import json
    from pearscarf import context_query
    from pearscarf.db import init_db
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


@mcp.group("keys")
def mcp_keys():
    """Manage MCP API keys."""


@mcp_keys.command("list")
def mcp_keys_list():
    """List all MCP API keys."""
    from pearscarf.store import list_mcp_keys
    from pearscarf.db import init_db
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
    from pearscarf.store import create_mcp_key
    from pearscarf.db import init_db
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
    from pearscarf.store import revoke_mcp_key
    from pearscarf.db import init_db
    init_db()
    if revoke_mcp_key(key_id):
        click.echo(f"Key {key_id} revoked.")
    else:
        click.echo(f"Key {key_id} not found or already revoked.")


@cli.group(invoke_without_command=True)
@click.pass_context
def curator(ctx) -> None:
    """Curator agent — processes indexed records for graph quality."""
    if ctx.invoked_subcommand is None:
        click.echo("Use 'psc curator start' to run or 'psc curator status' to inspect.")


@curator.command("start")
def curator_start() -> None:
    """Start the curator in the foreground."""
    from pearscarf.curator import Curator
    click.echo("Curator starting...")
    c = Curator()
    c.run_foreground()


@curator.command("status")
def curator_status() -> None:
    """Show curator queue status."""
    from pearscarf.db import _get_conn, init_db
    from pearscarf.config import CURATOR_CLAIM_TIMEOUT
    init_db()
    with _get_conn() as conn:
        unclaimed = conn.execute(
            "SELECT COUNT(*) AS c FROM curator_queue WHERE claimed_at IS NULL"
        ).fetchone()["c"]
        claimed = conn.execute(
            "SELECT COUNT(*) AS c FROM curator_queue WHERE claimed_at IS NOT NULL"
        ).fetchone()["c"]
        oldest = conn.execute(
            "SELECT MIN(queued_at) AS oldest FROM curator_queue WHERE claimed_at IS NULL"
        ).fetchone()["oldest"]
        timed_out = conn.execute(
            "SELECT COUNT(*) AS c FROM curator_queue "
            "WHERE claimed_at IS NOT NULL "
            "AND claimed_at < now() - interval '%s seconds'",
            (CURATOR_CLAIM_TIMEOUT,),
        ).fetchone()["c"]
    click.echo(f"  Unclaimed:  {unclaimed}")
    click.echo(f"  Claimed:    {claimed}")
    click.echo(f"  Timed out:  {timed_out}")
    if oldest:
        click.echo(f"  Oldest:     {oldest}")

    # Graph-derived metrics
    from datetime import datetime, timezone
    from pearscarf import graph
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
    from pearscarf.db import _get_conn, init_db
    init_db()
    with _get_conn() as conn:
        unclaimed = conn.execute(
            "SELECT COUNT(*) AS c FROM curator_queue WHERE claimed_at IS NULL"
        ).fetchone()["c"]
        claimed = conn.execute(
            "SELECT COUNT(*) AS c FROM curator_queue WHERE claimed_at IS NOT NULL"
        ).fetchone()["c"]
        oldest = conn.execute(
            "SELECT MIN(queued_at) AS oldest FROM curator_queue WHERE claimed_at IS NULL"
        ).fetchone()["oldest"]
    click.echo(f"  Unclaimed: {unclaimed}")
    click.echo(f"  Claimed:   {claimed}")
    if oldest:
        click.echo(f"  Oldest:    {oldest}")


@queue.command("list")
def queue_list() -> None:
    """List curator queue entries (up to 20)."""
    from pearscarf.db import _get_conn, init_db
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
    from pearscarf.db import _get_conn, init_db
    init_db()
    with _get_conn() as conn:
        result = conn.execute("DELETE FROM curator_queue WHERE claimed_at IS NULL")
        conn.commit()
        click.echo(f"Cleared {result.rowcount} unclaimed entries.")


@cli.command("erase-all")
def erase_all() -> None:
    """Wipe all system state: Postgres records, Neo4j graph, Qdrant vectors."""
    from pearscarf import vectorstore
    from pearscarf.db import _get_conn, close_pool, init_db
    from pearscarf.neo4j_client import close as neo4j_close, get_session

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
        records_count = conn.execute("SELECT count(*) AS c FROM records").fetchone()["c"]
        emails_count = conn.execute("SELECT count(*) AS c FROM emails").fetchone()["c"]
        issues_count = conn.execute("SELECT count(*) AS c FROM issues").fetchone()["c"]
        changes_count = conn.execute("SELECT count(*) AS c FROM issue_changes").fetchone()["c"]

    if node_count + vector_count + records_count == 0:
        click.echo("Nothing to do — all stores are empty.")
        return

    click.echo("This will DELETE:")
    click.echo(f"  Postgres:  {records_count} records, {emails_count} emails, {issues_count} issues, {changes_count} issue_changes")
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
    with _get_conn() as conn:
        conn.execute("TRUNCATE curator_queue, issue_changes, issues, emails, records CASCADE")
        conn.commit()
    click.echo(f"Deleted {records_count} records from Postgres.")

    click.echo("\nDone. All system state erased.")
    close_pool()
    neo4j_close()


import pearscarf.cli_memory  # noqa: F401 — registers memory command group

if __name__ == "__main__":
    cli()
