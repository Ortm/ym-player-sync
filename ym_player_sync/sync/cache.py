"""Mirror the desired track list into the local cache directory.

Tracks already present under the same name are kept; position changes,
new naming schemes and foreign filenames become cheap renames (no
re-download); anything else managed is deleted, so a max_tracks /
max_total_mb run also prunes whatever no longer fits the queue.
"""

from __future__ import annotations

import json
import os
import shutil
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

from ..matching import find_by_name
from ..models import DesiredTrack
from ..progress import LiveLine

AUDIO_EXTENSIONS = (".flac", ".mp3", ".m4a")
STATE_FILENAME = ".ym-player-sync-state.json"


@dataclass
class SyncCounts:
    downloaded: int = 0
    renamed: int = 0
    matched: int = 0  # renamed from a different filename instead of re-downloading
    adopted: int = 0  # recovered from the player dir into the cache
    removed_cache: int = 0
    copied: int = 0
    removed_player: int = 0
    skipped: int = 0
    failed: int = 0
    total_tracks: int = 0  # secured tracks this run (reused + downloaded)
    total_bytes: int = 0  # actual bytes secured this run


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
    adopt_from: Iterable[Path] = (),
    max_total_bytes: int | None = None,
    max_tracks: int | None = None,
) -> SyncCounts:
    """Mirror desired tracks into output_dir. ``download`` writes bytes
    for a DesiredTrack to the given path and returns bytes written.
    ``workers`` parallelizes downloads (threads; 1 = sequential).
    ``adopt_from`` lists extra directories (e.g. the player) searched for
    a same-track file under a different name before downloading.
    ``max_total_bytes`` is a hard stop on actual bytes secured this run
    (reused + downloaded); once exceeded, remaining tracks are skipped
    and pruned. It backs the estimate-based ``max_total_mb`` pre-filter
    for cases where estimates are off (VBR, transcoded m4a->flac).
    ``max_tracks`` is display-only here (truncation happens upstream);
    it feeds the tracks-limit progress readout."""
    counts = SyncCounts()
    output_dir.mkdir(parents=True, exist_ok=True)
    state = _load_state(output_dir)
    saved: dict[str, dict] = state.get("tracks", {})
    live = LiveLine()

    cap_mb = f"{max_total_bytes / 1_048_576:.0f}" if max_total_bytes is not None else "?"

    wanted_names = {d.filename for d in desired}
    new_saved: dict[str, dict] = {}
    pending: list[tuple[DesiredTrack, Path]] = []
    claimed: set[Path] = set()  # files taken by another track this run

    budget_bytes = 0
    budget_count = 0
    stopped_early = False

    def _file_size(p: Path, fallback: int) -> int:
        if dry_run:
            return fallback
        try:
            return p.stat().st_size
        except OSError:
            return fallback

    def _over_budget(next_size: int) -> bool:
        return (
            max_total_bytes is not None
            and budget_count >= 1
            and budget_bytes + max(next_size, 0) > max_total_bytes
        )

    def _progress() -> str:
        """Compact limits fill, e.g. '12/500 tracks (2%) | 345/6000 MB (6%)'."""
        if max_tracks is not None:
            tpct = (budget_count / max_tracks * 100) if max_tracks else 0.0
            tpart = f"{budget_count}/{max_tracks} tracks ({tpct:.0f}%)"
        else:
            tpart = f"{budget_count}/{len(desired)} tracks"
        if max_total_bytes is not None:
            mpct = (budget_bytes / max_total_bytes * 100) if max_total_bytes else 0.0
            mpart = (
                f"{budget_bytes / 1_048_576:.1f}/{max_total_bytes / 1_048_576:.0f} MB "
                f"({mpct:.1f}%)"
            )
        else:
            mpart = f"{budget_bytes / 1_048_576:.1f} MB"
        return f"{tpart} | {mpart}"

    def _drop_from_here(index: int) -> None:
        nonlocal stopped_early
        stopped_early = True
        for rest in desired[index:]:
            wanted_names.discard(rest.filename)

    def _tick(name: str, index: int) -> None:
        # One refreshing line; piped logs get every 25th as a heartbeat.
        live.update(f"  {_progress()} — {name}",
                    force=(index + 1 == len(desired) or index % 25 == 0))

    if max_total_bytes is not None:
        print("  budget cap set: securing in playlist order (newest first)")

    for index, d in enumerate(desired):
        if stopped_early:
            break
        dest = output_dir / d.filename
        prev = saved.get(d.track.key)
        # names other queued tracks own: never cannibalize those files
        protected = wanted_names - {d.filename}
        same_quality = (
            prev
            and prev.get("codec") == d.variant.codec
            and prev.get("bitrate_kbps") == d.variant.bitrate_kbps
            # Container changes (e.g. .m4a -> .flac transcoding) are never
            # cheap renames — the bytes must be re-downloaded/converted.
            and Path(prev.get("filename") or "").suffix == Path(d.filename).suffix
        )
        if prev and prev.get("filename") == d.filename and dest.is_file() and same_quality:
            size = _file_size(dest, d.estimated_bytes)
            if _over_budget(size):
                live.sticky(f"  [cap] {d.filename} (over {cap_mb} MB budget, skipped) [{_progress()}]")
                _drop_from_here(index)
                break
            counts.skipped += 1
            new_saved[d.track.key] = _state_entry(d)
            budget_bytes += size
            budget_count += 1
            _tick(d.filename, index)
        elif (
            prev
            and prev.get("filename") != d.filename
            and (output_dir / prev["filename"]).is_file()
            and same_quality
        ):
            old = output_dir / prev["filename"]
            size = _file_size(old, d.estimated_bytes)
            if _over_budget(size):
                live.sticky(f"  [cap] {d.filename} (over {cap_mb} MB budget, skipped) [{_progress()}]")
                _drop_from_here(index)
                break
            if not dry_run:
                os.replace(old, dest)
            claimed.add(old)
            counts.renamed += 1
            new_saved[d.track.key] = _state_entry(d)
            budget_bytes += size
            budget_count += 1
            _tick(f"{old.name} -> {d.filename}", index)
        elif (
            found := _find_elsewhere(d, output_dir, adopt_from, claimed, protected)
        ) is not None:
            src, where = found
            size = _file_size(src, d.estimated_bytes)
            if _over_budget(size):
                live.sticky(f"  [cap] {d.filename} (over {cap_mb} MB budget, skipped) [{_progress()}]")
                _drop_from_here(index)
                break
            if not dry_run:
                if where == output_dir:
                    os.replace(src, dest)
                else:
                    shutil.copy2(src, dest)
            claimed.add(src)
            new_saved[d.track.key] = _state_entry(d)
            budget_bytes += size
            budget_count += 1
            if where == output_dir:
                counts.matched += 1
            else:
                counts.adopted += 1
            _tick(f"{src.name} -> {d.filename}", index)
        else:
            if max_total_bytes is None:
                pending.append((d, dest))
                continue
            # Capped path: download right here, in playlist order, so a
            # new track near the top wins budget before older cached
            # tracks further down can consume it. (Uncapped runs keep the
            # parallel batch below.)
            if _over_budget(d.estimated_bytes):
                live.sticky(f"  [cap] {d.filename} (over {cap_mb} MB budget, stopping) [{_progress()}]")
                _drop_from_here(index)
                break
            if dry_run:
                size = d.estimated_bytes
            else:
                try:
                    size = download(d, dest)
                except Exception as e:  # noqa: BLE001 — per-track tolerance
                    counts.failed += 1
                    live.sticky(f"  [fail] {d.filename} ({e})")
                    continue
            counts.downloaded += 1
            new_saved[d.track.key] = _state_entry(d)
            budget_bytes += size
            budget_count += 1
            _tick(f"{d.filename} (~{size / 1_048_576:.1f} MB)", index)
            if budget_bytes > max_total_bytes:
                # Estimates were low (e.g. m4a->flac inflation) — stop,
                # keep this track, drop everything below it.
                live.sticky(f"  [cap] budget reached at {_progress()} — older tracks skipped")
                _drop_from_here(index + 1)
                break

    # Uncapped path only: capped downloads already happened inline above
    # in playlist order, so `pending` is non-empty just here.
    if max_total_bytes is None:
        total_pending = len(pending)
        for seq, (d, dest, size, error) in enumerate(
            _download_all(download, pending, dry_run, workers), 1
        ):
            if error is not None:
                # One bad track (stalled host, corrupt stream, transcode
                # error) skips instead of aborting the sync; it stays out
                # of the state so the next run retries it.
                counts.failed += 1
                live.sticky(f"  [fail] {d.filename} ({error})")
                continue
            counts.downloaded += 1
            budget_bytes += size
            budget_count += 1
            new_saved[d.track.key] = _state_entry(d)
            live.update(f"  [{seq}/{total_pending}] {_progress()} — {d.filename}",
                        force=(seq == total_pending or seq % 25 == 0))

    # Delete every managed file that is not part of the current queue —
    # this is what enforces the track-count / total-size limits. Leftover
    # .part temp files from interrupted downloads go too.
    for f in sorted(output_dir.iterdir()):
        if f.name == STATE_FILENAME or not f.is_file():
            continue
        if f in claimed:
            continue  # already renamed away during this run
        if f.name.endswith(".part"):
            if not dry_run:
                f.unlink()
            counts.removed_cache += 1
            live.sticky(f"  [del] {f.name} (leftover partial download)")
            continue
        if f.suffix.lower() in AUDIO_EXTENSIONS and f.name not in wanted_names:
            if not dry_run:
                f.unlink()
            counts.removed_cache += 1
            live.sticky(f"  [del] {f.name} (not in queue)")

    counts.total_tracks = budget_count
    counts.total_bytes = budget_bytes
    live.close()
    if max_tracks is not None or max_total_bytes is not None:
        print(f"  limits: {_progress()}")

    if not dry_run:
        _save_state(output_dir, {"tracks": new_saved})
    return counts


def _find_elsewhere(
    d: DesiredTrack,
    output_dir: Path,
    adopt_from: Iterable[Path],
    claimed: set[Path],
    protected_names: set[str],
) -> tuple[Path, Path] | None:
    """Locate this track's audio under a different name.

    Returns (source path, directory it lives in), preferring the cache.
    The stored extension (what ``filename`` ends with) is what must
    match — a transcoded track is never a cheap rename.
    """
    extension = Path(d.filename).suffix.lstrip(".") or d.variant.extension
    match = find_by_name(
        output_dir,
        d.track,
        extension,
        exclude=claimed,
        exclude_names=protected_names,
    )
    if match is not None:
        return match, output_dir
    for directory in adopt_from:
        if directory == output_dir:
            continue
        match = find_by_name(
            directory,
            d.track,
            extension,
            exclude=claimed,
            exclude_names=protected_names,
        )
        if match is not None:
            return match, directory
    return None
