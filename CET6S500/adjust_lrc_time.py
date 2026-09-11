#!/usr/bin/env python3
"""Shift LRC timestamps from a selected numbered sentence onward.

使用方法示例:

    # 从第 10 句开始, 后续时间增加 1500 毫秒, 默认生成 01_adjusted.lrc
    python3 adjust_lrc_time.py /path/to/01.lrc 10 1500

    # 从第 10 句开始, 后续时间提前 800 毫秒
    python3 adjust_lrc_time.py /path/to/01.lrc 10 -800

    # 指定输出文件
    python3 adjust_lrc_time.py /path/to/01.lrc 10 1500 \
        --output /path/to/01_new.lrc

    # 直接覆盖原文件
    python3 adjust_lrc_time.py /path/to/01.lrc 10 1500 --in-place

参数说明:
    第一个参数是 LRC 文件路径;
    第二个参数是开始调整的句子编号;
    第三个参数是调整毫秒数, 正数表示延后, 负数表示提前。
"""

from __future__ import annotations

import argparse
import logging
import re
from pathlib import Path


TIMESTAMP_PATTERN = re.compile(r"\[(\d+):(\d{2})\.(\d{2,3})\]")
SENTENCE_PATTERN = re.compile(r"^\s*(\d+)[.．]\s*")
logger = logging.getLogger(__name__)


def timestamp_to_milliseconds(minutes: str, seconds: str, fraction: str) -> int:
    """Convert an LRC timestamp to milliseconds."""
    fraction_ms = int(fraction.ljust(3, "0")[:3])
    return int(minutes) * 60_000 + int(seconds) * 1_000 + fraction_ms


def milliseconds_to_timestamp(milliseconds: int, fraction_digits: int = 2) -> str:
    """Convert milliseconds to an LRC timestamp, clamping at zero."""
    milliseconds = max(0, milliseconds)
    minutes, remainder = divmod(milliseconds, 60_000)
    seconds, remainder = divmod(remainder, 1_000)
    if fraction_digits == 3:
        return f"[{minutes:02d}:{seconds:02d}.{remainder:03d}]"
    return f"[{minutes:02d}:{seconds:02d}.{remainder // 10:02d}]"


def adjust_line(line: str, offset_ms: int) -> str:
    """Shift every timestamp on one LRC line by the given milliseconds."""
    def replace(match: re.Match[str]) -> str:
        original = timestamp_to_milliseconds(*match.groups())
        digits = len(match.group(3))
        return milliseconds_to_timestamp(original + offset_ms, digits)

    return TIMESTAMP_PATTERN.sub(replace, line)


def output_path_for(input_path: Path, requested: Path | None, in_place: bool) -> Path:
    """Resolve the output path while keeping the source intact by default."""
    if in_place:
        return input_path
    if requested is not None:
        return requested
    return input_path.with_name(f"{input_path.stem}_adjusted{input_path.suffix}")


def adjust_file(
    input_path: Path,
    output_path: Path,
    start_sentence: int,
    offset_ms: int,
) -> int:
    """Adjust timestamps from the selected sentence through the end of the file."""
    lines = input_path.read_text(encoding="utf-8").splitlines(keepends=True)
    started = False
    adjusted_lines = 0
    changed_timestamps = 0

    for index, line in enumerate(lines, start=1):
        sentence_match = SENTENCE_PATTERN.match(line[TIMESTAMP_PATTERN.search(line).end() :]) if TIMESTAMP_PATTERN.search(line) else None
        if sentence_match and int(sentence_match.group(1)) >= start_sentence:
            started = True
        if started and TIMESTAMP_PATTERN.search(line):
            before = line
            line = adjust_line(line, offset_ms)
            lines[index - 1] = line
            adjusted_lines += 1
            changed_timestamps += len(TIMESTAMP_PATTERN.findall(before))

    if not started:
        raise ValueError(f"Sentence {start_sentence} was not found in {input_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("".join(lines), encoding="utf-8")
    logger.info(
        "Adjusted %d timestamp line(s), %d timestamp(s), offset=%d ms, output=%s",
        adjusted_lines,
        changed_timestamps,
        offset_ms,
        output_path,
    )
    return changed_timestamps


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("lrc_file", type=Path, help="Input LRC file")
    parser.add_argument("start_sentence", type=int, help="Sentence number where adjustment starts")
    parser.add_argument("offset_ms", type=int, help="Timestamp adjustment in milliseconds; positive or negative")
    parser.add_argument("-o", "--output", type=Path, help="Output path (default: *_adjusted.lrc)")
    parser.add_argument("--in-place", action="store_true", help="Overwrite the input LRC file")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    input_path = args.lrc_file.resolve()
    if not input_path.is_file():
        logger.error("LRC file does not exist: %s", input_path)
        return 1
    if args.start_sentence < 1:
        parser.error("start_sentence must be at least 1")

    output_path = output_path_for(input_path, args.output.resolve() if args.output else None, args.in_place)
    try:
        adjust_file(input_path, output_path, args.start_sentence, args.offset_ms)
    except (OSError, UnicodeError, ValueError) as exc:
        logger.error("Could not adjust LRC file: %s", exc)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
