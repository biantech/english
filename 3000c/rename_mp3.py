#!/usr/bin/env python3
"""Rename Unit */Group *.mp3 files to group{unit:02d}{group}.mp3.

The script previews changes by default. Pass --execute to perform the rename.
"""

from __future__ import annotations

import argparse
import logging
import re
from pathlib import Path


UNIT_PATTERN = re.compile(r"^unit\s*(\d+)$", re.IGNORECASE)
GROUP_PATTERN = re.compile(r"^group\s*(\d+)\.mp3$", re.IGNORECASE)
logger = logging.getLogger(__name__)


def collect_renames(root: Path) -> list[tuple[Path, Path]]:
    """Collect source and destination paths without changing the filesystem."""
    renames: list[tuple[Path, Path]] = []

    for unit_dir in sorted(root.iterdir()):
        if not unit_dir.is_dir():
            continue

        unit_match = UNIT_PATTERN.fullmatch(unit_dir.name)
        if unit_match is None:
            continue
        unit_number = int(unit_match.group(1))

        for source in sorted(unit_dir.iterdir()):
            if not source.is_file():
                continue
            group_match = GROUP_PATTERN.fullmatch(source.name)
            if group_match is None:
                continue

            group_number = int(group_match.group(1))
            destination = unit_dir / f"group{unit_number:02d}{group_number}.mp3"
            if source != destination:
                renames.append((source, destination))

    return renames


def rename_files(renames: list[tuple[Path, Path]], execute: bool) -> int:
    """Log planned operations and optionally apply them."""
    if not renames:
        logger.info("No matching MP3 files found.")
        return 0

    target_sources: dict[Path, list[Path]] = {}
    for source, destination in renames:
        target_sources.setdefault(destination, []).append(source)

    conflicts = [(source, destination) for source, destination in renames if destination.exists()]
    duplicate_targets = {
        destination
        for destination, sources in target_sources.items()
        if len(sources) > 1
    }
    for destination in sorted(duplicate_targets):
        sources = ", ".join(str(source) for source in target_sources[destination])
        logger.warning("SKIP (duplicate target: %s -> %s)", sources, destination)

    if conflicts:
        for source, destination in conflicts:
            logger.warning("SKIP (target exists): %s -> %s", source, destination)

    pending = [
        (source, destination)
        for source, destination in renames
        if not destination.exists() and destination not in duplicate_targets
    ]
    for source, destination in pending:
        action = "RENAME" if execute else "PREVIEW"
        logger.info("%s: %s -> %s", action, source, destination)

    if execute:
        for source, destination in pending:
            source.rename(destination)
        skipped = len(renames) - len(pending)
        logger.info("Renamed %d file(s); skipped %d file(s).", len(pending), skipped)
    else:
        skipped = len(renames) - len(pending)
        logger.info("Previewed %d file(s); %d file(s) would be skipped.", len(pending), skipped)
        logger.info("Run with --execute to apply these changes.")

    return 0


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parent,
        help="Directory containing Unit folders (default: script directory)",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually rename files; without this flag only preview changes",
    )
    args = parser.parse_args()

    root = args.root.resolve()
    if not root.is_dir():
        logger.error("Root directory does not exist: %s", root)
        return 1

    return rename_files(collect_renames(root), args.execute)


if __name__ == "__main__":
    raise SystemExit(main())
