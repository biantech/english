#!/usr/bin/env python3
"""
Filename cleaner script: Convert "Week X Lesson Y" to "weekX-lessonYY" format.

Usage:
    python clean_filenames.py                    # Current directory
    python clean_filenames.py "Week 7 Lesson 1.mp3" # Specific file
    python clean_filenames.py /path/to/dir       # Specific directory
    python clean_filenames.py --dry-run          # Preview changes
    python clean_filenames.py -r /path/to/dir    # Recursive processing
"""

import os
import sys
import argparse
import re


def clean_filename(filename):
    """
    Convert 'Week X Lesson Y' pattern anywhere in the filename to 'weekX-lessonYY'.
    Week number keeps original digit count.
    Lesson number is zero-padded to 2 digits.
    Extension is converted to lowercase.
    """
    name, ext = os.path.splitext(filename)

    # Replace "Week X Lesson Y" pattern flexibly (case-insensitive, ignores extra spaces)
    new_name = re.sub(
        r'(?i)week\s*(\d+)\s*lesson\s*(\d+)',
        lambda m: f"week{m.group(1)}-lesson{int(m.group(2)):02d}",
        name
    )

    # Only return modified name if a change actually occurred
    if new_name != name:
        return new_name + ext.lower()
    return filename


def process_file(filepath, dry_run=False):
    """
    Process renaming for a single file.
    Returns True if a change was made or would be made in dry-run mode.
    """
    filename = os.path.basename(filepath)
    new_filename = clean_filename(filename)

    if new_filename == filename:
        return False

    directory = os.path.dirname(filepath)
    new_filepath = os.path.join(directory, new_filename)

    # Prevent accidental overwrites of existing files
    if os.path.exists(new_filepath):
        if not dry_run:
            print(f"Skipped (target exists): {filename} -> {new_filename}")
        return False

    if dry_run:
        print(f"[DRY RUN] {filepath}")
        print(f"       -> {new_filepath}")
    else:
        try:
            os.rename(filepath, new_filepath)
            print(f"Renamed: {filename}")
            print(f"       -> {new_filename}")
        except OSError as e:
            print(f"Failed: {filename} -> {e}")
            return False

    return True


def main():
    parser = argparse.ArgumentParser(
        description='Clean filenames: Convert Week/Lesson format to weekX-lessonYY',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Examples:\n"
               "  %(prog)s                          # Current directory\n"
               "  %(prog)s 'Week 7 Lesson 1.mp3'    # Specific file\n"
               "  %(prog)s /path/to/music           # Directory\n"
               "  %(prog)s --dry-run                # Preview changes\n"
               "  %(prog)s -r /path/to/music        # Recursive"
    )
    parser.add_argument('path', nargs='?', default='.', help='Target file or directory')
    parser.add_argument('--dry-run', '-d', action='store_true', help='Preview mode')
    parser.add_argument('--recursive', '-r', action='store_true', help='Process subdirectories')
    args = parser.parse_args()

    path = args.path
    if not os.path.exists(path):
        print(f"Error: Path does not exist - {path}")
        sys.exit(1)

    scanned_count = 0
    modified_count = 0

    if os.path.isfile(path):
        scanned_count += 1
        if process_file(path, args.dry_run):
            modified_count += 1
    elif os.path.isdir(path):
        print(f"Scanning directory: {os.path.abspath(path)}")

        if args.recursive:
            for root, _, files in os.walk(path):
                for f in files:
                    scanned_count += 1
                    if process_file(os.path.join(root, f), args.dry_run):
                        modified_count += 1
        else:
            for f in os.listdir(path):
                full_path = os.path.join(path, f)
                if os.path.isfile(full_path):
                    scanned_count += 1
                    if process_file(full_path, args.dry_run):
                        modified_count += 1

    action = "would be modified" if args.dry_run else "modified"
    print(f"\nScan complete. {scanned_count} file(s) checked, {modified_count} file(s) {action}.")
    if args.dry_run:
        print("(Dry run mode - no changes were applied)")


if __name__ == "__main__":
    main()
