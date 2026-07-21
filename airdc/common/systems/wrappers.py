from multiprocessing.managers import SharedMemoryManager
from multiprocessing import get_context, current_process
from multiprocessing.connection import Connection
from pydantic import BaseModel, ConfigDict, ImportString, validate_call
from typing import Union, Dict, Type, Optional
from airdc.common.systems.basis import Sensor, System
from airdc.basis import ConcurrentMode
from airdc.common.utils.event_rpc import (
    EventRpcManager,
    EventRpcServer,
)
from airdc.utils import init_logging
from airdc.common.utils.shareable_numpy import ShareableNumpy
from airdc.common.utils.shareable_value import ShareableValue
from numpy import uint64
from setproctitle import setproctitle

InterfaceType = Union[Sensor, System]


class ConcurrentWrapperConfig(BaseModel):
    """The config for the concurrent wrapper."""

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    interface: InterfaceType
    """the interface instance to be wrapped"""
    concurrent: ConcurrentMode = ConcurrentMode.process
    """the concurrent mode"""


class SensorConcurrentWrapper(Sensor):
    """A wrapper for sensors to run in a separate thread or process."""

    def __init__(self, config: ConcurrentWrapperConfig):
        self._concurrent = config.concurrent
        self._interface = config.interface

    # def __call__(self, interface: InterfaceType):
    #     self._interface = interface
    #     return self

    def on_configure(self) -> bool:
        # TODO: use protocol instead of inheriting Sensor?
        if self._concurrent is not ConcurrentMode.process:
            raise NotImplementedError(
                "Only process mode is supported for SensorConcurrentWrapper."
            )
        self._rpc = EventRpcManager(EventRpcManager.get_args(self._concurrent))
        spawn_ctx = get_context("spawn")
        parent, child = spawn_ctx.Pipe()
        self._smm = SharedMemoryManager(ctx=spawn_ctx)
        self._smm.start()
        self._concurrent = EventRpcManager.get_concurrent_cls(self._concurrent)(
            target=self._concurrent_loop,
            args=(self._interface, child, self._rpc.server),
            name=f"{self.__class__.__name__}Concurrent",
        )
        self._concurrent.start()
        if parent.poll(5.0):
            if parent.recv():
                self.get_logger().info("Receiving info and first observation...")
                if parent.poll(5.0):
                    self._info, obs = parent.recv()
                    self._obs: Dict[
                        str, Dict[str, Union[ShareableNumpy, ShareableValue]]
                    ] = {}
                    obs: dict
                    for key, value in obs.items():
                        self._obs[key] = {
                            "t": ShareableValue.from_value(
                                value["t"], uint64, smm=self._smm
                            ),
                            "data": ShareableNumpy.from_array(
                                value["data"], smm=self._smm
                            ),
                        }
                    self.get_logger().info("Sending shm observation...")
                    parent.send(self._obs)
                    parent.close()
                    return True
            else:
                self.get_logger().error("Failed to configure the interface.")
        else:
            self.get_logger().error("Timeout waiting for configure response.")
        return False

    @staticmethod
    def _concurrent_loop(
        interface: Sensor, conn: Connection, rpc_server: EventRpcServer
    ):
        init_logging()
        logger = interface.get_logger()
        logger.info("Configuring the interface...")
        setproctitle(f"{current_process().name}:{logger.name}")
        conn.send(interface.configure())
        conn.send((interface.get_info(), interface.capture_observation(5.0)))
        if not conn.poll(5.0):
            logger.error("Timeout waiting for shm observation.")
            return
        shm_obs = conn.recv()
        conn.close()
        while rpc_server.wait():
            for key, value in interface.capture_observation(5.0).items():
                shm_obs[key]["t"].value = value["t"]
                shm_obs[key]["data"][:] = value["data"]
            rpc_server.respond()
        logger.info("Shutting down the interface...")
        interface.shutdown()

    def _get_obs(self):
        return {
            key: {"t": value["t"].value, "data": value["data"].array}
            for key, value in self._obs.items()
        }

    def capture_observation(self, timeout: Optional[float] = None):
        if self._rpc.client.request(timeout=timeout):
            if timeout is not None and timeout <= 0:
                return None
            return self._get_obs()
        raise TimeoutError("Timeout waiting for observation.")

    def result(self, timeout: Optional[float] = None):
        if timeout is None or timeout > 0:
            if self._rpc.client.wait(timeout=timeout):
                return self._get_obs()
            raise TimeoutError("Timeout waiting for observation.")
        raise ValueError("Timeout must be None or positive.")

    def get_info(self):
        return self._info

    def shutdown(self):
        self._rpc.shutdown()
        self._concurrent.join(timeout=5.0)
        # SharedMemoryManager.shutdown() only exists after start() is called
        # It's dynamically added as a Finalize object during start()
        # Since self._smm.start() is always called in on_configure(), we can safely call shutdown()
        self._smm.shutdown()
        if self._concurrent.is_alive():
            self.get_logger().warning("Concurrent process did not terminate in time.")
        return True


@validate_call(config=ConfigDict(arbitrary_types_allowed=True))
def concurrent_wrapper(
    interface_cls: Union[Type[InterfaceType], ImportString[Type[InterfaceType]]],
    config_cls: Optional[Type[BaseModel]] = None,
):
    config_cls = config_cls or interface_cls.resolve_config_type(interface_cls)
    field_name = "concurrent_wrapped"
    if config_cls is None:
        ConfigWithConcurrent = ConcurrentWrapperConfig
    else:
        if field_name not in config_cls.model_fields:

            class ConfigWithConcurrent(config_cls):
                concurrent_wrapped: ConcurrentMode = ConcurrentMode.process
                """the wrapped concurrent mode"""
        else:
            # TODO: use logging instead of raising error?
            raise ValueError(
                f"The config class {config_cls.__name__} already has a field named '{field_name}'."
            )
            ConfigWithConcurrent = config_cls

    class ConcurrentWrappedClass(SensorConcurrentWrapper):
        """A concurrent wrapper class for the given interface class."""

        def __init__(self, config: ConfigWithConcurrent):
            self._concurrent = config.concurrent_wrapped
            """
            Interface configurations may include a `concurrent` parameter, typically used in conjunction with a `blocking` parameter to implement asynchronous, non-blocking reads. The former is a necessary condition for non-blocking, but asynchronous does not equal non-blocking. Blocking essentially ensures that data timestamps are not duplicated, while asynchronous operation determines how timestamps are updated. Even in asynchronous mode, blocking can still occur if the data timestamp has not been updated.

            When using asynchronous mode directly with an interface, using a child process is reasonable to maximize asynchronous loop speed and avoid interference from other threads in the current process. However, when combined with a wrapper, if the wrapper itself is an independent process, the child process mode within the interface becomes unnecessary. Even so, forced exceptions should not be added here, as there may be other thread contention or other considerations within the interface. At most, a warning message might be issued. Similarly, other combinations of inner and outer threads may also have certain considerations. For example, if both the wrapper and the inner thread are threads, it seems somewhat redundant, but if the interface involves I/O-intensive operations, the inner thread is sometimes necessary.

            In summary, adding additional checks and logs is not currently being considered.
            """
            # TODO:
            # inner_con = self.__get_inner_con(config)
            # if inner_con is self._concurrent:
            #     self.get_logger().warning(
            #         f"The inner concurrent {inner_con} is ignored in favor of the wrapped one {self._concurrent}."
            #     )
            # elif (
            #     self._concurrent is ConcurrentMode.thread
            #     and inner_con is ConcurrentMode.process
            # ):
            #     self.get_logger().warning(
            #         f"The inner concurrent {inner_con} is more powerful than the wrapped one {self._concurrent}."
            #     )
            # NOTE: use the original config to avoid errors caused by local
            # classes defined inside functions being unable to be pickled
            config_cls_dict = dict(config)
            config_cls_dict.pop(field_name)
            self._interface = interface_cls(config_cls(**config_cls_dict))

        # @classmethod
        # def __get_inner_con(cls, config):
        #     return getattr(config, "concurrent", None)

        # def __new__(cls, config: ConfigWithConcurrent):
        #     if config.concurrent_wrapped is ConcurrentMode.thread:
        #         with ForceSetAttr(config):
        #             if cls.__get_inner_con(config) is not None:
        #                 cls.get_logger().warning(f"Use the inner concurrent ")
        #                 config.concurrent = ConcurrentMode.thread
        #                 return interface_cls(config)
        #     return super().__new__(cls, config)

    return ConcurrentWrappedClass, ConfigWithConcurrent


def concurrent_instantiate(
    interface_cls, config_cls=None, config_kwargs: dict = None, **kwargs
) -> SensorConcurrentWrapper:
    cls, cfg = concurrent_wrapper(interface_cls, config_cls)
    config_kwargs = config_kwargs or {}
    config_kwargs.update(kwargs)
    return cls(cfg(**config_kwargs))


if __name__ == "__main__":
    from airdc.common.devices.cameras.mock import MockCamera
    import cv2
    import time

    init_logging()

    cls = "airdc.common.devices.cameras.mock.MockCamera"
    cls_wrapped, cfg_wrapped = concurrent_wrapper(cls)
    cls = MockCamera
    cls_wrapped, cfg_wrapped = concurrent_wrapper(cls)
    # con_mock_cam = cls_wrapped(
    #     cfg_wrapped(random=True, concurrent_wrapped=ConcurrentMode.process)
    # )
    con_mock_cam = concurrent_instantiate(cls)
    assert con_mock_cam.configure()
    con_mock_cam.get_logger().info("Successfully configured")
    for i in range(10):
        start = time.perf_counter()
        obs = con_mock_cam.capture_observation()
        print(f"{(time.perf_counter() - start) * 1000:.3} ms")
        for key, value in obs.items():
            print(key, value["t"])
            cv2.imshow(key, value["data"])
            cv2.waitKey(1)

    cv2.destroyAllWindows()
    con_mock_cam.shutdown()
