"""Derive relative-pose / rotation_6d channels from recorded MCAP data.

Reads absolute pose topics (``.../position``, ``.../orientation``,
``.../rotation_6d``) from one ``.mcap`` file or a directory of them, and writes
side-car files under ``<name>_processed/`` containing the derived channels:

* ``<pose>_rela`` -- world-frame relative pose w.r.t. the episode's first frame
  (position: vector subtraction; orientation/rotation_6d: ``abs * ref^{-1}``).
* ``<parent>/rotation_6d`` -- 6D rotation derived from an ``orientation`` quaternion.
* ``<parent>/rotation_6d_rela`` -- 6D rotation of the relative orientation.

Programmatic use::

    from airdc.scripts.process_poses import convert
    produced, ok = convert("episodes/0.mcap")   # -> ([.../0.mcap_processed/0.mcap], True)

CLI::

    python3 -m airdc.scripts.process_poses <path> [--keys ...] \
        [--targets rela rotation_6d] [--out_dir DIR]
"""

from collections import defaultdict
from pathlib import Path
from typing import Iterable, List, Optional, Set, Tuple
import argparse
import json
import logging

import numpy as np

from mcap_data_loader.datasets.mcap_dataset import (
    get_config_and_class_type,
    to_episodic_sequence,
)
from mcap_data_loader.utils.rela_abs import PoseGlobalRelaAbsTool
from mcap_data_loader.utils.rot6d import Rotation6D

from airdc.common.samplers.basis import TaskInfo
from airdc.common.samplers.mcap_samplers.sampler_flb import (
    McapFlbDataSampler,
    McapFlbDataSamplerConfig,
)


logger = logging.getLogger(__name__)

# Final path segments that identify a pose field (optionally suffixed "_rela").
_POSE_BASES = ("position", "orientation", "rotation_6d")


def _pose_field(key: str) -> Optional[Tuple[str, bool]]:
    """Classify ``key`` by its exact final path segment.

    Returns ``(base, is_rela)`` where ``base`` is one of ``_POSE_BASES``, or
    ``None`` if the key is not a pose field.  Matching the *whole* final segment
    avoids false positives such as ``.../disposition`` matching ``position``.
    """
    name = key.rsplit("/", 1)[-1]
    is_rela = name.endswith("_rela")
    base = name[: -len("_rela")] if is_rela else name
    if base in _POSE_BASES:
        return base, is_rela
    return None


def extract_pose_keys(stat_keys: Iterable[str]) -> Set[str]:
    """Select the pose keys (abs and ``_rela``) from available statistic keys."""
    return {key for key in stat_keys if _pose_field(key) is not None}


def _init_data_for(key: str, init: dict) -> Optional[np.ndarray]:
    """First-frame reference data for ``key`` (maps ``action/`` back to obs)."""
    obs_key = key[len("action/") :] if key.startswith("action/") else key
    entry = init.get(obs_key)
    if entry is None:
        return None
    return entry["data"]


def _rela_of(
    base: str, value_data: np.ndarray, init_data: np.ndarray
) -> Optional[np.ndarray]:
    """Relative value of an absolute pose field, with a round-trip sanity check.

    Returns ``None`` (and logs) when the base is unknown or the round-trip
    ``abs(rela) != value`` check fails, so a single bad frame never aborts the
    whole episode.
    """
    if base == "position":
        out = PoseGlobalRelaAbsTool.to_rela_position(value_data, init_data)
        back = PoseGlobalRelaAbsTool.to_abs_position(out, init_data)
    elif base == "orientation":
        out = PoseGlobalRelaAbsTool.to_rela_orientation(value_data, init_data)
        back = PoseGlobalRelaAbsTool.to_abs_orientation(out, init_data)
    elif base == "rotation_6d":
        out = PoseGlobalRelaAbsTool.to_rela_rot6d(value_data, init_data)
        back = PoseGlobalRelaAbsTool.to_abs_rot6d(out, init_data)
    else:
        return None
    if not np.allclose(back, value_data):
        logger.warning(
            "Round-trip check failed for '%s' field; skipping frame value.", base
        )
        return None
    return out


def process_sample(
    sample: dict, init: dict, keys: List[str], targets: Set[str]
) -> dict:
    """Derive the relative / rotation_6d channels for a single sample.

    ``keys`` should be pre-sorted so that ``*_rela`` sources come first; the
    write-once policy then lets an explicit ``_rela`` source win any collision
    (e.g. ``rotation_6d_rela``) deterministically.
    """
    want_rela = "rela" in targets
    want_rot6d = "rotation_6d" in targets

    processed: dict = {}
    processed_t: dict = {}

    def put(name: str, value: np.ndarray, t) -> None:
        # write-once: first writer wins (keys are sorted so _rela sources lead)
        if name not in processed:
            processed[name] = value
            processed_t[name] = t

    for key in keys:
        if key == "log_stamps":
            continue
        field = _pose_field(key)
        if field is None:
            # non-pose key (e.g. a manually passed --keys value): skip cleanly
            continue
        base, is_rela = field
        value = sample[key]
        value_data = value["data"]
        value_t = value["t"]

        # --- relative target ---------------------------------------------------
        value_rela: Optional[np.ndarray] = None
        if is_rela:
            # already relative; reuse directly for the rotation_6d target below
            value_rela = value_data
        elif want_rela:
            init_data = _init_data_for(key, init)
            if init_data is None:
                logger.warning("No first-frame reference for '%s'; skipping.", key)
            else:
                value_rela = _rela_of(base, value_data, init_data)
                if value_rela is not None:
                    put(f"{key}_rela", value_rela, value_t)

        # --- rotation_6d target (only for orientation quaternions) -------------
        if want_rot6d and base == "orientation":
            parent = str(Path(key).parent)
            rot6d_key = f"{parent}/rotation_6d" + ("_rela" if is_rela else "")
            if rot6d_key not in sample:
                put(rot6d_key, Rotation6D.quat_to_rot6d(value_data), value_t)
            if want_rela and not is_rela and value_rela is not None:
                rela_key = f"{parent}/rotation_6d_rela"
                if rela_key not in sample:
                    put(rela_key, Rotation6D.quat_to_rot6d(value_rela), value_t)

    result = {
        name: {"data": value, "t": processed_t[name]}
        for name, value in processed.items()
    }
    # log_stamps reads back as a raw scalar (JSON attachment) -> pass through
    result["log_stamps"] = sample["log_stamps"]
    return result


def read_source_info(episode) -> Tuple[dict, Optional[dict]]:
    """Read ``(component_info, task_info)`` from a source episode for round-trip.

    ``component_info`` is a JSON attachment; ``task_info`` is a metadata record
    whose values are JSON-encoded strings.  ``system`` provenance (flattened into
    many metadata records at save time) is intentionally *not* round-tripped.
    """
    component_info: dict = {}
    try:
        for attachment in episode.reader.reader.iter_attachments():
            if attachment.name == "component_info":
                component_info = json.loads(attachment.data)
                break
    except Exception as exc:  # pragma: no cover - defensive, source may lack it
        logger.warning("Failed to read component_info attachment: %s", exc)

    task_info: Optional[dict] = None
    raw = episode.metadata.get("task_info")
    if raw:
        task_info = {}
        for field, encoded in raw.items():
            try:
                task_info[field] = json.loads(encoded)
            except (json.JSONDecodeError, TypeError):
                task_info[field] = encoded
    return component_info, task_info


def _apply_source_info(
    sampler, component_info: dict, task_info: Optional[dict]
) -> None:
    """Propagate the source metadata onto the output sampler for this episode."""
    sampler.set_info(component_info or {})
    if not task_info:
        return

    try:
        info = TaskInfo.model_validate(task_info)
    except Exception as exc:
        logger.warning("Invalid task_info %s: %s; keeping default.", task_info, exc)
        return
    sampler.config = sampler.config.model_copy(update={"task_info": info})


def _build_sampler():
    """Construct and configure the MCAP writer sampler."""
    sampler = McapFlbDataSampler(McapFlbDataSamplerConfig())
    sampler.set_info({})
    if not sampler.configure():
        raise RuntimeError("Failed to configure McapFlbDataSampler")
    return sampler


def build_dataset(path: Path, keys: Optional[List[str]]) -> Tuple[object, Set[str]]:
    """Build a Sample (file) or Episode (dir) dataset and resolve the pose keys.

    Returns ``(dataset, pose_keys)``.  ``log_stamps`` is always added to the
    dataset's read keys (it is required at save time) even when the caller only
    asks for pose keys.
    """
    config_cls, dataset_cls = get_config_and_class_type(path)
    requested: Set[str] = set(keys) if keys else set()
    dataset = dataset_cls(
        config_cls(data_root=path, keys=requested, with_step=False, strict=True)
    )
    if keys:
        pose_keys = {key for key in requested if _pose_field(key) is not None}
    else:
        pose_keys = extract_pose_keys(dataset.statistics().keys())

    need = set(pose_keys) | {"log_stamps"}
    missing = need - set(dataset.config.keys)
    if missing:
        dataset.config.keys.update(missing)
        # only the episodic dataset caches a derived per-sample config
        if hasattr(dataset, "refresh_config"):
            dataset.refresh_config()
    return dataset, pose_keys


def process_episode(
    episode, sampler, out_dir: Path, keys: List[str], targets: Set[str]
) -> Path:
    """Process one episode (a Sample dataset) and write the derived MCAP file."""
    save_path = sampler.compose_path(out_dir, episode.stem)
    init = episode[0]
    component_info, task_info = read_source_info(episode)
    _apply_source_info(sampler, component_info, task_info)

    round_data = defaultdict(list)
    for sample in episode:
        processed = process_sample(sample, init, keys, targets)
        left = sampler.update(processed)
        for key, value in left.items():
            round_data[key].append(value)
    sampler.save(save_path, round_data)
    return save_path


def convert(
    path,
    keys: Optional[List[str]] = None,
    targets: Iterable[str] = ("rela", "rotation_6d"),
    out_dir=None,
) -> Tuple[List[Path], bool]:
    """Convert absolute pose data to derived channels.

    Args:
        path: an ``.mcap`` file or a directory of ``.mcap`` files.
        keys: keys to read; if omitted, pose keys are auto-detected.
        targets: derived targets to generate (subset of ``{"rela", "rotation_6d"}``).
        out_dir: output directory; defaults to ``<path>_processed`` next to input.

    Returns:
        ``(produced_paths, ok)``.  For a single-file input ``produced_paths`` has
        exactly one element.  ``ok`` is ``False`` if any episode failed (the rest
        are still processed).
    """
    path = Path(path)
    out_dir = (
        path.parent / f"{path.name}_processed" if out_dir is None else Path(out_dir)
    )
    out_dir.mkdir(parents=True, exist_ok=True)

    targets = set(targets)
    dataset, pose_keys = build_dataset(path, keys)
    # sort so *_rela sources precede their abs counterparts (write-once determinism)
    sorted_keys = sorted(pose_keys, key=lambda k: (not k.endswith("_rela"), k))
    logger.info("Processing keys: %s", sorted_keys)

    sampler = _build_sampler()
    produced: List[Path] = []
    ok = True
    try:
        for episode in to_episodic_sequence(dataset):
            try:
                save_path = process_episode(
                    episode, sampler, out_dir, sorted_keys, targets
                )
                produced.append(save_path)
                logger.info("Saved processed episode to %s", save_path)
            except Exception as exc:
                ok = False
                logger.exception(
                    "Failed to process episode '%s': %s",
                    getattr(episode, "stem", "?"),
                    exc,
                )
    finally:
        sampler.shutdown()
    return produced, ok


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Derive relative-pose / rotation_6d channels from MCAP data."
    )
    parser.add_argument(
        "path", type=str, help="Path to an .mcap file or a directory of .mcap files."
    )
    parser.add_argument(
        "--keys",
        type=str,
        nargs="+",
        help="Keys to load from the MCAP file(s). Default: auto-detect pose keys.",
    )
    parser.add_argument(
        "--targets",
        nargs="+",
        choices=("rela", "rotation_6d"),
        default=("rela", "rotation_6d"),
        help="Derived targets to generate.",
    )
    parser.add_argument(
        "--out_dir",
        type=str,
        help="Directory to save the processed MCAP files (default: <path>_processed).",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO)
    produced, ok = convert(
        Path(args.path),
        keys=args.keys,
        targets=tuple(args.targets),
        out_dir=args.out_dir,
    )
    logger.info("Produced %d file(s); ok=%s", len(produced), ok)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
