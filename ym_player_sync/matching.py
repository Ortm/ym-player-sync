"""Detect already-downloaded files that were saved under a different name.

Used when the sync wants ``003-Title - Artist.mp3`` but the disk still has
``003-Artist - Title.mp3`` (older naming scheme) or a foreign file with no
position prefix at all: instead of downloading again, the file is renamed.

Matching is token-based: the position prefix is stripped, text is
normalized (case-folded, punctuation dropped, ё→е) and the resulting word
multiset must equal the track's ``title + artists`` multiset — so artist
order, separators and punctuation don't matter, but an extra word in the
filename (a different version/mix) does.
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path

from .models import Track

# leading playlist position: "001-", "01. ", "1) ", "003 "
_POSITION_PREFIX = re.compile(r"^\s*\d{1,4}(?:\s*[-–—_.)\]]+\s*|\s+)")
_NON_WORD = re.compile(r"[\W_]+", re.UNICODE)


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).casefold().replace("ё", "е")
    return " ".join(_NON_WORD.sub(" ", text).split())


def strip_position_prefix(stem: str) -> str:
    """Remove a leading track-number prefix ("001-", "01. ", "1) ")."""
    return _POSITION_PREFIX.sub("", stem, count=1).strip()


def tokens(text: str) -> tuple[str, ...]:
    """Order-insensitive word multiset of a name."""
    return tuple(sorted(normalize(text).split()))


def track_tokens(track: Track) -> tuple[str, ...]:
    return tokens(" ".join([track.title, *track.artists]))


def find_by_name(
    directory: Path,
    track: Track,
    extension: str,
    exclude: set[Path] | None = None,
    exclude_names: set[str] | None = None,
) -> Path | None:
    """First file in directory that holds this track under any name.

    Only files with the wanted extension qualify — a different container
    means a different quality tier and must be re-downloaded.
    ``exclude_names`` shields files that are already the destination of
    another queued track (duplicate titles in one playlist).
    """
    if not directory.is_dir():
        return None
    wanted = track_tokens(track)
    if not wanted:
        return None
    exclude = exclude or set()
    exclude_names = exclude_names or set()
    suffix = f".{extension.lower().lstrip('.')}"
    for path in sorted(directory.iterdir()):
        if not path.is_file() or path in exclude or path.name in exclude_names:
            continue
        if path.suffix.lower() != suffix:
            continue
        if tokens(strip_position_prefix(path.stem)) == wanted:
            return path
        if tokens(path.stem) == wanted:
            return path
    return None
