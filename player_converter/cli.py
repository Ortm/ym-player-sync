"""player-converter CLI: sync / info."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .config import load_config
from .limits import apply_limits
from .models import DesiredTrack
from .naming import render_filename
from .sources import SourceError, detect_source, get_source
from .sync import sync_cache, sync_player


def _source_for(config):
    source = (
        get_source(config.source)
        if config.source
        else detect_source(config.playlist_url)
    )
    source.set_token(config.token)
    return source


def cmd_info(config) -> int:
    source = _source_for(config)
    try:
        playlist = source.fetch_playlist(config.playlist_url)
    except SourceError as e:
        print(f"Error: {e}")
        return 1
    print(f"Account : {source.account_login()}")
    print(f"Playlist: {playlist.title} (by {playlist.owner})")
    print(f"Tracks  : {len(playlist.track_keys)}")
    if config.max_tracks:
        print(f"Limit   : first {config.max_tracks} tracks")
    if config.max_total_mb:
        print(f"Limit   : {config.max_total_mb} MB total")
    print(f"Quality : {config.quality}")
    return 0


def cmd_sync(config, dry_run: bool) -> int:
    source = _source_for(config)
    try:
        playlist = source.fetch_playlist(config.playlist_url)
    except SourceError as e:
        print(f"Error: {e}")
        return 1

    keys = playlist.track_keys
    print(f"Playlist '{playlist.title}': {len(keys)} track(s)")
    if not keys:
        return 0

    if config.max_tracks:
        keys = keys[: config.max_tracks]
        print(f"  limited to first {len(keys)} track(s)")

    tracks = source.fetch_tracks(keys)
    print(f"  {len(tracks)} available for download")

    # pick variants + estimate sizes, enforcing the total-size cap
    candidates: list[DesiredTrack] = []
    for track in tracks:
        try:
            variant = source.pick_variant(track, config.quality)
        except SourceError as e:
            print(f"  [skip] {track.name}: {e}")
            continue
        candidates.append(
            DesiredTrack(
                track=track,
                variant=variant,
                estimated_bytes=variant.estimated_bytes(track.duration_ms),
            )
        )

    kept = apply_limits(
        candidates,
        [c.estimated_bytes for c in candidates],
        max_tracks=None,  # already applied to keys above
        max_total_mb=config.max_total_mb,
    )
    if config.max_total_mb and len(kept) < len(candidates):
        print(f"  size cap: keeping {len(kept)} of {len(candidates)} tracks")

    width = max(3, len(str(len(kept))))
    for i, d in enumerate(kept, 1):
        d.filename = render_filename(
            config.filename_template, i, width, d.track, d.variant.extension
        )

    def download(d: DesiredTrack, dest: Path) -> int:
        return source.download(d.track, d.variant, dest)

    print(f"\n-- cache: {config.output_dir}")
    counts = sync_cache(config.output_dir, kept, download, dry_run=dry_run)

    print(f"\n-- player: {config.player_dir}")
    player_counts = sync_player(config.output_dir, config.player_dir, dry_run=dry_run)
    counts.copied = player_counts.copied
    counts.removed_player = player_counts.removed_player

    mode = "(dry run) " if dry_run else ""
    print(
        f"\nDone {mode}— {counts.downloaded} downloaded, {counts.renamed} renumbered, "
        f"{counts.skipped} up to date, {counts.removed_cache} removed from cache, "
        f"{counts.copied} copied to player, "
        f"{counts.removed_player} removed from player."
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="player-converter",
        description="Download a Yandex Music playlist and mirror it onto a USB player.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument(
        "-c", "--config", default="config.yaml", help="config file (default: config.yaml)"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_sync = sub.add_parser("sync", help="download playlist and update the player")
    p_sync.add_argument(
        "--dry-run", action="store_true", help="show what would happen, change nothing"
    )
    sub.add_parser("info", help="check token, show playlist summary")

    args = parser.parse_args(argv)

    try:
        config = load_config(args.config)
    except (FileNotFoundError, ValueError) as e:
        print(f"Error: {e}")
        return 2

    if args.command == "info":
        return cmd_info(config)
    if args.command == "sync":
        return cmd_sync(config, dry_run=args.dry_run)
    parser.error(f"unknown command {args.command}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
