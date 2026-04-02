from auto_atom.basis.mjc.mujoco_env import (
    UnifiedMujocoEnv,
    BatchedUnifiedMujocoEnv,
    EnvConfig,
)
from airdc.common.systems.basis import System, SystemMode
from typing import Tuple, List
from pydantic import BaseModel, model_validator


class EnvConfigMixin(BaseModel):
    """A mixin class for Mujoco environment systems, providing common configuration and functionality."""

    interests: Tuple[List[str], List[str]] = ()
    """A tuple of two lists: the first list contains the names of interest objects, and the second list contains the names of interest operations."""
    env: dict = {}

    @model_validator(mode="before")
    def merge_env_config(cls, values: dict):
        env = values.pop("env", {})
        # from pprint import pprint

        if env:
            # print("env:")
            # pprint(env)
            from omegaconf import OmegaConf

            fields = EnvConfigMixin.model_fields.keys() | EnvConfig.model_fields.keys()
            for key in list(values.keys()):
                if key not in fields:
                    values.pop(key)
            # pprint("values before merge:")
            # pprint(values)
            values = OmegaConf.to_object(OmegaConf.merge(env, values))
        # print("values after merge:")
        # pprint(values)
        return values


class MujocoEnvConfig(EnvConfig, EnvConfigMixin):
    """Configuration for the Mujoco environment system."""


class BatchedMujocoEnv(System):
    """A system that interfaces with a Mujoco environment."""

    config: MujocoEnvConfig
    interface: BatchedUnifiedMujocoEnv

    def on_configure(self) -> bool:
        config = self.config
        self.env = self.interface
        for env in self.env.envs:
            env.set_interest_objects_and_operations(*config.interests)
        return True

    def capture_observation(self, timeout=None):
        data = self.env.capture_observation()
        self.env.update()
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
