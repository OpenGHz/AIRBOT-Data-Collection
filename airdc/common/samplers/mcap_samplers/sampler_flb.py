from pydantic import PositiveInt
from typing import Literal, List
from time import time_ns
from functools import cache
import numpy as np
from mcap_data_loader.utils.mcap_utils import MediaType
from mcap_data_loader.serialization.flb import McapFlatBuffersWriter, FlatBuffersSchemas
from mcap_data_loader.utils.rela_abs import PoseGlobalRelaAbsTool
from mcap_data_loader.utils.rot6d import Rotation6D
from airdc.common.samplers.mcap_samplers.basis import (
    McapDataSamplerBasis,
    McapDataSamplerBasisConfig,
)
from airdc.common.samplers.video_sampler import (
    VideoEncoderConfig,
    VideoSampler,
    VideoSamplerConfig,
)


class _RelativeFlbWriter(McapFlatBuffersWriter):
    """McapFlatBuffersWriter subclass that auto-writes relative data for position/orientation/rot6d topics.

    For topics ending with 'position', 'orientation', or 'rotation_6d', also writes '<topic>_rela'
    with data relative to the first frame. For orientation topics, additionally derives a 'rotation_6d'
    topic (if not already present) and its '_rela' variant. Each topic maintains its own reference
    frame independently; first-writer-wins prevents collisions.
    """

    _IDENTITY_QUAT = np.array([0, 0, 0, 1], dtype=np.float32)
    _IDENTITY_ROT6D = np.array([1, 0, 0, 0, 1, 0], dtype=np.float32)

    # Per-topic dispatch kinds. A topic's string + schema type fully determine
    # which branch it takes, so the kind is computed once (see _plan_for_topic)
    # and cached, turning per-message handling into a dict lookup instead of a
    # chain of endswith() calls and string concatenations.
    _KIND_PASSTHROUGH = 0  # write original only, no relative data
    _KIND_SOURCE_RELA = 1  # a source-provided "_rela" topic (first-writer-wins)
    _KIND_POSITION = 2
    _KIND_ORIENTATION = 3
    _KIND_ROT6D = 4

    def __init__(self, initial_builder_size: int = 1024):
        super().__init__(initial_builder_size)
        # Static topic -> dispatch plan cache. A plan is fully determined by the
        # topic name and schema type, both stable across episodes, so this cache
        # is built once per topic and never reset (unlike the reference frames).
        self._topic_plan = {}
        self.reset_references()

    def reset_references(self) -> None:
        """Clear reference frames (call at episode start)."""
        self._position_refs = {}
        self._orientation_refs = {}
        self._rot6d_refs = {}
        # Owner of each "_rela" topic: "auto" (generated here) or "source"
        # (already in the input). First writer wins; the other side is skipped
        # so a pre-existing _rela topic can't collide with a generated one.
        # Also tracks ownership of derived rotation_6d topics.
        self._rela_owner = {}

    def unset_writer(self, finish: bool = False):
        """Unset writer and clear reference frames (mirrors _stat.clear() in parent)."""
        super().unset_writer(finish)
        self.reset_references()

    def _plan_for_topic(self, schema_type, topic: str):
        """Classify a topic once and cache the result.

        Returns a tuple ``(kind, rela_topic, rot6d_topic, rot6d_rela_topic)``.
        The trailing names are pre-concatenated here so the per-message hot path
        never builds strings or scans suffixes again.
        """
        # Non-float-array messages never carry relative data. Handle them without
        # touching the cache: the cache is keyed by topic only, and a topic's
        # relative-data classification depends purely on its name suffix, so the
        # cache must not be seeded from a (possibly differently-typed) message.
        if schema_type is not FlatBuffersSchemas.FLOAT_ARRAY:
            return (self._KIND_PASSTHROUGH, None, None, None)

        plan = self._topic_plan.get(topic)
        if plan is not None:
            return plan

        if topic.endswith("_rela"):
            plan = (self._KIND_SOURCE_RELA, None, None, None)
        elif topic.endswith("position"):
            plan = (self._KIND_POSITION, topic + "_rela", None, None)
        elif topic.endswith("orientation"):
            # Derived rot6d topic naming: "foo/bar/orientation" -> "foo/bar/rotation_6d"
            if topic.endswith("/orientation"):
                rot6d_topic = topic[: -len("/orientation")] + "/rotation_6d"
            else:
                rot6d_topic = topic[: -len("orientation")] + "rotation_6d"
            plan = (
                self._KIND_ORIENTATION,
                topic + "_rela",
                rot6d_topic,
                rot6d_topic + "_rela",
            )
        elif topic.endswith("rotation_6d"):
            plan = (self._KIND_ROT6D, topic + "_rela", None, None)
        else:
            plan = (self._KIND_PASSTHROUGH, None, None, None)

        self._topic_plan[topic] = plan
        return plan

    def add_message(
        self, schema_type, topic: str, data, publish_time: int, log_time: int, **kwargs
    ):
        kind, rela_topic, rot6d_topic, rot6d_rela_topic = self._plan_for_topic(
            schema_type, topic
        )

        # Source topics whose name may collide with an auto-generated one
        # (a "_rela" stream, or a "rotation_6d" that could instead be derived
        # from orientation) are written only if they claim the name first.
        # Everything else is always written up front.
        if kind == self._KIND_SOURCE_RELA:
            if self._rela_owner.setdefault(topic, "source") == "source":
                super().add_message(
                    schema_type, topic, data, publish_time, log_time, **kwargs
                )
            return

        if kind == self._KIND_ROT6D:
            if self._rela_owner.setdefault(topic, "source") != "source":
                return  # A derived rotation_6d already claimed this topic; skip.
            super().add_message(
                schema_type, topic, data, publish_time, log_time, **kwargs
            )
        else:
            # Write the original message first (super() also auto-registers its channel).
            super().add_message(
                schema_type, topic, data, publish_time, log_time, **kwargs
            )

        if kind == self._KIND_PASSTHROUGH:
            return  # Not a float array carrying position/orientation/rot6d data

        arr = np.asarray(data, dtype=np.float32)

        if kind == self._KIND_POSITION:
            if topic not in self._position_refs:
                self._position_refs[topic] = arr
                rela = np.zeros_like(arr)
            else:
                rela = arr - self._position_refs[topic]

            if self._rela_owner.setdefault(rela_topic, "auto") == "auto":
                super().add_message(
                    FlatBuffersSchemas.FLOAT_ARRAY,
                    rela_topic,
                    rela,
                    publish_time,
                    log_time,
                )

        elif kind == self._KIND_ORIENTATION:
            if topic not in self._orientation_refs:
                self._orientation_refs[topic] = arr
                rela = self._IDENTITY_QUAT
            else:
                rela = PoseGlobalRelaAbsTool.to_rela_orientation(
                    arr, self._orientation_refs[topic]
                )

            # Write orientation_rela
            if self._rela_owner.setdefault(rela_topic, "auto") == "auto":
                super().add_message(
                    FlatBuffersSchemas.FLOAT_ARRAY,
                    rela_topic,
                    rela,
                    publish_time,
                    log_time,
                )

            # Derive rotation_6d from orientation, unless a source rot6d claimed
            # this topic first (first-writer-wins).
            if self._rela_owner.setdefault(rot6d_topic, "auto") == "auto":
                rot6d_arr = Rotation6D.quat_to_rot6d(arr)
                super().add_message(
                    FlatBuffersSchemas.FLOAT_ARRAY,
                    rot6d_topic,
                    rot6d_arr,
                    publish_time,
                    log_time,
                )

                # Derive rot6d_rela from orientation_rela (equivalent to to_rela_rot6d per regression)
                if self._rela_owner.setdefault(rot6d_rela_topic, "auto") == "auto":
                    rot6d_rela_arr = Rotation6D.quat_to_rot6d(rela)
                    super().add_message(
                        FlatBuffersSchemas.FLOAT_ARRAY,
                        rot6d_rela_topic,
                        rot6d_rela_arr,
                        publish_time,
                        log_time,
                    )

        elif kind == self._KIND_ROT6D:
            # Ownership of this topic was already claimed "source" by the gate
            # above (which skips the frame entirely if a derived rot6d won).
            if topic not in self._rot6d_refs:
                self._rot6d_refs[topic] = arr
                rela = self._IDENTITY_ROT6D
            else:
                rela = PoseGlobalRelaAbsTool.to_rela_rot6d(arr, self._rot6d_refs[topic])

            if self._rela_owner.setdefault(rela_topic, "auto") == "auto":
                super().add_message(
                    FlatBuffersSchemas.FLOAT_ARRAY,
                    rela_topic,
                    rela,
                    publish_time,
                    log_time,
                )


class McapFlbDataSamplerConfig(McapDataSamplerBasisConfig):
    """Configuration for MCAP data sampler."""

    initial_builder_size: PositiveInt = 1024 * 1024  # 1 MB
    """Initial size of the FlatBuffers builder."""
    add_relative_data: bool = False
    """Whether to auto-write a '<topic>_rela' topic (data relative to the first frame)
    for every topic ending in 'position'/'orientation'. Disable to write raw data only."""
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
        if self.config.add_relative_data:
            return _RelativeFlbWriter(self.config.initial_builder_size)
        # Disabled: stock writer, no relative-data machinery or overhead.
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
