#!/usr/bin/env python3
"""Move MP3 files from subdirectories into the root directory.

The script previews changes by default. Pass --execute to perform the move.
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path


logger = logging.getLogger(__name__)


def collect_moves(root: Path) -> list[tuple[Path, Path]]:
    """Collect MP3 files below root and their destinations in root."""
    moves: list[tuple[Path, Path]] = []
    for source in root.rglob("*"):
        if not source.is_file() or source.suffix.lower() != ".mp3":
            continue
        if source.parent == root:
            continue
        moves.append((source, root / source.name))
    return sorted(moves)


def move_files(moves: list[tuple[Path, Path]], execute: bool) -> int:
    """Log planned moves and optionally apply them."""
    if not moves:
        logger.info("No MP3 files found in subdirectories.")
        return 0

    target_sources: dict[Path, list[Path]] = {}
    for source, destination in moves:
        target_sources.setdefault(destination, []).append(source)

    duplicate_targets = {
        destination
        for destination, sources in target_sources.items()
        if len(sources) > 1
    }
    existing_targets = {
        destination for destination in target_sources if destination.exists()
    }

    for destination in sorted(duplicate_targets):
        sources = ", ".join(str(source) for source in target_sources[destination])
        logger.warning("SKIP (duplicate target): %s -> %s", sources, destination)
    for source, destination in moves:
        if destination in existing_targets and destination not in duplicate_targets:
            logger.warning("SKIP (target exists): %s -> %s", source, destination)

    pending = [
        (source, destination)
        for source, destination in moves
        if destination not in duplicate_targets
        and destination not in existing_targets
    ]
    for source, destination in pending:
        action = "MOVE" if execute else "PREVIEW"
        logger.info("%s: %s -> %s", action, source, destination)

    skipped = len(moves) - len(pending)
    if execute:
        for source, destination in pending:
            source.rename(destination)
        logger.info("Moved %d file(s); skipped %d file(s).", len(pending), skipped)
    else:
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
        help="Root directory that will receive the MP3 files",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually move files; without this flag only preview changes",
    )
    args = parser.parse_args()

    root = args.root.resolve()
    if not root.is_dir():
        logger.error("Root directory does not exist: %s", root)
        return 1
    return move_files(collect_moves(root), args.execute)


if __name__ == "__main__":
    raise SystemExit(main())
