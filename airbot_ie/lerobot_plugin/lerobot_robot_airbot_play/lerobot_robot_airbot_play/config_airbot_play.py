"""Configuration for the AIRBOT Play LeRobot robot plugin.

This follows the LeRobot "bring your own hardware" plugin conventions:
- the distribution name starts with ``lerobot_robot_`` (see pyproject),
- the config class is ``AIRBOTPlayRobotConfig`` and the device class is
  ``AIRBOTPlayRobot`` (``Config`` suffix dropped),
- both are exposed from the package ``__init__``.

The robot itself is a thin adapter over ``airbot_ie.robots.airbot_play.AIRBOTPlay``
(an ``airdc`` ``System``). See ``airbot_play.py`` for the bridge.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from lerobot.robots import RobotConfig


@dataclass
class AirdcCameraSpec:
    """Spec for reusing an ``airdc`` camera device inside this robot.

    The referenced ``target`` class is an ``airdc`` ``ConfigurableBasis`` sensor
    (e.g. ``airdc.common.devices.cameras.v4l2.V4L2Camera``). Thanks to the
    ``cfgable`` metaclass, it can be constructed directly as
    ``target_cls(width=..., height=..., fps=..., **extra)`` and it will build its
    own config internally.

    ``width``/``height``/``fps`` are duplicated here (rather than only in
    ``extra``) because LeRobot's ``RobotConfig`` validates that every camera
    exposes these attributes, and because ``observation_features`` needs the
    image shape while the robot is *not yet connected*.
    """

    target: str = "airdc.common.devices.cameras.v4l2.V4L2Camera"
    """Import path of the airdc camera Sensor class."""

    width: int = 640
    """Frame width in pixels (also used for observation_features shape)."""

    height: int = 480
    """Frame height in pixels (also used for observation_features shape)."""

    fps: Optional[int] = 30
    """Frame rate. Required to be non-None by LeRobot's RobotConfig validation."""

    extra: Dict = field(default_factory=dict)
    """Extra kwargs forwarded to the airdc camera config (e.g. ``camera_index``,
    ``serial_number``, ``blocking``)."""


@RobotConfig.register_subclass("airbot_play")
@dataclass
class AIRBOTPlayRobotConfig(RobotConfig):
    """Config for :class:`AIRBOTPlayRobot`.

    Feature-key naming follows the LeRobot tutorial default: joint positions are
    exposed as ``"<joint_name>.pos"`` and cameras as their dict key. If you need
    to match a checkpoint trained with different feature keys, change
    ``arm_joint_names`` / ``gripper_joint_name`` / camera keys accordingly.
    """

    # --- connection to the airbot arm (airdc System) ---
    url: str = "localhost"
    """Robot server URL (gRPC backend)."""

    port: int = 50050
    """Robot server port."""

    backend: str = "grpc"
    """airdc backend: ``grpc`` (real hardware) or ``thin``."""

    mock: bool = False
    """If True, use ``airbot_ie.robots.airbot_play_mock`` instead of the real
    system. Useful for offline testing of the LeRobot integration."""

    components: List[str] = field(default_factory=lambda: ["arm", "eef"])
    """airdc components to control. Currently ``arm`` and optional ``eef``."""

    # --- LeRobot-facing feature naming ---
    arm_joint_names: List[str] = field(
        default_factory=lambda: [f"joint_{i}" for i in range(1, 7)]
    )
    """LeRobot names for the 6 arm joints (order matters: maps to airdc arm
    ``joint_state/position`` in order)."""

    gripper_joint_name: str = "gripper"
    """LeRobot name for the single eef/gripper DoF. Ignored if ``eef`` is not in
    ``components``."""

    # --- cameras (reused airdc devices) ---
    cameras: Dict[str, AirdcCameraSpec] = field(default_factory=dict)
    """Mapping of LeRobot observation key -> airdc camera spec. Empty by default
    (state-only). The image observation key is exactly this dict key."""

    # --- startup homing ---
    initial_pose: Optional[List[float]] = None
    """Optional home joint pose to move to on connect, BEFORE entering servo mode.

    When set, the arm plans a motion to this pose (airdc RESETTING / PLANNING_POS,
    blocking until it arrives) so the policy always starts from a known posture.
    None (default) leaves the arm wherever it is.

    Length must match the proprio dim implied by ``components``: 6 for ``[arm]``
    (the 6 arm joints), or 7 for ``[arm, eef]`` (6 arm joints + gripper), in the
    same order as ``observation.state`` / actions. Values are joint positions in
    the arm's native units (radians for arm joints, the gripper's own unit)."""
