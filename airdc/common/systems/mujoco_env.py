from auto_atom.basis.mjc.mujoco_env import BatchedUnifiedMujocoEnv
from auto_atom.runtime import ComponentRegistry
from airdc.common.systems.basis import System
from pydantic import BaseModel


class MujocoEnvConfig(BaseModel):
    """Configuration for the Mujoco environment system."""

    name: str
    """The name of the registered Mujoco environment to load."""


class BatchedMujocoEnv(System):
    """A system that interfaces with a Mujoco environment."""

    config: MujocoEnvConfig

    def on_configure(self) -> bool:
        self.env: BatchedUnifiedMujocoEnv = ComponentRegistry.get_env(self.config.name)
        return True

    def capture_observation(self, timeout=None):
        data = self.env.capture_observation()
        data["skip"] = ~self.env.is_updated()
        return data

    def on_switch_mode(self, mode):
        # NOTE: let the manager (the auto atom runner) to handle the reset logic
        # emm, it is funny that resetting when the mode is not resetting, but it is what it is now
        # if mode is not SystemMode.RESETTING:
        #     self.env.reset()
        return True

    def send_action(self, action):
        self.env.step(action)

    def shutdown(self) -> bool:
        self.env.close()
        return True

    def get_info(self):
        return self.env.get_info()
