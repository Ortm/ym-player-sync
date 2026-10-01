"""Player-safe filename helpers (FAT32/vfat friendly)."""

from __future__ import annotations

import re

from .models import Track

_BAD_CHARS = re.compile(r'[\\/:*?"<>|\x00-\x1f]')
_TRAILING_DOTS = re.compile(r"[. ]+$")


def sanitize_name(name: str) -> str:
    """Make a string safe for player filesystems."""
    name = _BAD_CHARS.sub("_", name)
    name = re.sub(r"\s+", " ", name).strip()
    name = _TRAILING_DOTS.sub("", name)
    return name or "untitled"


def render_filename(
    template: str, position: int, width: int, track: Track, ext: str
) -> str:
    """Render the filename template.

    Fields: {position} (1-based int), {width} (zero-pad width),
    {name} ("Title - Artist"), {title}, {artists}, {ext}.
    """
    return template.format(
        position=position,
        width=width,
        name=sanitize_name(track.name),
        title=sanitize_name(track.title),
        artists=sanitize_name(", ".join(track.artists)),
        ext=ext,
    )


def queue_width(total_tracks: int, max_tracks: int | None = None) -> int:
    """Zero-pad width for ``{position}`` numbering.

    Derived from the full queue size *before* the size cap — never from
    the kept count — so estimate jitter around a power of 10 can't flip
    the width and rename the whole library every other run.
    """
    base = max_tracks if max_tracks else total_tracks
    return max(3, len(str(max(base, 0))))
