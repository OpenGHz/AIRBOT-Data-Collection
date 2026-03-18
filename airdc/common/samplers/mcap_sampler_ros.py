from typing import Optional, ClassVar, Dict, Any
from collections.abc import Sequence
from typing_extensions import Self, TypedDict
from airdc.common.utils.ros.mcap import Writer, get_mcap_writer
from airdc.common.samplers.mcap_sampler import (
    McapDataSamplerConfig,
    McapDataSampler,
)
from airdc.common.utils.ros import (
    get_message,
    get_message_short,
    get_fields_and_field_types,
    time_ns_to_stamp,
    process_camera_info_dict,
    set_message_fields,
    get_current_stamp,
)
from inflection import camelize
from pydantic import BaseModel
from functools import cache
from more_itertools import zip_equal
from std_msgs.msg import Header
from sensor_msgs.msg import CameraInfo, PointCloud2, PointField
import numpy as np


class MessageDict(TypedDict):
    value: Dict[str, dict]
    t: int
    log_time: int


class TopicInfo(BaseModel, frozen=True):
    topic: str
    msg_name_snake: str
    msg_type: type
    msg_type_stamped: Optional[type]
    fields_and_field_types: Dict[str, type]
    msg_dict: MessageDict = {"value": {}, "t": 0, "log_time": 0}
    topic_info: ClassVar[Dict[str, Self]] = {}

    @classmethod
    def from_topic_name(cls, topic: str) -> Optional[Self]:
        if topic in cls.topic_info:
            return cls.topic_info[topic]
        split = topic.rsplit("/", 1)
        if len(split) != 2:
            return None
        msg_name_no_stamp = split[1]
        msg_identifier = camelize(msg_name_no_stamp)
        msg_type = get_message_short(msg_identifier)
        if msg_type is not None:
            msg_type_stamped = get_message_short(msg_identifier + "Stamped")
            fields_and_field_types = {}
            for filed, field_type_str in get_fields_and_field_types(msg_type).items():
                field_type = (
                    list
                    if field_type_str.startswith("sequence")
                    or field_type_str.endswith("[]")
                    else get_message(field_type_str)
                )
                fields_and_field_types[filed] = field_type
            instance = cls(
                topic=topic,
                msg_name_snake=msg_name_no_stamp,
                msg_type=msg_type,
                msg_type_stamped=msg_type_stamped,
                fields_and_field_types=fields_and_field_types,
            )
            cls.topic_info[topic] = instance
            return instance

    @property
    def has_stamp(self) -> bool:
        return self.msg_type_stamped is not None


class KeyInfo(BaseModel, frozen=True):
    """The info for a specific key."""

    key: str
    """The name of the key."""
    topic_info: TopicInfo
    """The info of the topic the key belongs to."""
    field: str
    """The name of the corresponding field in the topic message."""
    field_type: type
    """The type of the corresponding field in the topic message."""

    def model_post_init(self, context):
        field_type = self.field_type
        if field_type is list:
            self._field_setter = lambda data: data
        else:  # e.g. Point(x=.., y=.., z=..)
            field_fft = get_fields_and_field_types(field_type)
            self._field_kwords = field_fft.keys()
            for field_t in set(field_fft.values()):
                for prefix in ("double", "float", "string", "int", "uint", "bool"):
                    if field_t.startswith(prefix):
                        break
                else:
                    raise NotImplementedError(
                        f"Field setter for {field_type} with {field_fft} not implemented"
                    )
            self._field_setter = self.seq2field_basic

    def add_data(self, data: dict, log_time: int):
        msg_dict = self.topic_info.msg_dict
        msg_dict["value"][self.field] = self._field_setter(data["data"])
        msg_dict["t"] = data["t"]
        msg_dict["log_time"] = log_time

    def seq2field_basic(self, seq: Sequence):
        return self.field_type(**dict(zip_equal(self._field_kwords, seq)))

    @staticmethod
    def _get_header(msg_dict: MessageDict) -> Header:
        return Header(stamp=time_ns_to_stamp(msg_dict["t"]))

    @classmethod
    def finish_add(cls) -> Dict[str, Any]:
        data = {}
        for topic, info in TopicInfo.topic_info.items():
            msg_dict = info.msg_dict
            msg = info.msg_type(**msg_dict["value"])
            if info.has_stamp:
                msg = info.msg_type_stamped(
                    header=cls._get_header(msg_dict),
                    **{info.msg_name_snake: msg},
                )
            elif "header" in info.fields_and_field_types:
                msg.header = cls._get_header(msg_dict)
            # TODO: use a tuple for better perf?
            data[topic] = {
                "message": msg,
                "log_time": msg_dict["log_time"],
                "publish_time": msg_dict["t"],
            }
            info.msg_dict["value"] = {}
        return data


class McapDataSamplerROS(McapDataSampler):
    """Mcap data sampler for ROS data."""

    def _create_writer(self, path):
        self._ros_writer = Writer(str(path))
        return get_mcap_writer(self._ros_writer), False

    def update(self, data):
        data = super().update(data)
        for topic, msg_data in KeyInfo.finish_add().items():
            topic = self.config.key_remap(topic)
            self._ros_writer.write_message(topic, **msg_data)
        return data

    def _add_messages(self, key, values, log_stamps):
        if self._is_tactile_point_cloud(key):
            for value, log_stamp in zip_equal(values, log_stamps):
                msg = self._get_tactile_point_cloud_msg(value)
                topic = self.config.key_remap(key)
                self._ros_writer.write_message(topic, message=msg, log_time=log_stamp)
            return True

        info = self._process_key(key)
        if info is not None:
            for i, value in enumerate(values):
                info.add_data(value, log_stamps[i])
            return True
        return super()._add_messages(key, values, log_stamps)

    @cache
    def _is_tactile_point_cloud(self, key: str) -> bool:
        return "tactile/point_cloud" in key

    @cache
    def _process_key(self, key: str) -> Optional[KeyInfo]:
        split = key.rsplit("/", 1)
        if len(split) != 2:
            return None
        topic_name, field_name = split
        topic_info = TopicInfo.from_topic_name(topic_name)
        if isinstance(topic_info, TopicInfo):
            return KeyInfo(
                key=key,
                topic_info=topic_info,
                field=field_name,
                field_type=topic_info.fields_and_field_types[field_name],
            )

    @cache
    def _get_camera_info(self) -> Dict[str, CameraInfo]:
        all_camera_info = {}
        for key, info in self._info.items():
            if "camera" in key or key.endswith("_cam") or key.startswith("cam_"):
                for stream_type in ("color", "depth"):
                    stream_cfg = info.get(stream_type, {})
                    camera_info = stream_cfg.get("camera_info")
                    if camera_info:
                        process_camera_info_dict(camera_info)
                        cam_info_msg = CameraInfo(
                            header=Header(stamp=get_current_stamp())
                        )
                        set_message_fields(cam_info_msg, camera_info)
                        all_camera_info[f"{key}/{stream_type}/camera_info"] = (
                            cam_info_msg
                        )
        return all_camera_info

    @cache
    def _get_tactile_point_cloud_msg(self, key: str, data):
        rows = 8
        cols = 5
        max_points = rows * cols

        packed_points = np.zeros((max_points, 6), dtype=np.float32)
        panel_data = data["data"]
        for i in range(min(len(panel_data), max_points)):
            row = i // cols
            col = i % cols
            packed_points[i, 0] = col * 0.005
            packed_points[i, 1] = row * 0.005
            packed_points[i, 2] = 0.0
            packed_points[i, 3] = panel_data[i, 0]
            packed_points[i, 4] = panel_data[i, 1]
            packed_points[i, 5] = panel_data[i, 2]

        fields = [
            PointField(name="x", offset=0, datatype=PointField.FLOAT32, count=1),
            PointField(name="y", offset=4, datatype=PointField.FLOAT32, count=1),
            PointField(name="z", offset=8, datatype=PointField.FLOAT32, count=1),
            PointField(name="fx", offset=12, datatype=PointField.FLOAT32, count=1),
            PointField(name="fy", offset=16, datatype=PointField.FLOAT32, count=1),
            PointField(name="fz", offset=20, datatype=PointField.FLOAT32, count=1),
        ]

        pc_msg = PointCloud2()
        pc_msg.header.stamp = panel_data["t"]
        pc_msg.header.frame_id = key.removeprefix("/").split("/")[0] + "_tactile_frame"
        pc_msg.height = rows
        pc_msg.width = cols
        pc_msg.fields = fields
        pc_msg.is_bigendian = False
        pc_msg.point_step = 24
        pc_msg.row_step = pc_msg.point_step * pc_msg.width
        pc_msg.data = packed_points.tobytes()
        pc_msg.is_dense = True
        return pc_msg

    def save(self, path, data):
        camera_info = self._get_camera_info()
        for topic, msg in camera_info.items():
            topic = self.config.key_remap(topic)
            self._ros_writer.write_message(topic, msg)
        return super().save(path, data)


if __name__ == "__main__":
    from airdc.common.samplers.mcap_sampler import (
        McapDataSamplerConfig,
    )
    from pathlib import Path
    import time
    import logging
    import rospy

    rospy.init_node("mcap_sampler_ros_test")

    logging.basicConfig(level=logging.INFO)

    sampler = McapDataSamplerROS(McapDataSamplerConfig())

    assert sampler.configure()
    directory = Path("data/ros1")
    directory.mkdir(exist_ok=True)
    path = sampler.compose_path(directory, 0)
    sampler.set_info({})
    data = sampler.update(
        {
            "/arm/joint_state/position": {"data": [0.1, 0.2, 0.3], "t": time.time_ns()},
            "/arm/joint_state/velocity": {"data": [0.4, 0.5, 0.6], "t": time.time_ns()},
            "/arm/joint_state/effort": {"data": [0.7, 0.8, 0.9], "t": time.time_ns()},
            "/eef/pose/position": {"data": [1.0, 2.0, 3.0], "t": time.time_ns()},
            "/eef/pose/orientation": {
                "data": [0.0, 0.0, 0.0, 1.0],
                "t": time.time_ns(),
            },
            "log_stamps": time.time_ns(),
        }
    )
    print(data)
    sampler.save(path, {"log_stamps": [time.time_ns()]})

    print(f"Saved MCAP file to {path}")
