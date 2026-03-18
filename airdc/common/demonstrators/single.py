from airdc.common.demonstrators.basis import Demonstrator
from airdc.common.systems.basis import System, Sensor, SystemMode
from airdc.common.utils.progress import MockProgressHandler
from airdc.demonstrate.configs import DemonstrateAction as Action
from typing import Union
from pydantic import BaseModel, ConfigDict


Component = Union[System, Sensor]


class SingleComponentDemonstratorConfig(BaseModel):
    """Configuration for the single component demonstrator."""

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    component: Component
    """the component instance"""


class SingleComponentDemonstrator(Demonstrator):
    """Demonstrator for a single component."""

    def __init__(self, config: SingleComponentDemonstratorConfig):
        self.config = config
        self._component = config.component
        self._handler = MockProgressHandler()

    def on_configure(self) -> bool:
        return self._component.configure()

    def capture_observation(self, timeout=None):
        return self._component.capture_observation(timeout)

    def get_info(self):
        return self._component.get_info()

    def on_switch_mode(self, mode):
        return self._component.on_switch_mode(mode)

    def send_action(self, action):
        return self._component.send_action(action)

    def shutdown(self) -> bool:
        return self._component.shutdown()

    def react(self, action):
        if action is Action.configure:
            return self.configure()
        elif action is Action.sample:
            return self.switch_mode(SystemMode.SAMPLING)
        return True

    @property
    def handler(self):
        return self._handler
