"""Configuration for the aao (auto-atomic-operation) MuJoCo sim LeRobot robot.

Follows the LeRobot plugin conventions: distribution name starts with
`lerobot_robot_`, config class is `AAOSimRobotConfig`, device class is
`AAOSimRobot` (both exported from the package `__init__`).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

from lerobot.robots import RobotConfig


@RobotConfig.register_subclass("aao_sim")
@dataclass
class AAOSimRobotConfig(RobotConfig):
    """Config for :class:`AAOSimRobot` (state-only, EEF-pose control).

    The state/action feature keys are config-driven so they line up with the
    features the checkpoint was trained on (same idea as the airbot plugin's
    joint-name config). Defaults expose an EEF pose: position xyz + orientation
    quaternion (xyzw) + gripper, i.e. a 8-dim vector; drop `gripper.pos` (and set
    `has_gripper=False`) or trim the quaternion to match a 7-dim eef-pose
    checkpoint that omits the gripper.
    """

    # --- aao scene / control ---
    task_config: str = "open_door_airbot_play_g2p"
    """auto-atomic-operation task config name (loaded via Hydra). Must be a
    COMPLETE task config (defines scene_name etc.), not a `basis_*` building
    block. Picks the robot morphology, scene, and IK — match what the policy was
    trained on. Default is an AIRBOT Play + G2P gripper door-opening scene."""

    operator: str = "arm"
    """Registered operator name in the aao env whose EEF pose is controlled."""

    config_dir: str = ""
    """Directory holding the aao task configs (the `aao_configs/` folder). Empty
    = auto-detect next to the installed `auto_atom` package. Set this if your
    configs live elsewhere; `load_task_file_hydra` otherwise defaults to
    `<cwd>/aao_configs`, which fails when run from a different working dir."""

    hydra_overrides: List[str] = field(default_factory=list)
    """Extra Hydra override strings passed to load_task_file_hydra
    (e.g. ["task.seed=0"]). batch_size is forced to 1 by the robot."""

    kinematic: bool = False
    """If True, teleport the EEF to the target pose (mj_forward only, exact pose,
    no physics). If False, reach it through physics with `substeps` mj_steps."""

    substeps: int = 1
    """Number of env steps to advance per send_action (physics settle)."""

    # --- LeRobot-facing feature naming ---
    position_keys: List[str] = field(
        default_factory=lambda: ["eef.x", "eef.y", "eef.z"]
    )
    """Feature names for the EEF position (3)."""

    orientation_keys: List[str] = field(
        default_factory=lambda: ["eef.qx", "eef.qy", "eef.qz", "eef.qw"]
    )
    """Feature names for the EEF orientation quaternion, xyzw (4)."""

    has_gripper: bool = True
    """Whether to expose/consume a gripper DoF."""

    gripper_key: str = "gripper.pos"
    """Feature name for the single gripper DoF (used iff has_gripper)."""
