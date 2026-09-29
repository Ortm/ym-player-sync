"""Audio post-processing: keep player-compatible formats.

Some players (including this project's target USB player) don't play
.m4a (MP4 container). Downloaded variants with such extensions are
transcoded to FLAC on the fly — for FLAC-in-MP4 sources this is a
lossless repackaging; for AAC sources it's a compatibility transcode
(quality can't exceed the source).
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

# downloaded extension -> extension stored in cache / copied to player
OUTPUT_EXTENSIONS = {
    "m4a": "flac",
}


def output_extension(ext: str) -> str:
    """Map a server-side extension to the stored one (identity default)."""
    return OUTPUT_EXTENSIONS.get(ext.lower().lstrip("."), ext)


def needs_transcode(ext: str) -> bool:
    return output_extension(ext) != ext


def ffmpeg_exe() -> str:
    """Path to an ffmpeg binary (bundled imageio-ffmpeg, else PATH)."""
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        pass
    found = shutil.which("ffmpeg")
    if found:
        return found
    raise RuntimeError(
        "ffmpeg is required to convert m4a downloads to FLAC "
        "(pip install imageio-ffmpeg or install system ffmpeg)"
    )


def transcode_to_flac(data: bytes, src_ext: str = "m4a") -> bytes:
    """Transcode one audio blob (e.g. ALAC/AAC-in-MP4) to FLAC bytes."""
    exe = ffmpeg_exe()
    with tempfile.TemporaryDirectory(prefix="music-sync-") as tmp:
        src = Path(tmp) / f"in.{src_ext.lstrip('.') or 'm4a'}"
        dst = Path(tmp) / "out.flac"
        src.write_bytes(data)
        proc = subprocess.run(
            [
                exe,
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-i",
                str(src),
                "-c:a",
                "flac",
                "-compression_level",
                "5",
                str(dst),
            ],
            capture_output=True,
            timeout=300,
        )
        if proc.returncode != 0:
            raise RuntimeError(
                f"ffmpeg m4a->flac failed: {proc.stderr.decode()[:300]}"
            )
        return dst.read_bytes()
