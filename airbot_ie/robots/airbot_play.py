from typing import List, Union, Dict, Tuple, Any, Optional, Literal
from pydantic import PositiveInt, Field
from time import time_ns, perf_counter
from collections import defaultdict
from functools import partial
from airdc.utils import linear_map, proxy_context
from airdc.common.systems.basis import (
    System,
    SystemConfig,
    InterfaceType,
    ReferenceMode,
    ActionConfigs,
    ObservationConfig,
    SystemMode,
)
from mcap_data_loader.utils.tf import (
    apply_tf_to_pose,
    pose2matrix,
    to_matrix,
    array_pose_to_list_wrapper,
    is_identity_matrix,
    StaticTFBuffer,
)
from mcap_data_loader.utils.rot6d import Rotation6D
from mcap_data_loader.utils.rela_abs import PoseGlobalRelaAbs, VectorRelaAbs
from airdc.common.configs.control import (
    JointControlBasis,
    JointPositionServo,
    JointPositionPlan,
    JointMIT,
    PoseControlBasis,
    PoseServo,
    PosePlan,
    get_control_cfg_kind,
)
from mcap_data_loader.basis import DictDataStamped, DataStamped
from functools import cache, wraps
import numpy as np
import math


AVAILABLE_BACKEND = set()
try:
    from airbot_py.arm import AIRBOTArm, RobotMode, SpeedProfile

    AVAILABLE_BACKEND.add("grpc")
except ImportError:
    from airbot_ie.robots.airbot_play_thin import (
        AIRBOTArm,
        RobotMode,
        SpeedProfile,
    )

    AVAILABLE_BACKEND.add("thin")


ComponentType = Literal["arm", "eef"]


class AIRBOTPlayConfig(SystemConfig):
    url: str = "localhost"
    """The robot server URL."""
    port: PositiveInt = 50050
    """The robot server port."""
    speed_profile: Optional[Union[SpeedProfile, str]] = SpeedProfile.FAST
    """The speed profile for the robot movements."""
    limit: Dict[str, Dict[Union[str, int], Tuple[float, float]]] = {}
    """The limit configuration for joint positions."""
    backend: str = "grpc"  # grpc or thin
    """The backend type for connecting to the robot."""
    components: List[ComponentType] = Field(["arm", "eef"], min_length=1)
    """List of robot components to control."""
    action: ActionConfigs = [
        {
            SystemMode.RESETTING: JointPositionPlan(),
            SystemMode.SAMPLING: JointPositionServo(),
        }
    ]
    observation: List[ObservationConfig] = [
        ObservationConfig(
            interfaces=InterfaceType.joint_states() | {InterfaceType.POSE}
        )
    ]
    joint_names: List[List[str]] = [
        [f"joint{i}" for i in range(1, 7)],
        ["arm_eef_gripper_joint"],
    ]
    """The joint names for each component."""

    def model_post_init(self, context):
        if isinstance(self.speed_profile, str):
            self.speed_profile = SpeedProfile[self.speed_profile]
        assert self.backend in AVAILABLE_BACKEND, (
            f"Backend is not available: {self.backend}, "
            f"available backends: {AVAILABLE_BACKEND}"
        )
        # NOTE: the airbot play robot does not provide pose interface for arm
        self.observation[self.components.index("arm")].interfaces.discard(
            InterfaceType.POSE
        )


class AIRBOTPlay(System):
    interface: AIRBOTArm

    def __init__(self, config: AIRBOTPlayConfig):
        self.config = config
        self._joint_names = dict(zip(self.config.components, self.config.joint_names))
        self._last_action = defaultdict(dict)

    def on_configure(self) -> bool:
        self._init_args()
        interface = self.interface
        # mapping action config type to robot mode and function
        type2mode = {
            # NOTE: PLANNING_POS can be used for both joint and cartesian planning
            JointPositionPlan: RobotMode.PLANNING_POS,
            PosePlan: RobotMode.PLANNING_POS,
            JointPositionServo: RobotMode.SERVO_JOINT_POS,
            JointMIT: RobotMode.MIT_INTEGRATED,
            PoseServo: RobotMode.SERVO_CART_POSE,
        }
        # NOTE: the first item of the functions must be joint position or pose
        # if use relative control
        type2func = {
            "arm": {
                JointPositionServo: interface.servo_joint_pos,
                JointPositionPlan: interface.move_to_joint_pos,
                JointMIT: interface.mit_joint_integrated_control,
                PoseServo: interface.servo_cart_pose,
                PosePlan: interface.move_to_cart_pose,
            },
            "eef": {
                JointPositionServo: interface.servo_eef_pos,
                JointPositionPlan: interface.move_eef_pos,
            },
        }
        # mapping action config type to action length
        # e.g., joint position control needs 6 values for arm and 1 value for eef, the action is like [arm_joint1, arm_joint2, ..., arm_joint6, eef_joint] but when using mit control for arm, the action is like [mit_control_list, eef_joint]
        type2length = {
            "arm": {
                JointPositionServo: 6,
                JointPositionPlan: 6,
                JointMIT: 0,
                PoseServo: 0,
                PosePlan: 0,
            },
            "eef": {
                JointPositionServo: 1,
                JointPositionPlan: 1,
                PoseServo: 0,
                PosePlan: 0,
            },
        }
        # mapping the system mode to robot mode
        self._mode_mapping = {SystemMode.PASSIVE: RobotMode.GRAVITY_COMP}
        mode_mapping = defaultdict(dict)
        self._mode2func = defaultdict(dict)
        self._mode2length = defaultdict(dict)
        config = self.config
        for component, mode_act_cfg in zip(config.components, config.action):
            for mode, act_cfg in mode_act_cfg.items():
                cfg_type = type(act_cfg)
                mode_mapping[mode][component] = type2mode[cfg_type]
                # wrap the control function to convert relative action to absolute action if needed, and save the last action for each component if needed for calculating the relative action.
                cfg_kind = get_control_cfg_kind(act_cfg)
                self._mode2func[mode][component] = self._rela_ctrl_wrapper(
                    self._last_action_wrapper(
                        type2func[component][cfg_type], component, cfg_kind
                    ),
                    component,
                    mode,
                    cfg_kind,
                )
                self._mode2length[mode][component] = type2length[component][cfg_type]
        self._mode_mapping.update(mode_mapping)
        # print(f"mode_mapping: {self._mode_mapping}")
        # set action post process function TODO: configure this?
        self.action_post_process = self.action_data_to_list
        self.get_logger().info(f"Connecting to {config.url}:{config.port}")
        with proxy_context:
            result = interface.connect()
        if result:
            # interface.set_speed_profile(self.config.speed_profile)
            interface.set_params(
                {
                    "servo_node.moveit_servo.scale.linear": 10.0,
                    "servo_node.moveit_servo.scale.rotational": 10.0,
                    "servo_node.moveit_servo.scale.joint": 1.0,
                    "sdk_server.max_velocity_scaling_factor": 1.0,
                    "sdk_server.max_acceleration_scaling_factor": 0.5,
                }
            )
            # check if the robot components are available
            info = interface.get_product_info()
            self.get_logger().info(f"Robot info: {info}")
            self._component_types = {
                "arm": info["product_type"],
                "eef": info["eef_types"][0],
            }
            for component in config.components:
                comp_type = self._component_types[component]
                if comp_type == "none":
                    self.get_logger().error(
                        f"Component {component} is not available. "
                        "Please check the configuration or the robot connection."
                    )
                    return False
                if component == "eef" and not interface.get_eef_pos():
                    self.get_logger().error(f"Can not get joint value of {component}")
                    return False
                fields = config.observation_info[component]["joint_state"]
                for field in fields.copy() - {"name"}:
                    js = self._get_joint_state(component, field)
                    if js is None or all(((v is None) or math.isnan(v)) for v in js):
                        self.get_logger().info(
                            f"{component} ({comp_type}) joint state field: {field} is not available ({js})."
                        )
                        fields.remove(field)
            return True
        return False

    def _rela_ctrl_wrapper(
        self, func, component: ComponentType, mode: SystemMode, cfg_kind: str
    ):
        """Wrap the control function to convert relative action to absolute action if needed.
        Args:
            func: the control function to be wrapped whose first argument is the action to be sent to the robot
            component: the robot component type (e.g., arm or eef)
            mode: the system mode (e.g., passive or sampling)
            cfg_kind: the control config kind (e.g., joint or pose)
        Returns:
            the wrapped control function
        """
        is_rela = self.config.action_refs[component][mode] is not ReferenceMode.ABSOLUTE
        if not is_rela:
            return func

        rela_ctrl = self._action_rela_abs[mode][component][cfg_kind]

        @wraps(func)
        def wrapper(*args, **kwargs):
            # print(f"{args[0]=}")
            return func(rela_ctrl.to_absolute(args[0]), *args[1:], **kwargs)

        return wrapper

    def _last_action_wrapper(self, func, component: ComponentType, cfg_kind: str):
        """Wrap the control function to save the last action for each component.
        Args:
            func: the control function to be wrapped whose first argument is the action to be sent to the robot
            component: the robot component type (e.g., arm or eef)
            cfg_kind: the control config kind (e.g., joint or pose)
        Returns:
            the wrapped control function
        """

        @wraps(func)
        def wrapper(*args, **kwargs):
            # print(
            #     f"Saving last action for component {component}, cfg_kind {cfg_kind}: {args[0]}"
            # )
            self._last_action[component][cfg_kind] = args[0]
            return func(*args, **kwargs)

        return wrapper

    @cache
    def _match_action_keys(
        self, mode: SystemMode, action_keys: Tuple[str]
    ) -> Dict[ComponentType, List[str]]:
        matched_keys = defaultdict(list)
        key_ends = {}
        for index, component in enumerate(self.config.components):
            # get the expected keys for each component
            act_cfg = self.config.action[index][mode]
            if isinstance(act_cfg, JointControlBasis):
                fields = ["position"]
                if isinstance(act_cfg, JointMIT):
                    fields.extend(["velocity", "effort", "kp", "kd"])
                key_ends[component] = [
                    f"{component}/joint_state/{field}" for field in fields
                ]
            elif isinstance(act_cfg, PoseControlBasis):
                key_ends[component] = [
                    f"{component}/pose/position",
                    f"{component}/pose/orientation",
                ]
            else:
                raise ValueError(f"Unsupported action type: {type(act_cfg)}")
        # print(f"Expected action key ends: {key_ends}")
        for component, key_ends in key_ends.items():
            for key_end in key_ends:
                # NOTE: eef pose should map to arm component
                replace = "eef" if "pose" in key_end else component
                for key in action_keys:
                    if key.replace(replace, component).endswith(key_end):
                        matched_keys[component].append(key)
                        break
        # print(f"Matched action keys: {matched_keys}")
        return dict(matched_keys)

    @staticmethod
    def action_data_to_list(action: DataStamped[np.ndarray]) -> List[float]:
        data = action["data"]
        if isinstance(data, list):
            return data
        return data.tolist()

    @staticmethod
    def action_to_list(action: np.ndarray) -> List[float]:
        return action.tolist()

    @staticmethod
    def action_forward(action: Any) -> Any:
        return action

    def send_action(
        self, action: Union[List[float], DictDataStamped[np.ndarray]]
    ) -> None:
        mode = self.current_mode
        self._update_refs_on_send(mode)
        component_func = self._mode2func[mode]
        if isinstance(action, dict):
            # tuple is hashable and can be cached
            act_keys = self._match_action_keys(mode, tuple(action.keys()))
            if not act_keys:
                self.get_logger().error(
                    f"No matching action keys from: {action.keys()}"
                )
                return
            for component, keys in act_keys.items():
                action_cfg = self.config.as_dict[component]["action"][mode]
                # flatten the action values
                if action_cfg.flatten:
                    target = []
                    for key in keys:
                        target.extend(self.action_post_process(action[key]))
                else:
                    target = [self.action_post_process(action[key]) for key in keys]
                    # TODO: is this always correct?
                    if len(target) == 1:
                        target = target[0]
                act_func = component_func[component]
                if action_cfg.unpack:
                    act_func(*target)
                else:
                    act_func(target)
        else:
            component_length = self._mode2length[self.current_mode]
            cnt = 0
            for component in self.config.components:
                length = component_length[component]
                act = action[cnt : cnt + length] if length > 0 else action[cnt]
                if act:  # error for numpy array
                    component_func[component](act)
                else:
                    break
                cnt += length or 1

    def _get_cur_refs(self) -> Dict[str, Dict[str, Any]]:
        refs = {}
        for component in self.config.components:
            interfaces = self.config.as_dict[component]["observation"].interfaces
            ref = {}
            if InterfaceType.POSE in interfaces:
                ref["pose"] = self._get_pose(component)
            if InterfaceType.JOINT_POSITION in interfaces:
                ref["joint_state"] = self._get_joint_state(component, "position")
            refs[component] = ref
        return refs

    def _update_refs_on_switch(self, mode: SystemMode):
        self.get_logger().info(f"Updating refs for mode {mode} for {self.config.port}")
        cur_refs = self._get_cur_refs()
        # print(cur_refs)
        act_rela_obs = self._action_rela_abs[mode]
        for component, configs in self.config.as_dict.items():
            # set ref for action
            action_cfg = configs["action"][mode]
            ref_mode = action_cfg.reference_mode
            if ref_mode is not ReferenceMode.ABSOLUTE:
                component_cur_ref = cur_refs[component]
                cfg_kind = get_control_cfg_kind(action_cfg)
                if ref_mode is ReferenceMode.INIT_STATE:
                    ref = component_cur_ref[cfg_kind]
                elif ref_mode is ReferenceMode.INIT_ACTION:
                    # NOTE: only one control type for each component in a mode
                    # so that the last_action is not a dict
                    # NOTE: now the same cfg_kind must be included in the observation interfaces when
                    #
                    ref = (
                        self._last_action[component].get(cfg_kind)
                        or component_cur_ref[cfg_kind]
                    )
                else:
                    raise NotImplementedError(
                        f"Unsupported action reference mode: {ref_mode}"
                    )
                act_rela_obs[component][cfg_kind].set_ref(ref)
            # set ref for observation
            obs_cfg = configs["observation"]
            component_cur_ref = cur_refs[component]
            for cfg_kind in component_cur_ref:
                ref_mode = obs_cfg.kind_ref[cfg_kind]
                if ref_mode is ReferenceMode.ABSOLUTE:
                    continue
                if ref_mode is ReferenceMode.INIT_STATE:
                    ref = component_cur_ref[cfg_kind]
                else:
                    # TODO: is other reference mode needed for observation?
                    raise NotImplementedError(
                        f"Unsupported observation reference mode: {ref_mode}"
                    )
                # print(
                #     f"Setting obs ref for component {component}, cfg_kind {cfg_kind}, ref_mode {ref_mode}: {ref}"
                # )
                self._obs_rela_abs[component][cfg_kind].set_ref(ref)

    def _update_refs_on_send(self, mode: SystemMode):
        act_rela_obs = self._action_rela_abs[mode]
        for component, config in self.config.as_dict.items():
            action_cfg = config["action"][mode]
            ref_mode = action_cfg.reference_mode
            if not ref_mode.is_step_mode():
                continue
            cfg_kind = get_control_cfg_kind(action_cfg)
            cur_refs = self._get_cur_refs()
            cur_ref = cur_refs[component][cfg_kind]
            if ref_mode is ReferenceMode.CURRENT_STATE:
                ref = cur_ref
            elif ref_mode is ReferenceMode.LAST_ACTION:
                ref = self._last_action[component].get(cfg_kind, cur_ref)
            else:  # this should not happen
                raise NotImplementedError(
                    f"Unsupported action reference mode: {ref_mode}"
                )
            act_rela_obs[component][cfg_kind].set_ref(ref)

    def on_switch_mode(self, mode: SystemMode) -> bool:
        # update the ref pose after each mode switch
        self._update_refs_on_switch(mode)
        if self.current_mode is not mode:
            # self.get_logger()(f"Switching to mode {mode} for {self.config.port}")
            robot_mode = self._mode_mapping[mode]
            if isinstance(robot_mode, RobotMode):
                robot_mode = {comp: robot_mode for comp in self.config.components}
            return self.interface.switch_mode(robot_mode["arm"])
        return True

    def _get_tf_key(self, component: str, frame: str) -> str:
        return f"{component}.{frame}"

    def _init_args(self):
        self._pose_fields = ("position", "orientation")
        self._post_capture = defaultdict(dict)
        limits: Dict[str, Dict[str, Dict[int, Tuple]]] = {
            "E2B": {"eef/joint_state/position": {0: (0, 0.0471)}},
            "G2": {
                "eef/joint_state/position": {0: (0, 0.0720)},
            },
            "play_pro": {
                "arm/joint_state/position": {0: (-2.74, 2.74)},
            },
            "play": {
                "arm/joint_state/position": {0: (-3.151, 2.080)},
            },
        }
        limits.update(
            {
                "PE2": limits["E2B"],
                "old_G2": limits["G2"],
                "play_lite": limits["play_pro"],
            }
        )
        self._default_limit = limits
        self._default_range = {
            "G2": {"eef/joint_state/position": {0: [0, 0.072]}},
            "play": {"arm/joint_state/position": {0: [-3.151, 2.080]}},
            "play_pro": {"arm/joint_state/position": {0: [-2.74, 2.74]}},
        }
        iden_rela_pose = ((0, 0, 0), (0, 0, 0, 1))
        x_pos = lambda x: (x, 0, 0)  # noqa: E731
        tf_dict = {
            "play": {
                "none": x_pos(0.0864995),
                "G2": x_pos(0.2466995),
                "old_G2": x_pos(0.2466995),
                "E2B": x_pos(0.1488995),
            },
        }
        tf_list = [("replay.PE2", "play.E2B", iden_rela_pose)]
        for arm_type, pos_rela in tf_dict.items():
            for eef_type, tf_part in pos_rela.items():
                tf_list.append(
                    (
                        self._get_tf_key(arm_type, eef_type),
                        self._get_tf_key(arm_type, "ref"),
                        tf_part,
                    )
                )
        self._tf_buffer = StaticTFBuffer(
            [(tgt, src, to_matrix(tf_part)) for tgt, src, tf_part in tf_list]
        )

        def _get_dict() -> Dict[str, Union[PoseGlobalRelaAbs, VectorRelaAbs]]:
            return {
                "pose": PoseGlobalRelaAbs(tolist=True),
                "joint_state": VectorRelaAbs(tolist=True),
            }

        # mode - component - pose/joint - PoseRelaAbs/VectorRelaAbs
        self._action_rela_abs = defaultdict(lambda: defaultdict(_get_dict))
        # component - pose/joint - PoseRelaAbs/VectorRelaAbs
        self._obs_rela_abs = defaultdict(_get_dict)

    def capture_observation(
        self, timeout: Optional[float] = None
    ) -> dict[str, dict[str, Union[float, Dict[str, List[float]]]]]:
        """key: component_name/data_type/field, e.g., arm/pose/position, value: {"t": timestamp in nanosecond, "data": data value}"""
        obs = {}
        config = self.config
        for component, info in config.observation_info.items():
            for kind, fields in info.items():
                self._update_kind_data(obs, component, kind, fields)
        return obs

    def _get_rela_obs(self, component: str, kind: str, data):
        ref_mode = self.config.as_dict[component]["observation"].kind_ref[kind]
        if ref_mode is ReferenceMode.INIT_STATE:
            data = self._obs_rela_abs[component][kind].to_relative(data)
        elif ref_mode is ReferenceMode.ABSOLUTE:
            data = None
        else:
            raise NotImplementedError(
                f"Unsupported observation reference mode: {ref_mode}"
            )
        return data

    def _update_kind_data(self, obs, component, kind, fields):
        start = perf_counter()
        key_prefix = f"{component}/{kind}"
        if kind == "joint_state":
            for field in fields:
                data = self._get_joint_state(component, field)
                obs[f"{key_prefix}/{field}"] = {"t": time_ns(), "data": data}
            key = f"{key_prefix}/position"
            rela_pos = self._get_rela_obs(component, "joint_state", obs[key]["data"])
            if rela_pos is not None:
                obs[key + "_rela"] = {"t": time_ns(), "data": rela_pos}
        elif kind == "pose":

            def update_pose(pose, suffix: str = ""):
                for field in fields:
                    obs[f"{key_prefix}/{field}{suffix}"] = {
                        "t": time_ns(),
                        "data": pose[{"position": 0, "orientation": 1}[field]],
                    }
                obs[f"{key_prefix}/rot6d{suffix}"] = {
                    "t": time_ns(),
                    "data": Rotation6D.quat_to_rot6d(pose[1]),
                }

            pose = self._get_pose(component)
            pose = self._post_capture.get(key_prefix, lambda *args: args)(*pose)
            rela_pose = self._get_rela_obs(component, kind, pose)
            if rela_pose is not None:
                update_pose(rela_pose, "_rela")
            update_pose(pose)
        else:
            raise ValueError(f"Unsupported observation kind: {kind}")
        self._metrics["durations"][f"capture/{key_prefix}"] = perf_counter() - start

    def _get_joint_state(self, component: str, field: str) -> List[float]:
        if component == "eef" and field == "velocity":
            return [0.0] * len(self._joint_names[component])
        if field == "name":
            return self._joint_names[component]
        else:
            data = getattr(
                self.interface, f"get_{component.replace('arm', 'joint')}_{field[:3]}"
            )()
            for index, process in self._post_capture.get(
                f"{component}/joint_state/{field}", {}
            ).items():
                # self.get_logger().info(
                #     f"Processing {component}/joint_state/{field} at index {index}: {data[index]}"
                # )
                data[index] = process(data[index])
                # self.get_logger().info(f"Post value: {data[index]}")
            return data

    def _get_pose(self, component: str) -> Tuple[List[float], List[float]]:
        return self.interface.get_end_pose()

    def shutdown(self) -> bool:
        return self.interface.disconnect()

    def get_info(self):
        return {
            key: list(value) if not isinstance(value, (str, bool)) else value
            for key, value in self.interface.get_product_info().items()
        } | {f"{comp}/joint_names": names for comp, names in self._joint_names.items()}

    def _get_default(
        self, arm_type: str, eef_type: str, default: dict
    ) -> Dict[str, dict]:
        return default.get(arm_type, {}) | default.get(eef_type, {})

    def set_post_capture(self, config, info):
        # the info is empty if no follower in the group
        # so we set it to self_info
        info = info or self.interface.get_product_info()
        arm_type = self._component_types["arm"]
        eef_type = self._component_types["eef"]
        default_limits = self._get_default(arm_type, eef_type, self._default_limit)
        default_range = self._get_default(arm_type, eef_type, self._default_range)
        default_transf = {}
        if config is None or config.transform is None or config.transform:
            default_transf["eef/pose"] = self._tf_buffer.lookup_transform(
                self._get_tf_key(info["product_type"], info["eef_types"][0]),
                self._get_tf_key(arm_type, eef_type),
            )
        if config is None:
            range_mapping = default_range
            transform = default_transf
        else:
            range_mapping = config.range_mapping
            transform = {
                key: pose2matrix(*value) if value is not None else default_transf[key]
                for key, value in config.transform.items()
            }
        for key, value in range_mapping.items():
            limit = self.config.limit.get(key, {})
            default_limit = default_limits.get(key, {})
            default_limit.update(limit)
            try:
                for index, target_range in value.items():
                    self._post_capture[key][int(index)] = partial(
                        linear_map,
                        raw_range=default_limit[index],
                        target_range=target_range,
                    )
                    # self.get_logger().info(
                    #     f"Post capture config set: {target_range=}"
                    # )
            except Exception as e:
                raise RuntimeError(
                    f"Failed to set post capture for {key} with "
                    f"{default_limits=}, {arm_type=}, {eef_type=}"
                ) from e
        for key, value in transform.items():
            # print(f"tf_matrix={value}")
            self._post_capture[key] = (
                array_pose_to_list_wrapper(apply_tf_to_pose, tf_matrix=value)
                if not is_identity_matrix(value)
                else lambda *args: args
            )
        # self.get_logger().info(f"Post capture config set: {self._post_capture}")
