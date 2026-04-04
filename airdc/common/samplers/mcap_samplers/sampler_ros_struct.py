from airdc.common.samplers.mcap_samplers.basis import McapDataSamplerBasis
from airdc.common.samplers.basis import DataSamplerConfig
from mcap_data_loader.serialization.ros.mcap import McapROSWriter
from mcap_data_loader.serialization.ros import TopicInfo, ROS_VERSION
from mcap_data_loader.basis.data_stamped import DictDataStamped
from mcap_data_loader.serialization.ros.compressed_video import (
    CompressedVideoEncoder,
    CompressedVideoEncoderConfig,
)
from typing import Optional, Dict, Any
from pathlib import Path
from foxglove_msgs.msg import CompressedVideo
from functools import cache
from collections import defaultdict


class McapDataSamplerROSStructConfig(DataSamplerConfig):
    """Configuration for McapDataSamplerROSStruct."""

    compressed_video: CompressedVideoEncoderConfig = CompressedVideoEncoderConfig()


class McapDataSamplerROSStruct(McapDataSamplerBasis):
    """McapDataSamplerROSStruct is a data sampler that handles ROS structured messages and saves them in MCAP format."""

    def __init__(self, config: McapDataSamplerROSStructConfig):
        self.config = config

    def on_configure(self):
        self._coders = defaultdict(
            lambda: CompressedVideoEncoder(self.config.compressed_video)
        )
        return super().on_configure()

    def clear(self):
        """Reset video coders so timestamps start fresh after abandon/clear."""
        for coder in self._coders.values():
            coder.reset()

    def on_compose_path(self, directory, episode):
        self.clear()
        return super().on_compose_path(directory, episode)

    def _create_writer(self):
        self._data_writer: McapROSWriter
        return McapROSWriter()

    def update(self, data: DictDataStamped[Dict[str, Any]]):
        for key in data.keys() - {"log_stamps"}:
            d = data.pop(key)
            d_value = d["data"]
            # print(f"Processing key: {key}")
            info = TopicInfo.from_topic_name(self._key_remapping(key))
            msg_type = info.msg_type
            if msg_type is CompressedVideo:
                d_value = self._coders[key].encode(d_value, timestamp_sec=d["t"] / 1e9)
            else:
                header = d_value.get("header")
                if header is not None:
                    if ROS_VERSION == "1" and isinstance(header.get("stamp"), dict):
                        stamp = header["stamp"]
                        header["stamp"] = [stamp["sec"], stamp["nsec"]]
                    if info.has_stamp:
                        msg_type = info.msg_type_stamped
            self._data_writer.add_message(
                msg_type, key, d_value, d["t"], data["log_stamps"]
            )
        return data

    def save(self, path, data):
        for coder in self._coders.values():
            coder.end()
        return super().save(path, data)

    def _key_to_msg_type(self, key: str) -> Optional[str]:
        """Convert a data key to a ROS message type string."""
        return Path(key).name

    @cache
    def _key_remapping(self, key: str) -> str:
        key_path = Path(key)
        parent = key_path.parent
        if key_path.name == "video_encoded":
            msg_type = "compressed_video"
        elif key_path.name == "image_raw":
            msg_type = "image"
        elif key_path.name == "distance":
            msg_type = "JointState"
        elif key_path.name == "rotation_angle":
            msg_type = "Vector3Stamped"
        else:
            msg_type = None
        if msg_type is not None:
            return str(parent / msg_type)
        return key


if __name__ == "__main__":
    import time
    import numpy as np

    sampler = McapDataSamplerROSStruct(McapDataSamplerROSStructConfig())

    sampler.set_info({})
    assert sampler.configure()

    episode = 0
    path = sampler.compose_path("data/test", episode)

    # sampling mock data
    sample_count = 10
    log_stamps = []
    for i in range(sample_count):
        t = time.time_ns()
        log_stamps.append(t)
        stamp = {"sec": t // 1_000_000_000, "nsec": t % 1_000_000_000}
        header = {"stamp": stamp, "frame_id": "base_link"}
        data = {
            # sensor_msgs/Image
            "/robot/camera/right_wrist/depth/image_raw": {
                "data": {
                    "header": header,
                    "height": 480,
                    "width": 640,
                    "encoding": "16UC1",
                    "is_bigendian": 0,
                    "step": 1280,
                    "data": np.zeros(480 * 640 * 2, dtype=np.uint8).tobytes(),
                },
                "t": t,
            },
            # geometry_msgs/TransformStamped
            "/robot/camera/right_wrist/hand_eye/transform": {
                "data": {
                    "header": header,
                    "child_frame_id": "right_wrist_camera",
                    "transform": {
                        "translation": {"x": 0.1, "y": 0.0, "z": 0.3},
                        "rotation": {"x": 0.0, "y": 0.0, "z": 0.0, "w": 1.0},
                    },
                },
                "t": t,
            },
            # sensor_msgs/CameraInfo
            "/robot/camera/right_wrist/camera_info": {
                "data": {
                    "header": header,
                    "height": 480,
                    "width": 640,
                    "distortion_model": "plumb_bob",
                    "D": [0.0] * 5,
                    "K": [615.0, 0.0, 320.0, 0.0, 615.0, 240.0, 0.0, 0.0, 1.0],
                    "R": [1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0],
                    "P": [
                        615.0,
                        0.0,
                        320.0,
                        0.0,
                        0.0,
                        615.0,
                        240.0,
                        0.0,
                        0.0,
                        0.0,
                        1.0,
                        0.0,
                    ],
                },
                "t": t,
            },
            # foxglove_msgs/CompressedVideo (video_encoded → compressed_video)
            "/robot/camera/right_wrist/video_encoded": {
                "data": np.random.randint(0, 256, (480, 640, 3), dtype=np.uint8),
                "t": t,
            },
            # geometry_msgs/PoseStamped
            "/robot/right_gripper/pose": {
                "data": {
                    "header": header,
                    "pose": {
                        "position": {"x": 0.3 + 0.01 * i, "y": 0.0, "z": 0.5},
                        "orientation": {"x": 0.0, "y": 0.0, "z": 0.0, "w": 1.0},
                    },
                },
                "t": t,
            },
            # sensor_msgs/JointState (gripper)
            "/robot/right_gripper/distance": {
                "data": {
                    "name": ["right_gripper"],
                    "position": [0.04 - 0.002 * i],
                    "velocity": [0.0],
                    "effort": [0.0],
                },
                "t": t,
            },
            # sensor_msgs/JointState (arm)
            "/robot/right_arm/joint_state": {
                "data": {
                    "name": [f"joint{j}" for j in range(1, 8)],
                    "position": [0.1 * i + 0.05 * j for j in range(7)],
                    "velocity": [0.0] * 7,
                    "effort": [0.0] * 7,
                },
                "t": t,
            },
            # geometry_msgs/Vector3Stamped (door)
            "/scene/door/rotation_angle": {
                "data": {
                    "header": header,
                    "vector": {"x": 0.0, "y": 0.0, "z": 0.1 * i},
                },
                "t": t,
            },
            # geometry_msgs/Vector3Stamped (handle)
            "/scene/door/handle/rotation_angle": {
                "data": {
                    "header": header,
                    "vector": {"x": 0.0, "y": 0.0, "z": 0.05 * i},
                },
                "t": t,
            },
            "log_stamps": t,
        }
        sampler.update(data)

    sampler.save(path, {"log_stamps": log_stamps})
    sampler.shutdown()

    print(f"Saved {sample_count} samples to {path}")
