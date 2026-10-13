"""Embed track metadata — artist/title/album/… and the cover — into files.

A player shows what is playing from the tags *inside* a file, not from its
name: mpd/rmpc reads ARTIST/TITLE/ALBUM from the audio file, and the USB
player does the same. A downloaded file carries no tags at all, so every
file in the cache gets the track's metadata written into it; tags the file
already had (a rip adopted from the player: genre, comment, …) are kept.

Tagging has to read before it writes — an untagged download and an
already-tagged file must be told apart, otherwise every run would rewrite
the whole library and push it to the player again — which is why this uses
mutagen instead of a blind ffmpeg remux.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

import mutagen
from mutagen.flac import FLAC, Picture
from mutagen.id3 import APIC, Frames
from mutagen.mp3 import MP3
from mutagen.mp4 import MP4, MP4Cover

from .models import Track

# pending() pseudo-field: the file carries no cover image yet
COVER = "cover"

# canonical field -> what each container calls it
KEYS = {
    ".flac": {
        "title": "TITLE",
        "artist": "ARTIST",
        "album": "ALBUM",
        "albumartist": "ALBUMARTIST",
        "date": "DATE",
        "tracknumber": "TRACKNUMBER",
        "discnumber": "DISCNUMBER",
    },
    ".mp3": {  # ID3v2 frame names
        "title": "TIT2",
        "artist": "TPE1",
        "album": "TALB",
        "albumartist": "TPE2",
        "date": "TDRC",
        "tracknumber": "TRCK",
        "discnumber": "TPOS",
    },
    ".m4a": {  # MP4 atoms
        "title": "\xa9nam",
        "artist": "\xa9ART",
        "album": "\xa9alb",
        "albumartist": "aART",
        "date": "\xa9day",
        "tracknumber": "trkn",
        "discnumber": "disk",
    },
}

_OPENERS = {".flac": FLAC, ".mp3": MP3, ".m4a": MP4}


class TagError(Exception):
    """The file cannot carry tags: unsupported container or not audio."""


def tag_values(track: Track) -> dict[str, str]:
    """Canonical field -> value; fields the track has no data for are dropped."""
    values = {
        "title": track.title.strip(),
        "artist": "; ".join(a.strip() for a in track.artists if a.strip()),
        "album": track.album.strip(),
        # compilations ("Various Artists") carry their own album artist
        "albumartist": "; ".join(
            a.strip() for a in (track.album_artists or track.artists) if a.strip()
        ),
        "date": str(track.year) if track.year else "",
        "tracknumber": str(track.track_number) if track.track_number else "",
        "discnumber": str(track.disc_number) if track.disc_number else "",
    }
    return {field: value for field, value in values.items() if value}


def _open(path: Path):
    """mutagen file object for a supported container (TagError otherwise)."""
    opener = _OPENERS.get(path.suffix.lower())
    if opener is None:
        raise TagError(
            f"{path.name}: tags are written for "
            f"{', '.join(sorted(_OPENERS))} only"
        )
    try:
        return opener(path)
    except (mutagen.MutagenError, OSError) as e:
        raise TagError(f"{path.name}: {e}") from e


def _text(value: Any) -> str:
    """One tag value as text: mutagen hands back lists, tuples or frames."""
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        if not value:
            return ""
        value = value[0]
    if isinstance(value, tuple):  # MP4 trkn/disk: (number, total)
        value = value[0]
    if isinstance(value, (int, float)):
        return str(int(value))
    return str(value).strip()


def _has_cover(audio: Any) -> bool:
    if isinstance(audio, FLAC):
        return bool(audio.pictures)
    if isinstance(audio, MP4):
        return bool(audio.tags and audio.tags.get("covr"))
    return bool(audio.tags and audio.tags.getall("APIC"))  # MP3


def _cover_mime(data: bytes) -> str:
    if data.startswith(b"\x89PNG"):
        return "image/png"
    if data.startswith(b"GIF8"):
        return "image/gif"
    return "image/jpeg"


def missing_fields(path: Path, track: Track, want_cover: bool = True) -> list[str]:
    """Fields whose tag is absent or different — reads only, never writes."""
    audio = _open(path)
    keys = KEYS[path.suffix.lower()]
    tags = audio.tags if audio.tags is not None else {}
    missing = [
        field
        for field, value in tag_values(track).items()
        if _text(tags.get(keys[field])) != value
    ]
    if want_cover and track.cover_url() and not _has_cover(audio):
        missing.append(COVER)
    return missing


def write_fields(path: Path, track: Track, cover: bytes | None = None) -> None:
    """Write the track's tags (and cover) into the file, keeping other tags."""
    audio = _open(path)
    if audio.tags is None:
        audio.add_tags()
    tags: Any = audio.tags
    values = tag_values(track)
    keys = KEYS[path.suffix.lower()]

    if isinstance(audio, MP3):
        for field, value in values.items():
            tags.add(Frames[keys[field]](encoding=3, text=value))
        if cover:
            tags.add(
                APIC(encoding=3, mime=_cover_mime(cover), type=3, desc="", data=cover)
            )
        # v2.3 + UTF-16: what USB players and taglib both read; v2.4 is
        # still rare on the cheaper end of the market.
        audio.save(v2_version=3)
        return

    for field, value in values.items():
        key = keys[field]
        if isinstance(audio, MP4):
            tags[key] = [(int(value), 0) if key in ("trkn", "disk") else value]
        else:
            tags[key] = value
    if cover:
        mime = _cover_mime(cover)
        if isinstance(audio, MP4):
            tags["covr"] = [
                MP4Cover(
                    cover,
                    imageformat=(
                        MP4Cover.FORMAT_PNG
                        if mime == "image/png"
                        else MP4Cover.FORMAT_JPEG
                    ),
                )
            ]
        else:
            picture = Picture()
            picture.data = cover
            picture.type = 3  # cover (front)
            picture.mime = mime
            audio.add_picture(picture)
    audio.save()


class Tagger:
    """Writes a track's metadata into its cached file.

    Covers are fetched through ``cover_provider`` (None = text tags only):
    one fetch per album, so a whole album costs one request, and a failed
    fetch is not retried for the rest of the run.
    """

    def __init__(
        self, cover_provider: Callable[[Track], bytes | None] | None = None
    ) -> None:
        self.cover_provider = cover_provider
        self._covers: dict[str, bytes | None] = {}

    def pending(self, path: Path, track: Track) -> list[str]:
        """Tag fields still missing from the file (reads only)."""
        return missing_fields(
            path, track, want_cover=self.cover_provider is not None
        )

    def apply(self, path: Path, track: Track, dry_run: bool = False) -> bool:
        """Tag the file. True when something was written (dry run: would be)."""
        fields = self.pending(path, track)
        if not fields:
            return False
        if dry_run:  # report only — never fetches a cover
            return True
        cover = self._cover(track) if COVER in fields else None
        if cover is None and set(fields) == {COVER}:
            # Only the cover was missing and it could not be fetched: leave
            # the file alone, or a dead CDN would rewrite it on every run
            # (and push the whole library to the player again).
            return False
        write_fields(path, track, cover)
        return True

    def _cover(self, track: Track) -> bytes | None:
        url = track.cover_url()
        if not url or self.cover_provider is None:
            return None
        if url not in self._covers:
            try:
                self._covers[url] = self.cover_provider(track)
            except Exception:  # noqa: BLE001 — covers are best-effort
                self._covers[url] = None
        return self._covers[url]
