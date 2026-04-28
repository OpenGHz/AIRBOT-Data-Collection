#!/usr/bin/env python3

import logging
import sys
from pathlib import Path
from typing import List, Optional, Sequence

from pydantic import BaseModel, Field
from pydantic_settings import CliApp

from airdc.utils import init_logging


logger = logging.getLogger(__name__)


GLOB_CHARS = frozenset("*?[")


class ListEpisodeMp4sConfig(BaseModel):
    output_name: str = Field(
        ...,
        description=(
            "Output episode name to look up. Fuzzy-matches as a substring "
            "against breadcrumb file names by default (e.g. 'episode_' matches "
            "'episode_0', 'episode_12'). If the value contains glob characters "
            "('*', '?', '['), it is used as a glob pattern verbatim."
        ),
    )
    """Output episode name pattern to look up (substring or glob)."""

    source_root: Path = Field(
        Path("data/aao_data"),
        description="Source root in the format <task>/<episode>.",
    )
    """Source root in the format <task>/<episode>."""


def breadcrumb_pattern(output_name: str) -> str:
    """Translate `output_name` into an `rglob` pattern.

    Treated as a literal glob when it contains glob metacharacters; otherwise
    wrapped with `*` on both sides for substring fuzzy matching.
    """
    if any(char in GLOB_CHARS for char in output_name):
        return output_name
    return "*{}*".format(output_name)


def find_breadcrumbs(source_root: Path, output_name: str) -> List[Path]:
    """Return all breadcrumb files matching `output_name` under `source_root`.

    Breadcrumbs are regular files written by reorganize_data_by_episode.py at
    `<source_root>/<task>/<source_episode>/<output_name>` to mark which source
    episode was mapped to a given output episode name. Matching is fuzzy by
    default — see `breadcrumb_pattern` for the rules. Directories that happen
    to share a matching name are ignored.
    """
    pattern = breadcrumb_pattern(output_name)
    return sorted(path for path in source_root.rglob(pattern) if path.is_file())


def list_episode_mp4s(config: ListEpisodeMp4sConfig) -> List[Path]:
    """Print mp4 paths from source episode dirs marked by the output_name breadcrumb."""
    source_root = config.source_root.expanduser().resolve()
    if not source_root.is_dir():
        raise FileNotFoundError(
            "Source root not found or not a directory: {}".format(source_root)
        )

    breadcrumbs = find_breadcrumbs(source_root, config.output_name)
    if not breadcrumbs:
        raise FileNotFoundError(
            "No breadcrumb file matching '{}' found under {}".format(
                breadcrumb_pattern(config.output_name), source_root
            )
        )

    mp4_paths: List[Path] = []
    for breadcrumb in breadcrumbs:
        episode_dir = breadcrumb.parent
        logger.debug("Found breadcrumb in %s", episode_dir)
        for mp4_path in sorted(episode_dir.rglob("*.mp4")):
            print(mp4_path)
            mp4_paths.append(mp4_path)

    logger.debug(
        "Listed %d mp4 file(s) across %d breadcrumb(s) under %s.",
        len(mp4_paths),
        len(breadcrumbs),
        source_root,
    )
    return mp4_paths


def main(cli_args: Optional[Sequence[str]] = None) -> List[Path]:
    """Parse CLI arguments and run the listing workflow."""
    config = CliApp.run(
        ListEpisodeMp4sConfig,
        cli_args=list(sys.argv[1:] if cli_args is None else cli_args),
    )
    return list_episode_mp4s(config)


if __name__ == "__main__":
    init_logging()
    try:
        main()
    except FileNotFoundError as exc:
        raise SystemExit(str(exc))
