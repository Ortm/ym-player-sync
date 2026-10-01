"""Exact-mirror of cached audio files onto the player directory."""

from __future__ import annotations

import shutil
from pathlib import Path

from .cache import AUDIO_EXTENSIONS, SyncCounts
from ..progress import LiveLine


def sync_player(output_dir: Path, player_dir: Path, dry_run: bool = False) -> SyncCounts:
    """Mirror cached audio onto the player.

    Stale files are deleted FIRST to free space for incoming copies
    (players are usually small); then new/changed files are copied.
    Non-audio files on the player are left alone.
    """
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
    live = LiveLine()
    for f in sorted(player_dir.iterdir()):
        if (
            f.is_file()
            and f.suffix.lower() in AUDIO_EXTENSIONS
            and f.name not in wanted
        ):
            if not dry_run:
                f.unlink()
            counts.removed_player += 1
            live.sticky(f"  [del-player] {f.name} (no longer in playlist)")
    names = sorted(wanted.items())
    total = len(names)
    for i, (name, src) in enumerate(names, 1):
        dst = player_dir / name
        if dst.is_file() and dst.stat().st_size == src.stat().st_size:
            counts.skipped += 1
            live.update(f"  [sync {i}/{total}] — {name}",
                        force=(i == total or i % 25 == 0))
            continue
        try:
            if not dry_run:
                shutil.copy2(src, dst)
        except OSError as e:
            counts.failed += 1
            live.sticky(f"  [fail-player] {name} ({e})")
            continue
        counts.copied += 1
        live.update(f"  [sync {i}/{total}] — {name}",
                    force=(i == total or i % 25 == 0))
    live.close()
    return counts
