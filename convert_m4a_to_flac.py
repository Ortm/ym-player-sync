#!/usr/bin/env python3
"""
Recursively find all .m4a files in a source directory and convert them
to .flac, placing every output file flat in a single output directory.
Files with the same name are overwritten.
"""

import argparse
import subprocess
import re
import sys
from pathlib import Path


def convert_file(src: Path, dst: Path, dry_run: bool = False) -> bool:
    """Convert a single .m4a to .flac. Returns True on success."""
    if dry_run:
        tag = "[overwrite]" if dst.exists() else "[convert]"
        print(f"  {tag} {src} → {dst}")
        return True

    cmd = [
        "ffmpeg",
        "-i", str(src),
        "-c:a", "flac",
        "-compression_level", "8",
        "-map_metadata", "0",
        "-y",  # overwrite without asking
        str(dst),
    ]

    result = subprocess.run(cmd, capture_output=True)
    if result.returncode != 0:
        stderr = result.stderr.decode("utf-8", errors="replace")
        print(f"  [error] {src.name}: {stderr.splitlines()[-1] if stderr else 'unknown error'}")
        return False

    src_mb = src.stat().st_size / 1_048_576
    dst_mb = dst.stat().st_size / 1_048_576
    print(f"  [ok] {src.name}  ({src_mb:.1f} MB → {dst_mb:.1f} MB)")
    return True


def main():
    parser = argparse.ArgumentParser(
        description="Recursively convert .m4a → .flac, all output in one flat directory."
    )
    parser.add_argument(
        "source_dir",
        nargs="?",
        default=".",
        help="Directory to search recursively for .m4a files (default: current directory)",
    )
    parser.add_argument(
        "output_dir",
        help="Directory where all .flac files will be written (flat, no subfolders)",
    )
    parser.add_argument(
        "--delete-source",
        action="store_true",
        help="Delete each .m4a after successful conversion.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would happen without converting anything.",
    )
    args = parser.parse_args()

    source_dir = Path(args.source_dir).resolve()
    output_dir = Path(args.output_dir).resolve()

    if not source_dir.is_dir():
        sys.exit(f"Error: source '{source_dir}' is not a directory.")

    if not args.dry_run:
        output_dir.mkdir(parents=True, exist_ok=True)

    files = sorted(source_dir.rglob("*.m4a"))
    if not files:
        print(f"No .m4a files found under '{source_dir}'.")
        return

    print(f"Found {len(files)} .m4a file(s) — output → '{output_dir}'")
    if args.dry_run:
        print("(dry-run mode — nothing will be changed)\n")

    ok = failed = 0

    for src in files:
        stem = re.sub(r"^\d+\s*-\s*", "", src.stem)
        dst = output_dir / f"{stem}.flac"
        success = convert_file(src, dst, dry_run=args.dry_run)
        if success:
            ok += 1
            if args.delete_source and not args.dry_run:
                src.unlink()
                print(f"         deleted source: {src}")
        else:
            failed += 1

    print(f"\nDone — {ok} converted, {failed} failed.")


if __name__ == "__main__":
    main()