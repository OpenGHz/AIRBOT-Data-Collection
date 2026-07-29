"""LeRobot Env plugin: a gymnasium env over the auto-atomic-operation MuJoCo
simulator, for native success-rate evaluation via ``lerobot-eval``.

Unlike ``lerobot_robot_aao_sim`` (which drives ``lerobot-rollout`` and has no
success signal), this exposes a ``gym.Env`` whose ``step()`` returns
``info["is_success"]`` so ``lerobot-eval`` computes ``pc_success`` natively.

LeRobot auto-discovers this by the distribution name prefix ``lerobot_env_``,
and ``@EnvConfig.register_subclass("aao_sim")`` registers ``--env.type=aao_sim``.
"""

from .config_aao_sim_env import AAOSimEnvConfig
from .rot6d_convention import swap_rot6d_convention, sim_rot6d_to_real, real_rot6d_to_sim
from .convention_wrapper import Rot6dObsWrapper, Rot6dActionWrapper

__all__ = [
    "AAOSimEnvConfig",
    # rot6d conversion (single self-inverse function + named aliases)
    "swap_rot6d_convention",
    "sim_rot6d_to_real",
    "real_rot6d_to_sim",
    # gymnasium wrappers
    "Rot6dObsWrapper",
    "Rot6dActionWrapper",
]
