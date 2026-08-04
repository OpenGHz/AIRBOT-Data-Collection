"""EnvConfig for the AAO MuJoCo simulator gymnasium environment.

LeRobot auto-discovers this package via the ``lerobot_env_`` distribution-name
prefix (lerobot/utils/import_utils.py::register_third_party_plugins).
``@EnvConfig.register_subclass("aao_sim")`` registers ``--env.type=aao_sim``
for use with ``lerobot-eval``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Tuple

from lerobot.configs import FeatureType, PolicyFeature
from lerobot.envs.configs import EnvConfig
from lerobot.utils.constants import ACTION, OBS_IMAGES, OBS_STATE


@EnvConfig.register_subclass("aao_sim")
@dataclass
class AAOSimEnvConfig(EnvConfig):
    """Gym env config for the auto-atomic-operation MuJoCo simulator.

    Usage::

        lerobot-eval \\
          --policy.path=<checkpoint> \\
          --env.type=aao_sim \\
          --env.task_config=open_door \\
          --env.observation_rotation=rot6d \\
          --eval.n_episodes=10 --eval.batch_size=1 \\
          --policy.device=cuda
    """

    type: str = "aao_sim"

    # --- aao backend ---
    task_config: str = "open_door"
    """AAO task config name loaded via Hydra (e.g. 'open_door')."""

    operator: str = "arm"
    """Registered operator whose EEF pose is controlled."""

    config_dir: str = ""
    """Directory holding aao task configs. Empty = auto-detect next to auto_atom package."""

    hydra_overrides: List[str] = field(default_factory=list)
    """Extra Hydra overrides passed to load_task_file_hydra."""

    kinematic: bool = False
    """True = teleport EEF (no physics). False = reach via substeps physics ticks."""

    substeps: int = 1
    """Physics ticks to advance per action step."""

    has_gripper: bool = True
    """Whether to read/write a gripper DoF."""

    # --- pose representation ---
    observation_rotation: str = "rot6d"
    """Rotation representation in observation.state.
    'rot6d': pos(3)+rot6d(6)+grip(1) = 10-dim (matches absolute_random_wrist ckpt).
    'quat':  pos(3)+quat(4)+grip(1)  = 8-dim.
    Sim now writes rotation_6d as column-major (first 2 columns of rotation matrix),
    matching the real-robot convention produced by Rotation6D.quat_to_rot6d()."""

    action_rotation: str = "quat"
    """Rotation representation expected in the action vector.
    'quat':  pos(3)+quat(4)+grip(1)  = 8-dim  (default; ACT absolute ckpt).
    'rot6d': pos(3)+rot6d(6)+grip(1) = 10-dim (for future rot6d-action ckpts).
    rot6d actions are converted back to quaternion via Rotation6D.rot6d_to_quat()
    before being passed to apply_pose_action()."""

    relative_pose: bool = False
    """Whether observations and actions use episode-relative coordinates.
    When True, position/orientation are relative to the episode-start pose,
    matching the _rela topics in MCAP training data."""

    # --- success detection ---
    success_object: str = "handle_body_phys"
    """AAO object name checked for displacement (task-dependent)."""

    displacement_threshold: float = 0.01
    """Displacement in metres from episode-start pose that counts as success."""

    # --- cameras ---
    sim_cameras: Dict[str, str] = field(
        default_factory=lambda: {"wrist_cam": "wrist_cam"}
    )
    """Mapping of LeRobot image key -> aao camera name."""

    camera_shape: Tuple[int, int, int] = (352, 640, 3)
    """(H, W, C) of each camera frame. Must match the task config resolution."""

    mujoco_gl: str = "egl"
    """MuJoCo GL backend. 'egl' for GPU headless (NVIDIA); 'osmesa' for CPU
    software rendering; 'glfw' requires X display."""

    # --- gym metadata ---
    fps: int = 30
    max_episode_steps: int = 300
    task_description: str = "complete the task"

    def __post_init__(self) -> None:
        obs_rot_dim = 6 if self.observation_rotation == "rot6d" else 4
        act_rot_dim = 6 if self.action_rotation      == "rot6d" else 4
        grip_dim    = 1 if self.has_gripper else 0
        state_dim   = 3 + obs_rot_dim + grip_dim
        action_dim  = 3 + act_rot_dim + grip_dim
        H, W, C     = self.camera_shape

        # features: PolicyFeature objects as expected by lerobot's env_to_policy_features.
        # Image shapes use HWC convention here; env_to_policy_features converts to CHW.
        self.features: Dict[str, Any] = {
            "agent_pos": PolicyFeature(type=FeatureType.STATE,  shape=(state_dim,)),
            ACTION:      PolicyFeature(type=FeatureType.ACTION, shape=(action_dim,)),
            **{
                f"pixels/{k}": PolicyFeature(type=FeatureType.VISUAL, shape=(H, W, C))
                for k in self.sim_cameras
            },
        }

        # features_map: raw obs key -> lerobot observation key.
        self.features_map: Dict[str, str] = {
            "agent_pos": OBS_STATE,
            ACTION: ACTION,
            **{f"pixels/{k}": f"{OBS_IMAGES}.{k}" for k in self.sim_cameras},
        }

    @property
    def gym_kwargs(self) -> Dict[str, Any]:
        # create_envs builds kwargs directly; this satisfies the abstract property.
        return {}

    def create_envs(
        self, n_envs: int = 1, use_async_envs: bool = False
    ) -> Dict[str, Any]:
        """Build a vectorised AAO gym env for use by lerobot-eval."""
        from .aao_sim_env import AAOSimEnv
        from gymnasium.vector import AsyncVectorEnv, SyncVectorEnv

        kwargs: Dict[str, Any] = dict(
            task_config=self.task_config,
            operator=self.operator,
            observation_rotation=self.observation_rotation,
            action_rotation=self.action_rotation,
            relative_pose=self.relative_pose,
            substeps=self.substeps,
            kinematic=self.kinematic,
            has_gripper=self.has_gripper,
            sim_cameras=dict(self.sim_cameras),
            camera_shape=tuple(self.camera_shape),
            mujoco_gl=self.mujoco_gl,
            success_object=self.success_object,
            displacement_threshold=self.displacement_threshold,
            config_dir=self.config_dir,
            hydra_overrides=list(self.hydra_overrides),
            fps=self.fps,
            max_episode_steps=self.max_episode_steps,
            task_description=self.task_description,
        )

        # Set GL env vars in the parent process so AsyncVectorEnv workers
        # inherit them before MuJoCo is initialized in the subprocess.
        import os
        if self.sim_cameras:
            os.environ.setdefault("MUJOCO_GL", self.mujoco_gl)
            if self.mujoco_gl == "egl":
                # Force NVIDIA EGL device; avoids Mesa software fallback (0x8cdd)
                os.environ.setdefault("MUJOCO_EGL_DEVICE_ID", "0")

        from functools import partial
        VecEnv = AsyncVectorEnv if use_async_envs else SyncVectorEnv
        fns = [partial(AAOSimEnv, **kwargs) for _ in range(n_envs)]

        vec = VecEnv(fns)
        return {self.type: {0: vec}}
