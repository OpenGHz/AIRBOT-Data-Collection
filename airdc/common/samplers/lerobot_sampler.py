from lerobot.datasets.lerobot_dataset import LeRobotDataset
from lerobot.datasets.utils import DEFAULT_FEATURES
from pathlib import Path
from shutil import rmtree
from typing import Any, Dict, List, Literal, Optional, Tuple

import numpy as np
from pydantic import BaseModel, ConfigDict

from airdc.common.samplers.basis import DataSampler, DataSamplerConfig


class LeRobotFeatureMapping(BaseModel, frozen=True):
    """Map an AIRDC key to a LeRobotDataset feature key."""

    model_config = ConfigDict(extra="forbid")

    feature_key: str
    """Target key stored in LeRobotDataset (e.g. 'observation.images.rgb')."""

    source_key: str
    """Source key in AIRDC round_data (before key_remap)."""

    dtype: Optional[str] = None
    """Override feature dtype. If None, inferred from data and `kind`."""

    kind: Literal["numeric", "image", "video", "string"] = "numeric"
    """How to interpret and validate the value."""

    shape: Optional[Tuple[int, ...]] = None
    """Override feature shape. If None, inferred from the first value."""


class LeRobotDataSamplerConfig(DataSamplerConfig):
    """Configuration for `LeRobotDataSampler`."""

    model_config = ConfigDict(extra="forbid")

    episode_dirname: str = "episode_{episode:06d}"
    """Episode directory name template under the dataset directory."""

    # --- lerobot writer behavior ---
    lerobot_repo_id: str = "airdc/local"
    """Repo id used by LeRobotDataset metadata."""

    lerobot_fps: int = 30
    """FPS used by LeRobotDataset."""

    lerobot_task: str = ""
    """Natural language task string for each frame. If empty, falls back to config.task_info fields."""

    lerobot_robot_type: Optional[str] = None
    """Optional robot type string stored in LeRobotDataset metadata."""

    lerobot_parallel_encoding: bool = True
    """Whether to encode videos in parallel when saving episodes (if video keys exist)."""

    lerobot_use_videos: bool = False
    """If True, treat mappings with kind='video' as video features (may trigger encoding)."""

    lerobot_image_writer_processes: int = 0
    lerobot_image_writer_threads: int = 0

    lerobot_batch_encoding_size: int = 1

    lerobot_timestamp_key: str = "log_stamps"
    """Key in round_data used as timestamps. Values can be ns (int) or seconds (float)."""

    lerobot_features: List[LeRobotFeatureMapping] = []
    """Mappings from AIRDC keys to LeRobotDataset feature keys.

    You should configure this to resolve ambiguities such as which key is 'action'.
    """

    lerobot_strict: bool = True
    """If True, missing mapped keys will raise and fail saving in lerobot mode."""

    lerobot_streaming_in_update: bool = True
    """If True, write frames to `LeRobotDataset` in `update()` to reduce memory usage.

    Notes:
        This mirrors `lerobot-record` where images are written to disk immediately via
        `LeRobotDataset.add_frame()` (optionally using async image writer threads/processes).
        When enabled, `update()` returns an empty dict so the DemonstrateInterface won't
        buffer per-step payloads in memory.
    """


class LeRobotDataSampler(DataSampler):
    """A DataSampler that mirrors the *data writing* concerns of `lerobot-record`.

    In AIRDC, control loops / teleop / policy inference live outside the sampler.
    This sampler focuses on: collecting per-step payloads and persisting them as an
    episode folder.

    This sampler writes a LeRobot dataset episode using `LeRobotDataset`.
    This file requires `lerobot` to be importable.
    """

    _info: Dict[str, Any]

    def __init__(self, config: LeRobotDataSamplerConfig = LeRobotDataSamplerConfig()):
        self.config = config
        self._current_episode_path: Optional[Path] = None
        self._dataset: Optional[LeRobotDataset] = None

    def on_configure(self) -> bool:
        """Finalize configuration.

        Returns:
            True if configured successfully.
        """
        return True

    def on_compose_path(self, directory: Path, episode: int) -> Path:
        """Compose the episode path for a episode.

        Notes:
            `LeRobotDataset.create(..., root=path)` requires root to not exist.
            This sampler will create the dataset lazily on the first `update()` call.
        """
        episode_dir = Path(directory) / self.config.episode_dirname.format(
            episode=episode
        )
        # Prepare for a new episode. Do not create directories here (compose_path might
        # be called for removal), but reset any previous in-flight state.
        self._reset_episode_state()
        self._current_episode_path = episode_dir
        return episode_dir

    def update(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Process a single-step payload.

        Args:
            data: One step payload.

        Returns:
            Data to be appended into the episode buffer.
        """
        if not self.config.lerobot_streaming_in_update:
            return data

        if self._current_episode_path is None:
            raise RuntimeError(
                "Current episode path is not set. Did you call compose_path() before update()?"
            )

        if not self.config.lerobot_features:
            raise ValueError(
                "`lerobot_features` is empty. Please configure feature mappings (e.g. action keys)."
            )

        if self._dataset is None:
            features: Dict[str, Dict[str, Any]] = {
                k: v for k, v in DEFAULT_FEATURES.items()
            }
            inferred = self._infer_lerobot_features_from_payload(data)
            features.update(inferred)

            self._dataset = LeRobotDataset.create(
                repo_id=self.config.lerobot_repo_id,
                fps=self.config.lerobot_fps,
                features=features,
                root=self._current_episode_path,
                robot_type=self.config.lerobot_robot_type,
                use_videos=self.config.lerobot_use_videos,
                image_writer_processes=self.config.lerobot_image_writer_processes,
                image_writer_threads=self.config.lerobot_image_writer_threads,
                batch_encoding_size=self.config.lerobot_batch_encoding_size,
            )

        task = self._get_task_string()
        frame: Dict[str, Any] = {"task": task}
        for mapping in self.config.lerobot_features:
            value = self._get_payload_value(data, mapping)
            if value is None:
                if self.config.lerobot_strict:
                    raise KeyError(
                        f"Missing key '{mapping.source_key}' for feature '{mapping.feature_key}'"
                    )
                continue
            frame[mapping.feature_key] = self._coerce_lerobot_value(mapping, value)

        # This will write images/videos as PNG files immediately (optionally async)
        # and store file paths in the episode buffer, which keeps memory usage low.
        self._dataset.add_frame(frame)

        # Do NOT return the large payload to the DemonstrateInterface buffer.
        return {}

    def save(self, path: Path, data: Any) -> bool:
        """Save one episode (episode).

        Args:
            path: Episode path returned by `compose_path`.
            data: Episode buffer, typically `Dict[str, List[Any]]`.

        Returns:
            True on success.
        """
        path = Path(path)
        try:
            if self.config.lerobot_streaming_in_update and self._dataset is not None:
                if (
                    self._current_episode_path is not None
                    and Path(self._current_episode_path) != path
                ):
                    raise RuntimeError(
                        f"save(path={path}) does not match current episode path {self._current_episode_path}"
                    )

                self._dataset.save_episode(
                    parallel_encoding=self.config.lerobot_parallel_encoding
                )
                self._dataset.finalize()
                self._cleanup_empty_images_dir(path)
                self._reset_episode_state()
                return True

            return self._save_with_lerobot(path, data)
        except Exception as exc:
            self.get_logger().exception("Failed saving episode to %s: %s", path, exc)
            return False

    def _save_with_lerobot(self, path: Path, data: Any) -> bool:
        """Write a single episode using the installed `lerobot` package.

        Notes:
        - This sampler only handles data formatting + persistence.
        - Control loops / teleop / policy inference are owned by AIRDC demonstrators.
        - Ambiguous field semantics (e.g. which key is 'action') must be resolved via
          `config.lerobot_features`.
        """

        round_data: Dict[str, List[Any]] = dict(data)
        if not self.config.lerobot_features:
            raise ValueError(
                "`lerobot_features` is empty. Please configure feature mappings (e.g. action keys)."
            )

        timestamps = self._get_timestamps(round_data)
        num_steps = len(timestamps)

        # Infer feature specs from the first step.
        features: Dict[str, Dict[str, Any]] = {
            k: v for k, v in DEFAULT_FEATURES.items()
        }
        inferred = self._infer_lerobot_features(round_data, num_steps)
        features.update(inferred)

        dataset = LeRobotDataset.create(
            repo_id=self.config.lerobot_repo_id,
            fps=self.config.lerobot_fps,
            features=features,
            root=path,
            robot_type=self.config.lerobot_robot_type,
            use_videos=self.config.lerobot_use_videos,
            image_writer_processes=self.config.lerobot_image_writer_processes,
            image_writer_threads=self.config.lerobot_image_writer_threads,
            batch_encoding_size=self.config.lerobot_batch_encoding_size,
        )

        task = self._get_task_string()
        for i in range(num_steps):
            # NOTE: lerobot.validate_frame() treats default features (including 'timestamp')
            # as not allowed in the input frame. LeRobotDataset.add_frame() will generate
            # timestamp automatically (frame_index / fps). If you need original timestamps,
            # store them via an explicit feature mapping.
            frame: Dict[str, Any] = {"task": task}
            for mapping in self.config.lerobot_features:
                value = self._get_step_value(round_data, mapping.source_key, i)
                if value is None:
                    if self.config.lerobot_strict:
                        raise KeyError(
                            f"Missing key '{mapping.source_key}' for feature '{mapping.feature_key}'"
                        )
                    continue
                frame[mapping.feature_key] = self._coerce_lerobot_value(mapping, value)
            dataset.add_frame(frame)

        dataset.save_episode(parallel_encoding=self.config.lerobot_parallel_encoding)
        dataset.finalize()
        self._cleanup_empty_images_dir(path)
        return True

    def _cleanup_empty_images_dir(self, episode_root: Path) -> None:
        """Remove lerobot temporary images directory if it contains no files.

        Notes:
            LeRobot may create an `images/` directory even when intermediate PNGs are
            cleaned up after `save_episode()`. For AIRDC contract tests and manual
            inspection, we treat `images/` as a temporary directory and remove it
            when it is empty to avoid leaving confusing empty folders around.
        """
        images_dir = Path(episode_root) / "images"
        if not images_dir.exists():
            return

        try:
            has_files = any(p.is_file() for p in images_dir.rglob("*"))
        except Exception:
            return

        if not has_files:
            try:
                rmtree(images_dir)
            except Exception:
                return

    def _infer_lerobot_features_from_payload(
        self, payload: Dict[str, Any]
    ) -> Dict[str, Dict[str, Any]]:
        """Infer lerobot feature specs (dtype/shape) from a single-step payload."""
        inferred: Dict[str, Dict[str, Any]] = {}
        for mapping in self.config.lerobot_features:
            if mapping.feature_key in inferred:
                continue

            raw = payload.get(mapping.source_key)
            if raw is None:
                if self.config.lerobot_strict:
                    raise KeyError(
                        f"Missing key '{mapping.source_key}' needed to infer feature '{mapping.feature_key}'"
                    )
                continue

            sample = raw.get("data") if isinstance(raw, dict) and "data" in raw else raw
            if sample is None:
                if self.config.lerobot_strict:
                    raise KeyError(
                        f"Missing key '{mapping.source_key}' needed to infer feature '{mapping.feature_key}'"
                    )
                continue

            dtype, shape = self._infer_feature_dtype_shape(mapping, sample)
            inferred[mapping.feature_key] = {
                "dtype": dtype,
                "shape": shape,
                "names": None,
            }
        return inferred

    def _get_payload_value(
        self, payload: Dict[str, Any], mapping: LeRobotFeatureMapping
    ) -> Any:
        """Extract (and optionally pop) a value from a single-step payload.

        Notes:
            To reduce peak memory during long episodes with large images, we pop image/video
            values from the payload once consumed.
        """
        raw = (
            payload.pop(mapping.source_key, None)
            if mapping.kind in {"image", "video"}
            else payload.get(mapping.source_key)
        )
        if raw is None:
            return None
        if isinstance(raw, dict) and "data" in raw:
            return raw.get("data")
        return raw

    def _reset_episode_state(self) -> None:
        """Reset in-flight episode state."""
        if self._dataset is not None:
            image_writer = getattr(self._dataset, "image_writer", None)
            if image_writer is not None:
                try:
                    image_writer.stop()
                except Exception:
                    pass
        self._dataset = None
        self._current_episode_path = None

    def _get_task_string(self) -> str:
        """Get per-frame natural language task string for lerobot."""
        if self.config.lerobot_task:
            return self.config.lerobot_task

        task_info = getattr(self.config, "task_info", None)
        if task_info is not None:
            if getattr(task_info, "task_description", ""):
                return task_info.task_description
            if getattr(task_info, "task_description_zh", ""):
                return task_info.task_description_zh
            if getattr(task_info, "task_name", ""):
                return task_info.task_name
        return ""

    def _get_timestamps(self, round_data: Dict[str, List[Any]]) -> List[float]:
        """Get timestamps and derive episode length.

        Notes:
            LeRobotDataset generates its own default `timestamp` field (frame_index / fps).
            We use timestamps primarily to determine `num_steps`.
        """
        key = self.config.lerobot_timestamp_key
        values = round_data.get(key)
        if not isinstance(values, list) or not values:
            # Fallback: derive length from the longest mapped key.
            lengths: List[int] = []
            for mapping in self.config.lerobot_features:
                mapped = round_data.get(mapping.source_key)
                if isinstance(mapped, list):
                    lengths.append(len(mapped))
            num_steps = max(lengths) if lengths else 0
            return [float(i) / float(self.config.lerobot_fps) for i in range(num_steps)]

        # Convert ns-like ints into seconds.
        ts0 = values[0]
        if isinstance(ts0, (int, np.integer)) and ts0 > 1_000_000_000_000:
            return [float(v) / 1e9 for v in values]
        return [float(v) for v in values]

    def _infer_lerobot_features(
        self, round_data: Dict[str, List[Any]], num_steps: int
    ) -> Dict[str, Dict[str, Any]]:
        """Infer lerobot feature specs (dtype/shape) from the first step."""
        inferred: Dict[str, Dict[str, Any]] = {}
        for mapping in self.config.lerobot_features:
            if mapping.feature_key in inferred:
                continue

            sample = self._get_step_value(round_data, mapping.source_key, 0)
            if sample is None:
                if self.config.lerobot_strict:
                    raise KeyError(
                        f"Missing key '{mapping.source_key}' needed to infer feature '{mapping.feature_key}'"
                    )
                continue

            dtype, shape = self._infer_feature_dtype_shape(mapping, sample)
            inferred[mapping.feature_key] = {
                "dtype": dtype,
                "shape": shape,
                "names": None,
            }
        return inferred

    def _infer_feature_dtype_shape(
        self, mapping: LeRobotFeatureMapping, value: Any
    ) -> Tuple[str, Tuple[int, ...]]:
        """Infer (dtype, shape) for one mapped feature."""
        if mapping.dtype is not None and mapping.shape is not None:
            return mapping.dtype, mapping.shape

        if mapping.kind in {"image", "video"}:
            arr = np.asarray(value)
            if mapping.shape is not None:
                inferred_shape = tuple(mapping.shape)
            else:
                # LeRobot expects image/video feature shapes as (C, H, W).
                # It accepts both channel-first and channel-last arrays at runtime.
                if arr.ndim == 3:
                    h, w, c = arr.shape
                    if c in (1, 3, 4):
                        inferred_shape = (c, h, w)
                    else:
                        # Fall back to raw shape if channels are ambiguous.
                        inferred_shape = tuple(arr.shape)
                else:
                    inferred_shape = tuple(arr.shape)
            inferred_dtype = mapping.dtype or (
                "video" if mapping.kind == "video" else "image"
            )
            return inferred_dtype, inferred_shape

        if mapping.kind == "string":
            return mapping.dtype or "string", mapping.shape or (1,)

        arr = np.asarray(value)
        inferred_shape = (
            tuple(mapping.shape) if mapping.shape is not None else tuple(arr.shape)
        )
        if inferred_shape == ():
            inferred_shape = (1,)
        if mapping.dtype is not None:
            return mapping.dtype, inferred_shape
        # Default to float32 for numeric vectors/scalars.
        return "float32", inferred_shape

    def _get_step_value(
        self, round_data: Dict[str, List[Any]], source_key: str, i: int
    ) -> Any:
        """Get i-th step value for a source key.

        Supports stamped items: {"data": ..., "t": ...}.
        """
        values = round_data.get(source_key)
        if not isinstance(values, list) or i >= len(values):
            return None
        item = values[i]
        if isinstance(item, dict) and "data" in item:
            return item.get("data")
        return item

    def _coerce_lerobot_value(self, mapping: LeRobotFeatureMapping, value: Any) -> Any:
        """Coerce a value into a lerobot-compatible representation."""
        if mapping.kind in {"image", "video"}:
            return np.asarray(value)
        if mapping.kind == "string":
            return str(value)
        # numeric
        arr = np.asarray(value)
        if arr.shape == ():
            arr = arr.reshape((1,))
        if mapping.dtype is None or mapping.dtype == "float32":
            return arr.astype(np.float32)
        return arr

    def remove(self, path: Path) -> Optional[bool]:
        """Remove saved episode directory."""
        if (
            self._current_episode_path is not None
            and self._current_episode_path == path
        ):
            self._reset_episode_state()
        return super().remove(path)

    def clear(self) -> None:
        """Clear per-episode internal state."""
        self._reset_episode_state()
