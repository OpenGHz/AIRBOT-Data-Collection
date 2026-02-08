import time
from typing import Tuple
from pydantic import IPvAnyAddress
from threading import Thread
from airdc.common.systems.basis import SystemConfig, System, SystemMode
from airdc.common.utils.http import RESTfulJson as rj
from airdc.common.configs.control import BaseControlParams
from mcap_data_loader.utils.transformations import quaternion_from_euler
from mcap_data_loader.utils.basic import Rate
from mcap_data_loader.data_types.basis import Pose3D


PoseTuple = Tuple[float, float, float]  # x, y, theta
VelocityTuple = Tuple[float, float, float]  # vx, vy, omega


class SlamtecAthena2Config(SystemConfig):
    """Slamtec Athena2 robotic base configuration"""

    ip: IPvAnyAddress = "192.168.11.1"
    """IP address of the robot"""


class Urls:
    def __init__(self, ip: str):
        url: str = f"http://{ip}:1448/api/core/"
        self.set_action: str = url + "motion/v1/actions"
        self.action_state: str = url + "motion/v1/actions/{action_id}"
        self.current_pose: str = url + "slam/v1/localization/pose"
        self.current_velocity: str = url + "motion/v1/speed"
        self.quantity_electricity: str = url + "system/v1/power/status"
        self.health_state: str = url + "system/v1/robot/health"
        self.mapping: str = url + "slam/v1/mapping/:enable"
        self.reset_origin: str = url + "slam/v1/localization/pose"
        self.light_ctrl: str = url + "system/v1/light/control"
        self.charge_station: str = url + "slam/v1/homepose"
        self.capabilities: str = url + "system/v1/capabilities"
        self.robot_info: str = url + "system/v1/robot/info"
        self.parameter: str = url + "system/v1/parameter"
        self.odometry: str = url + "statistics/v1/odometry"


class SlamtecAthena2(System):
    """Slamtec Athena2 interface. RESTful API reference: https://docs.slamtec.com/#/.
    This API is not fully functional, including the inability to control speed and brakes,
    which causes problems with data collection and usage. Future implementations should use
    the pybind version of the C++ SDK as the underlying interface.
    """

    def __init__(self, config: SlamtecAthena2Config):
        self.config = config
        self._urls = Urls(config.ip)
        self._cur_state = None

    def check_connection(self) -> bool:
        return self.get_error_state() is not None

    def on_configure(self) -> bool:
        self.get_logger().info(f"Connecting to {self.config.ip}")
        if not self.check_connection():
            self.get_logger().error("Failed to connect")
            return False

        rate = self.config.rate
        rate = 50 if (rate == 0 and not self.config.blocking) else rate

        def get_state_loop():
            loop_rate = Rate(rate)
            while True:
                self.get_state(True)
                loop_rate.sleep()

        if rate != 0:
            self._get_state_concur = Thread(target=get_state_loop, daemon=True)
            self._get_state_concur.start()
            while self._cur_state is None:
                # self.get_logger().info("")
                time.sleep(0.2)
        return True

    def capture_observation(self, timeout=None):
        block = timeout != 0 if self.config.blocking in {None, True} else False
        return self.get_state(block)

    def result(self, timeout=None):
        return self._cur_state

    def on_switch_mode(self, mode):
        if mode is SystemMode.PASSIVE:
            # TODO: use pybind api to unlock the robot
            pass
        return True

    def send_action(self, action):
        if self.current_mode is SystemMode.RESETTING:
            self.send_goal_pose(
                Pose3D(x=action[0], y=action[1], theta=action[2]), BaseControlParams()
            )
        elif self.current_mode is SystemMode.SAMPLING:
            # TODO: use pybind api to control speed
            pass
        else:
            self.get_logger().warning(
                f"Cannot send action in current mode: {self.current_mode}"
            )

    def wait_action(self, action_id, timeout=None):
        logger = self.get_logger()
        action_url = self._urls.action_state.format(action_id=action_id)
        start_time = time.time()
        while timeout is None or (time.time() - start_time < timeout):
            try:
                data = rj.get(action_url)
                if "action_name" in data:
                    break
            except Exception as e:
                logger.error(f"{e}")
            time.sleep(0.05)

    def send_goal_pose(self, pose: Pose3D, param: BaseControlParams) -> bool:
        x, y, yaw = pose.x, pose.y, pose.theta
        if yaw is not None:
            param.move_params.append("with_yaw")
        if param.fail_retry_count > 0:
            param.move_params.append("with_fail_retry_count")
        payload = {
            "action_name": "slamtec.agent.actions.MoveToAction",
            "options": {
                "target": {"x": x, "y": y},
                "move_options": {
                    "mode": param.navigation_mode,
                    "flags": param.move_params,
                    "yaw": yaw,
                    "fail_retry_count": param.fail_retry_count,
                },
                "speed_ratio": param.speed_ratio,
            },
        }

        response: dict = rj.post(self._urls.set_action, payload)
        if param.wait:
            self.wait(response.get("action_id"))
        return True

    def get_state(self, block=False):
        """Get current pose, velocity, odometry with a common stamp"""
        # TODO: add odometry
        if block:
            pose = self.get_current_pose()
            velocity = self.get_current_velocity()
            t = time.time_ns()
            base_state = {
                "pose/position": self._create_value([pose[0], pose[1], 0.0], t),
                "pose/orientation": self._create_value(
                    quaternion_from_euler(0, 0, pose[2]).tolist(), t
                ),
                "twist/linear": self._create_value([velocity[0], 0.0, 0.0], t),
                "twist/angular": self._create_value([0.0, 0.0, velocity[2]], t),
            }
            self._cur_state = base_state
            return base_state
        else:
            return self._cur_state

    def get_current_pose(self) -> PoseTuple:
        pose = rj.get(self._urls.current_pose)
        if pose is None:
            return (0.0, 0.0, 0.0)
        return pose["x"], pose["y"], pose["yaw"]

    def get_current_velocity(self) -> VelocityTuple:
        velocity = rj.get(self._urls.current_velocity)
        if velocity is None:
            return (0.0, 0.0, 0.0)
        return velocity["vx"], velocity["vy"], velocity["omega"]

    def get_battery_percentage(self) -> float:
        data = rj.get(self._urls.quantity_electricity)
        if data is None:
            return -1
        return data["batteryPercentage"]

    def get_error_state(self):
        data = rj.get(self._urls.health_state)
        if data is not None:
            return (
                [data["baseError"][0]["message"]]
                if data["hasError"]
                else data["hasError"]
            )

    def is_mapping(self) -> bool:
        data = rj.get(self._urls.mapping)
        if data is None:
            return False
        return data

    def enable_mapping(self, enable: bool = True) -> bool:
        payload = {"enable": enable}
        update_response = rj.put(self._urls.mapping, payload)
        self.get_logger().info(f"{update_response}")
        if update_response:
            return True
        return False

    def back_to_charging_station(self, param) -> bool:
        payload = {
            "action_name": "slamtec.agent.actions.GoHomeAction",
            "options": {
                "gohome_options": {
                    "flags": "dock",
                    "back_to_landing": False,
                    "charging_retry_count": 5,
                    "move_options": {"mode": param.navigation_mode},
                },
            },
        }
        response = rj.post(self._urls.set_action, payload)
        return True

    def get_charge_pose(self) -> PoseTuple:
        pose = rj.get(self._urls.charge_station)
        return pose["x"], pose["y"], pose["yaw"]

    def set_charge_pose(self, pose: Pose3D) -> bool:
        x, y, yaw = pose.x, pose.y, pose.theta
        payload = {"x": x, "y": y, "z": 0, "yaw": yaw, "picth": 0, "roll": 0}
        update_response = rj.put(self._urls.charge_station, payload)
        return update_response

    def reset_origin(self, x, y, yaw):
        payload = {"x": x, "y": y, "z": 0, "yaw": yaw, "pitch": 0, "roll": 0}
        update_response = rj.put(self._urls.reset_origin, payload)
        return update_response

    def rotate(self, angle: float, param: BaseControlParams) -> bool:
        # TODO: speed param is not used
        payload = {
            "action_name": "slamtec.agent.actions.RotateAction",
            "options": {"angle": angle},
        }
        response = rj.post(self._urls.set_action, payload)
        # speed = param.speed_ratio
        if param.wait:
            action_id = response.get("action_id", None)
            if action_id is not None:
                self.wait()
        return True

    def get_capabilities(self) -> dict:
        return rj.get(self._urls.capabilities)

    def get_robot_info(self) -> dict:
        return rj.get(self._urls.robot_info)

    def get_parameter(self) -> dict:
        return rj.get(self._urls.parameter)

    def get_odometry(self) -> float:
        return rj.get(self._urls.odometry)

    def get_info(self):
        return {
            "capabilities": self.get_capabilities(),
            "robot_info": self.get_robot_info(),
            "parameter": self.get_parameter(),
        }

    def get_status(self) -> dict:
        """Get robot status including battery, error state, mapping state, charge station pose"""
        return {
            "battery": self.get_battery_percentage(),
            "error_state": self.get_error_state(),
            "is_mapping": self.is_mapping(),
            "charge_station_pose": self.get_charge_pose(),
        }

    def shutdown(self):
        return True


if __name__ == "__main__":
    import logging
    from pprint import pprint

    logging.basicConfig(level=logging.INFO)

    base = SlamtecAthena2(SlamtecAthena2Config())
    assert base.configure()
    pprint(base.get_info())
    pprint(base.get_status())

    while True:
        pprint(base.capture_observation())
        time.sleep(0.5)
