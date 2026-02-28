from __future__ import annotations

import click


@click.group()
def cli() -> None:
    """pearscaff: Operational infrastructure that grows itself."""


@cli.command()
def run() -> None:
    """Start the full system: worker + experts + REPL."""
    from pearscaff.agents.runner import AgentRunner
    from pearscaff.agents.worker import create_worker_agent
    from pearscaff.bus import MessageBus
    from pearscaff.experts.gmail import create_gmail_expert_for_runner
    from pearscaff.repl import SessionRepl

    bus = MessageBus()

    # Start Gmail expert runner
    gmail_factory, gmail_manager = create_gmail_expert_for_runner(bus=bus)
    gmail_runner = AgentRunner("gmail_expert", gmail_factory, bus)
    gmail_runner.start()
    click.echo(click.style("Gmail expert started.", fg="green"))

    # Start Worker runner
    def worker_factory(session_id: str):
        return create_worker_agent(bus=bus, session_id=session_id)

    worker_runner = AgentRunner("worker", worker_factory, bus)
    worker_runner.start()
    click.echo(click.style("Worker agent started.", fg="green"))

    # Run REPL in main thread
    repl = SessionRepl(bus)
    try:
        repl.run()
    finally:
        worker_runner.stop()
        gmail_runner.stop()
        gmail_manager.close()


@cli.command()
def discord() -> None:
    """Run the full system with Discord as the frontend."""
    from pearscaff.discord_bot import run_bot

    run_bot()


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
def gmail(login: bool) -> None:
    """Gmail expert — login or direct standalone mode."""
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


if __name__ == "__main__":
    cli()
