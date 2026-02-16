from pydantic import BaseModel, NonNegativeFloat, ConfigDict, model_validator, Field
from typing import List, Union, Optional, Any, Dict, Literal, Set
from collections.abc import Callable
from typing_extensions import Self
from airdc.basis import (
    StrEnum,
    auto,
    PostCaptureConfig,
    ConcurrentMode,
    ForceSetAttr,
    force_set_attr,
    Bcolors,
    DictDataStamped,
)
from airdc.common.systems.basis import Sensor, System, SystemMode
from airdc.common.utils.progress import Waitable
from airdc.common.configs.component import (
    ComponentConfig,
    ComponentsConfig,
    T,
)
from airdc.utils import zip, init_logging
from airdc.common.systems.wrappers import (
    ConcurrentWrapperConfig,
    SensorConcurrentWrapper,
)
from airdc.common.utils.progress import create_handler
from mcap_data_loader.utils.dict import defaultdict_to_dict
from airdc.utils import ensure_equal_length
from logging import getLogger
from collections import defaultdict, Counter
from functools import cached_property, cache
import time


Component = Union[System, Sensor]


class ComponentRole(StrEnum):
    """The role of the component in the group."""

    l = auto()  #  # noqa: E741
    """the leader of the group"""
    f = auto()  #  # noqa: E741
    """the follower of the group"""
    o = auto()
    """
    the other components in the group
    e.g. the sensors such as cameras,
    imus, tactiles, etc.
    """


class ComponentGroupsConfig(ComponentsConfig[T], frozen=True):
    """Configuration for multiple components in groups."""

    groups: List[str] = []
    """the group name of each component"""
    roles: List[ComponentRole] = []
    """the role of each component in the group"""
    ignore_roles: Set[ComponentRole] = set()
    """
    the components with these roles will be ignored,
    which can be used to reuse the demonstration
    configuration when not demonstrating by ignoring
    some roles, e.g. ignoring the followers
    """

    @model_validator(mode="after")
    def validate_final(self):
        group_num = len(self.groups)
        if len(self.names) != group_num:
            raise ValueError("groups and names must have the same length")
        if len(self.roles) != group_num:
            raise ValueError("roles must have the same length as names")
        group_role_cnt = defaultdict(Counter)
        for index, group_name in enumerate(self.groups):
            group_role_cnt[group_name][self.roles[index]] += 1
        for group_name, role_counter in group_role_cnt.items():
            leader_cnt = role_counter[ComponentRole.l]
            follower_cnt = role_counter[ComponentRole.f]
            if leader_cnt == 0 and follower_cnt != 0:
                raise ValueError(
                    f"Group {group_name} must have at least one leader if it has followers"
                )
        # remove the components with ignored roles
        index = 0
        for role in self.roles.copy():
            if role in self.ignore_roles:
                fields = self.__class__.model_fields.copy()
                fields.pop("ignore_roles")
                for field in fields:
                    getattr(self, field).pop(index)
            else:
                index += 1
        return self

    def deep_copy_with_ignoring(self, roles: Set[ComponentRole]):
        """Create a copy of the configuration with the specified roles ignored."""
        # there may be a bug with pydantic that set `exclude_unset=True` still includes the
        # computed cached properties in the dumped dict, so we manually include the set fields
        cp_model = self.model_copy(deep=True)
        cp_model_dict = cp_model.model_dump(
            include=self.model_fields_set, exclude_unset=True
        )
        cp_model_dict["ignore_roles"] = roles
        new_model = self.__class__(**cp_model_dict)
        return new_model

    def group_has_role(self, group: str, role: ComponentRole) -> bool:
        """Check if a group has the specified role."""
        return role in self.grouped_instance[group]

    @model_validator(mode="after")
    def check_unique_names(self):
        # TODO: should check if the names are unique across all groups or
        # only within the same group at only within the same group and the
        # same role?
        # group_names_cnt = defaultdict(Counter)
        # for index, group_name in enumerate(self.groups):
        #     group_names_cnt[group_name][self.names[index]] += 1
        # for group_name, counter in group_names_cnt.items():
        #     if counter.most_common(1)[0][1] > 1:
        #         raise ValueError(
        #             f"The names within the same group {group_name} must be unique"
        #         )
        names_cnt = Counter(self.unique_keys)
        not_unique = {name for name in names_cnt if names_cnt[name] > 1}
        if not_unique:
            raise ValueError(
                f"The names within the same group must be unique, but {not_unique} appeared many times"
            )
        return self

    @property
    def instance_dict(self) -> Dict[str, T]:
        """Returns a dictionary of component instances."""
        return dict(zip(self.unique_keys, self.instances))

    @cached_property
    def unique_keys(self) -> List[str]:
        """Get the unique keys composed by group names and component names"""
        # TODO: should remove prefix
        return [
            f"{group_name}/{name}" for group_name, name in zip(self.groups, self.names)
        ]

    @cached_property
    def unique_groups(self) -> List[str]:
        groups = []
        for group in self.groups:
            if group not in groups:
                groups.append(group)
        return groups

    @cached_property
    def grouped_config(
        self,
    ) -> Dict[str, Dict[ComponentRole, List[ComponentConfig[T]]]]:
        """Get the grouped component configurations."""
        grouped_configs = defaultdict(lambda: defaultdict(list))
        for index, group_name in enumerate(self.groups):
            config = ComponentConfig[T](
                name=self.names[index],
                instance=self.instances[index],
                concurrent=self.concurrents[index],
                update_rate=self.update_rates[index],
            )
            grouped_configs[group_name][self.roles[index]].append(config)
        return defaultdict_to_dict(grouped_configs)

    @cached_property
    def grouped_instance(self) -> Dict[str, Dict[ComponentRole, List[T]]]:
        """Get the grouped component instances."""
        grouped_instances = defaultdict(lambda: defaultdict(list))
        for index, group_name in enumerate(self.groups):
            grouped_instances[group_name][self.roles[index]].append(
                self.instances[index]
            )
        return defaultdict_to_dict(grouped_instances)

    @cached_property
    def grouped_name(self) -> Dict[str, Dict[ComponentRole, List[str]]]:
        """Get the grouped component names."""
        grouped_names = defaultdict(lambda: defaultdict(list))
        for index, group_name in enumerate(self.groups):
            grouped_names[group_name][self.roles[index]].append(self.names[index])
        return defaultdict_to_dict(grouped_names)


class SystemSensorComponentGroupsConfig(ComponentGroupsConfig[Component]):
    """Configuration for multiple systems and sensors in groups."""


class AutoControlConfig(BaseModel, frozen=True):
    """Configuration for auto control of the followers based on the leaders."""

    model_config = ConfigDict(extra="forbid")

    groups: Optional[List[str]] = None
    """
    the group names where the leader states
    are used to control the follower states
    None means all group names are used
    if empty, the control should be implicitly implemented when
    switching to the active / passive mode
    """
    rates: List[NonNegativeFloat] = []
    """
    the rate of the auto control loop for each group
    0 means as fast as possible
    """
    modes: List[ConcurrentMode] = []
    """
    the mode of the auto control loop for each group
    can not be none
    """

    def refresh(self, groups: List[str]):
        for group in set(self.groups) - set(groups):
            index = self.groups.index(group)
            self.groups.pop(index)
            self.rates.pop(index)
            self.modes.pop(index)

    @force_set_attr
    def model_post_init(self, context):
        # check when groups are not empty
        if self.groups or self.groups is None:
            if self.groups:
                if len(set(self.groups)) != len(self.groups):
                    raise ValueError("groups must be unique")
                self.rates = ensure_equal_length(self.groups, self.rates)
                self.modes = ensure_equal_length(self.groups, self.modes)
            else:
                if not self.modes:
                    raise ValueError("modes must be set if groups is not empty")
                if not self.rates:
                    raise ValueError("rates must be set if groups is not empty")


class GroupsSendActionConfig(BaseModel, frozen=True):
    """Which action value and mode to perform for each group
    when the action is called. The action values and mode will be sent
    to the leaders only unless `to_follower` is set to True.
    """

    model_config = ConfigDict(extra="forbid")

    groups: List[str] = []
    """the group names to send the action to"""
    action_values: List[Any] = []
    """the action values to send to each group"""
    modes: List[SystemMode] = []
    """the modes to switch to for each group"""
    to_follower: List[bool] = []
    """whether to send the action to the followers instead of leaders"""

    @force_set_attr
    def model_post_init(self, context):
        length = len(self.groups)
        if not length:
            # The upper class is allowed to modify groups after initialization,
            # so no post-processing is performed here. The upper class should
            # explicitly call this post-processing method after the modification
            # is completed.
            return
        if len(set(self.groups)) != length:
            raise ValueError("groups must be unique")
        if len(self.action_values) == 1:
            self.action_values *= length
        if length != len(self.action_values):
            raise ValueError("groups and action_values must have the same length")
        if len(self.modes) == 0 and length > 0:
            getLogger(self.__class__.__name__).warning(
                "No modes found in the action, set to `RESETTING`"
            )
            self.modes = [SystemMode.RESETTING] * length
        elif len(self.modes) == 1:
            self.modes *= length
        if length != len(self.modes):
            raise ValueError("groups and modes must have the same length")
        if len(self.to_follower) == 1:
            self.to_follower *= length
        elif not self.to_follower:
            self.to_follower = [False] * length
        if length != len(self.to_follower):
            raise ValueError("groups and to_follower must have the same length")


class GroupedComponentsSystemConfig(BaseModel, frozen=True):
    model_config = ConfigDict(validate_assignment=True, extra="forbid")

    # NOTE: need to use a predefined class here to avoid
    # pickling issues with dynamically created generic types
    components: SystemSensorComponentGroupsConfig
    """the components in groups"""
    auto_control: AutoControlConfig = Field(
        default_factory=AutoControlConfig, validate_default=True
    )
    """the auto control configuration"""
    post_capture: Optional[Dict[str, Optional[PostCaptureConfig]]] = Field(
        None, validate_default=True
    )
    """the post capture config (value) for the leader of each group (key);
    if None, all group that has leaders will be set to a None post capture
    which means auto processing in the leaders."""

    @model_validator(mode="after")
    def validate_auto_control(self):
        with ForceSetAttr(self.auto_control) as v:
            components = self.components
            if v.groups is None:
                v.groups = components.unique_groups
            if {ComponentRole.l, ComponentRole.f} - set(components.roles):
                if v.groups:
                    getLogger(self.__class__.__name__).warning(
                        "No leader and follower role found in the components, "
                        "clear auto_control.groups."
                    )
                    v.groups = []
            auto_groups = v.groups
            if auto_groups:
                v.rates = ensure_equal_length(auto_groups, v.rates)
                v.modes = ensure_equal_length(auto_groups, v.modes)
        return self

    @model_validator(mode="after")
    @force_set_attr
    def validate_post_capture(self) -> Dict[str, PostCaptureConfig]:
        if self.post_capture is None:
            components = self.components
            self.post_capture = {
                group: None
                for group in components.unique_groups
                if components.group_has_role(group, ComponentRole.l)
            }
        return self


class ComponentGroupManager:
    def __init__(self, config: GroupedComponentsSystemConfig):
        self.components: ComponentGroupsConfig[Component] = config.components
        self._config = config
        self._role_mode_set = {}
        self._configured = False
        self._config_ori = self._config.model_copy(deep=True)

    @classmethod
    def get_logger(cls):
        return getLogger(cls.__name__)

    def configure_groups(self) -> bool:
        for group_name, role_configs in self.components.grouped_config.items():
            for role, configs in role_configs.items():
                for config in configs:
                    if not config.instance.configure():
                        self.get_logger().error(
                            f"Failed to configure {config.name} of role: {role} in group {group_name}"
                        )
                        return False
        for group_name, post_capture in self._config.post_capture.items():
            self.get_logger().info(
                f"Setting post capture for group {group_name}: {post_capture}"
            )
            leader = None
            grouped = self.components.grouped_instance[group_name]
            for leader in grouped[ComponentRole.l]:
                followers = grouped.get(ComponentRole.f)
                # TODO: should pass all the followers' info to the leader?
                leader.set_post_capture(
                    post_capture, followers[0].get_info() if followers else {}
                )
            if leader is None:
                self.get_logger().warning(
                    f"Group: {group_name} has no leader, post capture will not be set"
                )
        self._configured = True
        return True

    def auto_control_once(self, period: float = 0) -> float:
        """Control the followers to follow the leader."""
        start = time.perf_counter()
        for group_name in self._config.auto_control.groups:
            role_instances = self.components.grouped_instance[group_name]
            # merge leader observations
            leader_obs = {}
            for leader in role_instances.get(ComponentRole.l, []):
                # TODO: add and use capture_as_action to just capture needed obs?
                leader_obs.update(leader.capture_observation(1.0))
            # self.get_logger().info(f"{leader_obs}")
            if leader_obs:
                for follower in role_instances.get(ComponentRole.f, []):
                    # self.get_logger().info(f"Sending leader observations {leader_obs} to follower")
                    follower.send_action(leader_obs)
        sleep_time = period - (time.perf_counter() - start)
        if sleep_time > 0:
            time.sleep(sleep_time)
        # elif sleep_time < 0 and period:
        #     self.get_logger().warning(
        #         f"Auto control took too long: exceed {-sleep_time} s."
        #     )
        return sleep_time

    def auto_control_loop(self, waitable: Waitable):
        """Control the followers to follow the leader in a loop."""
        period = 1 / self._config.auto_control.rates[0]
        if not waitable.is_same_process():
            init_logging()
            waitable.set_process_title(waitable.current_process().name)
        logger = self.get_logger()
        configure_here = False
        if not self.is_configured:
            logger.info(Bcolors.cyan("Configuring groups"))
            if not self.configure_groups():
                raise RuntimeError("Failed to configure groups")
            configure_here = True
        # make sure followers are in sampling mode, at least the
        # internal flag is
        self.set_role_mode(ComponentRole.f, SystemMode.SAMPLING)
        logger.info(Bcolors.green("Auto control loop started"))
        # TODO: add ready event feedback
        with waitable:
            while waitable.wait():
                # logger.info("Running auto control loop")
                self.auto_control_once(period)
        if configure_here:
            self.get_logger().info(Bcolors.cyan("Shutting down all components"))
            self.shutdown()
        logger.info(Bcolors.blue("Auto control loop stopped"))

    def control_group_role(
        self, group_name: str, role: ComponentRole, mode: SystemMode, action_value: Any
    ) -> List[Component]:
        instances = self.components.grouped_instance.get(group_name, {}).get(role)
        if instances is None:
            self.get_logger().warning(f"No group {group_name} or group role {role}")
            return True
        for instance in instances:
            if instance.current_mode is mode or instance.switch_mode(mode):
                instance.send_action(action_value)
            else:
                self.get_logger().error(
                    f"Failed to switch leader mode for {group_name} to {mode}"
                )
                return False
        return True

    def send_grouped_action(self, action: GroupsSendActionConfig) -> bool:
        """Control the leaders or followers after some demonstrate action"""
        # self.get_logger().info(Bcolors.cyan(f"Sending action: {action}"))
        for group_name, action_value, mode, to_follower in zip(
            action.groups, action.action_values, action.modes, action.to_follower
        ):
            if not self.control_group_role(
                group_name, ComponentRole.l, mode, action_value
            ):
                return False
        return True

    def set_role_mode(self, role: ComponentRole, mode: Optional[SystemMode]) -> bool:
        """Set the mode of all the components of a role."""
        if mode is None:
            if self._role_mode_set[role] is SystemMode.PASSIVE:
                mode = SystemMode.RESETTING
            else:
                mode = SystemMode.PASSIVE
        self.get_logger().info(f"Setting {role} mode to {mode}")
        for group_name, role_configs in self.components.grouped_config.items():
            for config in role_configs.get(role, []):
                if not config.instance.switch_mode(mode):
                    self.get_logger().error(
                        f"Failed to set {group_name} {role} {config.name} to {mode} mode"
                    )
                    return False
        self._role_mode_set[role] = mode
        return True

    def new_for_auto_control(self) -> Self:
        # create a new instance of the class to remove
        # all references to the original instance
        config_auto_c = self._config_ori.model_copy(
            deep=True,
            update={
                "components": self._config_ori.components.deep_copy_with_ignoring(
                    {ComponentRole.o}
                )
            },
        )
        config_auto_c.auto_control.refresh(config_auto_c.components.groups)
        return self.__class__(config_auto_c)

    def shutdown(self) -> bool:
        for group_name, role_instances in self.components.grouped_instance.items():
            for role, instances in role_instances.items():
                for instance in instances:
                    instance.shutdown()
        return True

    @property
    def is_configured(self) -> bool:
        return self._configured


class GroupedComponentsSystem(System):
    config: GroupedComponentsSystemConfig

    def on_configure(self):
        # TODO: use multi modes handlers for different groups
        modes = self.config.auto_control.modes or [ConcurrentMode.none]
        self._handler = create_handler(modes[0])
        self._handler.register_callback("start", self._start_following)
        self._handler.register_callback(
            "stop", lambda: self.get_logger().info("Stopping following")
        )
        return self._init_all_components()

    def _init_all_components(self) -> bool:
        self._cg_manager = ComponentGroupManager(self.config)
        if self._cg_manager.configure_groups():
            # NOTE: concur is the first key to ensure concurrent components are processed first
            self._comp_tupe_dict = {"concur": [], "normal": []}
            for (
                group_name,
                role_configs,
            ) in self._cg_manager.components.grouped_config.items():
                for role, configs in role_configs.items():
                    for config in configs:
                        component = config.instance
                        comp_name = config.name
                        key = (
                            "concur"
                            if isinstance(component, SensorConcurrentWrapper)
                            else "normal"
                        )
                        self._comp_tupe_dict[key].append(
                            (group_name, component, comp_name)
                        )
            return True
        return False

    def _send_flattened_dict_action(self, action: Dict) -> bool:
        pass

    def _send_flattened_array_action(self, action) -> bool:
        pass

    def send_action(self, action: Union[GroupsSendActionConfig, Dict]) -> bool:
        if action is None:
            return True
        if isinstance(action, GroupsSendActionConfig):
            return self._cg_manager.send_grouped_action(action)
        elif isinstance(action, dict):
            # TODO
            raise NotImplementedError("Sending action as dict is not implemented yet")
        else:
            action = action[:]
            # TODO: need to implement sending flattened array action
            raise NotImplementedError(
                "Sending action as flattened array is not implemented yet"
            )

    def _start_following(self) -> bool:
        """Start to follow."""
        self.get_logger().info(Bcolors.cyan("Starting to follow"))
        # set the followers to resetting mode to move smoothly
        if self._cg_manager.set_role_mode(ComponentRole.f, SystemMode.RESETTING):
            # TODO: control until the joint positions are near the leader
            self.get_logger().info(
                Bcolors.cyan("Auto controlling once to move followers")
            )
            self._cg_manager.auto_control_once()
            return self._cg_manager.set_role_mode(ComponentRole.f, SystemMode.SAMPLING)
        self.get_logger().error("Failed to start following")
        return False

    def capture_observation(self, timeout: Optional[float] = None) -> DictDataStamped:
        # TODO: can be called when sampling?
        data = {}

        def add_data(
            group_name: str,
            component: Component,
            component_name: str,
            mode: Literal["capture", "result"] = "capture",
            wait: bool = True,
        ):
            start = time.perf_counter()
            prefix = self._get_component_data_prefix(group_name, component_name)
            if mode == "capture":
                func = component.capture_observation
                if not wait:  # just trigger capture
                    return func(0.0)
            else:
                func = component.result
            # TODO: configure the timeout
            for key, value in func(5.0).items():
                data[self._get_component_data_key(prefix, key)] = value
            # TODO: what about the concurrent wrapper metrics?
            for mtype, value in component.metrics.items():
                for key, v in value.items():
                    self._metrics[mtype][f"{prefix}/{key}"] = v
            self._metrics["durations"][f"capture/{prefix}"] = (
                time.perf_counter() - start
            )

        self._fully_process(add_data)
        return data

    def get_info(self):
        info = {}

        def add_info(group_name: str, component: Component, component_name: str, *args):
            prefix = self._get_component_data_prefix(group_name, component_name)
            info[self._get_component_data_key(prefix, "")] = component.get_info()

        self._fully_process(add_info)

        return info

    def _fully_process(self, func: Callable[[str, Component, str, str, bool], None]):
        wait = {"concur": False, "normal": True}
        for key, comps in self._comp_tupe_dict.items():
            for group, component, comp_name in comps:
                func(group, component, comp_name, "capture", wait[key])
        for group, component, comp_name in self._comp_tupe_dict["concur"]:
            func(group, component, comp_name, "result", True)

    @cache
    def _get_component_data_prefix(self, group_name: str, component_name: str) -> str:
        if component_name:
            return f"{group_name}/{component_name}"
        return f"{group_name}"

    @cache
    def _standardize_component_data_key(self, key: str) -> str:
        return ("/" + key).removeprefix("//").removesuffix("/")

    @cache
    def _get_component_data_key(self, prefix: str, key: str) -> str:
        # TODO: should allow component_name to be empty or the group name to be / ?
        return self._standardize_component_data_key(f"{prefix}/{key}")

    def on_switch_mode(self, mode):
        if mode is SystemMode.PASSIVE:
            f_mode = SystemMode.SAMPLING
            self.get_logger().info(f"Switching all followers to {f_mode} mode")
            if not self._cg_manager.set_role_mode(ComponentRole.f, f_mode):
                self.get_logger().error("Failed to switch")
                return False
        self.get_logger().info(f"Switching all leaders to {mode} mode")
        return self._cg_manager.set_role_mode(ComponentRole.l, mode)

    def shutdown(self) -> bool:
        if self.handler.exit():
            return self._cg_manager.shutdown()
        return False

    def start_auto_control(self):
        if not self.use_auto_control:
            return True
        mode = self.config.auto_control.modes[0]
        if mode is ConcurrentMode.process:
            self.get_logger().info("Copying the manager")
            manager = self._cg_manager.new_for_auto_control()
        else:
            manager = self._cg_manager
        if self._handler.launch(
            target=manager.auto_control_loop,
            name="auto_control_loop",
            daemon=False,
            args=(self._handler.get_waitable(),),
        ):
            if self._handler.start():
                return True
        return False

    @property
    def handler(self):
        return self._handler

    @property
    def use_auto_control(self) -> bool:
        return bool(self.config.auto_control.groups)
