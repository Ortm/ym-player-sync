"""Core data models shared by sources, sync, and naming."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Track:
    key: str  # source-local stable id, e.g. "trackId:albumId"
    title: str
    artists: list[str] = field(default_factory=list)
    duration_ms: int = 0

    @property
    def name(self) -> str:
        artist = ", ".join(self.artists)
        return f"{self.title} - {artist}" if artist else self.title


@dataclass
class Variant:
    """One downloadable encoding of a track, as offered by the source."""

    codec: str
    bitrate_kbps: int
    extension: str = ""
    # download locations + optional transport decryption key; interpreted
    # by the source's download().
    urls: list[str] = field(default_factory=list)
    decrypt_key: str | None = None

    def estimated_bytes(self, duration_ms: int) -> int:
        # bitrate(kbit/s) * duration(ms) / 8 = bytes:
        #   kbit/s * 1000 bit/kbit * duration_ms/1000 s / 8 bit/byte
        #   = bitrate_kbps * duration_ms / 8.
        # A zero/unknown bitrate estimates as 0 — callers must not treat
        # that as "free" (see pick_variant defaults + runtime budget stop).
        return self.bitrate_kbps * max(duration_ms, 0) // 8


@dataclass
class PlaylistInfo:
    title: str
    owner: str
    track_keys: list[str]  # ordered, source-local keys


@dataclass
class DesiredTrack:
    track: Track
    variant: Variant
    filename: str = ""  # filled in after limits are applied
    estimated_bytes: int = 0
