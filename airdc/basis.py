from enum import auto
from typing import Dict, Union, List, Tuple, Optional
from pydantic import BaseModel, ConfigDict
from cfgable import (  # noqa: F401
    StrEnum,
    ForceSetAttr,
    force_set_attr,
    ConfigurableBasis,
    ConfigType,
)
from mcap_data_loader.basis import DataStamped, DictDataStamped  # noqa: F401
from mcap_data_loader.utils.terminal import Bcolors  # noqa: F401


PACKAGE_NAME = "airdc"

Position = Tuple[float, float, float]
Orientation = Tuple[float, float, float, float]
Pose = Tuple[Position, Orientation]
RangeConfig = Dict[Union[str, int], Tuple[float, float]]
"""Target ranges (min, max) used for linear mapping for each index/name/id of data.
e.g. {0: (0.0, 1.0), 1: (0.0, 1.0)}. The original range or the limit should
be provided by the leader itself."""


class KeyFilterConfig(BaseModel, frozen=True):
    """The dict key filter config."""

    model_config = ConfigDict(extra="forbid")

    include: List[str] = []
    """The list of keys to include."""
    exclude: List[str] = []
    """The list of keys to exclude."""


class PostCaptureConfig(BaseModel, frozen=True):
    """The post capture config for the group leader.
    The dict keys are the leader observation data key to be processed,
    e.g. "arm/joint_state/position", "eef/joint_state/velocity".
    For transform, the key should not contain field names, e.g. "arm/pose" instead of
    "arm/pose/position" or "arm/pose/orientation".
    """

    model_config = ConfigDict(extra="forbid")

    range_mapping: Dict[str, RangeConfig] = {}
    """The range mapping config for each observation data key."""
    transform: Dict[str, Optional[Pose]] = {}
    """The transform config for each pose data key.
    The Pose is considered as the relative transform from the original position
    and orientation."""


class ConcurrentMode(StrEnum):
    """Concurrent mode."""

    thread = auto()
    process = auto()
    asynchronous = auto()
    none = auto()
