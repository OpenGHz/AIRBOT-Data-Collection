import time
import threading
import rclpy
from rclpy.node import Node
from rclpy.executors import MultiThreadedExecutor
from rclpy.callback_groups import MutuallyExclusiveCallbackGroup

from pydantic import BaseModel
from std_msgs.msg import Float32MultiArray
from typing import Optional, Callable, List, Dict, Union, Type
from enum import IntEnum, auto
from functools import partial
from collections import defaultdict
from airdc.basis import ConfigurableBasis
from airdc.common.utils.relative_control import RelativePoseControl
from airdc.common.utils.coordinate import CoordinateConverter
from airdc.common.utils.ros.ros2 import TFPublisher
from airdc.common.devices.basis import EventValueMode


class VRControllerEvent(IntEnum):
    A = 0
    B = auto()
    LEFT_STICK_V = auto()
    LEFT_STICK_H = auto()
    RIGHT_STICK_V = auto()
    RIGHT_STICK_H = auto()
    LEFT_TRIGGER = auto()
    RIGHT_TRIGGER = auto()
    LEFT_GRIP = auto()
    RIGHT_GRIP = auto()
    X = auto()
    Y = auto()


class VRQuestConfig(BaseModel):
    init_rcl: bool = True
    node_name: str = "vr_quest"
    # TODO: use a spin config
    spin_timeout: Optional[float] = None
    spin_period: float = 0.0
    spin_thread: bool = True
    # event to set the current info pose to be zero
    # which is used to rela-control
    zero_info: Dict[str, Union[VRControllerEvent, int]] = {}
    to_right_hand: bool = True
    publish_tf: bool = True


class VRQuest(ConfigurableBasis):
    config: VRQuestConfig
    event: VRControllerEvent

    def on_configure(self):
        self._pos = {"left", "right"}
        self._event_callbacks: Dict[
            EventValueMode, Dict[VRControllerEvent, List[Callable]]
        ] = defaultdict(lambda: defaultdict(list))
        self._callbacks = []
        self._vr_info_data = {}
        self._last_stamp = defaultdict(float)
        self._vr_control_data = [0.0] * len(self._get_event_type())
        self._init_judgers()
        self._init_ros2()
        return True

    def _get_event_type(self) -> Type[IntEnum]:
        return self.__annotations__["event"]

    def _init_ros2(self):
        if self.config.init_rcl:
            if rclpy.ok():
                self.get_logger().warning(
                    "rcl is already initialized, skipping initialization."
                )
            else:
                rclpy.init()
        self.node = Node(self.config.node_name)
        if self.config.publish_tf:
            self._tf_pub = TFPublisher()
        self._init_subs()
        self._executor = MultiThreadedExecutor(3)
        self._executor.add_node(self.node)
        if self.config.spin_thread:
            self._spin_thread = threading.Thread(target=self._ros_spin, daemon=True)
            self._spin_thread.start()
        self._info_rela_ctrl: Dict[str, RelativePoseControl] = {}
        for pos, event in self.config.zero_info.items():
            self.get_logger().info(f"Registering zero {pos} info callback for {event}.")
            self._info_rela_ctrl[pos] = RelativePoseControl()
            self._update_rela(pos, None)
            self.register_event_callback(
                event,
                partial(self._update_rela, pos),
                EventValueMode.LEAVE_ZERO,
            )
        self.wait_for_info()

    def _init_subs(self):
        """Initialize the ROS2 subscriptions for the VR controller data."""
        self._vr_ctrl_sub = self.node.create_subscription(
            Float32MultiArray,
            "vr_controller",
            self._vr_control_callback,
            10,
            callback_group=MutuallyExclusiveCallbackGroup(),
        )
        self._info_subs = [
            self.node.create_subscription(
                Float32MultiArray,
                f"{pos}Info",
                partial(self._vr_info_callback, pos),
                10,
                callback_group=MutuallyExclusiveCallbackGroup(),
            )
            for pos in self._pos
        ]

    def _update_rela(self, pos: str, data: float):
        """Update the relative control data."""
        self.get_logger().info(f"Updating relative control data for {pos}.")
        self.wait_for_info(pos)
        value = self.get_info_data()[pos]
        self._info_rela_ctrl[pos].update_state(value[:3], value[3:7])

    def _ros_spin(self):
        while rclpy.ok():
            self._executor.spin_once(self.config.spin_timeout)
            time.sleep(self.config.spin_period)

    def _get_control_msg_data(self, msg: Float32MultiArray) -> List[float]:
        """Get the data from the Float32MultiArray message."""
        return msg.data

    def _vr_control_callback(self, msg):
        """Callback for the VR controller data.
        The event callbacks are executed first,
        then the common callbacks, finally the
        internal control data value is updated.
        """
        # self.get_logger().info(
        #     f"Received VR control data: {msg.data}, length: {len(msg.data)}"
        # )
        msg_data = self._get_control_msg_data(msg)
        for mode, event_callbacks in self._event_callbacks.items():
            for event, callbacks in event_callbacks.items():
                data = msg_data[event]
                for callback in callbacks:
                    # self.get_logger().info(f"Processing event {event} with mode {mode}.")
                    if self._judgers[mode](data, event):
                        # self.get_logger().info(
                        #     f"Event {event} triggered with data: {data}, executing callback: {callback}."
                        # )
                        callback(data)
        for callback in self._callbacks:
            callback(self._vr_control_data)
        self._vr_control_data = msg_data

    def _vr_info_callback(self, pos: str, msg: Float32MultiArray):
        if self.config.to_right_hand:
            d = msg.data
            data = CoordinateConverter.convert_left_to_right_handed(d[:3], d[3:7])
            data = data[0] + data[1]
        else:
            data = msg.data
        self._update_pos_info(pos, data)

    def _update_pos_info(self, pos: str, data: List[float]):
        self._vr_info_data[pos] = list(data)
        self._last_stamp[pos] = time.time()
        if self.config.publish_tf:
            self._tf_pub.broadcast_tf(
                data[:3],
                data[3:7],
                child_frame_id=f"/{pos}Info",
            )

    def get_control_data(self) -> List[float]:
        return self._vr_control_data

    def get_info_data(self) -> Dict[str, List[float]]:
        """Get the information data for the left and right controllers."""
        return self._vr_info_data

    def get_rela_info_data(self, pos: str) -> List[float]:
        # self.get_logger().info(f"Getting relative info data for {pos}.")
        pos_data = self._vr_info_data[pos]
        data = self._info_rela_ctrl[pos].to_relative(pos_data[:3], pos_data[3:7])
        if self.config.publish_tf:
            self._tf_pub.broadcast_tf(
                data[0],
                data[1],
                child_frame_id=f"/{pos}RelaInfo",
            )
        return data[0] + data[1]

    def wait_for_info(
        self, pos: Optional[str] = None, timeout: Optional[float] = None
    ) -> bool:
        """Wait for the information data to be available."""
        self.get_logger().info(
            f"Waiting for VR info data for {pos} with timeout {timeout} seconds."
        )
        start_time = time.time()
        pos = {pos} if pos else self._pos
        last_stamp = self._last_stamp.copy()
        while timeout is None or time.time() - start_time < timeout:
            for p in pos:
                if self._last_stamp[p] == last_stamp[p]:
                    break
            else:
                self.get_logger().info(f"VR info data for {pos} is available.")
                return True
            time.sleep(0.1)  # Sleep to avoid busy waiting
        self.get_logger().error(
            f"Timeout waiting for VR info data after {timeout} seconds."
        )
        return False

    def spin_once(self) -> bool:
        rclpy.spin_once(self.node, timeout_sec=self.config.spin_timeout)
        return True

    def shutdown(self) -> bool:
        return self.node.destroy_node()


if __name__ == "__main__":
    from airdc.utils import init_logging
    from pprint import pprint
    import logging

    init_logging(logging.INFO)

    vr = VRQuest(VRQuestConfig(zero_info={"right": VRControllerEvent.RIGHT_GRIP}))
    assert vr.configure()
    vr.register_event_callback(
        VRControllerEvent.B,
        lambda data: vr.get_logger().info(f"B button value changed with data: {data}"),
        mode=EventValueMode.VALUE_CHANGE,
    )
    for event in {VRControllerEvent.RIGHT_STICK_V, VRControllerEvent.RIGHT_STICK_H}:
        vr.register_event_callback(
            event,
            lambda data, e=event: vr.get_logger().info(
                f"Event {e} triggered with data: {data}"
            ),
        )
    pos = "right"
    assert vr.wait_for_info(pos)
    pprint(vr.get_info_data()[pos])
    while input("Press Enter to continue...") != "z":
        pprint(vr.get_info_data()[pos])
        pprint(vr.get_rela_info_data(pos))
    assert vr.shutdown()
