#!/usr/bin/env python3
"""Extract numbered English sentences from WeRead book text into LRC files."""

from __future__ import annotations

import argparse
import logging
import re
from pathlib import Path


CHAPTER_RANGES = {
    "听力口语关键句": (1, 103),
    "攻克阅读关键句": (104, 330),
    "翻译语法关键句": (331, 400),
    "写作锦囊关键句": (401, 500),
}
HEADING_PATTERN = re.compile(r"^#\s+(.+?)\s*$")
SENTENCE_PATTERN = re.compile(r"^\s*(\d+)[.．]\s*(.+?)\s*$")
ANNOTATION_PATTERN = re.compile(r"^(【点睛】|【译文】)\s*(.*)$")
STOP_PREFIXES = ("#", "☀")
logger = logging.getLogger(__name__)


def normalize_sentence(number: int, parts: list[str]) -> str:
    """Join wrapped lines into one numbered English sentence."""
    content = " ".join(part.strip() for part in parts if part.strip())
    content = re.sub(r"\s+", " ", content)
    content = re.sub(r"\s+([,.;:!?])", r"\1", content)
    return f"{number}.{content}"


def extract_entries(book_text: str) -> dict[str, list[tuple[int, str, dict[str, list[str]]]]]:
    """Extract numbered sentences and selected Chinese annotations by chapter."""
    chapters: dict[str, list[tuple[int, str, dict[str, list[str]]]]] = {
        chapter: [] for chapter in CHAPTER_RANGES
    }
    chapter: str | None = None
    current_number: int | None = None
    current_parts: list[str] = []
    current_annotations: dict[str, list[str]] = {"【点睛】": [], "【译文】": []}
    annotation: str | None = None

    def flush() -> None:
        nonlocal current_number, current_parts, current_annotations, annotation
        if chapter is not None and current_number is not None and current_parts:
            sentence = normalize_sentence(current_number, current_parts)
            if re.search(r"[A-Za-z]", sentence):
                annotations = {
                    key: normalize_text(value)
                    for key, value in current_annotations.items()
                    if value
                }
                chapters[chapter].append((current_number, sentence, annotations))
        current_number = None
        current_parts = []
        current_annotations = {"【点睛】": [], "【译文】": []}
        annotation = None

    def normalize_text(parts: list[str]) -> str:
        content = " ".join(part.strip() for part in parts if part.strip())
        return re.sub(r"\s+", " ", content).strip()

    for raw_line in book_text.splitlines():
        line = raw_line.strip()
        heading_match = HEADING_PATTERN.fullmatch(line)
        if heading_match:
            flush()
            heading = heading_match.group(1)
            if heading in CHAPTER_RANGES:
                chapter = heading
            elif heading != "Untitled chapter":
                annotation = None
            continue

        if line in CHAPTER_RANGES:
            flush()
            chapter = line
            continue

        sentence_match = SENTENCE_PATTERN.match(line)
        if sentence_match and chapter is not None:
            number = int(sentence_match.group(1))
            lower, upper = CHAPTER_RANGES[chapter]
            if lower <= number <= upper:
                flush()
                current_number = number
                current_parts = [sentence_match.group(2)]
                continue

        if current_number is None:
            continue
        annotation_match = ANNOTATION_PATTERN.match(line)
        if annotation_match:
            annotation = annotation_match.group(1)
            content = annotation_match.group(2).strip()
            if content:
                current_annotations[annotation].append(content)
            continue
        if line.startswith("【"):
            annotation = "__ignore__"
            continue
        if annotation is not None:
            if annotation != "__ignore__" and line and not line.startswith(STOP_PREFIXES):
                current_annotations[annotation].append(line)
            continue
        if not line or line.startswith(STOP_PREFIXES) or line.startswith("【"):
            continue
        current_parts.append(line)

    flush()
    return chapters


def extract_sentences(book_text: str) -> dict[str, list[tuple[int, str]]]:
    """Extract sentences while preserving the original public helper shape."""
    return {
        chapter: [(number, sentence) for number, sentence, _ in entries]
        for chapter, entries in extract_entries(book_text).items()
    }


def format_timestamp(total_centiseconds: int) -> str:
    """Format an LRC timestamp as minutes, seconds, and centiseconds."""
    minutes, remainder = divmod(total_centiseconds, 6000)
    seconds, centiseconds = divmod(remainder, 100)
    return f"{minutes:02d}:{seconds:02d}.{centiseconds:02d}"


def parse_duration(value: str) -> float:
    """Parse seconds, MM:SS, or HH:MM:SS duration text."""
    value = value.strip()
    if ":" in value:
        parts = value.split(":")
        if len(parts) == 2:
            minutes, seconds = parts
            return int(minutes) * 60 + float(seconds)
        if len(parts) == 3:
            hours, minutes, seconds = parts
            return int(hours) * 3600 + int(minutes) * 60 + float(seconds)
        raise ValueError("duration must be MM:SS or HH:MM:SS")
    return float(value)


def sentence_starts(
    sentences: list[tuple[int, str]],
    seconds_per_character: float,
    total_duration: float | None,
    intro_seconds: float,
) -> list[int]:
    """Calculate timestamps, optionally scaling them to an audio duration."""
    weights = [len(re.sub(r"\s+", "", sentence)) for _, sentence in sentences]
    if total_duration is None:
        factor = seconds_per_character
    else:
        total_weight = sum(weights)
        speech_duration = max(0.0, total_duration - intro_seconds)
        factor = speech_duration / total_weight if total_weight else 0
        logger.info(
            "Scaled %d sentence(s) to %.2f speech second(s) after %.2f second intro",
            len(sentences), speech_duration, intro_seconds,
        )
    starts: list[int] = []
    elapsed_centiseconds = round(intro_seconds * 100)
    for character_count in weights:
        starts.append(elapsed_centiseconds)
        elapsed_centiseconds += round(character_count * factor * 100)
    return starts


def build_lrc(
    chapter: str,
    sentences: list[tuple[int, str]],
    seconds_per_character: float,
    total_duration: float | None = None,
    intro_seconds: float = 0,
) -> str:
    """Build LRC content using weighted sentence timestamps."""
    starts = sentence_starts(sentences, seconds_per_character, total_duration, intro_seconds)
    lines = [f"[ti:{chapter}]", ""]
    for (_, sentence), start in zip(sentences, starts):
        lines.append(f"[{format_timestamp(start)}]{sentence}")
    return "\n".join(lines) + "\n"


def build_zh_lrc(
    chapter: str,
    entries: list[tuple[int, str, dict[str, list[str]]]],
    seconds_per_character: float,
    total_duration: float | None = None,
    intro_seconds: float = 0,
) -> str:
    """Build a companion LRC containing the selected Chinese annotations."""
    sentences = [(number, sentence) for number, sentence, _ in entries]
    starts = sentence_starts(sentences, seconds_per_character, total_duration, intro_seconds)
    lines = [f"[ti:{chapter}]", ""]
    for (_, _, annotations), start in zip(entries, starts):
        timestamp = f"[{format_timestamp(start)}]"
        for label in ("【点睛】", "【译文】"):
            content = annotations.get(label, "")
            if content:
                lines.append(f"{timestamp}{label}{content}")
    return "\n".join(lines) + "\n"


def report_numbering(chapter: str, sentences: list[tuple[int, str]]) -> None:
    """Log missing and duplicate main sentence numbers."""
    lower, upper = CHAPTER_RANGES[chapter]
    numbers = [number for number, _ in sentences]
    unique_numbers = set(numbers)
    missing = [number for number in range(lower, upper + 1) if number not in unique_numbers]
    duplicates = sorted({number for number in numbers if numbers.count(number) > 1})
    if missing:
        logger.warning("Chapter %s is missing sentence numbers: %s", chapter, missing)
    if duplicates:
        logger.warning("Chapter %s has duplicate sentence numbers: %s", chapter, duplicates)


def unique_sentences(sentences: list[tuple[int, str]]) -> list[tuple[int, str]]:
    """Keep the first sentence for each number and return numeric order."""
    by_number: dict[int, str] = {}
    for number, sentence in sentences:
        by_number.setdefault(number, sentence)
    return sorted(by_number.items())


def unique_entries(
    entries: list[tuple[int, str, dict[str, list[str]]]],
) -> list[tuple[int, str, dict[str, list[str]]]]:
    """Keep the most complete occurrence for each sentence number."""
    by_number: dict[int, tuple[int, str, dict[str, list[str]]]] = {}
    for entry in entries:
        number = entry[0]
        previous = by_number.get(number)
        if previous is None or len(entry[1]) + sum(map(len, entry[2].values())) > len(previous[1]) + sum(map(len, previous[2].values())):
            by_number[number] = entry
    return [by_number[number] for number in sorted(by_number)]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("book", type=Path, help="Path to the exported book.txt")
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="LRC output directory (default: <book directory>/lrc)",
    )
    parser.add_argument(
        "--seconds-per-character",
        type=float,
        default=0.12,
        help="Duration assigned to each non-whitespace character (default: 0.12)",
    )
    parser.add_argument(
        "--chapter-duration",
        action="append",
        default=[],
        metavar="CHAPTER=MM:SS",
        help="Scale one chapter to an audio duration, repeatable",
    )
    parser.add_argument(
        "--intro-seconds",
        type=float,
        default=47.0,
        help="Non-speech audio at the beginning of each MP3 (default: 47)",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    book_path = args.book.resolve()
    if not book_path.is_file():
        logger.error("Book text file does not exist: %s", book_path)
        return 1
    if args.seconds_per_character <= 0:
        parser.error("--seconds-per-character must be greater than 0")
    if args.intro_seconds < 0:
        parser.error("--intro-seconds must not be negative")

    chapter_durations: dict[str, float] = {}
    for item in args.chapter_duration:
        if "=" not in item:
            parser.error("--chapter-duration must use CHAPTER=MM:SS")
        chapter_name, duration_text = item.split("=", 1)
        if chapter_name not in CHAPTER_RANGES:
            parser.error(f"Unknown chapter in --chapter-duration: {chapter_name}")
        try:
            duration = parse_duration(duration_text)
        except (TypeError, ValueError):
            parser.error(f"Invalid duration in --chapter-duration: {duration_text}")
        if duration <= args.intro_seconds:
            parser.error("Chapter duration must be greater than --intro-seconds")
        chapter_durations[chapter_name] = duration

    output_dir = (args.output_dir or book_path.parent / "lrc").resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    chapters = extract_entries(book_path.read_text(encoding="utf-8"))

    total = 0
    for chapter, sentences in chapters.items():
        sentences = unique_entries(sentences)
        report_numbering(chapter, [(number, sentence) for number, sentence, _ in sentences])
        output_path = output_dir / f"{chapter}.lrc"
        output_path.write_text(
            build_lrc(
                chapter,
                [(number, sentence) for number, sentence, _ in sentences],
                args.seconds_per_character,
                chapter_durations.get(chapter),
                args.intro_seconds,
            ),
            encoding="utf-8",
        )
        zh_output_path = output_dir / f"{chapter}_zh.lrc"
        zh_output_path.write_text(
            build_zh_lrc(
                chapter,
                sentences,
                args.seconds_per_character,
                chapter_durations.get(chapter),
                args.intro_seconds,
            ),
            encoding="utf-8",
        )
        total += len(sentences)
        logger.info("Wrote %d sentence(s) to %s", len(sentences), output_path)
        logger.info("Wrote Chinese annotations to %s", zh_output_path)

    logger.info("Generated %d sentence(s) across %d chapter(s).", total, len(chapters))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
