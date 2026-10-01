"""ym-player-sync CLI: sync / info."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .audio import output_extension
from .config import default_config_path, load_config
from .limits import apply_limits
from .models import DesiredTrack
from .naming import queue_width, render_filename
from .progress import LiveLine
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


def _quality_tiers(quality: str) -> tuple[str, ...]:
    """Tiers to try, best first (a denied tier falls back to a lower one)."""
    try:
        from .sources.yandex import QUALITY_FALLBACK
    except ImportError:
        QUALITY_FALLBACK = {}
    tiers = QUALITY_FALLBACK.get(quality)
    return tuple(tiers) if tiers else (quality,)


def cmd_download(config, dry_run: bool) -> int:
    """Stage 1 (online): fetch the playlist and fill the local cache."""
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
    denied = 0
    est_total = 0
    total_tracks = len(tracks)
    vlive = LiveLine()

    def _variant_progress(done: int) -> str:
        bits = [f"{done}/{total_tracks} tracks"]
        if config.max_tracks:
            tpct = done / config.max_tracks * 100 if config.max_tracks else 0
            bits[0] += f" (cap {config.max_tracks}, {tpct:.0f}%)"
        if config.max_total_mb:
            cap = config.max_total_mb * 1_048_576
            mpct = est_total / cap * 100 if cap else 0
            bits.append(f"~{est_total / 1_048_576:.0f}/{config.max_total_mb:.0f} MB ({mpct:.0f}%)")
        else:
            bits.append(f"~{est_total / 1_048_576:.0f} MB")
        return " | ".join(bits)

    for n, track in enumerate(tracks, 1):
        variant = None
        last_error: SourceError | None = None
        tried: list[str] = []
        for tier in _quality_tiers(config.quality):
            tried.append(tier)
            try:
                variant = source.pick_variant(track, tier)
                break
            except ValueError:
                raise
            except SourceError as e:
                last_error = e
                # Only fall back on access/availability errors; other
                # failures (network, unknown codec) stop at this tier.
                if "not-allowed" not in str(e) and "denied" not in str(e):
                    break
                continue
        if variant is None:
            if last_error is not None and "denied" in str(last_error):
                denied += 1
            vlive.sticky(f"  [skip] {track.name}: {last_error}")
            continue
        if len(tried) > 1:
            vlive.sticky(f"  [downgrade] {track.name}: {tried[0]} -> {tried[-1]}")
        est = variant.estimated_bytes(track.duration_ms)
        est_total += est
        candidates.append(
            DesiredTrack(
                track=track,
                variant=variant,
                estimated_bytes=est,
            )
        )
        vlive.update(f"  variants: {_variant_progress(n)} — {track.name}",
                     force=(n == total_tracks or n % 25 == 0))
    vlive.close()

    if denied and not candidates:
        print(
            "  All downloads were denied (403 not-allowed). This means the "
            "token's Yandex account has no file-download rights — usually no "
            "active Yandex Plus/Premium. Web playback still works, but the "
            "API won't hand out file URLs on any tier. Fix: activate Plus on "
            f"this account ({source.account_login()}) or use a token from an "
            "account that has it, then re-run download."
        )
    kept = apply_limits(
        candidates,
        [c.estimated_bytes for c in candidates],
        max_tracks=None,  # already applied to keys above
        max_total_mb=config.max_total_mb,
    )
    if config.max_total_mb:
        est_mb = sum(c.estimated_bytes for c in candidates) / 1_048_576
        kept_mb = sum(c.estimated_bytes for c in kept) / 1_048_576
        if len(kept) < len(candidates):
            print(
                f"  size cap: keeping {len(kept)} of {len(candidates)} tracks "
                f"(~{kept_mb:.0f} of ~{est_mb:.0f} MB estimated, cap {config.max_total_mb:.0f} MB)"
            )
        else:
            print(f"  size estimate: ~{est_mb:.0f} MB for {len(candidates)} tracks")

    # Stable width from the full queue, not the kept count (see queue_width).
    width = queue_width(len(tracks), config.max_tracks)
    for i, d in enumerate(kept, 1):
        d.filename = render_filename(
            config.filename_template, i, width, d.track,
            output_extension(d.variant.extension),
        )

    def download(d: DesiredTrack, dest: Path) -> int:
        return source.download(d.track, d.variant, dest)

    print(f"\n-- cache: {config.output_dir}")
    cap_bytes = (
        int(config.max_total_mb * 1_048_576) if config.max_total_mb else None
    )
    if config.max_tracks or cap_bytes:
        parts = []
        if config.max_tracks:
            parts.append(f"tracks 0/{config.max_tracks} (0%)")
        if cap_bytes:
            parts.append(f"size 0.0/{config.max_total_mb:.0f} MB (0.0%)")
        print(f"  limits: {' | '.join(parts)} — {len(kept)} queued")
    counts = sync_cache(
        config.output_dir, kept, download,
        dry_run=dry_run, workers=config.workers,
        adopt_from=[config.player_dir],
        max_total_bytes=cap_bytes,
        max_tracks=config.max_tracks,
    )

    mode = "(dry run) " if dry_run else ""
    limits_fill = ""
    if config.max_tracks or cap_bytes:
        bits = []
        if config.max_tracks:
            tpct = counts.total_tracks / config.max_tracks * 100 if config.max_tracks else 0
            bits.append(f"{counts.total_tracks}/{config.max_tracks} tracks ({tpct:.0f}%)")
        if cap_bytes:
            mpct = counts.total_bytes / cap_bytes * 100 if cap_bytes else 0
            bits.append(
                f"{counts.total_bytes / 1_048_576:.1f}/{config.max_total_mb:.0f} MB ({mpct:.1f}%)"
            )
        limits_fill = f" Limits: {' | '.join(bits)}."
    print(
        f"\nDone {mode}— {counts.downloaded} downloaded, {counts.matched} renamed, "
        f"{counts.adopted} recovered from player, {counts.renamed} renumbered, "
        f"{counts.skipped} up to date, {counts.failed} failed, "
        f"{counts.removed_cache} removed from cache.{limits_fill}"
    )
    return 0


def cmd_sync(config, dry_run: bool) -> int:
    """Stage 2 (offline): mirror the cache onto the player."""
    print(f"-- player: {config.player_dir}")
    try:
        counts = sync_player(config.output_dir, config.player_dir, dry_run=dry_run)
    except FileNotFoundError as e:
        print(f"Error: {e}")
        return 1

    mode = "(dry run) " if dry_run else ""
    print(
        f"\nDone {mode}— {counts.copied} copied to player, "
        f"{counts.removed_player} removed from player, "
        f"{counts.skipped} up to date, {counts.failed} failed."
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="ym-player-sync",
        description="Download a Yandex Music playlist and mirror it onto a USB player.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument(
        "-c",
        "--config",
        default=None,
        help=(
            "config file (default: ./config.yaml, falling back to "
            "~/.config/ym-player-sync/config.yaml)"
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_download = sub.add_parser("download", help="fetch playlist into the local cache")
    p_download.add_argument(
        "--dry-run", action="store_true", help="show what would happen, change nothing"
    )
    p_sync = sub.add_parser("sync", help="mirror the cache onto the player (offline)")
    p_sync.add_argument(
        "--dry-run", action="store_true", help="show what would happen, change nothing"
    )
    sub.add_parser("info", help="check token, show playlist summary")

    args = parser.parse_args(argv)

    try:
        config = load_config(args.config or default_config_path())
    except (FileNotFoundError, ValueError) as e:
        print(f"Error: {e}")
        return 2

    if args.command == "info":
        return cmd_info(config)
    if args.command == "download":
        return cmd_download(config, dry_run=args.dry_run)
    if args.command == "sync":
        return cmd_sync(config, dry_run=args.dry_run)
    parser.error(f"unknown command {args.command}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
