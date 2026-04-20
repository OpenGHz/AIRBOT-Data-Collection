from pydantic import BaseModel
from airdc.demonstrate.configs import DemonstrateConfig
from airdc.demonstrate.basis import (
    DemonstrateAction,
    DemonstrateState,
)
from airdc.demonstrate.interface import (
    DemonstrateInterface,
    Demonstrator,
)
from airdc.state_machine.basis import (
    StateMachineBasis,
    StateMachineConfig,
    CallbackEventType,
)


Action = DemonstrateAction
State = DemonstrateState


class DemonstrateFSMConfig(BaseModel, frozen=True):
    """Demonstrate FSM config."""

    state_machine: StateMachineConfig
    """State machine configuration."""
    interface: DemonstrateConfig
    """Demonstrate interface configuration."""


class DemonstrateFSM(StateMachineBasis):
    def __init__(self, config: DemonstrateFSMConfig):
        super().__init__(config.state_machine)
        self.config = config
        self.__interface = DemonstrateInterface(config.interface)
        self.register_callbacks(
            CallbackEventType.PREPARE_EVENT,
            {action: getattr(self.__interface, action.name) for action in Action},
        )
        for cbtype, callbacks in self.__interface.fsm_callbacks.items():
            self.register_callbacks(cbtype, callbacks)

    def on_enter_active(self, event):
        """Actions to perform when entering the active state."""
        self.__interface.log_round()

    def shutdown(self):
        return self.__interface.finish()

    @property
    def dataset_config(self):
        """Get the dataset config."""
        return self.__interface._config.dataset

    @property
    def sample_info(self):
        """Get the sample info."""
        return self.__interface._sample_info.model_copy()

    @property
    def last_capture(self) -> dict:
        """Get the last capture."""
        return self.__interface.last_capture

    @property
    def is_reached(self) -> bool:
        """Check if the maximum number of samples is reached."""
        return self.__interface.is_reached

    @property
    def is_reached_round(self) -> bool:
        """Check if the maximum number of rounds is reached."""
        return self.__interface.is_reached_round

    @property
    def demonstrator(self) -> Demonstrator:
        """Get the demonstrator."""
        return self.__interface.demonstrator

    @property
    def metrics(self) -> dict:
        """Get the metrics."""
        return self.__interface.metrics
