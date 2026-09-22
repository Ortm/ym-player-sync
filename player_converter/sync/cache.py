"""Mirror the desired track list into the local cache directory.

Tracks already present under the same name are kept; position changes
become cheap renames (no re-download); anything else managed is deleted.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from ..models import DesiredTrack

AUDIO_EXTENSIONS = (".flac", ".mp3", ".m4a")
STATE_FILENAME = ".player-converter-state.json"


@dataclass
class SyncCounts:
    downloaded: int = 0
    renamed: int = 0
    removed_cache: int = 0
    copied: int = 0
    removed_player: int = 0
    skipped: int = 0


def _load_state(output_dir: Path) -> dict:
    state_file = output_dir / STATE_FILENAME
    if state_file.is_file():
        try:
            return json.loads(state_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {"tracks": {}}


def _save_state(output_dir: Path, state: dict) -> None:
    (output_dir / STATE_FILENAME).write_text(
        json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def sync_cache(
    output_dir: Path,
    desired: list[DesiredTrack],
    download: Callable[[DesiredTrack, Path], int],
    dry_run: bool = False,
) -> SyncCounts:
    """Mirror desired tracks into output_dir. ``download`` writes bytes
    for a DesiredTrack to the given path and returns bytes written."""
    counts = SyncCounts()
    output_dir.mkdir(parents=True, exist_ok=True)
    state = _load_state(output_dir)
    saved: dict[str, dict] = state.get("tracks", {})

    wanted_names = {d.filename for d in desired}
    new_saved: dict[str, dict] = {}

    for d in desired:
        dest = output_dir / d.filename
        prev = saved.get(d.track.key)
        same_quality = (
            prev
            and prev.get("codec") == d.variant.codec
            and prev.get("bitrate_kbps") == d.variant.bitrate_kbps
            # Container changes (e.g. .m4a -> .flac transcoding) are never
            # cheap renames — the bytes must be re-downloaded/converted.
            and Path(prev.get("filename") or "").suffix == Path(d.filename).suffix
        )
        if prev and prev.get("filename") == d.filename and dest.is_file() and same_quality:
            counts.skipped += 1
        elif (
            prev
            and prev.get("filename") != d.filename
            and (output_dir / prev["filename"]).is_file()
            and same_quality
        ):
            old = output_dir / prev["filename"]
            if not dry_run:
                os.replace(old, dest)
            counts.renamed += 1
            print(f"  [renumber] {old.name} -> {d.filename}")
        else:
            size = download(d, dest) if not dry_run else d.estimated_bytes
            counts.downloaded += 1
            print(
                f"  [get] {d.filename} "
                f"({d.variant.codec} {d.variant.bitrate_kbps} kbps, "
                f"~{size / 1_048_576:.1f} MB)"
            )
        new_saved[d.track.key] = {
            "filename": d.filename,
            "codec": d.variant.codec,
            "bitrate_kbps": d.variant.bitrate_kbps,
        }

    for f in sorted(output_dir.iterdir()):
        if f.name == STATE_FILENAME or not f.is_file():
            continue
        if f.suffix.lower() in AUDIO_EXTENSIONS and f.name not in wanted_names:
            if not dry_run:
                f.unlink()
            counts.removed_cache += 1
            print(f"  [del] {f.name} (no longer in playlist)")

    if not dry_run:
        _save_state(output_dir, {"tracks": new_saved})
    return counts
