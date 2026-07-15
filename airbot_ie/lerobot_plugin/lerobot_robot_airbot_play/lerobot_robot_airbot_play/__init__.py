"""LeRobot Robot plugin for the AIRBOT Play arm.

Exposes the config and device classes so LeRobot's plugin discovery (packages
named ``lerobot_robot_*``) can find them and register ``--robot.type=airbot_play``.
"""

from .airbot_play import AIRBOTPlayRobot
from .config_airbot_play import AIRBOTPlayRobotConfig, AirdcCameraSpec

__all__ = ["AIRBOTPlayRobot", "AIRBOTPlayRobotConfig", "AirdcCameraSpec"]
