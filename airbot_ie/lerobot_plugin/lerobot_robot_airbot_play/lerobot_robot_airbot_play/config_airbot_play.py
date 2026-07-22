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

    # --- control space ---
    control_mode: str = "joint"
    """Control space for observation.state / action. Must match how the checkpoint
    was trained (``mcap.states`` / ``mcap.actions``):

    * ``"joint"`` (default): the 6 arm joints (+ gripper if ``eef`` in
      ``components``) as ``"<joint>.pos"`` — observation.state/action dim 6 or 7.
    * ``"pose"``: the arm EEF cartesian pose (position xyz[3] + orientation
      quaternion xyzw[4]) + gripper joint (1 if ``eef``) — dim 7 or 8, in the
      order [position, orientation, gripper]. The pose is read via the airdc
      System's ``eef/pose/*`` observation and commanded via ``servo_cart_pose``
      (SERVO_CART_POSE); the gripper stays a joint command. Homing/``initial_pose``
      remain joint-space regardless of this setting.

    Default ``"joint"`` keeps the previous behavior (and the base-model mock
    smoke test) working unchanged."""

    # --- LeRobot-facing feature naming ---
    arm_joint_names: List[str] = field(
        default_factory=lambda: [f"joint_{i}" for i in range(1, 7)]
    )
    """LeRobot names for the 6 arm joints (order matters: maps to airdc arm
    ``joint_state/position`` in order). Used only in ``control_mode="joint"``."""

    gripper_joint_name: str = "gripper"
    """LeRobot name for the single eef/gripper DoF. Ignored if ``eef`` is not in
    ``components``. Used in both control modes (the gripper is always a joint)."""

    # --- pose feature naming (control_mode="pose") ---
    # IMPORTANT: every scalar (non-camera) state/action feature key MUST end in
    # ".pos". LeRobot's rollout context filters the robot's scalar features with
    # `v is float and k.endswith(".pos")` (observation) and `k.endswith(".pos")`
    # (action) — see lerobot/rollout/context.py. Keys that don't match are
    # silently dropped, which would shrink observation.state / the action vector
    # (e.g. to just the gripper) instead of raising. So the pose components are
    # named `eef_x.pos` ... `eef_qw.pos` rather than `eef.x` / `eef.qx`.
    position_keys: List[str] = field(
        default_factory=lambda: ["eef_x.pos", "eef_y.pos", "eef_z.pos"]
    )
    """LeRobot feature names for the EEF position xyz (3). Order maps to the airdc
    ``eef/pose/position`` vector in order. Must end in ".pos" (see note above).
    Used only in ``control_mode="pose"``."""

    orientation_keys: List[str] = field(
        default_factory=lambda: [
            "eef_qx.pos",
            "eef_qy.pos",
            "eef_qz.pos",
            "eef_qw.pos",
        ]
    )
    """LeRobot feature names for the EEF orientation quaternion, xyzw (4). Order
    maps to the airdc ``eef/pose/orientation`` vector (xyzw, as returned by
    ``get_end_pose``). Must end in ".pos" (see note above). Used only in
    ``control_mode="pose"``."""

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
