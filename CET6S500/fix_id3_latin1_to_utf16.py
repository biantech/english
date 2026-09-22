#!/usr/bin/env python3
"""Convert incorrectly declared GBK ID3 text fields to ID3v2.3 UTF-16.

Usage examples:

    # Fix every MP3 in the current directory and create .bak backups.
    python3 fix_id3_latin1_to_utf16.py

    # Fix selected files.
    python3 fix_id3_latin1_to_utf16.py 01.mp3 02.mp3

    # Fix another directory without changing the working directory.
    python3 fix_id3_latin1_to_utf16.py --directory /path/to/mp3

    # Do not create backup files (use only after checking the result).
    python3 fix_id3_latin1_to_utf16.py --no-backup

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
    """Recover a GBK string that was decoded as Latin-1."""
    return value.encode("latin-1").decode("gbk")


def convert_latin1_frame(frame: object) -> bool:
    """Convert one Latin-1 ID3 frame to UTF-16 when all text is recoverable."""
    if getattr(frame, "encoding", None) != 0 or not hasattr(frame, "text"):
        return False

    text = getattr(frame, "text")
    if not isinstance(text, list):
        return False

    try:
        recovered = [recover_gbk(value) if isinstance(value, str) else value for value in text]
        if hasattr(frame, "desc") and isinstance(frame.desc, str):
            frame.desc = recover_gbk(frame.desc)
    except (UnicodeEncodeError, UnicodeDecodeError) as error:
        LOGGER.warning("Skipped frame %s: cannot recover GBK text: %s", frame.FrameID, error)
        return False

    frame.text = recovered
    frame.encoding = 1
    return True


def fix_file(path: Path, create_backup: bool) -> bool:
    """Fix one MP3 and return whether at least one frame changed."""
    try:
        tags = ID3(path)
    except ID3NoHeaderError:
        LOGGER.warning("Skipped %s: no ID3 header", path.name)
        return False

    changed_frames = []
    for frame in tags.values():
        if convert_latin1_frame(frame):
            changed_frames.append(frame.FrameID)

    if not changed_frames:
        LOGGER.info("Skipped %s: no Latin-1 text frame found", path.name)
        return False

    backup_path = path.with_name(path.name + ".bak")
    if create_backup:
        shutil.copy2(path, backup_path)
        LOGGER.info("Created backup: %s", backup_path)

    # ID3v2.3 + UTF-16 is broadly supported, including VOX.
    tags.save(path, v2_version=3, v1=0)
    LOGGER.info("Fixed %s: %s", path.name, ", ".join(changed_frames))
    return True


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "files",
        nargs="*",
        type=Path,
        help="MP3 files to fix; defaults to all MP3 files in --directory",
    )
    parser.add_argument(
        "--directory",
        type=Path,
        default=Path(__file__).resolve().parent,
        help="Directory containing MP3 files",
    )
    parser.add_argument(
        "--no-backup",
        action="store_true",
        help="Do not create .mp3.bak backups",
    )
    return parser.parse_args()


def main() -> int:
    """Configure logging and fix requested files."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    args = parse_args()
    directory = args.directory.expanduser().resolve()
    if not directory.is_dir():
        LOGGER.error("Directory does not exist: %s", directory)
        return 1

    paths = [
        (path if path.is_absolute() else directory / path).resolve()
        for path in args.files
    ] if args.files else sorted(directory.glob("*.mp3"))
    if not paths:
        LOGGER.error("No MP3 files found in: %s", directory)
        return 1

    fixed = 0
    for path in paths:
        if not path.is_file():
            LOGGER.error("File does not exist: %s", path)
            continue
        if fix_file(path, create_backup=not args.no_backup):
            fixed += 1
    LOGGER.info("Completed: fixed %d of %d file(s)", fixed, len(paths))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
