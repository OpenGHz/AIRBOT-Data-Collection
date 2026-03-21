from auto_atom.basis.mujoco_env import (
    UnifiedMujocoEnv,
    EnvConfig,
)
from auto_atom.runtime import ComponentRegistry
from airdc.common.systems.basis import System, SystemMode
from typing import Tuple, List


class MujocoEnvConfig(EnvConfig):
    """Configuration for the Mujoco environment system."""

    name: str
    """Name of the Mujoco environment to register."""
    interests: Tuple[List[str], List[str]] = ()
    """A tuple of two lists: the first list contains the names of interest objects, and the second list contains the names of interest operations."""


class MujocoEnv(System):
    """A system that interfaces with a Mujoco environment."""

    config: MujocoEnvConfig

    def on_configure(self) -> bool:
        config = self.config
        self.env = UnifiedMujocoEnv(config)
        if config.interests:
            self.env.set_interest_objects_and_operations(*config.interests)
        ComponentRegistry.register_env(config.name, self.env)
        return True

    def capture_observation(self, timeout=None):
        data = self.env.capture_observation()
        self.env.update()
        if not self.env.is_updated():
            data["skip"] = True
        return data

    def on_switch_mode(self, mode):
        # emm, it is funny that resetting when the mode is not resetting, but it is what it is now
        if mode is not SystemMode.RESETTING:
            self.env.reset()
        return True

    def send_action(self, action):
        self.env.step(action)

    def shutdown(self) -> bool:
        self.env.close()
        return True

    def get_info(self):
        return self.env.get_info()
