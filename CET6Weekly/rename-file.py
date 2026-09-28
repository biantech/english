import os
import re

weekday_map = {
    "Mon": "01",
    "Tues": "02",
    "Wed": "03",
    "Thur": "04",
    "Fri": "05"
}

def rename_files(target_dir, dry_run=True):
    pattern = re.compile(r"(Week(\d+)-)(Mon|Tues|Wed|Thur|Fri)(\.[a-z0-9]+)$")
    for filename in os.listdir(target_dir):
        m = pattern.match(filename)
        if not m:
            continue

        prefix = m.group(1)
        week_num = m.group(2)
        day_en = m.group(3)
        ext = m.group(4)

        day_num = weekday_map[day_en]
        new_name = f"Week{week_num}-{day_num}{ext}"

        old_path = os.path.join(target_dir, filename)
        new_path = os.path.join(target_dir, new_name)

        print(f"{filename:25s} --> {new_name}")
        if not dry_run:
            if os.path.exists(new_path):
                print(f"  WARNING: {new_name} exists, skip")
                continue
            os.rename(old_path, new_path)

if __name__ == "__main__":
    # 改成你的文件夹路径！
    folder = r"D:\English\CET6Weekly"

    # dry_run=True：只预览，不改名
    # 确认输出正确后，改成 dry_run=False 执行重命名
    rename_files(folder, dry_run=False)
