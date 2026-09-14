#!/usr/bin/env python3
"""
LRC Lyrics Fixer for LyricsX (macOS)
Extended Features:
  1. Fixes timestamps: [mm:ss] -> [mm:ss.00]
  2. Converts non-standard title lines: [00:00]Title - Artist -> [ti:Title]\n[ar:Artist]
  3. Enforces UTF-8 output (no BOM) to prevent LyricsX parsing errors
  4. Supports single file or directory batch processing (overwrites by default)
  5. Detects and lists LRC files with no valid timestamps
"""
import re
import sys
import os
import shutil
import argparse
import logging

# Configure logging for clean CLI output
logging.basicConfig(
    level=logging.INFO,
    format='%(levelname)s: %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

# 新增：匹配任意有效LRC时间戳的正则（[mm:ss] 或 [mm:ss.xx]）
VALID_TIMESTAMP_RE = re.compile(r'\[\d{2}:\d{2}(?:\.\d+)?\]')


def has_valid_timestamps(content: str) -> bool:
    """Check if LRC content contains at least one valid timestamp."""
    return bool(VALID_TIMESTAMP_RE.search(content))


def fix_lrc_content(content: str) -> str:
    """Core logic to fix LRC formatting issues."""
    lines = content.splitlines()
    fixed_lines = []
    title_replaced = False

    # Precompiled regex patterns for performance
    ti_tag_re = re.compile(r'^\[ti:', re.IGNORECASE)
    title_artist_re = re.compile(r'^\[00:00\.?\d*\]\s*(.+)\s*[-–—]\s*(.+)$')
    timestamp_re = re.compile(r'\[(\d{2}:\d{2})\]')

    for line in lines:
        stripped = line.strip()
        if not stripped:
            fixed_lines.append('')
            continue

        # Track if a standard title tag already exists
        if ti_tag_re.match(stripped):
            title_replaced = True

        # Convert [00:00]Title - Artist -> [ti:Title]\n[ar:Artist]
        if not title_replaced:
            match = title_artist_re.match(stripped)
            if match:
                fixed_lines.append(f'[ti:{match.group(1).strip()}]')
                fixed_lines.append(f'[ar:{match.group(2).strip()}]')
                title_replaced = True
                continue

        # Fix timestamp format: [mm:ss] -> [mm:ss.00]
        fixed_lines.append(timestamp_re.sub(r'[\1.00]', stripped))

    # Append trailing newline for parser compatibility
    return '\n'.join(fixed_lines) + '\n'


def process_file(input_path: str, output_path: str, backup: bool = False, check_no_timestamp: bool = False) -> tuple[bool, bool]:
    """
    Process a single LRC file.
    Returns: (processing_success: bool, has_no_timestamp: bool)
    """
    has_no_ts = False  # 标记是否无有效时间戳
    try:
        # Attempt encoding detection
        content = None
        used_enc = None
        for enc in ['utf-8-sig', 'utf-8', 'gbk', 'gb2312', 'big5', 'latin1']:
            try:
                with open(input_path, 'r', encoding=enc) as f:
                    content = f.read()
                used_enc = enc
                break
            except (UnicodeDecodeError, LookupError):
                continue

        if content is None:
            logger.error(f"Failed to detect encoding, skipping: {os.path.basename(input_path)}")
            return False, False

        # 新增：检测无时间戳
        if check_no_timestamp:
            has_no_ts = not has_valid_timestamps(content)
            if has_no_ts:
                logger.warning(f"NO VALID TIMESTAMPS: {os.path.abspath(input_path)}")

        # Backup original file before overwriting
        if backup and os.path.abspath(input_path) == os.path.abspath(output_path):
            bak_path = input_path + '.bak'
            shutil.copy2(input_path, bak_path)
            logger.info(f"Backup created: {os.path.basename(bak_path)}")

        # Apply fixes and write to UTF-8 (no BOM)
        fixed_content = fix_lrc_content(content)
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(fixed_content)
            
        if used_enc == 'latin1':
            logger.warning(f"Fallback to latin-1. Characters may be garbled if original encoding differs: {os.path.basename(input_path)}")
            
        return True, has_no_ts

    except Exception as e:
        logger.error(f"Processing failed for {os.path.basename(input_path)}: {str(e)}")
        return False, has_no_ts


def main():
    parser = argparse.ArgumentParser(
        description="LRC Lyrics Fixer for LyricsX (macOS) - with no-timestamp detection",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 fix_lrc.py song.lrc                  # Single file -> song_fixed.lrc
  python3 fix_lrc.py song.lrc -o fixed.lrc     # Single file -> custom output
  python3 fix_lrc.py ./lyrics/                 # Batch process directory (overwrite)
  python3 fix_lrc.py ./lyrics/ -b              # Batch process with .bak backups
  python3 fix_lrc.py ./lyrics/ --check-no-ts   # Only list files with no valid timestamps
        """
    )
    parser.add_argument("path", help="Path to a single .lrc file or a directory containing .lrc files")
    parser.add_argument("-o", "--output", help="Custom output file path (single file mode only)")
    parser.add_argument("-b", "--backup", action="store_true", help="Backup original files as .bak before overwriting")
    # 新增：添加检测无时间戳的参数
    parser.add_argument("--check-no-ts", action="store_true", 
                        help="Only check and list files with no valid timestamps (no modification)")
    args = parser.parse_args()

    # 存储无时间戳的文件列表
    no_timestamp_files = []

    # Single file mode
    if os.path.isfile(args.path):
        if args.check_no_ts:
            # 仅检测，不修改文件
            logger.info(f"Checking for no timestamps: {os.path.basename(args.path)}")
            _, has_no_ts = process_file(args.path, args.path, backup=False, check_no_timestamp=True)
            if has_no_ts:
                no_timestamp_files.append(os.path.abspath(args.path))
        else:
            out_path = args.output if args.output else f"{os.path.splitext(args.path)[0]}_fixed{os.path.splitext(args.path)[1]}"
            logger.info(f"Processing single file: {os.path.basename(args.path)} -> {os.path.basename(out_path)}")
            success, has_no_ts = process_file(args.path, out_path, args.backup, check_no_timestamp=True)
            if has_no_ts:
                no_timestamp_files.append(os.path.abspath(args.path))
            sys.exit(0 if success else 1)

    # Directory batch mode
    elif os.path.isdir(args.path):
        lrc_files = []
        for root, _, files in os.walk(args.path):
            for f in files:
                if f.lower().endswith('.lrc'):
                    lrc_files.append(os.path.join(root, f))
                    
        if not lrc_files:
            logger.info("No .lrc files found in the specified directory.")
            sys.exit(0)

        logger.info(f"Found {len(lrc_files)} .lrc file(s).")
        success_count = fail_count = 0
        
        if args.check_no_ts:
            logger.info("Starting no-timestamp check (no file modification)...")
        else:
            logger.info("Starting batch processing...")
            
        for i, f in enumerate(lrc_files, 1):
            rel_path = os.path.relpath(f, args.path)
            if args.check_no_ts:
                logger.info(f"[{i}/{len(lrc_files)}] Checking: {rel_path}")
                # 仅检测，不修改
                _, has_no_ts = process_file(f, f, backup=False, check_no_timestamp=True)
            else:
                logger.info(f"[{i}/{len(lrc_files)}] Processing: {rel_path}")
                success, has_no_ts = process_file(f, f, args.backup, check_no_timestamp=True)
                if success:
                    success_count += 1
                else:
                    fail_count += 1
            
            if has_no_ts:
                no_timestamp_files.append(os.path.abspath(f))
                
        # 输出无时间戳文件汇总
        if no_timestamp_files:
            logger.info("\n=== FILES WITH NO VALID TIMESTAMPS ===")
            for idx, file_path in enumerate(no_timestamp_files, 1):
                logger.info(f"{idx}. {file_path}")
            logger.info(f"Total files with no timestamps: {len(no_timestamp_files)}")
        else:
            logger.info("\nAll checked files have valid timestamps.")
            
        if not args.check_no_ts:
            logger.info(f"\nBatch processing completed. Success: {success_count} | Failed/Skipped: {fail_count}")
        
    else:
        logger.error(f"Path does not exist: '{args.path}'")
        sys.exit(1)

    # 若仅检测无时间戳，最后退出
    if args.check_no_ts:
        sys.exit(0 if len(no_timestamp_files) == 0 else 1)


if __name__ == '__main__':
    main()