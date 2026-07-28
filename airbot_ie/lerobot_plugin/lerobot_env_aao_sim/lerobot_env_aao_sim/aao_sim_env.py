"""gymnasium.Env wrapping the auto-atomic-operation MuJoCo simulator.

Drives the same MujocoTaskBackend that AAOSimRobot uses, but exposes a
gym.Env interface so lerobot-eval can compute pc_success natively from
info["is_success"] and record mp4 videos per episode.

This package has NO runtime dependency on lerobot_robot_aao_sim — all
pose-data helpers are defined locally below.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import gymnasium as gym
import numpy as np
from gymnasium import spaces

# ---------------------------------------------------------------------------
# aao observation key templates (same constants as in the robot adapter)
# ---------------------------------------------------------------------------
_POSE_POS   = "{op}/pose/position"
_POSE_ORI   = "{op}/pose/orientation"
_POSE_ROT6D = "{op}/pose/rotation_6d"   # native 6-D rotation emitted by sim
_EEF_JS     = "eef/joint_state/position"
_CAM_COLOR  = "{cam}/color/image_raw"


# ---------------------------------------------------------------------------
# Pose-data helpers (independent copy — no import from robot plugin)
# ---------------------------------------------------------------------------

def _as_flat(data: Any, n: int) -> List[float]:
    """First ``n`` values of an array-like, returned as Python floats."""
    arr = np.asarray(data, dtype=float).reshape(-1)
    return [float(v) for v in arr[:n]]


def _as_xyz(data: Any) -> List[float]:
    """Position as {x,y,z} dict (structured mode) or array (flat mode)."""
    if isinstance(data, dict):
        return [float(data["x"]), float(data["y"]), float(data["z"])]
    return _as_flat(data, 3)


def _as_quat(data: Any) -> List[float]:
    """Orientation as {x,y,z,w} dict (structured mode) or array (flat mode)."""
    if isinstance(data, dict):
        return [float(data[k]) for k in ("x", "y", "z", "w")]
    return _as_flat(data, 4)


class AAOSimEnv(gym.Env):
    """gymnasium.Env over a single AAO MuJoCo episode.

    Observation
    -----------
    ``pixels``    : dict[str, np.ndarray HWC uint8]  -- one entry per camera
    ``agent_pos`` : np.ndarray float32 (10,) rot6d  or (8,) quat

    Action
    ------
    np.ndarray float32 (8,): [pos_x, pos_y, pos_z, qx, qy, qz, qw, gripper]
    Action rotation is always quaternion regardless of observation_rotation.

    Success
    -------
    ``info["is_success"]`` is True when the target object has moved more than
    ``displacement_threshold`` metres from its initial pose at episode start.
    """

    metadata: Dict[str, Any] = {"render_modes": ["rgb_array"]}

    def __init__(
        self,
        task_config: str,
        operator: str,
        observation_rotation: str,
        substeps: int,
        kinematic: bool,
        has_gripper: bool,
        sim_cameras: Dict[str, str],
        camera_shape: Tuple[int, int, int],
        mujoco_gl: str,
        success_object: str,
        displacement_threshold: float,
        config_dir: str,
        hydra_overrides: List[str],
        fps: int,
        max_episode_steps: int,
        task_description: str,
    ) -> None:
        super().__init__()

        if observation_rotation not in ("quat", "rot6d"):
            raise ValueError(
                f"observation_rotation must be 'quat' or 'rot6d', "
                f"got {observation_rotation!r}"
            )

        self._task_config            = task_config
        self._operator               = operator
        self._observation_rotation   = observation_rotation
        self._substeps               = substeps
        self._kinematic              = kinematic
        self._has_gripper            = has_gripper
        self._sim_cameras            = sim_cameras          # {lerobot_key: aao_cam}
        self._camera_shape           = camera_shape         # (H, W, C)
        self._mujoco_gl              = mujoco_gl
        self._success_object         = success_object
        self._displacement_threshold = displacement_threshold
        self._config_dir             = config_dir
        self._hydra_overrides        = hydra_overrides

        self._backend: Any              = None
        self._env: Any                  = None
        self._initial_object_pose: Any  = None

        # gym metadata expected by lerobot-eval
        self.metadata           = {"render_modes": ["rgb_array"], "render_fps": fps}
        self._max_episode_steps = max_episode_steps
        self.task_description   = task_description
        self.task               = task_description

        # Spaces
        H, W, C   = camera_shape
        rot_dim   = 6 if observation_rotation == "rot6d" else 4
        grip_dim  = 1 if has_gripper else 0
        state_dim = 3 + rot_dim + grip_dim

        self.observation_space = spaces.Dict({
            "pixels": spaces.Dict({
                k: spaces.Box(0, 255, (H, W, C), dtype=np.uint8)
                for k in sim_cameras
            }),
            "agent_pos": spaces.Box(
                -np.inf, np.inf, (state_dim,), dtype=np.float32
            ),
        })
        self.action_space = spaces.Box(-np.inf, np.inf, (8,), dtype=np.float32)

        # NOTE: MuJoCo backend is initialized lazily in reset() — NOT here.
        # gymnasium's AsyncVectorEnv (>=1.0) instantiates env_fn() once in the
        # main process as a "dummy env" to read spaces, then closes it and forks
        # worker processes that call env_fn() again.  If we init the MuJoCo EGL
        # context here, the main-process dummy leaves global EGL state that the
        # forked worker inherits, causing "Offscreen framebuffer is not complete
        # (0x8cdd)" on NVIDIA.  Delaying setup to reset() keeps the dummy env
        # entirely MuJoCo-free.

    # ------------------------------------------------------------------
    # Internal: backend lifecycle
    # ------------------------------------------------------------------

    def _setup(self) -> None:
        """Build the MujocoTaskBackend (mirrors AAOSimRobot.connect logic)."""
        import os

        if self._sim_cameras:
            os.environ.setdefault("MUJOCO_GL", self._mujoco_gl)
            # For EGL GPU rendering with NVIDIA, explicitly select device 0
            # to avoid fallback to Mesa software renderer (fixes 0x8cdd error)
            if self._mujoco_gl == "egl":
                os.environ.setdefault("MUJOCO_EGL_DEVICE_ID", "0")

        import auto_atom
        from auto_atom import load_task_file_hydra

        pkg_parent = os.path.normpath(
            os.path.join(os.path.dirname(auto_atom.__file__), "..")
        )
        config_dir = self._config_dir or os.path.join(pkg_parent, "aao_configs")
        overrides = list(self._hydra_overrides) + [
            "env.batch_size=1",
            f"assets_dir={os.path.join(pkg_parent, 'assets')}",
        ]
        tf = load_task_file_hydra(
            self._task_config, config_dir=config_dir, overrides=overrides
        )
        backend = tf.backend(tf.task, tf.task_operators)
        backend.reset()
        self._backend = backend
        self._env     = backend.env.envs[0]

    # ------------------------------------------------------------------
    # gym.Env interface
    # ------------------------------------------------------------------

    def reset(
        self,
        *,
        seed: Optional[int] = None,
        options: Optional[Dict[str, Any]] = None,
    ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        super().reset(seed=seed)
        # Lazy init: build the MuJoCo backend on first reset (not in __init__)
        # so that the gymnasium AsyncVectorEnv dummy-env pass is MuJoCo-free.
        if self._backend is None:
            self._setup()
        self._backend.reset()
        # Snapshot per-episode initial pose for displacement-based success.
        self._initial_object_pose = (
            self._backend.get_object_handler(self._success_object).get_pose()
        )
        return self._get_obs(), {}

    def step(
        self, action: np.ndarray
    ) -> Tuple[Dict[str, Any], float, bool, bool, Dict[str, Any]]:
        pos     = action[:3].astype(np.float32)
        quat    = action[3:7].astype(np.float32)
        gripper = action[7:8].astype(np.float32) if self._has_gripper else None

        self._env.apply_pose_action(
            self._operator, pos, quat, gripper, kinematic=self._kinematic
        )
        if not self._kinematic:
            for _ in range(max(1, self._substeps)):
                self._env.step(np.empty(0))

        obs = self._get_obs()

        displaced = self._backend.is_object_displaced(
            self._success_object,
            self._initial_object_pose,
            self._displacement_threshold,
        )
        is_success = bool(displaced[0])

        info: Dict[str, Any] = {"is_success": is_success}
        if is_success:
            info["final_info"] = {"is_success": True}

        return obs, float(is_success), is_success, False, info

    def render(self) -> np.ndarray:
        """Return an HWC uint8 frame from the first configured camera."""
        raw       = self._env.capture_observation()
        first_cam = next(iter(self._sim_cameras.values()))
        return np.asarray(raw[_CAM_COLOR.format(cam=first_cam)]["data"], dtype=np.uint8)

    def close(self) -> None:
        if self._backend is not None:
            try:
                self._backend.teardown()
            except Exception:   # noqa: BLE001
                pass
        self._backend = None
        self._env     = None

    # ------------------------------------------------------------------
    # Internal: observation builder
    # ------------------------------------------------------------------

    def _get_obs(self) -> Dict[str, Any]:
        raw = self._env.capture_observation()
        op  = self._operator

        pos = _as_xyz(raw[_POSE_POS.format(op=op)]["data"])
        if self._observation_rotation == "rot6d":
            rot = _as_flat(raw[_POSE_ROT6D.format(op=op)]["data"], 6)
        else:
            rot = _as_quat(raw[_POSE_ORI.format(op=op)]["data"])

        state: List[float] = pos + rot
        if self._has_gripper:
            grip_raw = raw.get(_EEF_JS, {}).get("data")
            g = float(np.asarray(grip_raw).reshape(-1)[0]) if grip_raw is not None else 0.0
            state.append(g)

        pixels = {
            lk: np.asarray(
                raw[_CAM_COLOR.format(cam=cn)]["data"], dtype=np.uint8
            )
            for lk, cn in self._sim_cameras.items()
        }

        return {
            "pixels":    pixels,
            "agent_pos": np.array(state, dtype=np.float32),
        }
