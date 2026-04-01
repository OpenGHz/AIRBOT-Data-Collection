import json
from pydantic import PositiveInt
from typing import Literal, Dict, List
from collections.abc import Mapping
from mcap.writer import Writer
from flatten_dict import flatten
from time import time_ns
from pathlib import Path
from functools import cache
from mcap_data_loader.utils.av_coder import AvCoderConfig
from mcap_data_loader.utils.mcap_utils import McapTool, MediaType
from mcap_data_loader.serialization.flb import McapFlatBuffersWriter, FlatBuffersSchemas
from airdc.common.samplers.basis import DataSampler, DataSamplerConfig
from airdc.common.samplers.video_sampler import VideoSampler, VideoSamplerConfig


class McapDataSamplerConfig(DataSamplerConfig):
    """Configuration for MCAP data sampler."""

    initial_builder_size: PositiveInt = 1024 * 1024  # 1 MB
    """Initial size of the FlatBuffers builder."""
    video_save_to: Literal["file", "folder", "both"] = "file"
    """Where to save the video data: 'file' for MCAP attachment, 'folder' for separate folder, 'both' for both."""
    av_coder: AvCoderConfig = AvCoderConfig()
    """Configuration for the AV coder."""


class McapDataSampler(DataSampler):
    _info: Dict[str, Dict[str, str]]

    def __init__(self, config: McapDataSamplerConfig):
        self.config = config
        self._video_sampler = VideoSampler(
            VideoSamplerConfig(
                av_coder=config.av_coder,
                key_remap=config.key_remap,
                encode_to_file=False,
            )
        )
        self._video2file = config.video_save_to in {"file", "both"}
        self._video2folder = config.video_save_to in {"folder", "both"}

    def on_configure(self):
        """Configure the mcap data sampler."""
        self._mf_writer = McapFlatBuffersWriter(self.config.initial_builder_size)
        return self._video_sampler.configure()

    def _create_writer(self, path: Path) -> Writer:
        return Writer(str(path)), True

    def on_compose_path(self, directory: Path, episode: int) -> Path:
        path = directory / f"{episode}.mcap"
        # unset here to ensure a fresh writer for each file
        # but the writer is finished in save()
        self._mf_writer.unset_writer()
        self._mf_writer.set_writer(*self._create_writer(path))
        self._video_dir = self._video_sampler.compose_path(directory, episode)
        return path

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

    def save(self, path: Path, data: dict) -> bool:
        """Save the data to a MCAP file."""
        writer = self._mf_writer.get_writer()
        mcap_tool = McapTool(writer)
        info = self._info.copy()
        # add metadata
        self.add_config_metadata(writer, self.config)
        # Handle system info safely
        # TODO: save system info to attachment?
        # TODO: should remap info keys?
        system_info = info.pop("system", {})
        for key, value in system_info.items():
            flattened_value = (
                flatten(value, "path")
                if isinstance(value, Mapping)
                else {"value": value}
            )
            # Convert all values to strings
            string_dict = {k: json.dumps(v) for k, v in flattened_value.items()}
            writer.add_metadata(key, string_dict)

        writer.add_attachment(
            time_ns(),
            time_ns(),
            "component_info",
            MediaType.APPLICATION_JSON,
            json.dumps(info, default=lambda array: array.tolist()).encode("utf-8"),
        )
        log_stamps = data.pop("log_stamps")
        mcap_tool.add_log_stamps_attachment(log_stamps)
        mcap_tool.add_topic_statistics_attachment(self._mf_writer.topic_statistics)
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
        writer.finish()
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
                self._mf_writer.add_message(
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

    def _check_path(self, path):
        return McapTool.validate_file(path, True)

    @classmethod
    def add_config_metadata(cls, writer: Writer, config: McapDataSamplerConfig):
        config_dict = config.model_dump(mode="json")
        config_dict.pop("initial_builder_size")
        for key, value in config_dict.items():
            # Convert all values in dict to strings for MCAP metadata
            # MCAP add_metadata expects dict with string values
            if isinstance(value, dict):
                string_dict = {k: json.dumps(v) for k, v in value.items()}
            else:
                string_dict = {"value": json.dumps(value)}
            writer.add_metadata(name=key, data=string_dict)
