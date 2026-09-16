#!/usr/bin/env python3
"""Add proportional timestamps to the kaoyanfw20 LRC files.

Examples:

    # Update every LRC in the directory and create *.lrc.bak backups.
    python3 add_lrc_timestamps.py

    # Write results to another directory without changing source files.
    python3 add_lrc_timestamps.py --output-dir /tmp/kaoyanfw20_lrc

The script maps 1-01.lrc to the unique 1-01-*.mp3 row in
mp3_duration_list.csv. The LRC title is the matching MP3 filename without its
extension. Blank lines and redundant whitespace are removed, while the single
spaces required between English words are retained. Timestamps are allocated
by sentence length and scaled to the corresponding MP3 duration.
"""

from __future__ import annotations

import argparse
import csv
import logging
import re
import shutil
from pathlib import Path


TIMESTAMP_PATTERN = re.compile(r"\[\d+:\d{2}(?:\.\d{1,3})?\]")
TITLE_PATTERN = re.compile(r"^\[ti:.*]$", re.IGNORECASE)
SEGMENT_SPLIT_PATTERN = re.compile(r"(?<=[,;.!?。！？；])\s+")
ABBREVIATIONS = ("Mr.", "Mrs.", "Ms.", "Dr.", "Prof.", "St.")
ABBREVIATION_DOT = "<LRC_DOT>"
logger = logging.getLogger(__name__)


def load_durations(csv_path: Path) -> dict[str, tuple[str, float]]:
    """Load LRC stem to MP3 stem and duration mappings from CSV."""
    mappings: dict[str, tuple[str, float]] = {}
    with csv_path.open("r", encoding="utf-8-sig", newline="") as csv_file:
        for row in csv.DictReader(csv_file):
            filename = (row.get("filename") or "").strip()
            seconds_text = (row.get("total_seconds") or "").strip()
            if not filename or not seconds_text:
                continue
            mp3_stem = Path(filename).stem
            match = re.match(r"^(\d+-\d+)-", mp3_stem)
            if not match:
                logger.warning("Skipped MP3 with unsupported filename: %s", filename)
                continue
            lrc_stem = match.group(1)
            if lrc_stem in mappings:
                raise ValueError(f"Multiple MP3 files match {lrc_stem}.lrc")
            mappings[lrc_stem] = (mp3_stem, float(seconds_text))
    return mappings


def clean_source_text(content: str) -> str:
    """Remove existing LRC metadata/timestamps and normalize whitespace."""
    parts: list[str] = []
    for raw_line in content.splitlines():
        line = raw_line.strip().lstrip("\ufeff")
        if not line or TITLE_PATTERN.fullmatch(line):
            continue
        line = TIMESTAMP_PATTERN.sub("", line).strip()
        if line:
            parts.append(line)
    return re.sub(r"\s+", " ", " ".join(parts)).strip()


def split_sentences(text: str) -> list[str]:
    """Split on sentence-ending punctuation without splitting common titles."""
    protected = text
    for abbreviation in ABBREVIATIONS:
        protected = protected.replace(abbreviation, abbreviation[:-1] + ABBREVIATION_DOT)
    protected = re.sub(r"(?<=\d)\.(?=\d)", ABBREVIATION_DOT, protected)
    candidates = SEGMENT_SPLIT_PATTERN.split(protected)
    sentences: list[str] = []
    for candidate in candidates:
        sentence = candidate.replace(ABBREVIATION_DOT, ".").strip()
        if sentence and sentence[-1] in ",;.!?。！？；":
            sentences.append(sentence)
        elif sentence:
            logger.warning("Ignored text without sentence terminator: %s", sentence)
    return sentences


def format_timestamp(milliseconds: int) -> str:
    """Format milliseconds as an LRC timestamp."""
    minutes, remainder = divmod(max(0, milliseconds), 60_000)
    seconds, milliseconds = divmod(remainder, 1_000)
    return f"{minutes:02d}:{seconds:02d}.{milliseconds // 10:02d}"


def build_lrc(title: str, sentences: list[str], total_seconds: float) -> str:
    """Build LRC timestamps weighted by the preceding sentence length."""
    weights = [len(re.sub(r"\s+", "", sentence)) for sentence in sentences]
    total_weight = sum(weights)
    if not total_weight:
        raise ValueError("No complete sentences were found")
    milliseconds_per_character = total_seconds * 1_000 / total_weight
    elapsed = 0
    lines = [f"[ti:{title}]"]
    for sentence, weight in zip(sentences, weights):
        lines.append(f"[{format_timestamp(elapsed)}]{sentence}")
        elapsed += round(weight * milliseconds_per_character)
    return "\n".join(lines) + "\n"


def output_path_for(lrc_path: Path, output_dir: Path | None) -> Path:
    """Resolve the destination and preserve the source before in-place edits."""
    if output_dir is not None:
        output_dir.mkdir(parents=True, exist_ok=True)
        return output_dir / lrc_path.name
    backup_path = lrc_path.with_suffix(lrc_path.suffix + ".bak")
    if not backup_path.exists():
        shutil.copy2(lrc_path, backup_path)
        logger.info("Created backup: %s", backup_path)
    return lrc_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--directory",
        type=Path,
        default=Path("/Users/bianjq/github/english/kaoyanfw20"),
        help="Directory containing LRC, MP3, and duration CSV files",
    )
    parser.add_argument("--csv", type=Path, help="Duration CSV path")
    parser.add_argument("--output-dir", type=Path, help="Optional destination directory")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    directory = args.directory.resolve()
    csv_path = (args.csv or directory / "mp3_duration_list.csv").resolve()
    if not directory.is_dir():
        logger.error("Directory does not exist: %s", directory)
        return 1
    if not csv_path.is_file():
        logger.error("Duration CSV does not exist: %s", csv_path)
        return 1

    try:
        mappings = load_durations(csv_path)
    except (OSError, UnicodeError, ValueError) as exc:
        logger.error("Could not read duration CSV: %s", exc)
        return 1

    processed = 0
    failed = 0
    for lrc_path in sorted(directory.glob("*.lrc")):
        prefix_match = re.match(r"^(\d+-\d+)(?:-|$)", lrc_path.stem)
        mapping = mappings.get(prefix_match.group(1)) if prefix_match else None
        if mapping is None:
            logger.warning("No matching MP3 duration for %s", lrc_path.name)
            failed += 1
            continue
        mp3_title, total_seconds = mapping
        try:
            text = clean_source_text(lrc_path.read_text(encoding="utf-8-sig"))
            sentences = split_sentences(text)
            destination = output_path_for(
                lrc_path,
                args.output_dir.resolve() if args.output_dir else None,
            )
            destination.write_text(
                build_lrc(mp3_title, sentences, total_seconds),
                encoding="utf-8",
            )
        except (OSError, UnicodeError, ValueError) as exc:
            logger.error("Could not process %s: %s", lrc_path.name, exc)
            failed += 1
            continue
        processed += 1
        logger.info(
            "Processed %s: %d sentence(s), duration=%.2f second(s), title=%s",
            lrc_path.name,
            len(sentences),
            total_seconds,
            mp3_title,
        )

    logger.info("Finished: %d processed, %d failed", processed, failed)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
