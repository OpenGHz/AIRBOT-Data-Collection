from typing import Optional, Tuple
from airdc.common.systems.basis import ActionConfig, InterfaceType, InterfaceKind
from enum import Enum
from pydantic import BaseModel, PositiveFloat, NonNegativeInt
from typing import List, Literal


class JointControlBasis(ActionConfig):
    """Base configuration for joint control of the robot."""

    @property
    def interfaces(self):
        return {InterfaceType.JOINT_POSITION}


class JointPositionServo(JointControlBasis):
    """Configuration for the joint position control of the robot."""


class JointPositionPlan(JointControlBasis):
    """Configuration for the joint position plan control of the robot."""


class JointMIT(JointControlBasis):
    """Configuration for the MIT control of the robot."""

    @property
    def interfaces(self):
        return {
            InterfaceType.JOINT_POSITION,
            InterfaceType.JOINT_VELOCITY,
            InterfaceType.JOINT_EFFORT,
            InterfaceType.JOINT_KP,
            InterfaceType.JOINT_KD,
        }


class PoseControlBasis(ActionConfig):
    """Configuration for the pose control of the robot."""

    pose_reference_frame: str = ""
    """The reference frame for the pose control."""
    fixed_orientation: Optional[Tuple[float, float, float, float]] = None
    """The fixed orientation (as a quaternion) for the pose control."""

    @property
    def interfaces(self):
        return {InterfaceType.POSE}


class PoseServo(PoseControlBasis):
    """Configuration for the pose servo control of the robot."""

    pass


class PosePlan(PoseControlBasis):
    """Configuration for the pose servo control of the robot."""

    pass


class NavigationMode(Enum):
    Free = 0
    StrictVirtualTrack = 1
    PriorityVirtualTrack = 2
    FollowPathPoints = 3
    # auto set by the backward param
    ReverseWalk = 4
    StrictVirtualTrackReverseWalk = 5


class MoveParams(Enum):
    NoParam = 0
    Appending = 1
    NoSmooth = 4
    Precise = 16
    WithYaw = 32
    ReturnUnreachableDirectly = 64
    WithFailRetryCount = 512
    FindPathIgnoringDynamicObstacles = 1024
    WithDirectedVirtualTrack = 2048


class BaseControlParams(BaseModel):
    """Parameters for base control."""

    max_linear_speed: PositiveFloat = 1.0
    """Maximum linear speed in meters per second."""
    max_angular_speed: PositiveFloat = 1.0
    """Maximum angular speed in radians per second."""
    wait: bool = False
    """Whether to wait until the movement is complete."""
    backward: bool = False
    """Whether to move backward."""
    navigation_mode: int = NavigationMode.Free.value
    """Navigation mode for the base control."""
    move_params: List[str] = []
    """Additional movement parameters."""
    speed_ratio: PositiveFloat = 1.0
    """Speed ratio for the movement."""
    fail_retry_count: NonNegativeInt = 0
    """Number of retries on failure."""


class BuildMapParams(BaseModel):
    """Parameters for base build map."""

    move_to_origin: bool = False
    """Whether to move to the origin before building the map."""
    stop: bool = False
    """Whether to stop after building the map."""


class BaseChargeStationParams(BaseModel):
    """Parameters for base dock."""

    navigation_mode: int = NavigationMode.Free.value
    """Navigation mode for docking."""
    move_to_dock: bool = False
    """Whether to move to the dock position."""


def get_control_cfg_kind(control_cfg: ActionConfig) -> InterfaceKind:
    if isinstance(control_cfg, JointControlBasis):
        return "joint_state"
    elif isinstance(control_cfg, PoseControlBasis):
        return "pose"
    else:
        raise ValueError(f"Unsupported control config type: {type(control_cfg)}")
