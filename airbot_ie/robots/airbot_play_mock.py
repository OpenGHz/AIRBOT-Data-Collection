from airbot_ie.robots.airbot_play import (
    AIRBOTPlay as AIRBOTPlayReal,
    AIRBOTPlayConfig as AIRBOTPlayConfigReal,
    RobotMode,
    SpeedProfile,
)
import numpy as np
from typing import List
from airdc.common.utils.curve import SineGenerator
import logging


class AIRBOTArmMock:
    def __init__(self, config=None, **kwargs):
        length = 6
        self.value = [0.0] * length
        self._eef_pos = None
        self._joint_pos = None
        self._pose = None
        self._gen = SineGenerator(length, 0, np.pi / 10, 0.1)

    def get_joint_pos(self):
        return self._joint_pos or self._gen.update().tolist()

    def get_joint_vel(self):
        return [float("nan")] * len(self.value)

    def get_joint_eff(self):
        # return self.value
        return [None] * len(self.value)

    def get_eef_pos(self):
        return self._eef_pos or [np.random.uniform(0.0, 0.0471)]
        # return [0.0471 / 2]

    # def get_eef_vel(self):
    #     return [0.0]

    def get_eef_eff(self):
        return [0.0]

    def get_end_pose(self):
        return self._pose or [[0.0, 0.0, 0.0], [0.0, 0.0, 0.0, 1.0]]

    def connect(self):
        return True

    def set_speed_profile(self, speed_profile):
        return isinstance(speed_profile, SpeedProfile)

    def servo_joint_pos(self, joint_pos, speed_profile=None, log="servo joint pos"):
        self.get_logger().debug(f"{log}: {joint_pos}")
        assert isinstance(joint_pos, list)
        assert len(joint_pos) == 6, joint_pos
        self._joint_pos = joint_pos

    def servo_eef_pos(self, eef_pos, speed_profile=None, log="servo eef pos"):
        self.get_logger().debug(f"{log}: {eef_pos}")
        assert len(eef_pos) == 1, eef_pos
        assert isinstance(eef_pos, list), eef_pos
        assert isinstance(eef_pos[0], (float, int)), eef_pos
        self._eef_pos = eef_pos

    def move_eef_pos(self, eef_pos, speed_profile=None):
        self.servo_eef_pos(eef_pos, speed_profile, "move eef pos")

    def move_to_joint_pos(self, joint_pos, speed_profile=None):
        self.servo_joint_pos(joint_pos, speed_profile, "move_to_joint_pos")

    def move_to_cart_pose(self, pose, speed_profile=None, log="move to cart pose"):
        position, orientation = pose
        assert isinstance(position, list)
        assert isinstance(orientation, list)
        assert len(position) == 3
        assert len(orientation) == 4
        assert speed_profile is None
        self._pose = pose
        self.get_logger().debug(f"{log}: {pose}")

    def mit_joint_integrated_control(self, joint_pos, joint_vel, joint_eff, kp, kd):
        assert isinstance(joint_pos, list)
        assert isinstance(joint_vel, list)
        assert isinstance(joint_eff, list)
        assert isinstance(kp, list)
        assert isinstance(kd, list)
        assert len(joint_pos) == 6
        assert len(joint_vel) == 6
        assert len(joint_eff) == 6
        assert len(kp) == 6
        assert len(kd) == 6

    def servo_cart_pose(self, pose, speed_profile=None):
        self.move_to_cart_pose(pose, speed_profile, "servo cart pose")

    def get_product_info(self):
        return {"product_type": "replay", "eef_types": ["PE2"]}

    def set_params(self, params: dict):
        return isinstance(params, dict)

    def switch_mode(self, mode):
        self.get_logger().info(f"Switched mode to {mode}")
        return isinstance(mode, RobotMode)

    def disconnect(self):
        return True

    @classmethod
    def get_logger(cls) -> logging.Logger:
        return logging.getLogger(cls.__name__)


class AIRBOTPlayConfig(AIRBOTPlayConfigReal):
    """
    A mock configuration class for AIRBOTPlay.
    """

    product_type: str = "replay"
    eef_types: List[str] = ["PE2"]
    log_level: int = logging.INFO


class AIRBOTPlay(AIRBOTPlayReal):
    """
    A mock class for AIRBOTPlay.
    """

    config: AIRBOTPlayConfig
    interface: AIRBOTArmMock

    def on_configure(self):
        self.interface.get_product_info = lambda: {
            "product_type": self.config.product_type,
            "eef_types": self.config.eef_types,
        }
        self.interface.get_logger().setLevel(self.config.log_level)
        return super().on_configure()


if __name__ == "__main__":
    import numpy as np

    # Test the mock class
    robot = AIRBOTPlay(AIRBOTPlayConfig())
    assert robot.configure()
    # print(robot.capture_observation())
    robot.send_action([0.0] * 7)
    robot.send_action([0.0] * 6)
    robot.send_action(
        {
            "arm/joint_state/position": {"data": np.array([0.0] * 6)},
            "eef/joint_state/position": {"data": np.array([0.02355])},
        }
    )
    robot.send_action(
        {
            "arm/joint_state/position": {"data": np.array([0.0] * 6)},
            # "eef/joint_state/position": {"data": np.array([0.02355])},
        }
    )
    robot.action_post_process = robot.action_to_list
    robot.send_action(
        {
            "arm/joint_state/position": np.array([0.0] * 6),
        }
    )
    robot.action_post_process = robot.action_forward
    robot.send_action(
        {
            "arm/joint_state/position": [0.0] * 6,
        }
    )
