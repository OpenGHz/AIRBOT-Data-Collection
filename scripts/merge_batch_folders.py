#!/usr/bin/env python3
from __future__ import annotations

import argparse
import shutil
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Move files from subfolders into the root folder and rename them "
            "sequentially."
        )
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path("data/aao_data"),
        help="Target root folder that contains many subfolders (default: data/aao_data).",
    )
    parser.add_argument(
        "--start-index",
        type=int,
        default=0,
        help="Starting index for renaming (default: 0).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only print planned operations without moving files.",
    )
    return parser.parse_args()


def collect_source_files(root: Path) -> list[Path]:
    if not root.exists() or not root.is_dir():
        raise FileNotFoundError(f"Root path not found or not a directory: {root}")

    source_files: list[Path] = []
    for subdir in sorted(p for p in root.iterdir() if p.is_dir()):
        # Recursively collect files from all levels, sorted by path for determinism
        files = sorted(p for p in subdir.rglob("*") if p.is_file())
        source_files.extend(files)
    return source_files


def collect_source_dirs(root: Path) -> list[Path]:
    """Collect all subdirectories under root, deepest first for safe bottom-up removal."""
    all_dirs: list[Path] = []
    for top_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        # Walk bottom-up: deeper dirs come first so they can be removed before parents
        for d in sorted(top_dir.rglob("*"), reverse=True):
            if d.is_dir():
                all_dirs.append(d)
        all_dirs.append(top_dir)
    return all_dirs


def build_plan(source_files: list[Path], root: Path, start_index: int) -> list[tuple[Path, Path]]:
    plan: list[tuple[Path, Path]] = []
    index = start_index
    for src in source_files:
        dst = root / f"{index}{src.suffix}"
        plan.append((src, dst))
        index += 1
    return plan


def execute_plan(plan: list[tuple[Path, Path]], source_dirs: list[Path], dry_run: bool) -> None:
    if not plan:
        print("No files found in subfolders. Nothing to do.")
        return

    temp_moves: list[tuple[Path, Path]] = []

    for src, dst in plan:
        temp_dst = dst.with_name(f".__tmp_merge__{dst.name}")
        if dry_run:
            print(f"[DRY-RUN] {src} -> {dst}")
            continue
        shutil.move(str(src), str(temp_dst))
        temp_moves.append((temp_dst, dst))

    if dry_run:
        planned_sources = {src for src, _ in plan}
        print(f"[DRY-RUN] total files: {len(plan)}")
        # source_dirs is already ordered deepest-first for bottom-up removal
        simulated_empty: set[Path] = set()
        for subdir in source_dirs:
            entries = list(subdir.iterdir())
            will_be_empty = all(
                (entry.is_file() and entry in planned_sources)
                or (entry.is_dir() and entry in simulated_empty)
                for entry in entries
            )
            if will_be_empty:
                simulated_empty.add(subdir)
                print(f"[DRY-RUN] remove empty dir: {subdir}")
        return

    for temp_src, final_dst in temp_moves:
        shutil.move(str(temp_src), str(final_dst))

    removed_count = 0
    # source_dirs is already ordered deepest-first for safe bottom-up removal
    for subdir in source_dirs:
        if subdir.exists() and not any(subdir.iterdir()):
            subdir.rmdir()
            removed_count += 1

    print(f"Done. Moved and renamed {len(plan)} files. Removed {removed_count} empty folders.")


def main() -> None:
    args = parse_args()
    root = args.root.expanduser().resolve()

    source_dirs = collect_source_dirs(root)
    source_files = collect_source_files(root)
    plan = build_plan(source_files, root, args.start_index)
    execute_plan(plan, source_dirs, args.dry_run)


if __name__ == "__main__":
    main()
