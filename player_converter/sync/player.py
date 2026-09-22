"""Exact-mirror of cached audio files onto the player directory."""

from __future__ import annotations

import shutil
from pathlib import Path

from .cache import AUDIO_EXTENSIONS, SyncCounts


def sync_player(output_dir: Path, player_dir: Path, dry_run: bool = False) -> SyncCounts:
    """Copy new/changed audio files to the player, delete stale ones.
    Non-audio files on the player are left alone."""
    counts = SyncCounts()
    if not player_dir.is_dir():
        raise FileNotFoundError(
            f"player dir not found: {player_dir} — is the player mounted?"
        )
    wanted = {
        f.name: f
        for f in output_dir.iterdir()
        if f.is_file() and f.suffix.lower() in AUDIO_EXTENSIONS
    }
    for name, src in sorted(wanted.items()):
        dst = player_dir / name
        if dst.is_file() and dst.stat().st_size == src.stat().st_size:
            counts.skipped += 1
            continue
        if not dry_run:
            shutil.copy2(src, dst)
        counts.copied += 1
        print(f"  [copy] {name}")
    for f in sorted(player_dir.iterdir()):
        if (
            f.is_file()
            and f.suffix.lower() in AUDIO_EXTENSIONS
            and f.name not in wanted
        ):
            if not dry_run:
                f.unlink()
            counts.removed_player += 1
            print(f"  [del-player] {f.name} (no longer in playlist)")
    return counts
