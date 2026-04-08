"""Gmail connector entry point.

Exposes start(bus) — the only function PearScarf calls to bring the
gmail connector online. Wires the API client into a Poller (started as a
daemon thread) and a Writer, then subscribes to the bus for write-back
requests addressed to the gmail expert. No polling logic, no LLM calls,
just wiring.
"""

from __future__ import annotations

import threading

from pearscarf import log
from pearscarf.bus import MessageBus

from gmailscarf.connector.api_client import create_client
from gmailscarf.connector.poller import GmailPoller
from gmailscarf.connector.writer import GmailWriter


def start(bus: MessageBus) -> threading.Thread | None:
    """Start the Gmail connector.

    Reads OAuth credentials from the environment, instantiates a Poller
    and Writer sharing one API client, starts the Poller as a daemon
    thread, and subscribes to the bus for write-back requests.

    Returns the polling thread, or None if Gmail credentials are missing
    (the connector silently no-ops in that case so PearScarf can still
    boot without Gmail configured).
    """
    client = create_client()
    if client is None:
        log.write(
            "gmail_expert", "--", "warning",
            "Gmail credentials missing — connector not started",
        )
        return None

    poller = GmailPoller(bus, client)
    writer = GmailWriter(client)

    poll_thread = poller.start()

    # TODO: subscribe to bus write-back requests addressed to gmail_expert
    # and route them through writer.handle(action, **kwargs). The bus
    # subscribe API for routed messages is not yet defined; until it
    # lands, the writer is reachable but unsubscribed.
    _ = writer

    log.write("gmail_expert", "--", "action", "Gmail connector started")
    return poll_thread
