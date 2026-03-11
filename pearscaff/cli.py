from __future__ import annotations

import os
import sys

import click

from pearscaff import __version__

# Reset terminal to sane mode immediately on import.
# This fixes stale raw mode left by a previous crashed session.
os.system("stty sane 2>/dev/null")


def _print_version(ctx: click.Context, _param: click.Parameter, value: bool) -> None:
    if not value or ctx.resilient_parsing:
        return
    click.echo(f"PearScaff v{__version__}")
    ctx.exit()


@click.group()
@click.option("--version", is_flag=True, callback=_print_version, expose_value=False, is_eager=True, help="Show version and exit.")
def cli() -> None:
    """pearscaff: Operational infrastructure that grows itself."""


@cli.command()
@click.option("--poll-email", is_flag=True, default=False,
              help="Enable email polling loop (requires Gmail OAuth credentials)")
def run(poll_email: bool) -> None:
    """Start the full system: worker + experts + REPL."""
    from pearscaff.agents.runner import AgentRunner
    from pearscaff.agents.worker import create_worker_agent
    from pearscaff.bus import MessageBus
    from pearscaff.experts.gmail import create_gmail_expert_for_runner, start_email_polling
    from pearscaff.experts.retriever import create_retriever_for_runner
    from pearscaff.indexer import Indexer
    from pearscaff.memory import get_memory_backend
    from pearscaff.repl import SessionRepl

    bus = MessageBus()
    memory = get_memory_backend()

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
                "Run 'pearscaff gmail --auth' to set up OAuth."
            )
        start_email_polling(bus, mcp_client)
        sys.stdout.write("Email polling started.\r\n")
        sys.stdout.flush()

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
    indexer = Indexer(memory=memory)
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
        gmail_runner.stop()
        if gmail_manager:
            gmail_manager.close()


@cli.command()
@click.option("--poll-email", is_flag=True, default=False,
              help="Enable email polling loop (requires Gmail OAuth credentials)")
def discord(poll_email: bool) -> None:
    """Run the full system with Discord as the frontend."""
    from pearscaff.discord_bot import run_bot

    run_bot(poll_email=poll_email)


@cli.command()
def chat() -> None:
    """Start a direct chat with the worker agent (no session bus)."""
    from pearscaff.agents.base import BaseAgent
    from pearscaff.tools import registry

    registry.discover()
    agent = BaseAgent(
        tool_registry=registry,
        on_tool_call=lambda name, args: click.echo(f"  -> {name}({args})"),
    )
    click.echo("pearscaff chat — direct mode (type 'exit' or Ctrl+C to quit)\n")

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
        from pearscaff.experts.gmail import run_oauth_flow

        run_oauth_flow()
        return

    from pearscaff.experts.gmail import create_gmail_expert
    from pearscaff.experts.gmail import login as gmail_login

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


@cli.command("gmail")
@click.option("--auth", is_flag=True, help="Run Gmail OAuth flow for API-based access.")
def gmail_shortcut(auth: bool) -> None:
    """Gmail utilities (shortcut for 'expert gmail')."""
    if auth:
        from pearscaff.experts.gmail import run_oauth_flow

        run_oauth_flow()
        return
    click.echo("Usage: pearscaff gmail --auth")


if __name__ == "__main__":
    cli()
