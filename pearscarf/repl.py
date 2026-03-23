from __future__ import annotations

import threading

import click

from pearscarf import __version__, log, status
from pearscarf.bus import MessageBus
from pearscarf.terminal import TerminalUI

def _color(text: str, fg: str) -> str:
    """Apply click-style ANSI color without a trailing reset quirk."""
    return click.style(text, fg=fg)


class SessionRepl:
    def __init__(self, bus: MessageBus) -> None:
        self._bus = bus
        self._active_session: str | None = None
        self._stop = threading.Event()
        self._ui = TerminalUI()

    def _ensure_session(self) -> str:
        if not self._active_session:
            self._active_session = self._bus.create_session("human", "New session")
        return self._active_session

    def _prompt_str(self) -> str:
        session_id = self._active_session or "none"
        return _color(f"[{session_id}]", "blue") + " you > "

    # --- Background threads ---

    def _poll_responses(self) -> None:
        """Background thread: polls for messages addressed to human."""
        while not self._stop.is_set():
            try:
                messages = self._bus.poll("human")
                for msg in messages:
                    session_id = msg["session_id"]
                    from_agent = msg["from_agent"]
                    content = msg["content"]

                    log.write(
                        "human",
                        session_id,
                        "message_received",
                        f"from={from_agent}: {content[:200]}",
                    )

                    if session_id == self._active_session:
                        prefix = (
                            _color(f"[{session_id}]", "blue")
                            + " "
                            + _color(from_agent, "magenta")
                            + " > "
                        )
                        formatted = prefix + content
                        self._ui.print_above(formatted)
                    else:
                        line = _color(
                            f"--- [{session_id}] {from_agent}: {content[:80]} ---",
                            "yellow",
                        )
                        self._ui.print_above(line)
            except Exception:
                pass
            self._stop.wait(1)

    def _poll_status(self) -> None:
        """Background thread: updates the status line with agent activity."""
        while not self._stop.is_set():
            try:
                session = self._active_session
                if session:
                    activity = status.get_activity(session)
                    if activity:
                        agent, text, elapsed = activity
                        secs = int(elapsed)
                        status_text = (
                            _color(f"[{session}]", "blue")
                            + " "
                            + _color(f"{agent} {text}... ({secs}s)", "yellow")
                        )
                        self._ui.set_status(status_text)
                    else:
                        self._ui.clear_status()
            except Exception:
                pass
            self._stop.wait(1)

    # --- Commands ---

    def _handle_command(self, text: str) -> bool:
        """Handle REPL commands. Returns True if handled."""
        parts = text.strip().split(maxsplit=1)
        cmd = parts[0]

        if cmd == "/sessions":
            sessions = self._bus.list_sessions()
            if not sessions:
                self._ui.print_above("No sessions.")
            else:
                for s in sessions:
                    marker = " *" if s["id"] == self._active_session else ""
                    self._ui.print_above(
                        f"  {s['id']}{marker}  initiated_by={s['initiated_by']}  {s['summary']}"
                    )
            return True

        if cmd == "/switch":
            if len(parts) < 2:
                self._ui.print_above("Usage: /switch <session_id>")
                return True
            target = parts[1]
            session = self._bus.get_session(target)
            if not session:
                self._ui.print_above(f"Session {target} not found.")
            else:
                self._active_session = target
                self._ui.print_above(f"Switched to {target}")
            return True

        if cmd == "/new":
            self._active_session = self._bus.create_session("human", "New session")
            self._ui.print_above(f"Created {self._active_session}")
            return True

        if cmd == "/history":
            target = parts[1] if len(parts) > 1 else self._active_session
            if not target:
                self._ui.print_above("No active session.")
                return True
            history = self._bus.get_history(target)
            if not history:
                self._ui.print_above("No messages.")
            else:
                for msg in history:
                    direction = _color(msg["from_agent"], "cyan")
                    arrow = " -> "
                    to = _color(msg["to_agent"], "green")
                    self._ui.print_above(
                        f"  {direction}{arrow}{to}: {msg['content'][:120]}"
                    )
            return True

        if cmd == "/memory":
            self._handle_memory_command(text)
            return True

        return False

    def _handle_memory_command(self, text: str) -> None:
        """Handle /memory subcommands."""
        from pearscarf.cli_memory import (
            _get_all,
            _get_entity,
            _get_memories_for_record,
            _graph_stats,
            _search,
            format_entity,
            format_graph_stats,
            format_memory_list,
            format_record_memories,
            format_search_results,
        )

        subparts = text.split(maxsplit=2)
        subcmd = subparts[1] if len(subparts) > 1 else "help"
        arg = subparts[2] if len(subparts) > 2 else ""

        if subcmd == "help":
            self._ui.print_above("Memory commands:")
            self._ui.print_above("  /memory list [limit]     — List stored memories")
            self._ui.print_above("  /memory search <query>   — Search memories")
            self._ui.print_above("  /memory entity <name>    — Look up entity")
            self._ui.print_above("  /memory graph            — Graph overview")
            self._ui.print_above("  /memory record <id>      — Memories from a record")
            return

        try:
            if subcmd == "list":
                limit = int(arg) if arg.isdigit() else 10
                results = _get_all(limit=limit)
                for line in format_memory_list(results):
                    self._ui.print_above(line)

            elif subcmd == "search":
                if not arg:
                    self._ui.print_above("Usage: /memory search <query>")
                    return
                results = _search(arg, limit=10)
                for line in format_search_results(results):
                    self._ui.print_above(line)

            elif subcmd == "entity":
                if not arg:
                    self._ui.print_above("Usage: /memory entity <name>")
                    return
                entity = _get_entity(arg)
                for line in format_entity(entity):
                    self._ui.print_above(line)

            elif subcmd == "graph":
                stats = _graph_stats()
                for line in format_graph_stats(stats):
                    self._ui.print_above(line)

            elif subcmd == "record":
                if not arg:
                    self._ui.print_above("Usage: /memory record <record_id>")
                    return
                results = _get_memories_for_record(arg)
                for line in format_record_memories(results):
                    self._ui.print_above(line)

            else:
                self._ui.print_above(f"Unknown memory command: {subcmd}. Type /memory help.")
        except Exception as exc:
            self._ui.print_above(f"Memory error: {exc}")

    # --- Main loop ---

    def run(self) -> None:
        self._ensure_session()

        # Start background threads
        poll_thread = threading.Thread(
            target=self._poll_responses, name="repl-poll", daemon=True
        )
        poll_thread.start()

        status_thread = threading.Thread(
            target=self._poll_status, name="repl-status", daemon=True
        )
        status_thread.start()

        self._ui.println(f"PearScarf v{__version__} (type 'exit' or Ctrl+C to quit)")
        self._ui.println("Commands: /sessions, /switch <id>, /new, /history [id], /memory")
        self._ui.println("")

        try:
            while True:
                text = self._ui.read_line(self._prompt_str())

                text = text.strip()
                if not text:
                    continue

                if text.lower() in ("exit", "quit"):
                    break

                if text.startswith("/"):
                    if self._handle_command(text):
                        continue

                # Send message to worker
                session = self._ensure_session()
                log.write("human", session, "message_sent", f"to=worker: {text[:200]}")
                self._bus.send(
                    session_id=session,
                    from_agent="human",
                    to_agent="worker",
                    content=text,
                    reasoning="Human input from REPL",
                )

        except (KeyboardInterrupt, EOFError):
            click.echo("\nbye.")
        finally:
            self._stop.set()
