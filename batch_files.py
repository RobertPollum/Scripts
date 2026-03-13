import os
import shutil
import argparse
import math


def find_existing_batches(source_dir: str):
    """Return sorted list of (folder_name, folder_path) for existing numeric batch folders."""
    entries = []
    for name in os.listdir(source_dir):
        path = os.path.join(source_dir, name)
        if os.path.isdir(path) and name.isdigit():
            entries.append((name, path))
    entries.sort(key=lambda x: int(x[0]))
    return entries


def batch_files(source_dir: str, batch_size: int = 10000, dry_run: bool = False):
    source_dir = os.path.abspath(source_dir)

    if not os.path.isdir(source_dir):
        print(f"Error: '{source_dir}' is not a valid directory.")
        return

    new_files = [
        f for f in os.listdir(source_dir)
        if os.path.isfile(os.path.join(source_dir, f))
    ]
    new_files.sort()

    total_new = len(new_files)
    if total_new == 0:
        print("No new files found in source directory.")
        return

    existing_batches = find_existing_batches(source_dir)

    # Determine resume state: last batch folder and how full it is
    if existing_batches:
        last_name, last_path = existing_batches[-1]
        last_count = len([
            f for f in os.listdir(last_path)
            if os.path.isfile(os.path.join(last_path, f))
        ])
        last_batch_num = int(last_name)
        slots_remaining = batch_size - last_count
        pad_width = max(len(last_name), 3)
    else:
        last_batch_num = 0
        last_count = 0
        slots_remaining = 0
        # Estimate pad width from total batches we'll need
        total_batches_est = math.ceil(total_new / batch_size)
        pad_width = max(len(str(total_batches_est)), 3)

    print(f"Source:          {source_dir}")
    print(f"New files:       {total_new}")
    print(f"Batch size:      {batch_size}")
    if existing_batches:
        print(f"Resuming from:   folder {existing_batches[-1][0]} ({last_count}/{batch_size} full, {slots_remaining} slots open)")
    print(f"Dry run:         {dry_run}")
    print()

    files_cursor = 0
    current_batch_num = last_batch_num
    moved_total = 0

    # Fill the last existing batch first if it has room
    if slots_remaining > 0 and existing_batches:
        fill_count = min(slots_remaining, total_new)
        fill_files = new_files[:fill_count]
        batch_folder = existing_batches[-1][1]
        batch_label = existing_batches[-1][0]
        print(f"Filling batch {batch_label}: {fill_count} files -> {batch_folder}")
        if not dry_run:
            for filename in fill_files:
                src = os.path.join(source_dir, filename)
                dst = os.path.join(batch_folder, filename)
                shutil.move(src, dst)
        files_cursor += fill_count
        moved_total += fill_count

    # Create new batch folders for remaining files
    while files_cursor < total_new:
        current_batch_num += 1
        batch_label = str(current_batch_num).zfill(pad_width)
        batch_folder = os.path.join(source_dir, batch_label)

        chunk = new_files[files_cursor:files_cursor + batch_size]
        print(f"Batch {batch_label}: {len(chunk)} files -> {batch_folder}")

        if not dry_run:
            os.makedirs(batch_folder, exist_ok=True)
            for filename in chunk:
                src = os.path.join(source_dir, filename)
                dst = os.path.join(batch_folder, filename)
                shutil.move(src, dst)

        files_cursor += len(chunk)
        moved_total += len(chunk)

    print(f"\nTotal files moved: {moved_total}")
    if dry_run:
        print("Dry run complete. No files were moved.")
    else:
        print("Done.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Batch files in a folder into numbered subfolders."
    )
    parser.add_argument("source_dir", help="Path to the folder containing files to batch.")
    parser.add_argument(
        "--batch-size", type=int, default=10000,
        help="Number of files per batch (default: 10000)."
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Preview what would happen without moving any files."
    )

    args = parser.parse_args()
    batch_files(args.source_dir, args.batch_size, args.dry_run)
