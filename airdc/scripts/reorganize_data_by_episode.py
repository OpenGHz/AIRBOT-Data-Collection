#!/usr/bin/env python3

import json
import os
import shutil
import sys
import logging
from pathlib import Path
from typing import List, NamedTuple, Optional, Sequence, Tuple

from pydantic import BaseModel, Field, model_validator
from pydantic_settings import CliApp
from typing_extensions import Self

from airdc.utils import init_logging


logger = logging.getLogger(__name__)


class LinkOperation(BaseModel):
    source: Path
    """Source episode directory."""

    destination: Path
    """Destination symlink path."""


class EpisodeMapping(BaseModel):
    source_name: str
    """Episode name in the source tree."""

    output_name: str
    """Episode name in the output tree."""


class ExecutionSummary(BaseModel):
    total_mappings: int = 0
    """Number of planned mappings."""

    created_symlinks: int = 0
    """Number of new symlinks created."""

    reused_symlinks: int = 0
    """Number of matching existing symlinks reused."""


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
) -> List[LinkOperation]:
    """Collect all source-to-destination symlink operations."""
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
                LinkOperation(
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
) -> DestinationStatus:
    """Check whether the destination should be created or reused."""
    if not path_exists(destination):
        return DestinationStatus(True, False)

    if destination.is_symlink():
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


def execute_plan(
    operations: Sequence[LinkOperation],
    overwrite: bool,
    dry_run: bool,
) -> ExecutionSummary:
    """Execute the planned symlink operations and log the summary."""
    if not operations:
        logger.info("No task/episode directories found. Nothing to do.")
        return ExecutionSummary()

    created_count = 0
    reused_count = 0

    for operation in operations:
        destination_status = ensure_destination(
            operation.destination,
            operation.source,
            overwrite=overwrite,
            dry_run=dry_run,
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
                "[LINK] {} -> {}".format(operation.destination, operation.source)
            )
            created_count += 1
            continue

        create_relative_symlink(operation.source, operation.destination)
        created_count += 1

    summary = ExecutionSummary(
        total_mappings=len(operations),
        created_symlinks=created_count,
        reused_symlinks=reused_count,
    )
    logger.info(
        "Done. Prepared {} mappings, created {} symlinks, reused {} existing "
        "symlinks.".format(
            summary.total_mappings,
            summary.created_symlinks,
            summary.reused_symlinks,
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
