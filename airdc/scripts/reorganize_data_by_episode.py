#!/usr/bin/env python3

import json
import os
import shutil
import sys
import logging
from pathlib import Path
from typing import List, Literal, NamedTuple, Optional, Sequence, Tuple

from pydantic import BaseModel, Field, model_validator
from pydantic_settings import CliApp
from typing_extensions import Self

from airdc.utils import init_logging


logger = logging.getLogger(__name__)


FileType = Literal["symlink", "hardlink", "copy", "move"]


class FileOperation(BaseModel):
    source: Path
    """Source episode directory."""

    destination: Path
    """Destination path."""


class EpisodeMapping(BaseModel):
    source_name: str
    """Episode name in the source tree."""

    output_name: str
    """Episode name in the output tree."""


class ExecutionSummary(BaseModel):
    total_mappings: int = 0
    """Number of planned mappings."""

    created_outputs: int = 0
    """Number of new outputs created."""

    reused_outputs: int = 0
    """Number of matching existing outputs reused."""

    copied_files: int = 0
    """Number of files copied as fallback when a hard link could not be created."""


class ReorganizeDataByEpisodeConfig(BaseModel):
    source_root: Path = Field(
        Path("data/aao_data"),
        description="Source root in the format <task>/<episode>.",
    )
    """Source root in the format <task>/<episode>."""

    output_root: Path = Field(
        Path("data/aao_data_by_episode"),
        description=(
            "Output root in the format <episode>/<task>. Missing output "
            "directories are created automatically."
        ),
    )
    """Output root in the format <episode>/<task>, created as needed."""

    dry_run: bool = Field(
        False,
        description="Log planned symlink operations without writing anything.",
    )
    """Whether to log planned operations only."""

    overwrite: bool = Field(
        False,
        description="Replace existing paths under the output root when necessary.",
    )
    """Whether to replace existing paths."""

    file_type: FileType = Field(
        "symlink",
        description=(
            "How to materialize source episodes in the output tree. 'symlink' "
            "creates a relative symlink per episode directory. 'hardlink' walks the "
            "episode directory, mirrors the structure with mkdir, and hard-links "
            "each file; files that cannot be hard-linked (e.g. across filesystems) "
            "are copied. 'copy' recursively copies the episode directory. 'move' "
            "moves the episode directory, removing it from the source tree."
        ),
    )
    """File strategy: 'symlink' (default), 'hardlink', 'copy', or 'move'."""

    episode: Optional[List[str]] = Field(
        None,
        description=(
            "Only reorganize one episode. Pass one value to keep the output name "
            "unchanged, or two values to rename the mapped episode, for example: "
            "--episode 5 or --episode 5 eval_005."
        ),
    )
    """Optional source/output episode mapping."""

    @model_validator(mode="after")
    def validate_episode(self) -> Self:
        """Validate the optional episode filter/rename argument."""
        if self.episode is not None and len(self.episode) not in (1, 2):
            raise ValueError("--episode accepts one or two values only.")
        return self


class DestinationStatus(NamedTuple):
    should_create: bool
    reused_existing: bool


def normalize_episode_argument(values: Sequence[str]) -> str:
    """Convert `--episode` values into a JSON list for `pydantic_settings`."""
    if not values:
        raise ValueError("--episode requires one or two values.")
    if len(values) > 2:
        raise ValueError("--episode accepts one or two values only.")
    if len(values) == 1 and values[0].startswith("[") and values[0].endswith("]"):
        return values[0]
    return json.dumps(list(values))


def normalize_cli_args(cli_args: Optional[Sequence[str]] = None) -> List[str]:
    """Normalize CLI arguments before handing them to `CliApp.run`."""
    raw_args = list(sys.argv[1:] if cli_args is None else cli_args)
    normalized_args = []
    index = 0

    while index < len(raw_args):
        arg = raw_args[index]
        if arg == "--episode":
            episode_values = []
            index += 1
            while index < len(raw_args) and not raw_args[index].startswith("-"):
                episode_values.append(raw_args[index])
                index += 1
            normalized_args.extend(
                ["--episode", normalize_episode_argument(episode_values)]
            )
            continue

        if arg.startswith("--episode="):
            episode_value = arg.split("=", 1)[1]
            normalized_args.extend(
                ["--episode", normalize_episode_argument([episode_value])]
            )
            index += 1
            continue

        normalized_args.append(arg)
        index += 1

    return normalized_args


def parse_config(
    cli_args: Optional[Sequence[str]] = None,
) -> ReorganizeDataByEpisodeConfig:
    """Parse CLI arguments into a validated config model."""
    normalized_args = normalize_cli_args(cli_args)
    return CliApp.run(ReorganizeDataByEpisodeConfig, cli_args=normalized_args)


def build_episode_mapping(
    values: Optional[Sequence[str]],
) -> Optional[EpisodeMapping]:
    """Build the source/output episode mapping from validated config values."""
    if values is None:
        return None

    source_name = values[0]
    output_name = values[1] if len(values) == 2 else source_name
    return EpisodeMapping(source_name=source_name, output_name=output_name)


def sorted_entries(paths: Sequence[Path]) -> List[Path]:
    """Sort paths numerically when possible, otherwise lexicographically."""

    def sort_key(path: Path) -> Tuple[int, str]:
        if path.name.isdigit():
            return 0, "{:020d}".format(int(path.name))
        return 1, path.name

    return sorted(paths, key=sort_key)


def collect_operations(
    source_root: Path,
    output_root: Path,
    episode_mapping: Optional[EpisodeMapping] = None,
) -> List[FileOperation]:
    """Collect all source-to-destination operations."""
    if not source_root.exists() or not source_root.is_dir():
        raise FileNotFoundError(
            "Source root not found or not a directory: {}".format(source_root)
        )

    operations = []
    task_dirs = sorted_entries(
        [path for path in source_root.iterdir() if path.is_dir()]
    )

    for task_dir in task_dirs:
        episode_dirs = sorted_entries(
            [path for path in task_dir.iterdir() if path.is_dir()]
        )
        for episode_dir in episode_dirs:
            if (
                episode_mapping is not None
                and episode_dir.name != episode_mapping.source_name
            ):
                continue

            output_episode_name = (
                episode_mapping.output_name
                if episode_mapping is not None
                else episode_dir.name
            )
            operations.append(
                FileOperation(
                    source=episode_dir,
                    destination=output_root / output_episode_name / task_dir.name,
                )
            )

    if episode_mapping is not None and not operations:
        raise FileNotFoundError(
            "Episode '{}' not found under {}".format(
                episode_mapping.source_name,
                source_root,
            )
        )

    return operations


def path_exists(path: Path) -> bool:
    """Return whether a path exists, including broken symlinks."""
    return os.path.lexists(path)


def remove_existing_path(path: Path) -> None:
    """Remove an existing file, directory, or symlink."""
    if path.is_symlink() or path.is_file():
        path.unlink()
        return

    if path.is_dir():
        shutil.rmtree(path)
        return

    raise RuntimeError("Unsupported existing path type: {}".format(path))


def ensure_destination(
    destination: Path,
    source: Path,
    overwrite: bool,
    dry_run: bool,
    file_type: FileType,
) -> DestinationStatus:
    """Check whether the destination should be created or reused."""
    if not path_exists(destination):
        return DestinationStatus(True, False)

    if file_type == "symlink" and destination.is_symlink():
        current_target = destination.resolve(strict=False)
        desired_target = source.resolve(strict=False)
        if current_target == desired_target:
            return DestinationStatus(False, True)

    if not overwrite:
        raise FileExistsError(
            "Destination already exists: {}. Use --overwrite to replace it.".format(
                destination
            )
        )

    if dry_run:
        return DestinationStatus(True, False)

    remove_existing_path(destination)
    return DestinationStatus(True, False)


def create_relative_symlink(source: Path, destination: Path) -> None:
    """Create a relative symlink from destination to source, creating parent directories first."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    relative_target = os.path.relpath(source, start=destination.parent)
    destination.symlink_to(relative_target)


def create_hardlink_tree(source: Path, destination: Path) -> Tuple[int, int]:
    """Mirror `source` under `destination`, hard-linking files (copying on failure).

    Returns (linked_files, copied_files). Symlinks inside the source are recreated
    as symlinks at the destination rather than dereferenced.
    """
    destination.parent.mkdir(parents=True, exist_ok=True)

    linked = 0
    copied = 0
    for root, _dirs, files in os.walk(source, followlinks=False):
        root_path = Path(root)
        relative_dir = root_path.relative_to(source)
        dest_dir = destination / relative_dir
        dest_dir.mkdir(parents=True, exist_ok=True)

        for file_name in files:
            src_file = root_path / file_name
            dst_file = dest_dir / file_name

            if src_file.is_symlink():
                link_target = os.readlink(src_file)
                os.symlink(link_target, dst_file)
                continue

            try:
                os.link(src_file, dst_file)
                linked += 1
            except OSError as exc:
                logger.debug(
                    "Hard link failed for %s -> %s (%s); falling back to copy.",
                    dst_file,
                    src_file,
                    exc,
                )
                shutil.copy2(src_file, dst_file)
                copied += 1

    return linked, copied


def copy_tree(source: Path, destination: Path) -> None:
    """Recursively copy `source` into `destination`, preserving inner symlinks."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, destination, symlinks=True)


def move_tree(source: Path, destination: Path) -> Tuple[int, int]:
    """Mirror `source` under `destination`, moving files into place.

    Walks the source tree, mirrors it via mkdir at the destination, and moves
    each file with `os.rename` (falling back to copy+unlink when the rename
    crosses filesystems). Source directories are retained so consumers that
    cached paths into the source tree still see valid parents.

    Returns (moved_files, copied_files).
    """
    destination.parent.mkdir(parents=True, exist_ok=True)

    moved = 0
    copied = 0
    for root, _dirs, files in os.walk(source, followlinks=False):
        root_path = Path(root)
        relative_dir = root_path.relative_to(source)
        dest_dir = destination / relative_dir
        dest_dir.mkdir(parents=True, exist_ok=True)

        for file_name in files:
            src_file = root_path / file_name
            dst_file = dest_dir / file_name

            if src_file.is_symlink():
                link_target = os.readlink(src_file)
                os.symlink(link_target, dst_file)
                src_file.unlink()
                continue

            try:
                os.rename(src_file, dst_file)
                moved += 1
            except OSError as exc:
                logger.debug(
                    "Rename failed for %s -> %s (%s); falling back to copy+unlink.",
                    dst_file,
                    src_file,
                    exc,
                )
                shutil.copy2(src_file, dst_file)
                src_file.unlink()
                copied += 1

    return moved, copied


ACTION_TAGS: dict[FileType, str] = {
    "symlink": "SYMLINK",
    "hardlink": "HARDLINK",
    "copy": "COPY",
    "move": "MOVE",
}


def execute_plan(
    operations: Sequence[FileOperation],
    overwrite: bool,
    dry_run: bool,
    file_type: FileType,
) -> ExecutionSummary:
    """Execute the planned file operations and log the summary."""
    if not operations:
        logger.info("No task/episode directories found. Nothing to do.")
        return ExecutionSummary()

    created_count = 0
    reused_count = 0
    copied_count = 0
    action_tag = ACTION_TAGS[file_type]

    for operation in operations:
        destination_status = ensure_destination(
            operation.destination,
            operation.source,
            overwrite=overwrite,
            dry_run=dry_run,
            file_type=file_type,
        )
        if destination_status.reused_existing:
            reused_count += 1
            logger.info(
                "[SKIP] {} already points to {}".format(
                    operation.destination,
                    operation.source,
                )
            )
            continue

        if dry_run:
            logger.info(
                "[{}] {} -> {}".format(
                    action_tag, operation.destination, operation.source
                )
            )
            created_count += 1
            continue

        if file_type == "symlink":
            create_relative_symlink(operation.source, operation.destination)
        elif file_type == "hardlink":
            _linked, copied = create_hardlink_tree(
                operation.source, operation.destination
            )
            copied_count += copied
        elif file_type == "copy":
            copy_tree(operation.source, operation.destination)
        elif file_type == "move":
            _moved, copied = move_tree(operation.source, operation.destination)
            copied_count += copied
        created_count += 1

    summary = ExecutionSummary(
        total_mappings=len(operations),
        created_outputs=created_count,
        reused_outputs=reused_count,
        copied_files=copied_count,
    )
    if file_type == "hardlink":
        logger.info(
            "Done. Prepared {} mappings, created {} hardlink trees, reused {} "
            "existing destinations, copied {} files as fallback.".format(
                summary.total_mappings,
                summary.created_outputs,
                summary.reused_outputs,
                summary.copied_files,
            )
        )
    elif file_type == "symlink":
        logger.info(
            "Done. Prepared {} mappings, created {} symlinks, reused {} existing "
            "symlinks.".format(
                summary.total_mappings,
                summary.created_outputs,
                summary.reused_outputs,
            )
        )
    elif file_type == "copy":
        logger.info(
            "Done. Prepared {} mappings, copied {} trees, reused {} existing "
            "destinations.".format(
                summary.total_mappings,
                summary.created_outputs,
                summary.reused_outputs,
            )
        )
    else:
        logger.info(
            "Done. Prepared {} mappings, moved {} trees, reused {} existing "
            "destinations, copied {} files as fallback.".format(
                summary.total_mappings,
                summary.created_outputs,
                summary.reused_outputs,
                summary.copied_files,
            )
        )
    return summary


def reorganize_data_by_episode(
    config: ReorganizeDataByEpisodeConfig,
) -> ExecutionSummary:
    """Run the reorganization workflow from a validated config and create missing output directories on demand."""
    source_root = config.source_root.expanduser().resolve()
    output_root = config.output_root.expanduser().resolve()
    episode_mapping = build_episode_mapping(config.episode)

    operations = collect_operations(
        source_root,
        output_root,
        episode_mapping=episode_mapping,
    )
    if episode_mapping is not None:
        logger.info(
            "Episode '%s' output directory: %s",
            episode_mapping.source_name,
            output_root / episode_mapping.output_name,
        )
    return execute_plan(
        operations,
        overwrite=config.overwrite,
        dry_run=config.dry_run,
        file_type=config.file_type,
    )


def main(cli_args: Optional[Sequence[str]] = None) -> ExecutionSummary:
    """Parse CLI arguments and run the reorganization workflow."""
    config = parse_config(cli_args)
    return reorganize_data_by_episode(config)


if __name__ == "__main__":
    init_logging()
    try:
        main()
    except ValueError as exc:
        raise SystemExit(str(exc))
