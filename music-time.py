import os
import csv
import logging
import argparse
from mutagen.mp3 import MP3
from mutagen import MutagenError

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def get_mp3_duration(file_path: str) -> tuple[float, str]:
    """
    Get mp3 duration and formatted mm:ss time
    :param file_path: absolute path of mp3
    :return: total_seconds, mm:ss string
    """
    try:
        audio = MP3(file_path)
        total_sec = audio.info.length
        minutes = int(total_sec // 60)
        seconds = int(total_sec % 60)
        time_str = f"{minutes:02d}:{seconds:02d}"
        return round(total_sec, 2), time_str
    except MutagenError as e:
        logger.error(f"Failed to read mp3: {file_path}, error: {str(e)}")
        return -1.0, "ERROR"


def scan_folder_mp3(root_dir: str, output_csv: str):
    """
    Recursively scan folder, collect mp3 file name and duration, save to csv
    :param root_dir: target folder path
    :param output_csv: output csv file path
    """
    rows = []
    for dirpath, _, filenames in os.walk(root_dir):
        for fname in filenames:
            if fname.lower().endswith(".mp3"):
                full_path = os.path.join(dirpath, fname)
                sec, timestr = get_mp3_duration(full_path)
                rows.append([fname, full_path, sec, timestr])

    # write csv
    with open(output_csv, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["filename", "full_path", "total_seconds", "duration(mm:ss)"])
        writer.writerows(rows)
    logger.info(f"Scan finished. Total mp3 found: {len(rows)}")
    logger.info(f"Result saved to: {output_csv}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Scan mp3 files and export duration to csv")
    # nargs='?' 实现：--dir 不带参数时使用default值
    parser.add_argument(
        "--dir",
        type=str,
        nargs='?',
        default="/Users/xxx/Music",
        help="target directory to scan mp3. If use --dir without path, use default: /Users/xxx/Music"
    )
    parser.add_argument(
        "--out",
        type=str,
        default=None,
        help="output csv file path. If not set, save mp3_duration_list.csv under scanned dir"
    )
    args = parser.parse_args()

    # auto build output path: if --out not given, put csv under scan dir
    if args.out is None:
        args.out = os.path.join(args.dir, "mp3_duration_list.csv")

    scan_folder_mp3(args.dir, args.out)


