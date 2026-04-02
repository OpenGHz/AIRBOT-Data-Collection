from airdc.common.systems.mujoco_env import EnvConfigMixin, BatchedMujocoEnv
from auto_atom.basis.mjc.gs_mujoco_env import BatchedGSUnifiedMujocoEnv, GSEnvConfig


class MujocoGSEnvConfig(GSEnvConfig, EnvConfigMixin):
    """Configuration for the Mujoco environment system with Gaussian Splatting rendering."""


class BatchedMujocoGSEnv(BatchedMujocoEnv):
    """A system that interfaces with a Mujoco environment using Gaussian Splatting rendering."""

    config: MujocoGSEnvConfig
    interface: BatchedGSUnifiedMujocoEnv
