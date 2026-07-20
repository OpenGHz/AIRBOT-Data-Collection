"""LeRobot Robot plugin: run a LeRobot policy in the auto-atomic-operation
MuJoCo simulator (state-only, EEF-pose control).

Exposes the config + device classes so LeRobot's plugin discovery (packages
named ``lerobot_robot_*``) registers ``--robot.type=aao_sim``.
"""

from .aao_sim import AAOSimRobot
from .config_aao_sim import AAOSimRobotConfig

__all__ = ["AAOSimRobot", "AAOSimRobotConfig"]
