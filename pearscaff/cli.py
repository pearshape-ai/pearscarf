from __future__ import annotations

import click

from pearscaff.agent import Agent
from pearscaff.tools import registry


@click.group()
def cli() -> None:
    """pearscaff: Operational infrastructure that grows itself."""
    registry.discover()


@cli.command()
def chat() -> None:
    """Start an interactive chat session with the agent."""
    agent = Agent(
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
    """Run the agent as a Discord bot."""
    from pearscaff.discord_bot import run_bot

    run_bot()


if __name__ == "__main__":
    cli()
