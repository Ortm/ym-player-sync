"""PlaylistSource protocol: the seam for adding new music sources.

To add a source (e.g. Spotify, local folder):
  1. Subclass :class:`PlaylistSource` in a new ``sources/<name>.py``.
  2. Register it in :data:`REGISTRY` and extend :func:`detect_source`
     if the source can be guessed from the playlist URL.
  3. Add tests; no other module needs to change.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from ..models import PlaylistInfo, Track, Variant


class SourceError(Exception):
    """Base error for source failures."""


class AuthError(SourceError):
    """Bad/expired credentials."""


class NotFoundError(SourceError):
    """Playlist/track not found or unavailable."""


class PlaylistSource(Protocol):
    """A place playlists can be downloaded from."""

    def set_token(self, token: str) -> None:
        """Receive the API credential (no-op for sources without auth)."""
        ...

    def account_login(self) -> str:
        """Human-readable account id for `info` (may be "?")."""
        ...

    def fetch_playlist(self, url: str) -> PlaylistInfo:
        """Fetch playlist title + ordered track keys. Raises SourceError."""
        ...

    def fetch_tracks(self, keys: list[str]) -> list[Track]:
        """Batch-fetch metadata for keys; skips unavailable tracks,
        preserves playlist order."""
        ...

    def pick_variant(self, track: Track, quality: str) -> Variant:
        """Choose the download variant for a quality tier
        (``lossless`` | ``high`` | ``low``). Raises SourceError when the
        track has nothing downloadable."""
        ...

    def download(self, track: Track, variant: Variant, dest: Path) -> int:
        """Download the track bytes to dest. Returns bytes written."""
        ...


AVAILABLE_SOURCES = ("yandex",)
"""Names usable as the config `source` value / get_source() argument."""


def get_source(name: str) -> PlaylistSource:
    """Instantiate a registered source. Extend REGISTRY to add sources."""
    if name == "yandex":
        from .yandex import YandexSource

        return YandexSource()
    raise ValueError(f"unknown source {name!r} (available: {', '.join(AVAILABLE_SOURCES)})")


def detect_source(url: str) -> PlaylistSource:
    """Guess the source from a playlist URL."""
    if "music.yandex." in url:
        return get_source("yandex")
    raise ValueError(f"cannot detect source from URL: {url!r}")
