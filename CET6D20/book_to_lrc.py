#!/usr/bin/env python3
"""Generate Day LRC files from a CET6D20 vocabulary Markdown book.

Usage:
    # Read book01-02.md and mp3_duration_list.csv beside this script.
    python3 book_to_lrc.py book01-02.md

    # Specify the duration CSV and output directory.
    python3 book_to_lrc.py /path/to/book.md \
        --duration-csv /path/to/mp3_duration_list.csv \
        --output-dir /path/to/lrc

The normal LRC contains the word, phonetic, dictionary definition, and English
example. The companion *_zh.lrc also contains the Chinese example translation.
Audio duration is distributed by the length of each rendered entry.
"""

from __future__ import annotations

import argparse
import csv
import logging
import re
from dataclasses import dataclass
from pathlib import Path


LOGGER = logging.getLogger(__name__)
DAY_PATTERN = re.compile(r"^Day\s*(\d{1,2})\s*$", re.IGNORECASE)
NUMBER_PATTERN = re.compile(r"^(\d{3})(?:\1)?$")
WORD_PATTERN = re.compile(r"^([A-Za-z][A-Za-z' -]*?)\s*/\s*(.+?)\s*/\s*$")
CHINESE_PATTERN = re.compile(r"[\u3400-\u9fff]")
SECTION_PATTERN = re.compile(r"^(释|搭|例)\s*(.*)$")


@dataclass
class Entry:
    """One vocabulary entry extracted from the book."""

    word: str
    phonetic: str
    definition: str
    example: str
    translation: str


def normalize(parts: list[str]) -> str:
    """Join wrapped lines and normalize whitespace."""
    value = re.sub(r"\s+", " ", " ".join(part.strip() for part in parts if part.strip()))
    return re.sub(r"\s+([,.;:!?])", r"\1", value).strip()


def split_english_translation(text: str) -> tuple[str, str]:
    """Split an example line at its first Chinese character."""
    match = CHINESE_PATTERN.search(text)
    if not match:
        return text.strip(), ""
    return text[: match.start()].strip(), text[match.start() :].strip()


def parse_entries(lines: list[str]) -> dict[int, list[Entry]]:
    """Parse numbered vocabulary entries grouped by Day."""
    days: dict[int, list[Entry]] = {}
    current_day: int | None = None
    block: list[str] = []

    def flush() -> None:
        if current_day is None or not block:
            return
        entry = parse_entry(block)
        if entry is not None:
            days.setdefault(current_day, []).append(entry)

    for raw_line in lines:
        line = raw_line.strip()
        day_match = DAY_PATTERN.fullmatch(line)
        if day_match:
            flush()
            block.clear()
            current_day = int(day_match.group(1))
            days.setdefault(current_day, [])
            continue
        if current_day is None:
            continue
        if NUMBER_PATTERN.fullmatch(line):
            flush()
            block.clear()
        block.append(line)
    flush()
    return days


def parse_entry(block: list[str]) -> Entry | None:
    """Parse one numbered entry block."""
    lines = [line for line in block if line]
    if not lines or not NUMBER_PATTERN.fullmatch(lines[0]):
        return None

    word_index = next(
        (index for index, line in enumerate(lines[1:], start=1) if WORD_PATTERN.fullmatch(line)),
        None,
    )
    if word_index is None:
        return None
    word_match = WORD_PATTERN.fullmatch(lines[word_index])
    assert word_match is not None
    word = word_match.group(1).strip()
    phonetic = word_match.group(2).strip()

    definition_parts: list[str] = []
    example_parts: list[str] = []
    translation_parts: list[str] = []
    state = "before_definition"
    translation_started = False

    for line in lines[word_index + 1 :]:
        section_match = SECTION_PATTERN.match(line)
        if section_match:
            section, content = section_match.groups()
            if section == "释":
                state = "definition"
                if content:
                    definition_parts.append(content)
            elif section == "例":
                state = "example"
                if content:
                    english, chinese = split_english_translation(content)
                    if english:
                        example_parts.append(english)
                    if chinese:
                        translation_parts.append(chinese)
                        translation_started = True
            else:
                state = "other"
            continue

        if state == "definition":
            if not line.startswith(("搭", "例")):
                definition_parts.append(line)
        elif state == "example":
            if line.startswith(("搭", "释")):
                state = "other"
                continue
            english, chinese = split_english_translation(line)
            if translation_started:
                if line:
                    translation_parts.append(line)
            elif chinese:
                if english:
                    example_parts.append(english)
                translation_parts.append(chinese)
                translation_started = True
            elif english:
                example_parts.append(english)

    if not word or not phonetic:
        return None
    return Entry(
        word=word,
        phonetic=phonetic,
        definition=normalize(definition_parts),
        example=normalize(example_parts),
        translation=normalize(translation_parts),
    )


def load_durations(path: Path) -> dict[str, float]:
    """Load MP3 filename to total seconds from the duration CSV."""
    durations: dict[str, float] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            filename = (row.get("filename") or "").strip()
            seconds = (row.get("total_seconds") or "").strip()
            if filename and seconds:
                durations[Path(filename).name] = float(seconds)
    return durations


def render_entry(entry: Entry, include_translation: bool) -> str:
    """Render an entry for a normal or translated LRC."""
    parts = [entry.word, entry.phonetic]
    if entry.definition:
        parts.append(entry.definition)
    if entry.example:
        parts.extend(["例", entry.example])
    if include_translation and entry.translation:
        parts.append(entry.translation)
    return " ".join(parts)


def format_timestamp(milliseconds: int) -> str:
    """Format milliseconds as an LRC timestamp."""
    minutes, remainder = divmod(max(0, milliseconds), 60_000)
    seconds, milliseconds = divmod(remainder, 1_000)
    return f"{minutes:02d}:{seconds:02d}.{milliseconds // 10:02d}"


def build_lrc(title: str, entries: list[Entry], duration: float, include_translation: bool) -> str:
    """Build timestamped LRC content weighted by entry length."""
    rendered = [render_entry(entry, include_translation) for entry in entries]
    # Both files share audio timestamps; Chinese text must not change timing.
    timing_text = [render_entry(entry, include_translation=False) for entry in entries]
    weights = [len(re.sub(r"\s+", "", value)) for value in timing_text]
    total_weight = sum(weights)
    if not total_weight:
        raise ValueError(f"No text found for {title}")
    milliseconds_per_weight = duration * 1000 / total_weight
    elapsed = 0
    lines = [f"[ti:{title}]", ""]
    for text, weight in zip(rendered, weights):
        lines.append(f"[{format_timestamp(elapsed)}]{text}")
        elapsed += round(weight * milliseconds_per_weight)
    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("book", type=Path, help="Markdown book file to extract")
    parser.add_argument(
        "--duration-csv",
        type=Path,
        help="Duration CSV (default: mp3_duration_list.csv beside the book)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="Output directory (default: directory containing the book)",
    )
    return parser.parse_args()


def main() -> int:
    """Run the book to LRC conversion."""
    args = parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    book_path = args.book.expanduser().resolve()
    csv_path = (args.duration_csv or book_path.parent / "mp3_duration_list.csv").expanduser().resolve()
    output_dir = (args.output_dir or book_path.parent).expanduser().resolve()

    if not book_path.is_file():
        LOGGER.error("Book file does not exist: %s", book_path)
        return 1
    if not csv_path.is_file():
        LOGGER.error("Duration CSV does not exist: %s", csv_path)
        return 1

    try:
        days = parse_entries(book_path.read_text(encoding="utf-8").splitlines())
        durations = load_durations(csv_path)
        output_dir.mkdir(parents=True, exist_ok=True)
    except (OSError, UnicodeError, ValueError) as exc:
        LOGGER.error("Could not read input files: %s", exc)
        return 1

    processed = 0
    total_entries = 0
    for day, entries in sorted(days.items()):
        mp3_name = f"Day{day:02d}.mp3"
        duration = durations.get(mp3_name)
        if duration is None:
            LOGGER.warning("No duration found for %s; skipped Day %02d", mp3_name, day)
            continue
        if not entries:
            LOGGER.warning("No entries found for Day %02d", day)
            continue
        title = Path(mp3_name).stem
        (output_dir / f"{title}.lrc").write_text(
            build_lrc(title, entries, duration, include_translation=False), encoding="utf-8"
        )
        (output_dir / f"{title}_zh.lrc").write_text(
            build_lrc(title, entries, duration, include_translation=True), encoding="utf-8"
        )
        processed += 1
        total_entries += len(entries)
        LOGGER.info(
            "Wrote %s.lrc and %s_zh.lrc: %d entries, duration=%.2f seconds",
            title,
            title,
            len(entries),
            duration,
        )

    LOGGER.info("Finished: %d Day(s), %d entries", processed, total_entries)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
