#!/usr/bin/env python3
"""Generate LRC files for the MP3 files in this directory.

Usage examples:

    python3 generate_lrc.py

    python3 generate_lrc.py \
        --book /Users/bianjq/work/activity/book1/book.md \
        --csv /Users/bianjq/github/english/ljzjh/mp3_duration_list.csv \
        --output-dir /Users/bianjq/github/english/ljzjh

Each LRC line contains the word, its familiar meaning, and its complete example.
When a book entry uses the label "释义" instead of "熟义", the script treats it
as the familiar meaning. Timestamps are weighted by non-whitespace text length
and scaled to the duration recorded in the CSV file.
"""

from __future__ import annotations

import argparse
import csv
import logging
import re
from dataclasses import dataclass
from pathlib import Path


DEFAULT_BOOK = Path("/Users/bianjq/work/activity/book1/book.md")
DEFAULT_DIRECTORY = Path("/Users/bianjq/github/english/ljzjh")
WEEK_NAMES = {
    "第一周": 1,
    "第二周": 2,
    "第三周": 3,
    "第四周": 4,
    "第五周": 5,
}
DAY_NAMES = {
    "Monday": "Mon",
    "Tuesday": "Tues",
    "Wednesday": "Wed",
    "Thursday": "Thur",
    "Friday": "Fri",
}
DAY_ORDER = {name: index for index, name in enumerate(DAY_NAMES.values())}
DEFINITION_PATTERN = re.compile(r"^\s*(熟义|释义)\s*(.*)$")
EXAMPLE_PATTERN = re.compile(r"^\s*示例\s*(.*)$")
COGNITIVE_AUDIO_PATTERN = re.compile(r"^Cognitive-P(\d+)-P?(\d+)\.mp3$")
FIELD_PATTERN = re.compile(r"^\s*(?:生义|助记|搭配|派生|同义|反义|辨析)\s*")
INLINE_FIELD_PATTERN = re.compile(r"\s*(?:生\s*义|助\s*记|搭\s*配|派\s*生|同\s*义|反\s*义|辨\s*析)\s*")
PHONETIC_PATTERN = re.compile(r"/[^/\n]+/")
WORD_PATTERN = re.compile(r"^[A-Za-z][A-Za-z'’.,&() -]*$")
CJK_RANGE = "\u3400-\u4dbf\u4e00-\u9fff"
LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class Entry:
    word: str
    meaning: str
    example: str

    @property
    def lrc_text(self) -> str:
        return f"{self.word} 熟义 {self.meaning} 示例 {self.example}"


def normalize_text(parts: list[str]) -> str:
    """Join wrapped book lines while preserving natural word boundaries."""
    text = re.sub(r"\s+", " ", " ".join(part.strip() for part in parts if part.strip()))
    text = re.sub(rf"(?<=[{CJK_RANGE}])\s+(?=[{CJK_RANGE}])", "", text)
    text = re.sub(r"([A-Za-z]-)\s+(?=[A-Za-z])", r"\1", text)
    text = re.sub(r"\s+([,.;:!?，。；：！？、）])", r"\1", text)
    text = re.sub(r"([（])\s+", r"\1", text)
    return text.strip()


def split_book_sections(lines: list[str]) -> tuple[dict[str, list[str]], list[str]]:
    """Split the book into 25 weekday sections and one cognitive section."""
    weekday_sections: dict[str, list[str]] = {}
    cognitive_lines: list[str] = []
    current_week: int | None = None
    current_section: str | None = None

    for raw_line in lines:
        line = raw_line.strip()
        if line in WEEK_NAMES:
            current_week = WEEK_NAMES[line]
            current_section = None
            continue
        if line in DAY_NAMES and current_week is not None:
            current_section = f"Week{current_week:02d}-{DAY_NAMES[line]}"
            if current_section in weekday_sections:
                raise ValueError(f"Duplicate book section: {current_section}")
            weekday_sections[current_section] = []
            continue
        if line == "Test":
            current_section = None
            continue
        if line == "认知词汇":
            current_section = "Cognitive"
            continue
        if line.startswith("附录一"):
            current_section = None
            continue

        if current_section == "Cognitive":
            cognitive_lines.append(raw_line)
        elif current_section is not None:
            weekday_sections[current_section].append(raw_line)

    return weekday_sections, cognitive_lines


def find_word(lines: list[str], definition_index: int) -> tuple[int, str]:
    """Find the word line immediately before a definition field."""
    # Page boundaries in the exported book can leave several consecutive blank lines.
    for index in range(definition_index - 1, max(-1, definition_index - 32), -1):
        candidate = lines[index].strip()
        if not candidate or candidate == "音频":
            continue
        word = candidate.split("/", 1)[0].strip()
        word = re.sub(r"\s*听读写译\s*$", "", word).strip()
        if WORD_PATTERN.fullmatch(word):
            return index, word
    raise ValueError(f"Cannot find word before source line {definition_index + 1}")


def extract_meaning(lines: list[str], definition_index: int, example_index: int) -> str:
    """Extract only the familiar meaning before other vocabulary fields."""
    match = DEFINITION_PATTERN.match(lines[definition_index])
    if match is None:
        raise ValueError(f"Invalid definition at source line {definition_index + 1}")

    parts = [match.group(2)]
    for line in lines[definition_index + 1 : example_index]:
        if FIELD_PATTERN.match(line):
            break
        parts.append(line)

    meaning = normalize_text(parts)
    field_match = INLINE_FIELD_PATTERN.search(meaning)
    if field_match:
        meaning = meaning[: field_match.start()].rstrip()
    meaning = PHONETIC_PATTERN.sub("", meaning)
    meaning = re.sub(r"\s+", " ", meaning).strip()
    if not meaning:
        raise ValueError(f"Empty familiar meaning at source line {definition_index + 1}")
    return meaning


def extract_entries(lines: list[str], section_name: str) -> list[Entry]:
    """Extract word, familiar meaning, and example fields from one section."""
    definitions = [index for index, line in enumerate(lines) if DEFINITION_PATTERN.match(line)]
    examples = [index for index, line in enumerate(lines) if EXAMPLE_PATTERN.match(line)]
    if len(definitions) != len(examples):
        raise ValueError(
            f"Section {section_name} has {len(definitions)} definitions but {len(examples)} examples"
        )

    word_fields = [find_word(lines, index) for index in definitions]
    entries: list[Entry] = []
    for position, (definition_index, example_index) in enumerate(zip(definitions, examples)):
        if example_index <= definition_index:
            raise ValueError(f"Example precedes definition in {section_name}, entry {position + 1}")

        _, word = word_fields[position]
        meaning = extract_meaning(lines, definition_index, example_index)
        example_match = EXAMPLE_PATTERN.match(lines[example_index])
        assert example_match is not None
        example_parts = [example_match.group(1)]
        next_word_index = word_fields[position + 1][0] if position + 1 < len(word_fields) else len(lines)
        for line in lines[example_index + 1 : next_word_index]:
            if FIELD_PATTERN.match(line):
                break
            example_parts.append(line)
        example = normalize_text(example_parts)
        if not example:
            raise ValueError(f"Empty example in {section_name}, entry {position + 1}")
        entries.append(Entry(word=word, meaning=meaning, example=example))

    return entries


def load_durations(csv_path: Path) -> dict[str, float]:
    """Load unique positive MP3 durations from the CSV file."""
    durations: dict[str, float] = {}
    with csv_path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        required_columns = {"filename", "total_seconds"}
        if not reader.fieldnames or not required_columns.issubset(reader.fieldnames):
            raise ValueError(f"CSV must contain columns: {', '.join(sorted(required_columns))}")
        for row_number, row in enumerate(reader, start=2):
            filename = row["filename"].strip()
            if not filename:
                continue
            if filename in durations:
                raise ValueError(f"Duplicate CSV filename at row {row_number}: {filename}")
            try:
                duration = float(row["total_seconds"])
            except (TypeError, ValueError) as error:
                raise ValueError(f"Invalid duration at CSV row {row_number}: {row['total_seconds']}") from error
            if duration <= 0:
                raise ValueError(f"Duration must be positive at CSV row {row_number}: {duration}")
            durations[filename] = duration
    return durations


def format_timestamp(seconds: float) -> str:
    """Format seconds as an LRC timestamp with centisecond precision."""
    total_centiseconds = max(0, round(seconds * 100))
    minutes, remainder = divmod(total_centiseconds, 6_000)
    whole_seconds, centiseconds = divmod(remainder, 100)
    return f"{minutes:02d}:{whole_seconds:02d}.{centiseconds:02d}"


def build_lrc(title: str, entries: list[Entry], duration: float) -> str:
    """Build LRC text and scale line starts to the full audio duration."""
    weights = [max(1, len(re.sub(r"\s+", "", entry.lrc_text))) for entry in entries]
    total_weight = sum(weights)
    elapsed_weight = 0
    output = [f"[ti:{title}]", ""]
    for entry, weight in zip(entries, weights):
        timestamp = duration * elapsed_weight / total_weight
        output.append(f"[{format_timestamp(timestamp)}]{entry.lrc_text}")
        elapsed_weight += weight
    return "\n".join(output) + "\n"


def weekday_sort_key(name: str) -> tuple[int, int]:
    """Sort WeekXX-Day sections in calendar order."""
    match = re.fullmatch(r"Week(\d{2})-(Mon|Tues|Wed|Thur|Fri)", name)
    if match is None:
        raise ValueError(f"Invalid weekday section name: {name}")
    return int(match.group(1)), DAY_ORDER[match.group(2)]


def discover_cognitive_audio(audio_dir: Path) -> list[str]:
    """Return cognitive MP3 filenames ordered by their first printed page."""
    files: list[tuple[int, str]] = []
    for path in audio_dir.glob("Cognitive-*.mp3"):
        match = COGNITIVE_AUDIO_PATTERN.fullmatch(path.name)
        if match:
            files.append((int(match.group(1)), path.name))
    return [filename for _, filename in sorted(files)]


def generate(args: argparse.Namespace) -> int:
    """Parse the book, validate mappings, and write all LRC files."""
    book_path = args.book.expanduser().resolve()
    csv_path = args.csv.expanduser().resolve()
    audio_dir = args.audio_dir.expanduser().resolve()
    output_dir = args.output_dir.expanduser().resolve()
    for label, path in (("Book", book_path), ("CSV", csv_path)):
        if not path.is_file():
            LOGGER.error("%s file does not exist: %s", label, path)
            return 1
    if not audio_dir.is_dir():
        LOGGER.error("Audio directory does not exist: %s", audio_dir)
        return 1

    try:
        durations = load_durations(csv_path)
        weekday_sections, cognitive_lines = split_book_sections(
            book_path.read_text(encoding="utf-8").splitlines()
        )
        if len(weekday_sections) != 25:
            raise ValueError(f"Expected 25 weekday sections, found {len(weekday_sections)}")

        entries_by_audio: dict[str, list[Entry]] = {}
        for section_name in sorted(weekday_sections, key=weekday_sort_key):
            entries = extract_entries(weekday_sections[section_name], section_name)
            if len(entries) != 40:
                raise ValueError(f"Expected 40 entries in {section_name}, found {len(entries)}")
            entries_by_audio[f"{section_name}.mp3"] = entries

        cognitive_entries = extract_entries(cognitive_lines, "Cognitive")
        cognitive_files = discover_cognitive_audio(audio_dir)
        if not cognitive_files:
            raise ValueError("No Cognitive-P*.mp3 files found")
        if len(cognitive_entries) % len(cognitive_files) != 0:
            raise ValueError(
                f"Cannot evenly map {len(cognitive_entries)} cognitive entries "
                f"to {len(cognitive_files)} audio files"
            )
        cognitive_chunk_size = len(cognitive_entries) // len(cognitive_files)
        if cognitive_chunk_size != 100:
            raise ValueError(f"Expected 100 cognitive entries per audio, found {cognitive_chunk_size}")
        for index, filename in enumerate(cognitive_files):
            start = index * cognitive_chunk_size
            entries_by_audio[filename] = cognitive_entries[start : start + cognitive_chunk_size]

        output_dir.mkdir(parents=True, exist_ok=True)
        for filename, entries in entries_by_audio.items():
            audio_path = audio_dir / filename
            if not audio_path.is_file():
                raise ValueError(f"MP3 file does not exist: {audio_path}")
            if filename not in durations:
                raise ValueError(f"CSV duration is missing for: {filename}")
            output_path = output_dir / f"{audio_path.stem}.lrc"
            output_path.write_text(
                build_lrc(filename, entries, durations[filename]),
                encoding="utf-8",
            )
            LOGGER.info(
                "Generated %s with %d entries for %.2f seconds",
                output_path,
                len(entries),
                durations[filename],
            )
    except (OSError, ValueError) as error:
        LOGGER.error("Generation failed: %s", error)
        return 1

    LOGGER.info("Generated %d LRC files with %d entries", len(entries_by_audio), sum(map(len, entries_by_audio.values())))
    return 0


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--book", type=Path, default=DEFAULT_BOOK, help="Source book.md path")
    parser.add_argument(
        "--csv",
        type=Path,
        default=DEFAULT_DIRECTORY / "mp3_duration_list.csv",
        help="MP3 duration CSV path",
    )
    parser.add_argument("--audio-dir", type=Path, default=DEFAULT_DIRECTORY, help="Directory containing MP3 files")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_DIRECTORY, help="Directory for generated LRC files")
    return parser.parse_args()


def main() -> int:
    """Configure logging and run the generator."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    return generate(parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
