from airdc.basis import (
    ConfigurableBasis,
    PostCaptureConfig,
    DictDataStamped,
    DataStamped,
)
from abc import abstractmethod
from enum import Enum, auto
from typing import (
    Any,
    Dict,
    Union,
    List,
    Optional,
    Set,
    DefaultDict,
    Type,
    Literal,
    Tuple,
    final,
)
from typing_extensions import Self
from pydantic import (
    BaseModel,
    ValidationInfo,
    ConfigDict,
    JsonValue,
    field_validator,
    model_validator,
)
from collections import defaultdict
from airdc.utils import StrEnum
from functools import cached_property
from copy import deepcopy


class SystemMode(Enum):
    PASSIVE = auto()  # e.g., gravity compensation
    RESETTING = auto()  # mode for resetting
    SAMPLING = auto()  # mode for sampling


class Sensor(ConfigurableBasis):
    """Base class for sensors."""

    def config_post_init(self):
        super().config_post_init()
        self._metrics: DefaultDict[str, Dict[str, Any]] = defaultdict(dict)
        self.get_logger().debug(f"Sensor {self.__class__.__name__} initialized.")

    @abstractmethod
    def capture_observation(
        self, timeout: Optional[float] = None
    ) -> Optional[DictDataStamped]:
        """Capture observation from the sensor
        Args:
            timeout: Maximum time to wait for the observation to be ready. If None, wait indefinitely.
                If 0, do not wait and return None immediately. Then the caller can use the `result` method to get the result later.
        Returns:
            The observation data as a dictionary, or None if timeout is zero.
        Raises:
            TimeoutError: If the observation is not ready within the timeout period.
        """
        raise NotImplementedError

    def result(self, timeout: Optional[float] = None) -> DictDataStamped:
        """Wait and get the result of the last capture_observation call
        Args:
            timeout: Maximum time to wait for the result. If None, wait indefinitely.
        Returns:
            The observation data as a dictionary.
        Raises:
            TimeoutError: If the result is not ready within the timeout period.
            ValueError: If timeout is not None or positive.
        """
        # This method can be overridden by subclasses if needed
        if timeout is not None and timeout <= 0:
            raise ValueError("timeout must be None or positive")
        return self.capture_observation(timeout)

    @abstractmethod
    def shutdown(self) -> None:
        """Shutdown"""
        # TODO: should use on_shutdown
        # to set the internal state
        # which can be used in __del__?
        raise NotImplementedError

    @abstractmethod
    def get_info(self) -> JsonValue:
        """Get information. TODO: should be reacquired before each sampling?"""
        raise NotImplementedError

    def set_post_capture(
        self, config: Optional[PostCaptureConfig], info: JsonValue
    ) -> None:
        """Set post capture process.
        Args:
            config: The post capture configuration.
            info: Additional information about the post capture process.
                It is typically used when a sensor is used as a controller (e.g. the leader)
                to transmit information about the controlled object, thereby aligning the data with
                the controlled object.
        """
        # This method can be overridden by subclasses to set post capture processing

    @final
    @property
    def metrics(self) -> Dict[str, JsonValue]:
        """Get metrics"""
        return self._metrics

    @final
    @staticmethod
    def _create_value(data: Any, t: int = 0) -> DataStamped:
        return DataStamped.create(data, t)


class System(Sensor):
    """Base class for systems with modes and actions."""

    force_switch_mode: bool = True
    """
    Whether to force switch mode even if the mode is the same.
    Generally, it is recommended to set it to False for the
    bottom-level System class to avoid repeated switching, and
    to True for the top-level class to ensure that the bottom-level
    mode can be restored uniformly after being destroyed.
    """

    @final
    def config_post_init(self):
        super().config_post_init()
        self._current_mode = None

    @abstractmethod
    def send_action(self, action: Any) -> Any: ...

    @final
    def switch_mode(self, mode: SystemMode) -> bool:
        if (not self.force_switch_mode) and self._current_mode is mode:
            return True
        if self.on_switch_mode(mode):
            self._current_mode = mode
            return True
        else:
            return False

    @abstractmethod
    def on_switch_mode(self, mode: SystemMode) -> bool: ...

    @final
    @property
    def current_mode(self) -> SystemMode:
        return self._current_mode


AllInterfaceKind = {"joint_state", "pose", "twist"}
InterfaceKind = Literal["joint_state", "pose", "twist"]


class InterfaceType(StrEnum):
    JOINT_POSITION = auto()
    JOINT_VELOCITY = auto()
    JOINT_EFFORT = auto()
    JOINT_NAME = auto()
    JOINT_KP = auto()
    JOINT_KD = auto()
    POSE = auto()
    TWIST = auto()

    @cached_property
    def kind(self) -> InterfaceKind:
        return self.split("_")[0].replace("joint", "joint_state")

    @cached_property
    def fields(self) -> Tuple[str, ...]:
        if self.kind == "joint_state":
            return self.split("_")[1:]
        elif self is InterfaceType.POSE:
            return ("position", "orientation")
        elif self is InterfaceType.TWIST:
            return ("linear", "angular")
        else:
            raise ValueError(f"Unknown interface type: {self}")

    @classmethod
    def joint_states(cls, with_name: bool = False) -> Set[Self]:
        js = {
            cls.JOINT_POSITION,
            cls.JOINT_VELOCITY,
            cls.JOINT_EFFORT,
        }
        if with_name:
            js.add(cls.JOINT_NAME)
        return js


class ReferenceBase(StrEnum):
    """The reference base for relative control, which can be either state or action."""

    STATE = auto()
    """reference to the state"""
    ACTION = auto()
    """reference to the action"""


class ReferenceMode(StrEnum):
    """Relative mode for the robot action and observation."""

    ABSOLUTE = auto()
    """no reference, the action/observation is in absolute values."""
    INIT_STATE = auto()
    """relative to the initial state"""
    INIT_ACTION = auto()
    """relative to the initial action"""
    CURRENT_STATE = auto()
    """relative to the current state, which is updated after each action"""
    LAST_ACTION = auto()
    """relative to the last action, which is updated after each action"""

    def is_step_mode(self) -> bool:
        """Check if the reference mode is step mode, i.e. need to be updated after each action."""
        return self in {
            ReferenceMode.LAST_ACTION,
            ReferenceMode.CURRENT_STATE,
        }

    def ref_base(self) -> ReferenceBase:
        """Get the reference base for the mode."""
        if self in {ReferenceMode.INIT_STATE, ReferenceMode.CURRENT_STATE}:
            return ReferenceBase.STATE
        elif self in {ReferenceMode.INIT_ACTION, ReferenceMode.LAST_ACTION}:
            return ReferenceBase.ACTION


class ConcurrentConfig(BaseModel, frozen=True):
    """Configuration for concurrent systems."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    blocking: Optional[bool] = None
    """Whether to block until completed. None means use the system default or not blocking."""
    rate: Optional[float] = None
    """periodic update rate in Hz, 0/None means not used, < 0 means no limit """


class CommonConfig(ConcurrentConfig):
    """Common configuration for both observation and action."""

    reference_mode: ReferenceMode = ReferenceMode.ABSOLUTE


class ActionConfig(CommonConfig):
    """Configuration for the control system of the robot."""

    flatten: bool = False
    """Whether to flatten the action dictionary into a single list."""
    unpack: bool = False
    """Whether to unpack the action list into multiple args."""

    @model_validator(mode="after")
    def validate_unpack_flatten(self) -> Self:
        if self.flatten and self.unpack:
            raise ValueError("Cannot set both flatten and unpack to True.")
        return self

    @property
    def interfaces(self) -> Set[InterfaceType]:
        """No interfaces by default. The subclasses can override this property."""
        return {}


class ObservationConfig(CommonConfig):
    """Configuration for the observation system of the robot."""

    interfaces: Set[InterfaceType] = InterfaceType.joint_states()
    """The interfaces to observe. By default, it observes joint states."""
    kind_ref: Dict[InterfaceKind, ReferenceMode] = {}
    """The reference mode for each interface kind.
    By default, it uses the same top level reference mode for all kinds."""

    def model_post_init(self, context):
        assert self.reference_mode not in {
            ReferenceMode.CURRENT_STATE,
            ReferenceMode.LAST_ACTION,
        }, f"Reference mode {self.reference_mode} is not supported for observation."
        for kind in AllInterfaceKind:
            if kind not in self.kind_ref:
                self.kind_ref[kind] = self.reference_mode


ActionConfigs = List[Dict[SystemMode, ActionConfig]]
"""Type alias for action configurations for each component.
Each component has a dictionary mapping SystemMode to ActionConfig.
"""


class SystemConfig(ConcurrentConfig):
    """Configuration for the robot system.
    If the top level concurrent config is set (not None),
    it will override the component-level settings which are set to None.
    """

    model_config = ConfigDict(validate_default=True)

    blocking: Optional[bool] = True
    """Whether to block until completed."""
    components: List[str] = []
    """List of components in the system."""
    action: ActionConfigs = []
    """Action configurations for each component."""
    observation: List[ObservationConfig] = []
    """Observation configurations for each component."""

    @field_validator("action", "observation", mode="after")
    def extend_list(cls, v: list, info: ValidationInfo) -> List[Any]:
        """Ensure the field list is always the same length as components."""
        data = info.data
        length = len(data.get("components", []))
        if len(v) == 1:
            for _ in range(length - 1):
                v.append(deepcopy(v[0]))
        return v

    @staticmethod
    def _override_cfgs(cfgs: List[CommonConfig], data: dict):
        fields = ("blocking", "rate")
        for field in fields:
            for cfg in cfgs:
                if getattr(cfg, field) is None:
                    object.__setattr__(cfg, field, data.get(field))
        return cfgs

    @field_validator("action", mode="after")
    def validate_action(cls, v: ActionConfigs, info: ValidationInfo):
        for cfg_dict in v:
            cls._override_cfgs(cfg_dict.values(), info.data)
        return v

    @field_validator("observation", mode="after")
    def validate_obs(cls, v: List[ObservationConfig], info: ValidationInfo):
        return cls._override_cfgs(v, info.data)

    @cached_property
    def as_dict(
        self,
    ) -> Dict[
        str,  # component name
        Dict[
            Literal["action", "observation"],
            Union[Dict[SystemMode, ActionConfig], ObservationConfig],
        ],
    ]:
        """Get the config as a nested dict."""
        cfg_dict = {}
        for comp, act_cfg, obs_cfg in zip(
            self.components, self.action, self.observation
        ):
            cfg_dict[comp] = {
                "action": act_cfg,
                "observation": obs_cfg,
            }
        return cfg_dict

    @cached_property
    def action_types(self) -> Dict[str, Dict[SystemMode, Type[ActionConfig]]]:
        """Get the action config types for each component."""
        action_types = {}
        for comp, act_cfg in zip(self.components, self.action):
            action_types[comp] = {mode: type(cfg) for mode, cfg in act_cfg.items()}
        return action_types

    @cached_property
    def action_refs(self) -> Dict[str, Dict[SystemMode, ReferenceMode]]:
        """Get the reference mode for each action config."""
        action_refs = {}
        for comp, act_cfg in zip(self.components, self.action):
            action_refs[comp] = {
                mode: cfg.reference_mode for mode, cfg in act_cfg.items()
            }
        return action_refs

    @cached_property
    def observation_info(self) -> Dict[str, Dict[InterfaceKind, Set[str]]]:
        """Get the observation info for each component, which is a dictionary mapping component name to a dictionary mapping interface kind (e.g. joint, pose, etc.) to the set of fields."""
        info = {}
        for component, configs in self.as_dict.items():
            component_info = defaultdict(set)
            for interface in configs["observation"].interfaces:
                component_info[interface.kind].update(interface.fields)
            info[component] = dict(component_info)
        return info
