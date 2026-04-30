from mcap_data_loader.serialization.video.basis import AvCoderBasis, AvCoderConfig
from airdc.common.samplers.basis import DataSampler, DataSamplerConfigBasis
from typing import Dict, Any, Type
from collections import defaultdict
from functools import cache
from pathlib import Path
from pydantic import BaseModel, ImportString, ConfigDict
import csv


class VideoEncoderConfig(BaseModel, frozen=True):
    """Configuration for the video coder."""

    model_config = ConfigDict(
        extra="forbid", arbitrary_types_allowed=True, validate_default=True
    )

    cfg: Dict[str, Any] = {}
    """Configuration dictionary for the video coder. The specific keys depend on the implementation of the coder."""
    cls: ImportString[Type[AvCoderBasis]] = (
        "mcap_data_loader.serialization.video.pyav.AvCoder"
    )
    """Import string for the video coder class. Must be a subclass of AvCoderBasis. Default is a PyAV-based implementation."""


class VideoSamplerConfig(DataSamplerConfigBasis):
    """Configuration for video data sampler."""

    encoder: VideoEncoderConfig = VideoEncoderConfig()
    """Configuration for the AV coder."""
    encode_to_file: bool = True
    """Whether to encode video to files directly during sampling."""
    save_stamps: bool = False
    """Whether to save frame timestamps to a CSV file."""


class VideoSampler(DataSampler):
    """Sampler for video data."""

    def __init__(self, config: VideoSamplerConfig):
        self.config = config

    def on_configure(self):
        """Configure the video data sampler."""
        encoder_cfg = self.config.encoder
        encoder_cls = encoder_cfg.cls
        config_cls = encoder_cls.resolve_config_type(encoder_cls)
        cfg: AvCoderConfig = config_cls(**encoder_cfg.cfg)
        self._coders: Dict[str, AvCoderBasis] = defaultdict(lambda: encoder_cls(cfg))
        self._frame_stamp_factor = int(1e9 / cfg.time_base)
        self._save_stamps = self.config.save_stamps
        return True

    def clear(self) -> None:
        """Reset all video coders so timestamps start fresh for the next episode."""
        for coder in self._coders.values():
            coder.reset()

    def on_compose_path(self, directory: Path, episode: int) -> Path:
        self._first_encode = {}
        self._stamps = defaultdict(list)
        self.clear()
        self._dir = directory / str(episode)
        return self._dir

    @cache
    def _is_save_video(self, key: str) -> bool:
        return "/color/" in key

    def encode_frame(self, key: str, frame: dict):
        mapped_key = self.config.key_remap(key)
        if self._first_encode.get(mapped_key) is None:
            self._first_encode[mapped_key] = False
            if self.config.encode_to_file:
                path = self._get_video_path(self._dir, mapped_key)
                path.parent.mkdir(parents=True, exist_ok=True)
                self._coders[mapped_key].set_output(path)
        self._coders[mapped_key].encode_frame(
            frame["data"], frame["t"] // self._frame_stamp_factor
        )
        if self._save_stamps:
            self._stamps[key].append(frame["t"])

    def is_updated(self) -> bool:
        return bool(self._coders)

    def end_videos(
        self, save_to_file: bool = False, reset: bool = False
    ) -> Dict[str, bytes]:
        video_dir = self._dir
        if save_to_file:
            video_dir.mkdir(parents=True, exist_ok=True)
            self.get_logger().info(f"Saving videos to: {video_dir}")
        video_data = {}
        for key, coder in self._coders.items():
            file_path = self._get_video_path(video_dir, key) if save_to_file else ""
            video_bytes = coder.end(file_path, reset)
            if video_bytes is not None:
                video_data[key] = video_bytes
        return video_data

    def update(self, data):
        for key in tuple(data.keys()):
            if self._is_save_video(key):
                self.encode_frame(key, data[key])
                data.pop(key)
        return data

    def _get_video_path(self, directory: Path, key: str) -> Path:
        return directory / f"{key.removeprefix('/').replace('/', '.')}.mp4"

    def save(self, path, data):
        self.end_videos(not self.config.encode_to_file, False)
        # Save frame timestamps if required
        if self._save_stamps:
            stamps_path = path / "frame_timestamps.csv"
            with open(stamps_path, "w", newline="") as csvfile:
                writer = csv.writer(csvfile)
                writer.writerow(["port", "frame_time"])
                for key, timestamps in self._stamps.items():
                    for stamp in timestamps:
                        writer.writerow([key, stamp])
            self.get_logger().info(f"Saved frame timestamps to: {stamps_path}")
        return True


class VideoSamplerOnce(VideoSampler):
    """Sampler that saves video data only in one folder for all episodes.
    TODO: make this a common mode for all samplers in the sampler basis class.
    """

    def get_start_episode(self, directory: Path):
        return int(directory.exists())

    def on_compose_path(self, directory, episode):
        # we do not know the video name until update
        # TODO: use a warm-up phase to determine the data keys
        super().on_compose_path(directory.parent, directory.name)
        return directory


class VideoSamplerEach(VideoSamplerOnce):
    def get_start_episode(self, directory):
        if directory.exists():
            self._each = [
                self._file_to_key(file)
                for file in directory.iterdir()
                if not file.is_dir()
            ]
            return len(self._each)
        self._each = []
        return 0

    def _file_to_key(self, file: Path):
        return "/" + file.stem.replace(".", "/")

    def update(self, data: dict):
        if not self._first_encode:
            for key in data.keys():
                if self._is_save_video(key):
                    if key not in self._each:
                        self._each.append(key)
                        break
            else:
                if not self._each:
                    raise ValueError("No video data found.")
                self._each = self._each[:1]
            # self.get_logger().info(f"Sampling {self._each[-1]}")
        key = self._each[-1]
        return super().update({key: data[key]})

    def remove(self, path):
        to_remove = self._get_video_path(path, self._each.pop())
        # self.get_logger().info(f"Removing {to_remove}")
        return super().remove(to_remove)
