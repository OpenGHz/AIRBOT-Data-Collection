from airdc.common.demonstrators.basis import Demonstrator
from airdc.common.systems.basis import System, Sensor, SystemMode
from airdc.common.utils.progress import MockProgressHandler
from airdc.demonstrate.configs import DemonstrateAction as Action
from typing import Union
from pydantic import BaseModel, ConfigDict, NonNegativeInt, PositiveInt
from threading import Lock


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


class SingleBatchedComponentDemonstratorConfig(SingleComponentDemonstratorConfig):
    """Configuration for the single component demonstrator."""

    batch_id: NonNegativeInt = 0
    """the batch id of the component to control, default to 0"""


class SingleBatchedComponentDemonstrator(SingleComponentDemonstrator):
    """Demonstrator for a single component."""

    observation: dict = {}
    batch_size: PositiveInt = 0
    batch_copied: NonNegativeInt = 0
    _component_configured: bool = False
    _served_batch_ids = set()
    _lock = Lock()

    def __init__(self, config: SingleBatchedComponentDemonstratorConfig):
        super().__init__(config)
        self.config = config

    def on_configure(self) -> bool:
        cls = self.__class__
        if cls._component_configured:
            return True
        result = self._component.configure()
        cls._component_configured = result
        return result

    def capture_observation(self, timeout=None):
        cls = self.__class__
        with self._lock:
            batch_id = self.config.batch_id
            # A new sampling round starts when the same batch slot requests data again.
            if not cls.observation or batch_id in cls._served_batch_ids:
                cls.observation = self._component.capture_observation(timeout)
                cls._served_batch_ids = set()
            observation = cls.observation
            cls.batch_size = len(next(iter(observation.values()))["data"])
            cur_obs = {}
            skip = observation.get("skip", None)
            for key, value in observation.items():
                if key == "skip":
                    continue
                # print(key, value["data"], batch_id)
                cur_obs[key] = {
                    "data": value["data"][batch_id],
                    "t": int(value["t"][batch_id]),
                }
            cls._served_batch_ids.add(batch_id)
            cur_obs["skip"] = False if skip is None else skip[batch_id]
            return cur_obs

    def _copy(self, deep):
        """Copy the demonstrator with a new batch id."""
        cls = self.__class__
        with self._lock:
            cls.batch_copied += 1
            self.get_logger().info(
                f"Copying demonstrator to batch_id {cls.batch_copied} with {deep=}"
            )
            return self.copy(
                {"batch_id": cls.batch_copied, "component": self.config.component},
                deep=True,
            )

    def __copy__(self):
        return self._copy(False)

    def __deepcopy__(self, memo):
        return self._copy(True)
