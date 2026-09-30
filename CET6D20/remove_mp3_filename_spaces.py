#!/usr/bin/env python3
"""Remove spaces from MP3 filenames in the CET6Day20 directory.

Usage:
    # Preview the rename operations without changing files.
    python3 remove_mp3_filename_spaces.py --dry-run

    # Rename MP3 files in this script's directory.
    python3 remove_mp3_filename_spaces.py

    # Process another directory.
    python3 remove_mp3_filename_spaces.py --directory /path/to/CET6Day20

Only filename spaces are removed. File contents and ID3 tags are unchanged.
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path


LOGGER = logging.getLogger(__name__)


def configure_logging(verbose: bool) -> None:
    """Configure console logging."""
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(levelname)s: %(message)s",
    )


def rename_mp3_files(directory: Path, dry_run: bool) -> tuple[int, int]:
    """Remove spaces from MP3 filenames and return renamed and skipped counts."""
    renamed = 0
    skipped = 0

    for source in sorted(directory.glob("*.mp3"), key=lambda path: path.name.casefold()):
        target_name = source.name.replace(" ", "")
        target = source.with_name(target_name)

        if source == target:
            LOGGER.debug("No spaces: %s", source.name)
            continue
        if target.exists():
            LOGGER.error("Target already exists, skipped: %s -> %s", source.name, target.name)
            skipped += 1
            continue

        if dry_run:
            LOGGER.info("Would rename: %s -> %s", source.name, target.name)
        else:
            source.rename(target)
            LOGGER.info("Renamed: %s -> %s", source.name, target.name)
        renamed += 1

    return renamed, skipped


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--directory",
        type=Path,
        default=Path(__file__).resolve().parent,
        help="Directory containing MP3 files (default: script directory)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview renames without changing files",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable debug logging",
    )
    return parser.parse_args()


def main() -> int:
    """Run the filename cleanup command."""
    args = parse_args()
    configure_logging(args.verbose)
    directory = args.directory.expanduser().resolve()

    if not directory.is_dir():
        LOGGER.error("Directory does not exist: %s", directory)
        return 1

    renamed, skipped = rename_mp3_files(directory, args.dry_run)
    action = "would rename" if args.dry_run else "renamed"
    LOGGER.info("Finished: %d file(s) %s, %d skipped", renamed, action, skipped)
    return 0 if skipped == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
