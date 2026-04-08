"""Linear connector entry point.

Exposes start(bus) — the only function PearScarf calls to bring the
linear connector online. Wires the API client into a Poller (started as
a daemon thread) and a Writer, then subscribes to the bus for write-back
requests addressed to the linear expert. No polling logic, no LLM calls,
just wiring.
"""

from __future__ import annotations

import threading

from pearscarf import log
from pearscarf.bus import MessageBus

from linearscarf.connector.api_client import create_client
from linearscarf.connector.poller import LinearPoller
from linearscarf.connector.writer import LinearWriter


def start(bus: MessageBus) -> threading.Thread | None:
    """Start the Linear connector.

    Reads the API key from the environment, instantiates a Poller and
    Writer sharing one API client, starts the Poller as a daemon thread,
    and subscribes to the bus for write-back requests.

    Returns the polling thread, or None if the Linear API key is missing
    (the connector silently no-ops in that case so PearScarf can still
    boot without Linear configured).
    """
    client = create_client()
    if client is None:
        log.write(
            "linear_expert", "--", "warning",
            "Linear credentials missing — connector not started",
        )
        return None

    poller = LinearPoller(bus, client)
    writer = LinearWriter(client)

    poll_thread = poller.start()

    # TODO: subscribe to bus write-back requests addressed to linear_expert
    # and route them through writer.handle(action, **kwargs). The bus
    # subscribe API for routed messages is not yet defined; until it
    # lands, the writer is reachable but unsubscribed.
    _ = writer

    log.write("linear_expert", "--", "action", "Linear connector started")
    return poll_thread
