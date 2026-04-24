"""Consumer — base class for channel consumers.

A Consumer subscribes to a channel (records in a state, a queue table, a
bus topic, an external API) and acts per message. Two overrides per
subclass:

    def _next(self) -> Any | None:   # poll the channel; return one message, or None
    def _handle(self, msg) -> None:  # do the work for one message

The base class owns the lifecycle (start / stop / run_foreground), the
poll loop, and the sleep cadence between empty polls. Subclasses don't
touch threading.
"""

from __future__ import annotations

import threading
import traceback
from abc import ABC, abstractmethod
from typing import Any

from pearscarf import log
from pearscarf.tracked_call import (
    _consumer_var,
    _runtime_id_var,
    register_runtime,
)


class Consumer(ABC):
    """Base class: subscribes to a channel, acts per message."""

    # Subclasses override to change the default sleep between empty polls.
    # Callers can still override per-instance via the constructor kwarg.
    default_poll_interval: float = 5.0

    # Subclasses set this to the channel name used for logging.
    name: str = "consumer"

    # Per-consumer LLM-run turn ceiling. None = fall back to the global
    # MAX_TURNS (30 by default). Subclasses override to tighten.
    max_turns: int | None = None

    def __init__(self, poll_interval: float | None = None) -> None:
        self._poll_interval = (
            poll_interval if poll_interval is not None else self.default_poll_interval
        )
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @abstractmethod
    def _next(self) -> Any | None:
        """Return the next message to process, or None if the channel is empty."""

    @abstractmethod
    def _handle(self, msg: Any) -> None:
        """Process a single message. Exceptions are logged; the loop continues."""

    def _setup(self) -> None:  # noqa: B027 — intentional optional hook, not abstract
        """Optional one-shot setup before the loop starts (e.g. init_db).

        Called once from _loop before the first poll. Override if needed.
        """

    def _loop(self) -> None:
        # Register one `runtimes` row for this Consumer boot and set the
        # ContextVars that `tracked_call` reads. ContextVar scope is per-
        # thread/async-task, so doing this inside _loop (which runs in the
        # Consumer's own thread under start(), or the main thread under
        # run_foreground()) is the right place.
        self._runtime_id = register_runtime(self.name)
        _runtime_id_var.set(self._runtime_id)
        _consumer_var.set(self.name)

        try:
            self._setup()
        except Exception:
            log.write(self.name, "--", "error", "setup failed")
            traceback.print_exc()
            return

        while not self._stop.is_set():
            try:
                msg = self._next()
            except Exception:
                log.write(self.name, "--", "error", "_next raised")
                traceback.print_exc()
                self._stop.wait(self._poll_interval)
                continue

            if msg is None:
                self._stop.wait(self._poll_interval)
                continue

            try:
                self._handle(msg)
            except Exception:
                log.write(self.name, "--", "error", "_handle raised")
                traceback.print_exc()
                # Don't sleep — drain remaining work even if one message failed.

    def start(self) -> None:
        """Start the consumer on a daemon thread."""
        self._thread = threading.Thread(target=self._loop, name=self.name, daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        """Signal stop and join the thread."""
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=timeout)

    def run_foreground(self) -> None:
        """Run the loop in the foreground (blocking). Ctrl-C stops cleanly."""
        try:
            self._loop()
        except KeyboardInterrupt:
            pass
