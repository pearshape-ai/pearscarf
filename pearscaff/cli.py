from __future__ import annotations

import click


@click.group()
def cli() -> None:
    """pearscaff: Operational infrastructure that grows itself."""


if __name__ == "__main__":
    cli()
