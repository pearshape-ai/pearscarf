from __future__ import annotations

import threading
import time

import click

from pearscaff.bus import MessageBus


class SessionRepl:
    def __init__(self, bus: MessageBus) -> None:
        self._bus = bus
        self._active_session: str | None = None
        self._stop = threading.Event()
        self._poll_thread: threading.Thread | None = None

    def _ensure_session(self) -> str:
        if not self._active_session:
            self._active_session = self._bus.create_session("human", "New session")
        return self._active_session

    def _poll_responses(self) -> None:
        """Background thread: polls for messages addressed to human."""
        while not self._stop.is_set():
            try:
                messages = self._bus.poll("human")
                for msg in messages:
                    session_id = msg["session_id"]
                    from_agent = msg["from_agent"]
                    content = msg["content"]

                    if session_id == self._active_session:
                        click.echo(
                            f"\n{click.style(from_agent, fg='magenta')} > {content}\n"
                        )
                    else:
                        # Notification for a different session
                        click.echo(
                            click.style(
                                f"\n--- NEW MESSAGE {session_id}: {from_agent} — {content[:80]} ---\n",
                                fg="yellow",
                            )
                        )
            except Exception:
                pass
            self._stop.wait(1)

    def _handle_command(self, text: str) -> bool:
        """Handle REPL commands. Returns True if handled."""
        parts = text.strip().split(maxsplit=1)
        cmd = parts[0]

        if cmd == "/sessions":
            sessions = self._bus.list_sessions()
            if not sessions:
                click.echo("No sessions.")
            else:
                for s in sessions:
                    marker = " *" if s["id"] == self._active_session else ""
                    click.echo(
                        f"  {s['id']}{marker}  initiated_by={s['initiated_by']}  {s['summary']}"
                    )
            return True

        if cmd == "/switch":
            if len(parts) < 2:
                click.echo("Usage: /switch <session_id>")
                return True
            target = parts[1]
            session = self._bus.get_session(target)
            if not session:
                click.echo(f"Session {target} not found.")
            else:
                self._active_session = target
                click.echo(f"Switched to {target}")
            return True

        if cmd == "/new":
            self._active_session = self._bus.create_session("human", "New session")
            click.echo(f"Created {self._active_session}")
            return True

        if cmd == "/history":
            target = parts[1] if len(parts) > 1 else self._active_session
            if not target:
                click.echo("No active session.")
                return True
            history = self._bus.get_history(target)
            if not history:
                click.echo("No messages.")
            else:
                for msg in history:
                    direction = click.style(msg["from_agent"], fg="cyan")
                    arrow = click.style(" → ", fg="white")
                    to = click.style(msg["to_agent"], fg="green")
                    click.echo(f"  {direction}{arrow}{to}: {msg['content'][:120]}")
                    if msg["reasoning"]:
                        click.echo(
                            click.style(f"    reasoning: {msg['reasoning']}", fg="yellow")
                        )
            return True

        return False

    def run(self) -> None:
        self._ensure_session()

        # Start background polling
        self._poll_thread = threading.Thread(
            target=self._poll_responses, name="repl-poll", daemon=True
        )
        self._poll_thread.start()

        click.echo("pearscaff (type 'exit' or Ctrl+C to quit)")
        click.echo("Commands: /sessions, /switch <id>, /new, /history [id]\n")

        try:
            while True:
                session_id = self._active_session or "none"
                user_input = click.prompt(
                    click.style(f"[{session_id}]", fg="blue"),
                    prompt_suffix=" > ",
                )

                text = user_input.strip()
                if not text:
                    continue

                if text.lower() in ("exit", "quit"):
                    break

                if text.startswith("/"):
                    if self._handle_command(text):
                        continue

                # Send message to worker
                session = self._ensure_session()
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
