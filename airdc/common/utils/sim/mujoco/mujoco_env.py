from enum import Enum
from math import tan, pi
from pathlib import Path
from typing import Any, Dict, List
from pydantic import BaseModel, ConfigDict
import os
import numpy as np
import mujoco
import logging


class DataType(str, Enum):
    CAMERA = "camera"
    IMU = "imu"
    JOINT_POSITION = "position"
    JOINT_VELOCITY = "velocity"
    JOINT_EFFORT = "effort"
    TACTILE = "tactile"
    WRENCH = "wrench"
    POSE = "pose"


class CameraSpec(BaseModel, extra="forbid"):
    name: str
    width: int = 640
    height: int = 480
    enable_color: bool = True
    enable_depth: bool = True


class EnvConfig(BaseModel, extra="forbid"):
    model_config = ConfigDict(validate_assignment=True)

    model_path: Path
    arm_mode: str = "single"
    enabled_sensors: List[DataType] = []
    cameras: List[CameraSpec] = []
    stamp_ns: bool = True


class UnifiedMujocoEnv:
    def __init__(self, config: EnvConfig):
        self.get_logger().info("Initializing...")
        self.config = config
        self.model, self.data = self._load_model(config.model_path)

        if self.model.nkey > 0:
            mujoco.mj_resetDataKeyframe(self.model, self.data, 0)
        else:
            mujoco.mj_resetData(self.model, self.data)
        mujoco.mj_forward(self.model, self.data)

        self._components = (
            ["arm"] if config.arm_mode == "single" else ["left_arm", "right_arm"]
        )
        self._prefix = {"arm": "", "left_arm": "left_", "right_arm": "right_"}

        self._camera_specs = {c.name: c for c in config.cameras}
        self._renderers: Dict[str, mujoco.Renderer] = {}
        self._camera_ids = {}

        logger = self.get_logger()

        if DataType.CAMERA in config.enabled_sensors:
            logger.info(f"Setting up cameras: {list(self._camera_specs.keys())}")
            for name, spec in self._camera_specs.items():
                cam_id = mujoco.mj_name2id(self.model, mujoco.mjtObj.mjOBJ_CAMERA, name)
                if cam_id < 0:
                    raise ValueError(
                        f"Camera '{name}' not found in the Mujoco model. Available cameras: {[mujoco.mj_id2name(self.model, mujoco.mjtObj.mjOBJ_CAMERA, i) for i in range(self.model.ncam)]}"
                    )
                self._camera_ids[name] = cam_id
                self._renderers[name] = mujoco.Renderer(
                    self.model,
                    height=spec.height,
                    width=spec.width,
                )

        self._imu_ids = {}
        self._pose_ids = {}
        self._wrench_ids = {}
        for comp in self._components:
            prefix = self._prefix[comp]
            self._imu_ids[comp] = {
                "acc": self._sensor_id(f"{prefix}imu_acc"),
                "gyro": self._sensor_id(f"{prefix}imu_gyro"),
                "quat": self._sensor_id(f"{prefix}imu_quat"),
            }
            self._pose_ids[comp] = {
                "pos": self._sensor_id(f"{prefix}global_gripper_pos"),
                "quat": self._sensor_id(f"{prefix}global_gripper_quat"),
            }
            self._wrench_ids[comp] = {
                "force": self._sensor_id(f"{prefix}eef_force"),
                "torque": self._sensor_id(f"{prefix}eef_torque"),
            }

        self._tactile_manager = None
        if (
            DataType.TACTILE in config.enabled_sensors
            or DataType.WRENCH in config.enabled_sensors
        ):
            self._init_tactile_manager()
        self._last_time = None

    @staticmethod
    def _load_model(model_path: Path) -> tuple[Any, Any]:
        original_dir = os.getcwd()
        xml_path = Path(model_path).resolve()
        xml_dir = xml_path.parent
        try:
            os.chdir(xml_dir)
            model = mujoco.MjModel.from_xml_path(xml_path.name)
            data = mujoco.MjData(model)
        finally:
            os.chdir(original_dir)
        return model, data

    def _init_tactile_manager(self) -> None:
        try:
            import importlib
            import sys

            tactile_dir = Path(__file__).resolve().parents[1] / "tactile"
            if str(tactile_dir) not in sys.path:
                sys.path.insert(0, str(tactile_dir))
            tactile_module = importlib.import_module("tactile_sensor")
            tactile_manager_cls = getattr(tactile_module, "TactileSensorManager")

            self._tactile_manager = tactile_manager_cls(
                self.model,
                self.data,
                enable=DataType.TACTILE in self.config.enabled_sensors,
            )
        except Exception:
            self._tactile_manager = None

    def _sensor_id(self, name: str) -> int:
        sid = mujoco.mj_name2id(self.model, mujoco.mjtObj.mjOBJ_SENSOR, name)
        return int(sid)

    def _sensor_data(self, sensor_id: int) -> np.ndarray:
        if sensor_id < 0:
            return np.zeros((0,), dtype=np.float32)
        idx = self.model.sensor_adr[sensor_id]
        dim = self.model.sensor_dim[sensor_id]
        return np.asarray(self.data.sensordata[idx : idx + dim], dtype=np.float32)

    def _component_q_indices(self, component: str) -> np.ndarray:
        if component == "arm":
            return np.arange(min(7, self.model.nq), dtype=np.int32)

        prefix = self._prefix[component]
        indices = []
        for jid in range(self.model.njnt):
            name = mujoco.mj_id2name(self.model, mujoco.mjtObj.mjOBJ_JOINT, jid) or ""
            if name.startswith(prefix):
                qpos_adr = int(self.model.jnt_qposadr[jid])
                indices.append(qpos_adr)
        indices = sorted(set(indices))
        if not indices:
            return np.arange(min(7, self.model.nq), dtype=np.int32)
        return np.asarray(indices[:7], dtype=np.int32)

    def _component_actuator_indices(self, component: str) -> np.ndarray:
        prefix = self._prefix[component]
        if component == "arm":
            return np.arange(min(7, self.model.nu), dtype=np.int32)

        indices = []
        for aid in range(self.model.nu):
            name = (
                mujoco.mj_id2name(self.model, mujoco.mjtObj.mjOBJ_ACTUATOR, aid) or ""
            )
            if name.startswith(prefix):
                indices.append(aid)
        if not indices:
            return np.arange(min(7, self.model.nu), dtype=np.int32)
        return np.asarray(indices[:7], dtype=np.int32)

    def reset(self) -> None:
        if self.model.nkey > 0:
            mujoco.mj_resetDataKeyframe(self.model, self.data, 0)
        else:
            mujoco.mj_resetData(self.model, self.data)
        mujoco.mj_forward(self.model, self.data)

    def step(self, action: np.ndarray) -> None:
        action = np.asarray(action, dtype=np.float64).reshape(-1)
        n = min(len(action), self.model.nu)
        if n > 0:
            ctrl = np.asarray(self.data.ctrl, dtype=np.float64)
            ctrl[:n] = action[:n]
            if self.model.nu > 0:
                low = self.model.actuator_ctrlrange[:n, 0]
                high = self.model.actuator_ctrlrange[:n, 1]
                ctrl[:n] = np.clip(ctrl[:n], low, high)
            self.data.ctrl[:n] = ctrl[:n]
        self.update()

    def capture_observation(self) -> dict[str, dict[str, Any]]:
        t = (
            float(self.data.time)
            if not self.config.stamp_ns
            else int(self.data.time * 1e9)
        )
        obs: dict[str, dict[str, Any]] = {}

        for component in self._components:
            qidx = self._component_q_indices(component)
            aidx = self._component_actuator_indices(component)

            if DataType.JOINT_POSITION in self.config.enabled_sensors:
                obs[f"{component}/joint_state/position"] = {
                    "data": np.asarray(self.data.qpos[qidx], dtype=np.float32),
                    "t": t,
                }
            if DataType.JOINT_VELOCITY in self.config.enabled_sensors:
                vsize = np.minimum(qidx, max(0, self.data.qvel.shape[0] - 1))
                obs[f"{component}/joint_state/velocity"] = {
                    "data": np.asarray(self.data.qvel[vsize], dtype=np.float32),
                    "t": t,
                }
            if DataType.JOINT_EFFORT in self.config.enabled_sensors:
                obs[f"{component}/joint_state/effort"] = {
                    "data": np.asarray(self.data.ctrl[aidx], dtype=np.float32),
                    "t": t,
                }

            if DataType.POSE in self.config.enabled_sensors:
                pos = self._sensor_data(self._pose_ids[component]["pos"])
                quat = self._sensor_data(self._pose_ids[component]["quat"])
                obs[f"{component}/pose/position"] = {
                    "data": pos.astype(np.float32),
                    "t": t,
                }
                obs[f"{component}/pose/orientation"] = {
                    "data": quat.astype(np.float32),
                    "t": t,
                }

            if DataType.IMU in self.config.enabled_sensors:
                acc = self._sensor_data(self._imu_ids[component]["acc"])
                gyro = self._sensor_data(self._imu_ids[component]["gyro"])
                quat = self._sensor_data(self._imu_ids[component]["quat"])
                obs[f"{component}/imu/linear_acceleration"] = {
                    "data": acc,
                    "t": t,
                }
                obs[f"{component}/imu/angular_velocity"] = {
                    "data": gyro,
                    "t": t,
                }
                obs[f"{component}/imu/orientation"] = {
                    "data": quat,
                    "t": t,
                }

            if DataType.WRENCH in self.config.enabled_sensors:
                force = self._sensor_data(self._wrench_ids[component]["force"])
                torque = self._sensor_data(self._wrench_ids[component]["torque"])
                if force.size == 0 or torque.size == 0:
                    force, torque = self._wrench_from_tactile(component)
                obs[f"{component}/wrench/force"] = {
                    "data": np.asarray(force, dtype=np.float32),
                    "t": t,
                }
                obs[f"{component}/wrench/torque"] = {
                    "data": np.asarray(torque, dtype=np.float32),
                    "t": t,
                }

        if (
            DataType.TACTILE in self.config.enabled_sensors
            and self._tactile_manager is not None
        ):
            tactile_data = self._tactile_manager.get_data().get("tactile")
            if tactile_data is not None:
                for component, data in self._group_tactile_by_component(
                    tactile_data
                ).items():
                    obs[f"{component}/tactile/point_cloud_raw"] = {
                        "data": data,
                        "t": t,
                    }

        if DataType.CAMERA in self.config.enabled_sensors:
            for cam_name, renderer in self._renderers.items():
                cam_id = self._camera_ids[cam_name]
                spec = self._camera_specs[cam_name]
                renderer.update_scene(self.data, camera=cam_id)
                if spec.enable_color:
                    obs[f"{cam_name}/color/image_raw"] = {
                        "data": np.asarray(renderer.render(), dtype=np.uint8),
                        "t": t,
                    }
                if spec.enable_depth:
                    renderer.enable_depth_rendering()
                    depth = renderer.render()
                    obs[f"{cam_name}/aligned_depth_to_color/image_raw"] = {
                        "data": np.asarray(depth, dtype=np.float32),
                        "t": t,
                    }

        return obs

    def is_updated(self) -> bool:
        current_time = self.data.time
        if self._last_time != current_time:
            self._last_time = current_time
            return True
        return False

    def update(self):
        mujoco.mj_step(self.model, self.data)

    def _wrench_from_tactile(self, component: str) -> tuple[np.ndarray, np.ndarray]:
        if self._tactile_manager is None:
            return np.zeros(3, dtype=np.float32), np.zeros(3, dtype=np.float32)

        wrenches = self._tactile_manager.get_finger_wrenches()
        force = np.zeros(3, dtype=np.float64)
        torque = np.zeros(3, dtype=np.float64)
        for panel_name, panel_wrench in wrenches.items():
            if component == "arm":
                matches = True
            elif component == "left_arm":
                matches = panel_name.startswith("left_")
            else:
                matches = panel_name.startswith("right_")
            if not matches:
                continue
            panel_wrench = np.asarray(panel_wrench, dtype=np.float64).reshape(-1)
            if panel_wrench.shape[0] >= 6:
                force += panel_wrench[:3]
                torque += panel_wrench[3:6]
        return force.astype(np.float32), torque.astype(np.float32)

    def _group_tactile_by_component(
        self, tactile_tensor: np.ndarray
    ) -> dict[str, np.ndarray]:
        tactile_tensor = np.asarray(tactile_tensor, dtype=np.float32)
        if tactile_tensor.ndim != 3 or self._tactile_manager is None:
            return {}

        grouped: dict[str, list[np.ndarray]] = {k: [] for k in self._components}
        for i, panel_name in enumerate(self._tactile_manager.panel_order):
            if i >= tactile_tensor.shape[0]:
                break
            panel = tactile_tensor[i]
            if "left_" in panel_name:
                comp = "left_arm" if "left_arm" in grouped else "arm"
            elif "right_" in panel_name:
                comp = "right_arm" if "right_arm" in grouped else "arm"
            else:
                comp = "arm"
            grouped.setdefault(comp, []).append(panel)

        out = {}
        for comp, blocks in grouped.items():
            if blocks:
                out[comp] = np.concatenate(blocks, axis=0)
        return out

    def get_info(self) -> dict[str, Any]:
        mujoco.mj_forward(self.model, self.data)
        info: dict[str, Any] = {
            "model_path": str(self.config.model_path),
            "arm_mode": self.config.arm_mode,
            "enabled_sensors": [s.value for s in self.config.enabled_sensors],
            "cameras": {},
        }

        for cam_name, cam_id in self._camera_ids.items():
            spec = self._camera_specs[cam_name]
            fovy_deg = float(self.model.cam_fovy[cam_id])
            fovy_rad = fovy_deg * pi / 180.0
            f = (spec.height / 2.0) / tan(fovy_rad / 2.0)

            camera_info = {
                "width": spec.width,
                "height": spec.height,
                "distortion_model": "plumb_bob",
                "d": [0.0, 0.0, 0.0, 0.0, 0.0],
                "k": [
                    f,
                    0.0,
                    spec.width / 2.0,
                    0.0,
                    f,
                    spec.height / 2.0,
                    0.0,
                    0.0,
                    1.0,
                ],
                "r": [
                    1.0,
                    0.0,
                    0.0,
                    0.0,
                    1.0,
                    0.0,
                    0.0,
                    0.0,
                    1.0,
                ],
                "p": [
                    f,
                    0.0,
                    spec.width / 2.0,
                    0.0,
                    0.0,
                    f,
                    spec.height / 2.0,
                    0.0,
                    0.0,
                    0.0,
                    1.0,
                    0.0,
                ],
            }

            cam_rot = np.asarray(self.data.cam_xmat[cam_id]).reshape(3, 3)
            cam_pos = np.asarray(self.data.cam_xpos[cam_id])

            info["cameras"][cam_name] = {
                "camera_info": {
                    stream_type: camera_info for stream_type in ("color", "depth")
                },
                # TODO: should separate extrinsics for color and depth?
                "camera_extrinsics": {
                    "translation": cam_pos,
                    "rotation_matrix": cam_rot,
                },
            }
        return info

    def close(self) -> None:
        for renderer in self._renderers.values():
            if hasattr(renderer, "close"):
                renderer.close()
        self._renderers.clear()

    def get_logger(self) -> logging.Logger:
        return logging.getLogger(self.__class__.__name__)
