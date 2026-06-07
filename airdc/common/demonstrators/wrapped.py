from airdc.common.demonstrators.basis import Demonstrator
from pydantic import BaseModel, ConfigDict
from typing import List
from airdc.demonstrate.configs import DemonstrateAction
from airdc.common.wrappers.basis import (
    EnvironmentBasis,
    ForwardingWrapper,
    TakeOverEnvWrapper,
    WrapperBasis,
)
from airdc.common.callers.basis import CallerBasis


class WrappedDemonstratorConfig(BaseModel):
    """Configuration for WrappedDemonstrator"""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    environment: EnvironmentBasis
    caller: CallerBasis
    wrappers: List[WrapperBasis] = []


class WrappedDemonstrator(Demonstrator):
    """Wrapped Demonstrator"""

    config: WrappedDemonstratorConfig

    def on_configure(self):
        if self.config.caller.configure():
            if self.config.environment.configure():
                self.config.environment.reset()
                if self._init_wrapped():
                    self._last_action = None
                    return True
            self.get_logger().error("Failed to configure the environment")
        else:
            self.get_logger().error("Failed to configure the caller")
        return False

    def _init_wrapped(self):
        env = self.config.environment
        wrappers = self.config.wrappers
        caller = self.config.caller
        # wrap, warm up and reset all the wrappers once
        # using the initial observation from the environment
        init_input = env.output().observation
        # wrap by a forwarding wrapper to make a complete output chain
        wrapped = (
            ForwardingWrapper().wrap(caller)
            if not isinstance(wrappers[0], ForwardingWrapper)
            else caller
        )
        for i, wrapper in enumerate(wrappers):
            if not wrapper.configure():
                self.get_logger().error(f"Failed to configure wrapper: {wrapper}")
                return False
            wrapped = wrapper.wrap(wrapped)
            wrapped.warm_up(init_input)
            # reset all the wrapped wrappers since the topper
            # wrapper will call it when warming up
            for wp in wrappers[: i + 1]:
                wp.reset()
            WrapperBasis.output_chain = []
        # check that only the topmost wrapper can take over the environment
        # and reset all the other wrappers since they have been called
        # once during warming up the topmost wrapper
        for wrapper in wrappers[1:]:
            if wrapper.should_take_over_env:
                raise RuntimeError(
                    "Only the topmost wrapper can take over the environment"
                )

        # take over the environment
        if not wrapped.should_take_over_env:
            wrapped.get_logger().info("Do not take over the environment")
            wrapped = TakeOverEnvWrapper().wrap(wrapped)
            # wrapped.warm_up()  # actually no need to warm up
            # WrapperBasis.output_chain = []
        wrapped.get_logger().info("Taking over the environment")
        wrapped.take_over_env(env)
        self._wrapped = wrapped
        return True

    def react(self, action):
        if action is DemonstrateAction.sample:
            self.config.caller.reset()
            for wrapper in self.config.wrappers:
                wrapper.reset()
        self._last_action = action
        return True

    def capture_observation(self, timeout=None):
        if self._last_action is DemonstrateAction.sample:
            env_output = self._wrapped()
            obs = env_output.observation | {"/action": self._wrapped.output_chain[-1]}
            WrapperBasis.clear_output_chain()
            return obs
        else:
            env_output = self.config.environment.output()
            return env_output.observation

    def on_switch_mode(self, mode):
        raise NotImplementedError("Mode switching is not implemented yet.")

    def send_action(self, action):
        raise NotImplementedError("Sending action is not implemented yet.")

    def shutdown(self):
        for wrapper in reversed(self.config.wrappers):
            if not wrapper.shutdown():
                self.get_logger().error(f"Failed to shutdown wrapper: {wrapper}")
                return False
        return True

    def get_info(self):
        return {}

    @property
    def handler(self):
        return None


if __name__ == "__main__":
    from cfgable.hydra_utils import (
        init_hydra_config,
        hydra_instance_from_dict,
    )
    from omegaconf import OmegaConf
    from airdc.utils import init_logging
    from airdc.common.systems.basis import SystemMode
    from pprint import pprint

    init_logging()

    config_dict = init_hydra_config("defaults/config_infer.yaml")
    config_dict = OmegaConf.to_container(
        config_dict, resolve=True, throw_on_missing=True
    )
    print(config_dict.keys())
    demon: WrappedDemonstrator = hydra_instance_from_dict(config_dict)
