from airdc.common.utils.sim.mujoco.mujoco_env import (
    UnifiedMujocoEnv,
    EnvConfig,
)
from airdc.common.systems.basis import System, SystemMode


class MujocoEnv(System):
    """A system that interfaces with a Mujoco environment."""

    config: EnvConfig

    def on_configure(self) -> bool:
        self.env = UnifiedMujocoEnv(self.config)
        return True

    def capture_observation(self, timeout=None):
        data = self.env.capture_observation()
        # self.env.update()
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
