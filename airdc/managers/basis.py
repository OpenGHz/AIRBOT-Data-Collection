from abc import abstractmethod
from typing import (
    Optional,
    Protocol,
    Dict,
    Hashable,
    Union,
    List,
    final,
    runtime_checkable,
)
from pydantic import BaseModel, model_validator, Field
from enum import auto
from airdc.basis import ConfigurableBasis, Bcolors, StrEnum
from airdc.state_machine.fsm import (
    DemonstrateAction,
    DemonstrateFSM,
    State,
)
from airdc.common.systems.basis import SystemMode
from pprint import pformat
from mcap_data_loader.utils.dict import merge_keys_by_value
from functools import cached_property


class ManagerAction(StrEnum):
    """Actions for the manager."""

    INSTRUCTION = auto()
    """ Show instruction action."""
    LOCK = auto()
    """ Lock / unlock control action."""
    FOLLOW = auto()
    """ Start / stop following  action."""
    MODE = auto()
    """ Switch passive / resetting mode action."""


ActionType = Union[DemonstrateAction, ManagerAction]
KeyToAction = Dict[str, ActionType]


class ManagerConfigBasis(BaseModel, frozen=True):
    """Configuration for the manager."""

    key_to_action: KeyToAction = Field(min_length=1)
    """Mapping from DemonstrateAction to manager interface (e.g. key/button) names."""
    instruction: Dict[str, str] = {}
    """Mapping from manager interface names to instruction strings.
    If a key is missing, it will be auto filled according to the action."""

    @model_validator(mode="after")
    def validate_instruction(self):
        action_info = {
            DemonstrateAction.sample: "Start sampling",
            DemonstrateAction.save: "Save sampled data in the current episode",
            DemonstrateAction.abandon: "Abandon current sampling without saving",
            DemonstrateAction.finish: "Finish the current episode and save all data",
            DemonstrateAction.remove: "Remove the last saved episode",
            DemonstrateAction.capture: "Capture current component observations",
            ManagerAction.INSTRUCTION: "Show this instruction again",
            ManagerAction.MODE: "Switch passive (gravity composation) / resetting mode of the leaders",
            ManagerAction.FOLLOW: "Start / stop following",
            ManagerAction.LOCK: "Lock / unlock the manager control",
        }
        for key, action in merge_keys_by_value(self.key_to_action, "/").items():
            if key not in self.instruction:
                self.instruction[key] = action_info[action]
        return self

    @cached_property
    def instruction_str(self) -> str:
        """Get the instruction string."""
        return pformat(self.instruction)


@runtime_checkable
class DemonstrateManager(Protocol):
    def configure(self) -> bool: ...
    def on_configure(self) -> bool: ...
    def set_fsms(self, fsm: List[DemonstrateFSM]): ...
    def update(self) -> bool: ...
    def shutdown(self) -> bool: ...


class DemonstrateManagerBasis(ConfigurableBasis):
    """Demonstrate manager for managing the demonstration."""

    config: ManagerConfigBasis

    @final
    def config_post_init(self):
        super().config_post_init()
        self.finalized = False
        self._locked = False
        self.fsms = []

    @final
    def set_fsms(self, fsms: List[DemonstrateFSM]):
        """Set the demonstrate fsms. This must be called before configure."""
        self.fsms = fsms
        if len(fsms) == 1:
            self.fsm = fsms[0]

    @final
    def shutdown(self) -> bool:
        """Shutdown the manager."""
        self.finalized = True
        return self.on_shutdown()

    @abstractmethod
    def update(self) -> bool:
        """Update the manager."""

    @abstractmethod
    def on_shutdown(self) -> bool:
        """Callback to be called when shutting down the manager."""

    @final
    def show_instruction(self) -> None:
        """Displays the instructions for the key press actions.

        This function provides a user-friendly guide to inform the user about the available
        key press actions for controlling the system.
        """
        self.get_logger().info(Bcolors.cyan(f" \n{self.config.instruction_str}"))

    def _act_key(self, key: Hashable):
        action = self.config.key_to_action.get(key)
        self._act(action)

    def _act(self, action: ActionType):
        return self._act_one(self.fsms[0], action)

    def _act_one(self, fsm: DemonstrateFSM, action: ActionType):
        if action is None:
            return
        if action is ManagerAction.LOCK:
            self._locked = not self._locked
            self.get_logger().info(
                Bcolors.green(
                    f"Manager control is now {'locked' if self._locked else 'unlocked'}."
                )
            )
            return
        elif self._locked:
            return
        if action is ManagerAction.INSTRUCTION:
            self.show_instruction()
        elif action is ManagerAction.MODE:
            cur_mode = (
                SystemMode.PASSIVE
                if fsm.demonstrator.current_mode is not SystemMode.PASSIVE
                else SystemMode.RESETTING
            )
            fsm.demonstrator.switch_mode(cur_mode)
        elif action is ManagerAction.FOLLOW:
            if fsm.demonstrator.handler.is_stopped():
                fsm.demonstrator.handler.start()
            else:
                fsm.demonstrator.handler.stop()
        elif action is DemonstrateAction.capture:
            fsm.act(action)
            data = {}
            # only print low dim data
            last_cap = fsm.last_capture
            for key, value in last_cap.items():
                vd = value["data"]
                if isinstance(vd, bytes):
                    continue
                if isinstance(vd, dict):
                    vd_data = vd.get("data", None)
                    if isinstance(vd_data, bytes):
                        vd_cp = vd.copy()
                        vd_cp["data"] = f"<{len(vd_data)} bytes>"
                        value = {"data": vd_cp, "t": value["t"]}
                elif shape := getattr(vd, "shape", ()):
                    if sum(shape) > 10:
                        value = {"t": value["t"], "type": type(vd), "shape": shape}
                        if dtype := getattr(vd, "dtype", None):
                            value["dtype"] = dtype
                data[key] = value
            data["keys"] = list(last_cap.keys())
            self.get_logger().info(Bcolors.blue(f"\n{pformat(data)}"))
        else:
            self.get_logger().info(f"Executing action: {action.name}")
            fsm.act(action)


class SelfManagerConfig(BaseModel):
    """Configuration for the self manager."""

    on_reach: Optional[DemonstrateAction] = DemonstrateAction.save
    """what to do when the maximum number of samples is reached
    or the time duration is reached if not both are 0 usually save, abandon or None
    """
    on_reach_round: Optional[DemonstrateAction] = DemonstrateAction.finish
    """what to do when the maximum episode of samples is reached usually finish or None"""


class SelfManager(DemonstrateManagerBasis):
    """Self manager for managing the demonstration.
    This manager will be used to update the data sampling
    when the current state is sampling using the given
    sample configuration.
    """

    config: SelfManagerConfig

    def on_configure(self):
        if not self.fsms:
            self.fsms = [self.fsm]
        self.on_reach = self.config.on_reach
        self.on_reach_round = self.config.on_reach_round
        self.first_configure = [True] * len(self.fsms)
        self.failed_capture = [False] * len(self.fsms)
        return True

    def update(self) -> bool:
        return all(self._update_one(fsm, i) for i, fsm in enumerate(self.fsms))

    def _update_one(self, fsm: DemonstrateFSM, fsm_idx: int = 0) -> bool:
        state = fsm.get_state()
        reached_round = fsm.is_reached_round
        if reached_round:
            self.get_logger().warning("Maximum number of rounds reached.")
            if self.on_reach_round:
                return fsm.act(self.on_reach_round)
        if state is State.sampling and not reached_round:
            if fsm.is_reached:
                self.get_logger().info("Sample limitation reached.")
                if self.on_reach:
                    return fsm.act(self.on_reach)
            else:
                return fsm.act(DemonstrateAction.update)
        elif state is State.unconfigured and self.first_configure[fsm_idx]:
            self.first_configure[fsm_idx] = False
            self.get_logger().info("Configuring the demonstrate interface.")
            if fsm.act(DemonstrateAction.configure):
                self.get_logger().info("Activating the demonstrate interface.")
                return fsm.act(DemonstrateAction.activate)
            else:
                self.get_logger().info("Failed to configure the demonstrate interface.")
                return False
        elif (
            state not in {State.unconfigured, State.inactive}
            and not self.failed_capture[fsm_idx]
        ):
            # capture to update the visualizers
            if not fsm.act(DemonstrateAction.capture):
                self.failed_capture[fsm_idx] = True
                self.get_logger().error(
                    "Failed to capture the current component observations."
                )
                return False
        return True

    def on_shutdown(self) -> bool:
        return True
