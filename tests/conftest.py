"""Shared fixtures: real (tagless) audio files and a cover image.

Tagging tests need actual containers — mutagen refuses to touch anything
that is not audio — so the suite synthesizes short tones with the bundled
ffmpeg instead of shipping binary blobs.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from ym_player_sync.audio import ffmpeg_exe

# container -> encoder args; a 0.3 s sine is a real file with a real header
CONTAINERS = {
    "flac": ["-c:a", "flac"],
    "mp3": ["-c:a", "libmp3lame", "-b:a", "320k"],
    "m4a": ["-c:a", "aac", "-b:a", "128k"],
}


@pytest.fixture(scope="session")
def audio_templates(tmp_path_factory) -> dict[str, Path]:
    """One tagless file per container, built once for the whole session."""
    directory = tmp_path_factory.mktemp("audio")
    templates = {}
    for extension, encode in CONTAINERS.items():
        path = directory / f"template.{extension}"
        subprocess.run(
            [
                ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-y",
                "-f", "lavfi", "-i", "sine=frequency=440:duration=0.3",
                *encode, str(path),
            ],
            check=True,
            timeout=120,
        )
        templates[extension] = path
    return templates


@pytest.fixture
def make_audio(audio_templates):
    """make_audio(path) -> a fresh copy of the tagless template of that type."""

    def make(dest: Path) -> Path:
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(audio_templates[dest.suffix.lstrip(".")], dest)
        return dest

    return make


@pytest.fixture(scope="session")
def cover_jpeg(tmp_path_factory) -> bytes:
    """A real JPEG, the way a source hands one over."""
    path = tmp_path_factory.mktemp("cover") / "cover.jpg"
    subprocess.run(
        [
            ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "color=c=red:s=64x64", "-frames:v", "1",
            str(path),
        ],
        check=True,
        timeout=60,
    )
    return path.read_bytes()
