#!/usr/bin/env python3
"""Generate one LRC file per study day from the BEC vocabulary Markdown book.

使用方法示例:

    # 使用默认 book.md, 输出到 book.md 所在目录的 lrc 子目录
    python3 bec-gjlx.py

    # 指定输入和输出目录
    python3 bec-gjlx.py \
        --book /Users/bianjq/work/activity/book6/book.md \
        --output-dir /Users/bianjq/english/BECGJLX/lrc

    # 根据 MP3 实际时长缩放每个 Day 的时间, 例如 Day01.mp3
    python3 bec-gjlx.py \
        --audio-dir /Users/bianjq/english/BECGJLX

每条 LRC 内容由“单词 音标/词典释义 例 英文例句 搭 搭配”组成。没有例句
的词条仍会输出单词、音标和词典释义。例句可以跨多行, 遇到中文翻译
或下一个词条时停止。默认每个非空白字符占 0.12 秒; 使用 --audio-dir
时, 会按对应 MP3 时长比例缩放, 不需要额外安装 ffmpeg。
"""

from __future__ import annotations

import argparse
import logging
import re
import subprocess
from pathlib import Path


DAY_PATTERN = re.compile(r"^Day\s+(\d{1,2})\s*$", re.IGNORECASE)
PHONETIC_PATTERN = re.compile(r"^\s*\[[^\]]+\]")
WORD_PATTERN = re.compile(r"^[A-Za-z][A-Za-z'-]*(?:\s+[A-Za-z][A-Za-z'-]*)?$")
EXAMPLE_PATTERN = re.compile(r"^例\s*[:：]?\s*(.*)$")
CHINESE_PATTERN = re.compile(r"[\u3400-\u9fff]")
SECTION_PATTERN = re.compile(r"^(?:商|搭|派|记|同|反|近|形|辨|写|听说)\s*")
logger = logging.getLogger(__name__)


def normalize_text(parts: list[str]) -> str:
    """Join wrapped lines and normalize whitespace around punctuation."""
    text = re.sub(r"\s+", " ", " ".join(part.strip() for part in parts if part.strip()))
    return re.sub(r"\s+([,.;:!?])", r"\1", text).strip()


def english_prefix(text: str) -> str:
    """Keep the English part before an inline Chinese translation."""
    match = CHINESE_PATTERN.search(text)
    return text[: match.start()].rstrip() if match else text.strip()


def split_days(lines: list[str]) -> dict[int, list[str]]:
    """Split Markdown lines by Day headings."""
    days: dict[int, list[str]] = {}
    current: int | None = None
    for line in lines:
        match = DAY_PATTERN.match(line.strip())
        if match:
            current = int(match.group(1))
            days.setdefault(current, [])
        elif current is not None:
            days[current].append(line.rstrip("\n"))
    return days


def extract_day_entries(lines: list[str]) -> list[tuple[str, str, str, str, str]]:
    """Extract word metadata, examples, translations, and collocations."""
    entries: list[tuple[str, str, str, str, str]] = []
    word: str | None = None
    header_parts: list[str] = []
    example_parts: list[str] = []
    translation_parts: list[str] = []
    collocation_parts: list[str] = []
    collecting = False
    collecting_translation = False
    collecting_collocation = False
    skipping_section = False

    def is_word_start(index: int) -> bool:
        """Check a word followed by an optional blank line and phonetic line."""
        candidate = lines[index].strip()
        if not WORD_PATTERN.fullmatch(candidate):
            return False
        lookahead = index + 1
        while lookahead < len(lines) and not lines[lookahead].strip():
            lookahead += 1
        return lookahead < len(lines) and PHONETIC_PATTERN.match(lines[lookahead].strip()) is not None

    def flush() -> None:
        nonlocal word, header_parts, example_parts, translation_parts
        nonlocal collocation_parts, collecting, collecting_translation
        nonlocal collecting_collocation, skipping_section
        if word:
            header = normalize_text(header_parts)
            sentence = normalize_text(example_parts)
            translation = normalize_text(translation_parts)
            collocation = normalize_text(collocation_parts)
            if header or sentence:
                entries.append((word, header, sentence, translation, collocation))
        word = None
        header_parts = []
        example_parts = []
        translation_parts = []
        collocation_parts = []
        collecting = False
        collecting_translation = False
        collecting_collocation = False
        skipping_section = False

    for index, raw_line in enumerate(lines):
        line = raw_line.strip()

        if line and is_word_start(index):
            flush()
            word = line
            continue

        if word is None or not line:
            continue

        if collecting_collocation:
            if SECTION_PATTERN.match(line):
                collecting_collocation = False
                if line.startswith("搭"):
                    collocation_parts.append(re.sub(r"^搭\s*", "", line))
                    collecting_collocation = True
                else:
                    skipping_section = True
            else:
                collocation_parts.append(line)
            continue

        if not collecting:
            example_match = EXAMPLE_PATTERN.match(line)
            if example_match:
                collecting = True
                original = example_match.group(1).strip()
                first = english_prefix(original)
                if first:
                    example_parts.append(first)
                if first != original:
                    translation_parts.append(original[len(first) :].strip())
                    collecting_translation = True
                skipping_section = False
            elif line.startswith("搭"):
                collocation_parts.append(re.sub(r"^搭\s*", "", line))
                collecting_collocation = True
                skipping_section = False
            elif not SECTION_PATTERN.match(line):
                if not skipping_section:
                    header_parts.append(line)
            else:
                skipping_section = True
            continue

        if line.startswith("搭"):
            collecting = False
            collocation_parts.append(re.sub(r"^搭\s*", "", line))
            collecting_collocation = True
            continue
        if SECTION_PATTERN.match(line):
            collecting = False
            collecting_translation = False
            skipping_section = True
            continue
        if collecting_translation:
            translation_parts.append(line)
            continue

        part = english_prefix(line)
        if part:
            example_parts.append(part)
        if part != line:
            suffix = line[len(part) :].strip()
            if suffix:
                translation_parts.append(suffix)
            collecting_translation = True

    flush()
    return entries


def parse_duration(value: str) -> float:
    """Parse seconds, MM:SS, or HH:MM:SS."""
    parts = value.strip().split(":")
    if len(parts) == 1:
        return float(parts[0])
    if len(parts) == 2:
        return int(parts[0]) * 60 + float(parts[1])
    if len(parts) == 3:
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
    raise ValueError(f"Invalid duration: {value}")


def audio_duration(path: Path) -> float | None:
    """Read MP3 duration with macOS afinfo when available."""
    try:
        result = subprocess.run(["afinfo", str(path)], capture_output=True, text=True, check=False)
    except OSError:
        return None
    match = re.search(r"estimated duration:\s*([0-9.]+)\s+sec", result.stdout)
    return float(match.group(1)) if match else None


def format_timestamp(milliseconds: int) -> str:
    """Format milliseconds as an LRC timestamp."""
    minutes, remainder = divmod(max(0, milliseconds), 60_000)
    seconds, centiseconds = divmod(remainder, 1_000)
    return f"{minutes:02d}:{seconds:02d}.{centiseconds // 10:02d}"


def build_lrc(day: int, entries: list[tuple[str, str, str, str, str]], seconds_per_character: float, duration: float | None, include_translation: bool = False) -> str:
    """Build LRC text using sentence length as the time weight."""
    weights = [
        len(re.sub(r"\s+", "", render_entry(entry, include_translation)))
        for entry in entries
    ]
    factor = seconds_per_character
    if duration is not None and sum(weights):
        factor = duration / sum(weights)
        logger.info("Day %02d scaled to %.2f second(s)", day, duration)
    elapsed = 0
    output = [f"[ti:Day {day:02d}]", ""]
    for weight, entry in zip(weights, entries):
        text = render_entry(entry, include_translation)
        output.append(f"[{format_timestamp(elapsed)}]{text}")
        elapsed += round(weight * factor * 1000)
    return "\n".join(output) + "\n"


def render_entry(
    entry: tuple[str, str, str, str, str], include_translation: bool = False
) -> str:
    """Render one entry with metadata, optional example, and collocations."""
    word, header, sentence, translation, collocation = entry
    parts = [word]
    if header:
        parts.append(header)
    if sentence:
        parts.extend(["例", sentence])
    if include_translation and translation:
        parts.append(translation)
    if collocation:
        parts.extend(["搭", collocation])
    return " ".join(parts)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--book",
        type=Path,
        default=Path(__file__).resolve().parent / "book.md",
        help="Input Markdown book (defaults to book.md beside this script)",
    )
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--audio-dir", type=Path, help="Directory containing Day01.mp3, Day02.mp3, ...")
    parser.add_argument("--seconds-per-character", type=float, default=0.12)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    book_path = args.book.resolve()
    if not book_path.is_file():
        logger.error("Book file does not exist: %s", book_path)
        return 1
    if args.seconds_per_character <= 0:
        parser.error("--seconds-per-character must be greater than 0")

    output_dir = (args.output_dir or book_path.parent / "lrc").resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    days = split_days(book_path.read_text(encoding="utf-8").splitlines())
    total = 0
    for day, lines in sorted(days.items()):
        entries = extract_day_entries(lines)
        if not entries:
            logger.warning("Day %02d has no vocabulary examples", day)
            continue
        duration = audio_duration(args.audio_dir / f"Day{day:02d}.mp3") if args.audio_dir else None
        output_path = output_dir / f"Day{day:02d}.lrc"
        output_path.write_text(build_lrc(day, entries, args.seconds_per_character, duration), encoding="utf-8")
        zh_output_path = output_dir / f"Day{day:02d}_zh.lrc"
        zh_output_path.write_text(
            build_lrc(day, entries, args.seconds_per_character, duration, include_translation=True),
            encoding="utf-8",
        )
        total += len(entries)
        logger.info("Wrote Day %02d: %d entr%s to %s", day, len(entries), "y" if len(entries) == 1 else "ies", output_path)
        logger.info("Wrote translated Day %02d LRC to %s", day, zh_output_path)
    logger.info("Generated %d entr%s across %d day(s)", total, "y" if total == 1 else "ies", len(days))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
