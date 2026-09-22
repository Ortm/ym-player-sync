import subprocess

import pytest

from player_converter.audio import (
    ffmpeg_exe,
    needs_transcode,
    output_extension,
    transcode_to_flac,
)


def test_output_extension_maps_m4a_to_flac():
    assert output_extension("m4a") == "flac"
    assert output_extension("flac") == "flac"
    assert output_extension("mp3") == "mp3"


def test_needs_transcode():
    assert needs_transcode("m4a")
    assert not needs_transcode("flac")
    assert not needs_transcode("mp3")


def test_transcode_to_flac_produces_flac(tmp_path):
    # Synthesize a 0.2s tone, wrap as m4a, convert, check FLAC magic.
    exe = ffmpeg_exe()
    src = tmp_path / "in.m4a"
    subprocess.run(
        [exe, "-hide_banner", "-loglevel", "error", "-y",
         "-f", "lavfi", "-i", "sine=frequency=440:duration=0.2",
         "-c:a", "aac", str(src)],
        check=True,
        timeout=120,
    )
    out = transcode_to_flac(src.read_bytes(), "m4a")
    assert out[:4] == b"fLaC"
    assert len(out) > 1000
