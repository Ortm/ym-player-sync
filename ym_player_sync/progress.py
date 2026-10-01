"""Single-line refreshing progress output.

``LiveLine`` rewrites the current terminal line instead of spamming one
line per track. Persistent events (failures, cap stops, deletions) go
through :meth:`sticky`, which prints above the live line.

Portability notes (learned the hard way on Windows conhost):

- No ANSI escape codes — plain ``\\r`` + space padding erases the old
  tail, which works even without virtual-terminal processing.
- Messages are truncated to the terminal width (wide CJK chars count
  double), because a wrapped line can't be rewound with ``\\r`` and each
  update would spill onto a new line.

On non-TTY output (pipes, CI logs, pytest capture) rewriting is
impossible, so ``update`` stays silent unless ``force=True`` — callers
pass that every N items so logs still show a heartbeat.
"""

from __future__ import annotations

import shutil
import sys
import unicodedata
from typing import TextIO


def _char_width(char: str) -> int:
    return 2 if unicodedata.east_asian_width(char) in ("W", "F") else 1


def _display_width(text: str) -> int:
    return sum(_char_width(c) for c in text)


def _term_width(default: int = 80) -> int:
    try:
        return max(40, shutil.get_terminal_size().columns)
    except (AttributeError, ValueError, OSError):
        return default


def fit_width(msg: str, width: int | None = None) -> str:
    """Cut ``msg`` (from the end) so its display width fits ``width``."""
    limit = width if width is not None else _term_width()
    if _display_width(msg) <= limit:
        return msg
    out: list[str] = []
    used = 0
    for char in msg:
        char_w = _char_width(char)
        if used + char_w > limit - 1:
            break
        out.append(char)
        used += char_w
    return "".join(out)


class LiveLine:
    def __init__(self, stream: TextIO | None = None, enabled: bool | None = None) -> None:
        self.stream = stream if stream is not None else sys.stdout
        if enabled is None:
            try:
                enabled = self.stream.isatty()
            except (AttributeError, ValueError):
                enabled = False
        self.enabled = enabled
        self._drawn_len = 0
        self._last = ""

    def update(self, msg: str, force: bool = False) -> None:
        """Refresh the live line. No-op on non-TTY unless ``force``."""
        if self.enabled:
            line = fit_width(msg)
            pad = max(0, self._drawn_len - _display_width(line))
            self.stream.write("\r" + line + " " * pad)
            self.stream.flush()
            self._drawn_len = _display_width(line)
            self._last = line
        elif force:
            self.stream.write(msg + "\n")
            self.stream.flush()

    def sticky(self, msg: str) -> None:
        """Print a persistent line above the live line."""
        if self.enabled and self._drawn_len:
            self.stream.write("\r" + " " * self._drawn_len + "\r")
            self.stream.write(msg + "\n")
            if self._last:
                self.stream.write(self._last)
            self.stream.flush()
        else:
            self.stream.write(msg + "\n")
            self.stream.flush()

    def close(self) -> None:
        """End the live line so the next print starts on a fresh line."""
        if self.enabled and self._drawn_len:
            self.stream.write("\n")
            self.stream.flush()
            self._drawn_len = 0
