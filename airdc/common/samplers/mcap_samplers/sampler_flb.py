from pydantic import PositiveInt
from typing import Literal, List
from time import time_ns
from functools import cache
from mcap_data_loader.utils.mcap_utils import MediaType
from mcap_data_loader.serialization.flb import McapFlatBuffersWriter, FlatBuffersSchemas
from airdc.common.samplers.mcap_samplers.basis import (
    McapDataSamplerBasis,
    McapDataSamplerBasisConfig,
)
from airdc.common.samplers.video_sampler import (
    VideoEncoderConfig,
    VideoSampler,
    VideoSamplerConfig,
)


class McapFlbDataSamplerConfig(McapDataSamplerBasisConfig):
    """Configuration for MCAP data sampler."""

    initial_builder_size: PositiveInt = 1024 * 1024  # 1 MB
    """Initial size of the FlatBuffers builder."""
    video_save_to: Literal["file", "folder", "both"] = "file"
    """Where to save the video data: 'file' for MCAP attachment, 'folder' for separate folder, 'both' for both."""
    encoder: VideoEncoderConfig = VideoEncoderConfig()
    """Configuration for the video encoder."""


class McapFlbDataSampler(McapDataSamplerBasis):
    """McapFlbDataSampler is a data sampler that handles various types of data, including video frames, and saves them in MCAP format using FlatBuffers serialization."""

    def __init__(self, config: McapFlbDataSamplerConfig):
        self.config = config
        self._video_sampler = VideoSampler(
            VideoSamplerConfig(
                encoder=config.encoder,
                key_remap=config.key_remap,
                encode_to_file=False,
            )
        )
        self._video2file = config.video_save_to in {"file", "both"}
        self._video2folder = config.video_save_to in {"folder", "both"}

    def on_configure(self):
        """Configure the mcap data sampler."""
        super().on_configure()
        return self._video_sampler.configure()

    def _create_writer(self):
        return McapFlatBuffersWriter(self.config.initial_builder_size)

    def clear(self) -> None:
        """Reset video coders so timestamps start fresh after abandon/clear."""
        self._video_sampler.clear()

    def on_compose_path(self, directory, episode):
        self._video_dir = self._video_sampler.compose_path(directory, episode)
        return super().on_compose_path(directory, episode)

    def update(self, data: dict):
        """Update the data with the latest frames."""
        for key in tuple(data.keys()):
            if flag := self._is_save_h264(key):
                self._video_sampler.encode_frame(key, data[key])
            else:
                # print(f"{key} {type(data[key])}")
                flag = self._add_messages(key, [data[key]], [data["log_stamps"]])
            if flag:
                data.pop(key)
        return data

    def _on_save(self, path, data):
        writer = self._data_writer.get_writer()
        log_stamps = data.pop("log_stamps")
        for key, values in data.items():
            if not self._add_messages(key, values, log_stamps):
                self.get_logger().warning(f"Unknown data type for key: {key}")
        if self._video_sampler.is_updated():
            video_data = self._video_sampler.end_videos(self._video2folder)
            if self._video2file:
                for key, video_bytes in video_data.items():
                    writer.add_attachment(
                        time_ns(), time_ns(), key, MediaType.VIDEO_MP4, video_bytes
                    )
        return True

    def remove(self, path):
        if self._video2folder:
            self._video_sampler.remove(path)
        return super().remove(path)

    def _add_messages(
        self, key: str, values: List[dict], log_stamps: List[float]
    ) -> FlatBuffersSchemas:
        # self.get_logger().info(f"Adding messages for key: {key}")
        schema_type = self._key_to_schema_type(key)
        # print(f"Adding messages for key: {key} with schema type: {schema_type}")
        if schema_type is not FlatBuffersSchemas.NONE:
            color_save_type = self.config.save_type.color
            if schema_type is FlatBuffersSchemas.COMPRESSED_IMAGE:
                kwargs = {"format": color_save_type, "frame_id": "airbot"}
            elif schema_type is FlatBuffersSchemas.RAW_IMAGE:
                kwargs = {"encoding": "", "frame_id": "airbot"}
            else:
                kwargs = {}
            if len(log_stamps) != len(values):
                raise ValueError(
                    f"Log stamps length ({len(log_stamps)}) must match data values length ({len(values)})."
                )
            key = self.config.key_remap(key)
            _ = [
                self._data_writer.add_message(
                    schema_type, key, value["data"], value["t"], log_stamps[i], **kwargs
                )
                for i, value in enumerate(values)
            ]
        # else:
        #     self.get_logger().warning(f"Unknown data type for key: {key}")
        return schema_type

    @cache
    def _is_save_h264(self, key: str) -> bool:
        return "/color/" in key and self.config.save_type.color == "h264"

    @cache
    def _key_to_schema_type(self, key: str) -> FlatBuffersSchemas:
        is_pose = key.endswith("/pose")
        if is_pose:
            return FlatBuffersSchemas.POSE_IN_FRAME
        is_heat_map = key.endswith("/heat_map")
        if is_heat_map:
            return FlatBuffersSchemas.MULTI_CHANNEL_IMAGE
        is_pc2 = key.endswith("/point_cloud2")
        if is_pc2:
            return FlatBuffersSchemas.POINT_CLOUD2
        is_color = "/color/" in key
        if is_color:
            save_type = self.config.save_type.color
            if save_type == "jpeg":
                return FlatBuffersSchemas.COMPRESSED_IMAGE
            elif save_type == "raw":
                return FlatBuffersSchemas.RAW_IMAGE
            else:
                return FlatBuffersSchemas.NONE
        is_depth = "depth" in key
        if is_depth:
            save_type = self.config.save_type.depth
            if save_type == "raw":
                return FlatBuffersSchemas.RAW_IMAGE
            raise NotImplementedError
        elif key == "log_stamps":
            return FlatBuffersSchemas.NONE
        return FlatBuffersSchemas.FLOAT_ARRAY
