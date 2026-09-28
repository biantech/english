#!/usr/bin/env python3
"""Convert incorrectly declared GBK ID3 text fields to ID3v2.3 UTF-16.

Usage examples:

    # Preview every MP3 recursively without changing files.
    python3 fix_id3_latin1_to_utf16.py --dry-run

    # Fix every MP3 recursively and create .mp3.bak backups.
    python3 fix_id3_latin1_to_utf16.py

    # Fix selected files.
    python3 fix_id3_latin1_to_utf16.py 01.mp3 02.mp3

    # Fix another directory without changing the working directory.
    python3 fix_id3_latin1_to_utf16.py --directory /path/to/mp3

    # Do not create backup files (use only after checking the result).
    python3 fix_id3_latin1_to_utf16.py --no-backup

    # Replace existing backup files explicitly.
    python3 fix_id3_latin1_to_utf16.py --overwrite-backup

The source files contain GBK bytes stored in ID3v2.3 frames marked as
Latin-1. The script recovers those bytes, writes the text as UTF-16, and
removes ID3v1 tags for better player compatibility. Audio data is not changed.
"""

from __future__ import annotations

import argparse
import logging
import shutil
from pathlib import Path

from mutagen.id3 import ID3, ID3NoHeaderError


LOGGER = logging.getLogger(__name__)


def recover_gbk(value: str) -> str:
    """Recover a GBK/GB18030 string that was decoded as Latin-1."""
    return value.encode("latin-1").decode("gb18030")


def convert_latin1_frame(frame: object) -> tuple[bool, list[tuple[str, str]]]:
    """Convert one Latin-1 ID3 frame and return visible text changes."""
    if getattr(frame, "encoding", None) != 0 or not hasattr(frame, "text"):
        return False, []

    text = getattr(frame, "text")
    if not isinstance(text, list):
        return False, []

    try:
        recovered = [recover_gbk(value) if isinstance(value, str) else value for value in text]
        changes = [
            (old, new)
            for old, new in zip(text, recovered)
            if isinstance(old, str) and old != new
        ]
        if hasattr(frame, "desc") and isinstance(frame.desc, str):
            old_desc = frame.desc
            frame.desc = recover_gbk(frame.desc)
            if old_desc != frame.desc:
                changes.append((old_desc, frame.desc))
    except (UnicodeEncodeError, UnicodeDecodeError) as error:
        LOGGER.warning("Skipped frame %s: cannot recover GB18030 text: %s", frame.FrameID, error)
        return False, []

    frame.text = recovered
    frame.encoding = 1
    return True, changes


def fix_file(
    path: Path,
    create_backup: bool,
    dry_run: bool,
    overwrite_backup: bool,
) -> bool:
    """Fix one MP3 and return whether at least one frame changed."""
    try:
        tags = ID3(path)
    except ID3NoHeaderError:
        LOGGER.warning("Skipped %s: no ID3 header", path)
        return False
    except Exception as error:
        LOGGER.error("Cannot read ID3 tag from %s: %s", path, error)
        return False

    changed_frames = []
    for frame in tags.values():
        changed, changes = convert_latin1_frame(frame)
        if changed:
            changed_frames.append(frame.FrameID)
            for old, new in changes:
                LOGGER.info("  %s: %r -> %r", frame.FrameID, old, new)

    if not changed_frames:
        LOGGER.info("Skipped %s: no Latin-1 text frame found", path)
        return False

    if dry_run:
        LOGGER.info("Would fix %s: %s", path, ", ".join(changed_frames))
        return True

    backup_path = path.with_name(path.name + ".bak")
    if create_backup:
        if backup_path.exists() and not overwrite_backup:
            LOGGER.error("Skipped %s: backup already exists: %s", path, backup_path)
            return False
        shutil.copy2(path, backup_path)
        LOGGER.info("Created backup: %s", backup_path)

    # ID3v2.3 + UTF-16 is broadly supported, including VOX.
    try:
        tags.save(path, v2_version=3, v1=0)
    except Exception as error:
        LOGGER.error("Cannot save repaired ID3 tag to %s: %s", path, error)
        return False
    LOGGER.info("Fixed %s: %s", path, ", ".join(changed_frames))
    return True


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "files",
        nargs="*",
        type=Path,
        help="MP3 files to fix; defaults to all MP3 files recursively under --directory",
    )
    parser.add_argument(
        "--directory",
        type=Path,
        default=Path(__file__).resolve().parent,
        help="Root directory containing MP3 files",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview changes without modifying files or creating backups",
    )
    parser.add_argument(
        "--no-backup",
        action="store_true",
        help="Do not create .mp3.bak backups",
    )
    parser.add_argument(
        "--overwrite-backup",
        action="store_true",
        help="Replace an existing .mp3.bak backup",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable debug logging",
    )
    return parser.parse_args()


def main() -> int:
    """Configure logging and fix requested files."""
    args = parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s: %(message)s",
    )
    directory = args.directory.expanduser().resolve()
    if not directory.is_dir():
        LOGGER.error("Directory does not exist: %s", directory)
        return 1

    paths = [
        (path if path.is_absolute() else directory / path).resolve()
        for path in args.files
    ] if args.files else sorted(directory.rglob("*.mp3"))
    if not paths:
        LOGGER.error("No MP3 files found in: %s", directory)
        return 1

    fixed = 0
    for path in paths:
        if not path.is_file():
            LOGGER.error("File does not exist: %s", path)
            continue
        if fix_file(
            path,
            create_backup=not args.no_backup,
            dry_run=args.dry_run,
            overwrite_backup=args.overwrite_backup,
        ):
            fixed += 1
    action = "would fix" if args.dry_run else "fixed"
    LOGGER.info("Completed: %s %d of %d file(s)", action, fixed, len(paths))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
