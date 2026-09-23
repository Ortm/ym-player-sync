"""Mirror the desired track list into the local cache directory.

Tracks already present under the same name are kept; position changes
become cheap renames (no re-download); anything else managed is deleted.
"""

from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor
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
    failed: int = 0


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


def _state_entry(d: DesiredTrack) -> dict:
    return {
        "filename": d.filename,
        "codec": d.variant.codec,
        "bitrate_kbps": d.variant.bitrate_kbps,
    }


def _download_all(
    download: Callable[[DesiredTrack, Path], int],
    pending: list[tuple[DesiredTrack, Path]],
    dry_run: bool,
    workers: int,
) -> list[tuple[DesiredTrack, Path, int, Exception | None]]:
    """Fetch pending tracks, returning (track, dest, size, error) in order.

    With workers > 1 downloads run in threads; results are still resolved
    in playlist order so output stays readable and state stays ordered.
    """
    if dry_run:
        return [(d, dest, d.estimated_bytes, None) for d, dest in pending]
    if workers <= 1 or len(pending) <= 1:
        out = []
        for d, dest in pending:
            try:
                out.append((d, dest, download(d, dest), None))
            except Exception as e:  # noqa: BLE001 — per-track tolerance
                out.append((d, dest, 0, e))
        return out
    print(f"  downloading {len(pending)} track(s) with {workers} workers")
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = [(d, dest, pool.submit(download, d, dest)) for d, dest in pending]
        out = []
        for d, dest, fut in futs:
            try:
                out.append((d, dest, fut.result(), None))
            except Exception as e:  # noqa: BLE001 — per-track tolerance
                out.append((d, dest, 0, e))
        return out


def sync_cache(
    output_dir: Path,
    desired: list[DesiredTrack],
    download: Callable[[DesiredTrack, Path], int],
    dry_run: bool = False,
    workers: int = 1,
) -> SyncCounts:
    """Mirror desired tracks into output_dir. ``download`` writes bytes
    for a DesiredTrack to the given path and returns bytes written.
    ``workers`` parallelizes downloads (threads; 1 = sequential)."""
    counts = SyncCounts()
    output_dir.mkdir(parents=True, exist_ok=True)
    state = _load_state(output_dir)
    saved: dict[str, dict] = state.get("tracks", {})

    wanted_names = {d.filename for d in desired}
    new_saved: dict[str, dict] = {}
    pending: list[tuple[DesiredTrack, Path]] = []

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
            new_saved[d.track.key] = _state_entry(d)
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
            new_saved[d.track.key] = _state_entry(d)
        else:
            pending.append((d, dest))

    for d, dest, size, error in _download_all(download, pending, dry_run, workers):
        if error is not None:
            # One bad track (stalled host, corrupt stream, transcode
            # error) skips instead of aborting the sync; it stays out
            # of the state so the next run retries it.
            counts.failed += 1
            print(f"  [fail] {d.filename} ({error})")
            continue
        counts.downloaded += 1
        print(
            f"  [get] {d.filename} "
            f"({d.variant.codec} {d.variant.bitrate_kbps} kbps, "
            f"~{size / 1_048_576:.1f} MB)"
        )
        new_saved[d.track.key] = _state_entry(d)

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
