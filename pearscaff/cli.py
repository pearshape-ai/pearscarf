from __future__ import annotations

import click

from pearscaff.agents.worker import WorkerAgent
from pearscaff.tools import registry


@click.group()
def cli() -> None:
    """pearscaff: Operational infrastructure that grows itself."""


@cli.command()
def chat() -> None:
    """Start an interactive chat session with the worker agent."""
    registry.discover()
    agent = WorkerAgent(
        tool_registry=registry,
        on_tool_call=lambda name, args: click.echo(f"  -> {name}({args})"),
    )
    click.echo("pearscaff chat (type 'exit' or Ctrl+C to quit)\n")

    try:
        while True:
            user_input = click.prompt("you", prompt_suffix=" > ")
            if user_input.strip().lower() in ("exit", "quit"):
                break
            response = agent.run(user_input)
            click.echo(f"\nagent > {response}\n")
    except (KeyboardInterrupt, EOFError):
        click.echo("\nbye.")


@cli.command()
def discord() -> None:
    """Run the worker agent as a Discord bot."""
    from pearscaff.discord_bot import run_bot

    run_bot()


@cli.group()
def expert() -> None:
    """Run an expert agent."""


@expert.command()
@click.option("--login", is_flag=True, help="Open a visible browser to log into Gmail.")
def gmail(login: bool) -> None:
    """Run the Gmail expert agent."""
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

    click.echo("Gmail expert (type 'exit' or Ctrl+C to quit)\n")

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
