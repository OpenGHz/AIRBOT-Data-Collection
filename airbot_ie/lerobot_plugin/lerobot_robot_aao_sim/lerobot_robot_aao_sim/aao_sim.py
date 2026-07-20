"""LeRobot ``Robot`` adapter over the auto-atomic-operation MuJoCo simulator.

Runs a LeRobot policy in sim through the same rollout path as the real arm:
lerobot owns the per-step loop (get_observation -> policy -> send_action); this
adapter wraps a single (batch=1) ``UnifiedMujocoEnv``.

State-only, EEF-pose: observation.state / action = EEF position(3) +
orientation(4, xyzw) [+ gripper(1)]. See config_aao_sim.py.
"""

from __future__ import annotations

from typing import Any, Dict, List

import numpy as np
from lerobot.robots import Robot

from .config_aao_sim import AAOSimRobotConfig

# aao obs keys (nested dict from capture_observation). These are the
# operator-prefixed pose keys the env emits; resolved against the operator name.
_POSE_POS = "{op}/pose/position"
_POSE_ORI = "{op}/pose/orientation"
_EEF_JS = "eef/joint_state/position"  # gripper joint (best-effort)


def _as_xyz(data: Any) -> List[float]:
    """capture_observation stores position as {x,y,z} (structured) or [x,y,z]."""
    if isinstance(data, dict):
        return [float(data["x"]), float(data["y"]), float(data["z"])]
    arr = np.asarray(data, dtype=float).reshape(-1)
    return [float(v) for v in arr[:3]]


def _as_quat(data: Any) -> List[float]:
    """Orientation as {x,y,z,w} (structured) or [x,y,z,w]."""
    if isinstance(data, dict):
        return [float(data["x"]), float(data["y"]), float(data["z"]), float(data["w"])]
    arr = np.asarray(data, dtype=float).reshape(-1)
    return [float(v) for v in arr[:4]]


class AAOSimRobot(Robot):
    """LeRobot-compatible auto-atomic-operation MuJoCo sim robot."""

    config_class = AAOSimRobotConfig
    name = "aao_sim"

    def __init__(self, config: AAOSimRobotConfig):
        super().__init__(config)
        self.config = config
        self._backend = None
        self._env = None  # single UnifiedMujocoEnv (batch=1)

    # ------------------------------------------------------------------ #
    # Feature contracts (callable while disconnected)
    # ------------------------------------------------------------------ #
    @property
    def _state_names(self) -> List[str]:
        names = list(self.config.position_keys) + list(self.config.orientation_keys)
        if self.config.has_gripper:
            names.append(self.config.gripper_key)
        return names

    @property
    def observation_features(self) -> dict:
        return {name: float for name in self._state_names}

    @property
    def action_features(self) -> dict:
        return {name: float for name in self._state_names}

    @property
    def is_connected(self) -> bool:
        return self._env is not None

    @property
    def is_calibrated(self) -> bool:
        return True

    def calibrate(self) -> None:
        pass

    def configure(self) -> None:
        pass

    # ------------------------------------------------------------------ #
    # Connection lifecycle
    # ------------------------------------------------------------------ #
    def connect(self, calibrate: bool = True) -> None:
        if self.is_connected:
            raise RuntimeError(f"{self} is already connected.")
        import os

        import auto_atom
        from auto_atom import load_task_file_hydra

        # Resolve the aao config dir. Default: the `aao_configs/` shipped next to
        # the installed auto_atom package (works regardless of cwd, unlike
        # load_task_file_hydra's <cwd>/aao_configs default).
        pkg_parent = os.path.normpath(
            os.path.join(os.path.dirname(auto_atom.__file__), "..")
        )
        config_dir = self.config.config_dir or os.path.join(pkg_parent, "aao_configs")
        # aao configs default `assets_dir: assets` (relative to cwd). Force it to
        # the absolute assets/ shipped in the aao repo so scene XMLs resolve
        # regardless of the working directory.
        overrides = list(self.config.hydra_overrides) + [
            "env.batch_size=1",
            f"assets_dir={os.path.join(pkg_parent, 'assets')}",
        ]
        tf = load_task_file_hydra(
            self.config.task_config, config_dir=config_dir, overrides=overrides
        )
        # tf.backend is a callable that builds the MujocoTaskBackend (owns .env).
        backend = tf.backend(tf.task, tf.task_operators)
        backend.reset()
        self._backend = backend
        # Drive the underlying single env directly (batch=1).
        self._env = backend.env.envs[0]

    def disconnect(self) -> None:
        if self._backend is not None:
            try:
                self._backend.teardown()
            except Exception:  # noqa: BLE001 - best-effort cleanup
                pass
        self._backend = None
        self._env = None

    # ------------------------------------------------------------------ #
    # Runtime I/O
    # ------------------------------------------------------------------ #
    def get_observation(self) -> Dict[str, Any]:
        if not self.is_connected:
            raise ConnectionError(f"{self} is not connected.")
        raw = self._env.capture_observation()
        op = self.config.operator
        pos = _as_xyz(raw[_POSE_POS.format(op=op)]["data"])
        quat = _as_quat(raw[_POSE_ORI.format(op=op)]["data"])

        obs: Dict[str, Any] = {}
        for name, value in zip(self.config.position_keys, pos):
            obs[name] = float(value)
        for name, value in zip(self.config.orientation_keys, quat):
            obs[name] = float(value)
        if self.config.has_gripper:
            grip = raw.get(_EEF_JS, {}).get("data")
            obs[self.config.gripper_key] = (
                float(np.asarray(grip).reshape(-1)[0]) if grip is not None else 0.0
            )
        return obs

    def send_action(self, action: Dict[str, Any]) -> Dict[str, Any]:
        if not self.is_connected:
            raise ConnectionError(f"{self} is not connected.")
        position = np.array(
            [float(action[k]) for k in self.config.position_keys], dtype=np.float32
        )
        orientation = np.array(
            [float(action[k]) for k in self.config.orientation_keys], dtype=np.float32
        )
        gripper = None
        if self.config.has_gripper:
            gripper = np.array(
                [float(action[self.config.gripper_key])], dtype=np.float32
            )

        self._env.apply_pose_action(
            self.config.operator,
            position,
            orientation,
            gripper,
            kinematic=self.config.kinematic,
        )
        # Advance physics so the pose target is realized (skip if kinematic).
        if not self.config.kinematic:
            for _ in range(max(1, self.config.substeps)):
                self._env.step(np.empty(0))
        return action
