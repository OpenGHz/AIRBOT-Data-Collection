from auto_atom.basis.mjc.mujoco_env import (
    UnifiedMujocoEnv,
    EnvConfig,
)
from auto_atom.basis.mjc.gs_mujoco_env import GSUnifiedMujocoEnv, GSEnvConfig
from auto_atom.runtime import ComponentRegistry
from airdc.common.systems.basis import System, SystemMode
from typing import Tuple, List


class MujocoEnvConfig(EnvConfig):
    """Configuration for the Mujoco environment system."""

    name: str
    """Name of the Mujoco environment to register."""
    interests: Tuple[List[str], List[str]] = ()
    """A tuple of two lists: the first list contains the names of interest objects, and the second list contains the names of interest operations."""


class GsMujocoEnvConfig(GSEnvConfig):
    """Configuration for GS Mujoco environment with registry metadata."""

    name: str
    """Name of the Mujoco environment to register."""
    interests: Tuple[List[str], List[str]] = ()
    """Optional interest objects/operations used by downstream task logic."""


class MujocoEnv(System):
    """A system that interfaces with a Mujoco environment."""

    config: MujocoEnvConfig
    interface: UnifiedMujocoEnv

    def on_configure(self) -> bool:
        config = self.config
        self.env = self.interface
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


class GsMujocoEnv(MujocoEnv):
    config: GsMujocoEnvConfig
    interface: GSUnifiedMujocoEnv
