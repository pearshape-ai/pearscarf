"""Raw terminal I/O for the non-blocking REPL.

Provides character-by-character input so other threads can print
messages above the prompt without corrupting the display.
"""

from __future__ import annotations

import atexit
import signal
import sys
import termios
import threading
import tty

# Save the original terminal settings at import time so we can
# always restore them, even after a crash or unexpected exit.
_original_termios: list | None = None
try:
    _original_termios = termios.tcgetattr(sys.stdin.fileno())
except Exception:
    pass


def _restore_terminal() -> None:
    """Restore terminal to its original state."""
    if _original_termios is not None:
        try:
            termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, _original_termios)
        except Exception:
            pass


atexit.register(_restore_terminal)

# Also restore on SIGTERM (kill) — SIGKILL can't be caught.
try:
    _prev_sigterm = signal.getsignal(signal.SIGTERM)

    def _sigterm_handler(signum: int, frame: object) -> None:
        _restore_terminal()
        # Re-raise with previous handler or default
        if callable(_prev_sigterm):
            _prev_sigterm(signum, frame)
        else:
            raise SystemExit(1)

    signal.signal(signal.SIGTERM, _sigterm_handler)
except Exception:
    pass


class TerminalUI:
    def __init__(self) -> None:
        self._input_buffer: str = ""
        self._prompt: str = ""
        self._status_line: str = ""
        self._lock = threading.Lock()

    def _write(self, text: str) -> None:
        sys.stdout.write(text)
        sys.stdout.flush()

    def _redraw(self) -> None:
        """Redraw status line (if any) and prompt + input buffer."""
        parts = ""
        if self._status_line:
            parts += self._status_line + "\n"
        parts += self._prompt + self._input_buffer
        self._write(parts)

    def _clear_current_display(self) -> None:
        """Clear the prompt line and status line (if present) from the terminal."""
        # Clear the current line (prompt + input)
        self._write("\r\033[K")
        if self._status_line:
            # Move up one line and clear it (the status line)
            self._write("\033[A\r\033[K")

    def print_above(self, text: str) -> None:
        """Print text above the current prompt. Thread-safe."""
        with self._lock:
            self._clear_current_display()
            self._write(text + "\n")
            self._redraw()

    def set_status(self, text: str) -> None:
        """Update the status line between messages and prompt. Thread-safe."""
        with self._lock:
            old_status = self._status_line
            self._status_line = text
            # Clear current display and redraw with new status
            self._write("\r\033[K")
            if old_status:
                self._write("\033[A\r\033[K")
            self._redraw()

    def clear_status(self) -> None:
        """Remove the status line. Thread-safe."""
        with self._lock:
            if not self._status_line:
                return
            self._write("\r\033[K")
            # Clear the status line above
            self._write("\033[A\r\033[K")
            self._status_line = ""
            self._redraw()

    def read_line(self, prompt: str) -> str:
        """Read a line of input using raw terminal mode.

        Other threads can call print_above() / set_status() while this blocks.
        Supports: printable chars, backspace, Ctrl+C, Ctrl+D.
        """
        with self._lock:
            self._prompt = prompt
            self._input_buffer = ""
            self._redraw()

        fd = sys.stdin.fileno()
        old_settings = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            while True:
                ch = sys.stdin.read(1)
                if ch in ("\r", "\n"):
                    with self._lock:
                        result = self._input_buffer
                        self._input_buffer = ""
                        # Clear status if present before the newline
                        if self._status_line:
                            self._write("\r\033[K\033[A\r\033[K")
                            self._status_line = ""
                        self._write("\r\033[K" + self._prompt + result + "\n")
                    return result
                elif ch in ("\x7f", "\x08"):  # Backspace
                    with self._lock:
                        if self._input_buffer:
                            self._input_buffer = self._input_buffer[:-1]
                            self._write("\b \b")
                elif ch == "\x03":  # Ctrl+C
                    with self._lock:
                        if self._status_line:
                            self._clear_current_display()
                            self._status_line = ""
                        self._write("\n")
                    raise KeyboardInterrupt
                elif ch == "\x04":  # Ctrl+D
                    with self._lock:
                        if self._status_line:
                            self._clear_current_display()
                            self._status_line = ""
                        self._write("\n")
                    raise EOFError
                elif ch >= " " and ord(ch) < 127:  # Printable ASCII
                    with self._lock:
                        self._input_buffer += ch
                        self._write(ch)
                # Ignore other control chars / escape sequences
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
