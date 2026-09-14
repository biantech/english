"""
Batch rename files in a directory by removing Chinese characters from filenames.
Extension is preserved and lowercased.
"""
import os
import re
from pathlib import Path

TARGET_DIR = Path("/Users/bianjq/english/考研易考范文80")
CHINESE_PATTERN = re.compile(r"[\u4e00-\u9fa5]+")


def clean_name(filename: str) -> str:
    """Remove Chinese characters from stem; lowercase extension."""
    p = Path(filename)
    stem = CHINESE_PATTERN.sub("", p.stem)
    ext = p.suffix.lower()
    return stem + ext


def rename_all(directory: Path, dry_run: bool = False) -> None:
    if not directory.is_dir():
        print(f"[ERROR] Directory not found: {directory}")
        return

    files = sorted(f for f in directory.iterdir() if f.is_file())
    renamed = skipped = errors = 0

    for src in files:
        new_name = clean_name(src.name)

        if new_name == src.name:
            continue  # nothing to do

        dst = src.parent / new_name

        if dst.exists():
            print(f'[SKIP]  Target already exists, skip: "{src.name}" -> "{new_name}"')
            skipped += 1
            continue

        print(f'Renaming: "{src.name}" -> "{new_name}"')
        if not dry_run:
            try:
                os.rename(src, dst)
                renamed += 1
            except OSError as e:
                print(f'[ERROR] Failed to rename "{src.name}": {e}')
                errors += 1
        else:
            renamed += 1

    print(f"\nDone — renamed: {renamed}, skipped: {skipped}, errors: {errors}"
          + (" (dry-run)" if dry_run else ""))


if __name__ == "__main__":
    rename_all(TARGET_DIR)
