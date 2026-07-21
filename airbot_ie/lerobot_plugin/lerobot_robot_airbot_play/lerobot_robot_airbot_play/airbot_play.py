"""LeRobot ``Robot`` adapter over the AIRBOT Play arm.

This wraps ``airbot_ie.robots.airbot_play.AIRBOTPlay`` (an ``airdc`` ``System``)
so it can be driven by the LeRobot ecosystem (``lerobot-rollout`` for policy
inference, ``lerobot-teleoperate``, etc.).

Bridging summary (see docs/feasibility in the repo):

- ``connect``     -> airdc ``System.configure()`` (builds the interface and
                     connects) + connect airdc cameras + ``switch_mode(SAMPLING)``.
- ``disconnect``  -> camera ``shutdown()`` + airdc ``System.shutdown()``.
- ``get_observation`` -> airdc ``capture_observation()`` flattened to the
                     LeRobot ``"<joint>.pos"`` scheme + camera frames.
- ``send_action`` -> LeRobot flat action dict -> airdc stamped dict ->
                     ``System.send_action`` (dict path, robust to gripper == 0.0).
"""

from __future__ import annotations

from time import time_ns
from typing import Any, Dict

import numpy as np
from lerobot.robots import Robot

from .config_airbot_play import AIRBOTPlayRobotConfig

# airdc imports are done lazily inside methods where hardware is touched, except
# SystemMode which is a lightweight enum needed for mode switching.
from airdc.common.systems.basis import SystemMode


class AIRBOTPlayRobot(Robot):
    """LeRobot-compatible AIRBOT Play robot."""

    config_class = AIRBOTPlayRobotConfig
    name = "airbot_play"

    def __init__(self, config: AIRBOTPlayRobotConfig):
        super().__init__(config)
        self.config = config
        self._sys = None  # airdc AIRBOTPlay System (set on connect)
        self._cameras: Dict[str, Any] = {}  # key -> airdc camera Sensor
        self._has_eef = "eef" in config.components

    # ------------------------------------------------------------------ #
    # Feature contracts (must be callable while disconnected)
    # ------------------------------------------------------------------ #
    @property
    def _motors_ft(self) -> Dict[str, type]:
        ft = {f"{name}.pos": float for name in self.config.arm_joint_names}
        if self._has_eef:
            ft[f"{self.config.gripper_joint_name}.pos"] = float
        return ft

    @property
    def _cameras_ft(self) -> Dict[str, tuple]:
        return {
            key: (spec.height, spec.width, 3)
            for key, spec in self.config.cameras.items()
        }

    @property
    def observation_features(self) -> dict:
        return {**self._motors_ft, **self._cameras_ft}

    @property
    def action_features(self) -> dict:
        return self._motors_ft

    # ------------------------------------------------------------------ #
    # Connection lifecycle
    # ------------------------------------------------------------------ #
    @property
    def is_connected(self) -> bool:
        sys_ok = self._sys is not None and self._sys.configured
        cams_ok = all(getattr(c, "configured", False) for c in self._cameras.values())
        return bool(sys_ok and cams_ok)

    def _build_airdc_system(self):
        """Instantiate the underlying airdc AIRBOTPlay System (real or mock)."""
        if self.config.mock:
            from airbot_ie.robots.airbot_play_mock import (
                AIRBOTPlay as _System,
                AIRBOTPlayConfig as _SystemConfig,
            )
        else:
            from airbot_ie.robots.airbot_play import (
                AIRBOTPlay as _System,
                AIRBOTPlayConfig as _SystemConfig,
            )
        sys_cfg = _SystemConfig(
            url=self.config.url,
            port=self.config.port,
            backend=self.config.backend,
            components=list(self.config.components),
        )
        return _System(sys_cfg)

    def _build_cameras(self) -> Dict[str, Any]:
        from cfgable import import_string  # provided via airdc's cfgable dep

        cameras: Dict[str, Any] = {}
        for key, spec in self.config.cameras.items():
            cam_cls = import_string(spec.target)
            cameras[key] = cam_cls(
                width=spec.width,
                height=spec.height,
                fps=spec.fps,
                **spec.extra,
            )
        return cameras

    def connect(self, calibrate: bool = True) -> None:
        if self.is_connected:
            raise RuntimeError(f"{self} is already connected.")

        self._sys = self._build_airdc_system()
        if not self._sys.configure():
            raise ConnectionError(f"{self}: airdc System failed to configure/connect.")

        self._cameras = self._build_cameras()
        for key, cam in self._cameras.items():
            if not cam.configure():
                raise ConnectionError(f"{self}: camera '{key}' failed to configure.")

        # Optionally plan a motion to a known home pose BEFORE servo mode, so the
        # policy always starts from the same posture. Done in RESETTING mode
        # (PLANNING_POS, blocking until arrival) — servo mode can't guarantee it.
        # This runs before lerobot captures its "initial position", so lerobot's
        # end-of-run "return to initial" also targets this home pose.
        if self.config.initial_pose is not None:
            self._move_to_initial_pose()

        # Enter servo (streaming) control for inference. The server-side servo
        # layer (MoveIt Servo + max_velocity/acceleration scaling) initializes
        # from the current joint state and velocity-limits toward any target, so
        # no manual "hold current position" priming is needed here.
        if not self._sys.switch_mode(SystemMode.SAMPLING):
            raise ConnectionError(f"{self}: failed to switch to SAMPLING mode.")

        self.configure()

    def disconnect(self) -> None:
        for key, cam in self._cameras.items():
            try:
                cam.shutdown()
            except Exception:  # noqa: BLE001 - best-effort cleanup
                pass
        self._cameras = {}
        if self._sys is not None:
            self._sys.shutdown()
            self._sys = None

    # ------------------------------------------------------------------ #
    # Calibration / configuration (no-ops: airbot has no LeRobot-style calib)
    # ------------------------------------------------------------------ #
    @property
    def is_calibrated(self) -> bool:
        return True

    def calibrate(self) -> None:
        pass

    def configure(self) -> None:
        # airdc System.on_configure already applied servo params on connect.
        pass

    # ------------------------------------------------------------------ #
    # Runtime I/O
    # ------------------------------------------------------------------ #
    def get_observation(self) -> Dict[str, Any]:
        if not self.is_connected:
            raise ConnectionError(f"{self} is not connected.")

        raw = self._sys.capture_observation()
        obs: Dict[str, Any] = {}

        arm = raw["arm/joint_state/position"]["data"]
        for name, value in zip(self.config.arm_joint_names, arm):
            obs[f"{name}.pos"] = float(value)

        if self._has_eef:
            eef = raw["eef/joint_state/position"]["data"]
            obs[f"{self.config.gripper_joint_name}.pos"] = float(eef[0])

        for key, cam in self._cameras.items():
            frame = cam.capture_observation()
            obs[key] = np.asarray(frame["color/image_raw"]["data"])

        return obs

    def send_action(self, action: Dict[str, Any]) -> Dict[str, Any]:
        if not self.is_connected:
            raise ConnectionError(f"{self} is not connected.")

        arm = [float(action[f"{name}.pos"]) for name in self.config.arm_joint_names]
        stamp = time_ns()
        airdc_action: Dict[str, Any] = {
            "arm/joint_state/position": {"data": arm, "t": stamp},
        }
        if self._has_eef:
            grip = float(action[f"{self.config.gripper_joint_name}.pos"])
            airdc_action["eef/joint_state/position"] = {"data": [grip], "t": stamp}

        self._sys.send_action(airdc_action)
        return action

    # ------------------------------------------------------------------ #
    # Homing
    # ------------------------------------------------------------------ #
    def _move_to_initial_pose(self) -> None:
        """Plan a blocking motion to ``config.initial_pose`` (RESETTING mode).

        Splits the pose into the arm's 6 joints (+ optional gripper) and drives
        the airdc System in RESETTING mode, which maps to PLANNING_POS ->
        ``move_to_joint_pos(..., blocking=True)`` so the call returns only once
        the arm has arrived. Then it is up to ``connect()`` to switch to servo.
        """
        pose = list(self.config.initial_pose)
        n_arm = len(self.config.arm_joint_names)
        expected = n_arm + (1 if self._has_eef else 0)
        if len(pose) != expected:
            raise ValueError(
                f"{self}: initial_pose has {len(pose)} values but components "
                f"{self.config.components} expect {expected} "
                f"({n_arm} arm{' + 1 gripper' if self._has_eef else ''})."
            )

        if not self._sys.switch_mode(SystemMode.RESETTING):
            raise ConnectionError(f"{self}: failed to switch to RESETTING mode.")

        stamp = time_ns()
        airdc_action: Dict[str, Any] = {
            "arm/joint_state/position": {"data": pose[:n_arm], "t": stamp},
        }
        if self._has_eef:
            airdc_action["eef/joint_state/position"] = {
                "data": [pose[n_arm]],
                "t": stamp,
            }

        self._sys.send_action(airdc_action)
