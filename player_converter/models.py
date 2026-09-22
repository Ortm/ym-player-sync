"""Core data models shared by sources, sync, and naming."""

from __future__ import annotations

from dataclasses import dataclass, field

CODEC_EXTENSIONS = {"flac": "flac", "mp3": "mp3", "aac": "m4a"}


@dataclass
class Track:
    key: str  # source-local stable id, e.g. "trackId:albumId"
    title: str
    artists: list[str] = field(default_factory=list)
    duration_ms: int = 0

    @property
    def name(self) -> str:
        artist = ", ".join(self.artists)
        return f"{artist} - {self.title}" if artist else self.title


@dataclass
class Variant:
    """One downloadable encoding of a track offered by the source."""

    codec: str
    bitrate_kbps: int
    extension: str = ""
    # source-private payload (e.g. Yandex download-info URL); the source
    # interprets it when downloading.
    ref: str = ""
    preview: bool = False

    def __post_init__(self) -> None:
        if not self.extension:
            self.extension = CODEC_EXTENSIONS.get(self.codec, self.codec)

    def estimated_bytes(self, duration_ms: int) -> int:
        # bitrate(kbit/s) * duration(ms) / 8000 = bytes
        return self.bitrate_kbps * max(duration_ms, 0) // 8000


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
