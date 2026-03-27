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

    # Run REPL in main thread
    repl = SessionRepl(bus)
    try:
        repl.run()
    finally:
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
    """Run extraction eval against a dataset and score results."""
    from pearscarf.eval_runner import run_eval

    run_eval(dataset, verbose=verbose)


import pearscarf.cli_memory  # noqa: F401 — registers memory command group

if __name__ == "__main__":
    cli()
