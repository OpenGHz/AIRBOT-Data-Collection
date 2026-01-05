from threading import Event
from multiprocessing.synchronize import Event as ProcessEvent
from multiprocessing import get_context
from pydantic import BaseModel, ConfigDict, Field
from typing import Optional, Union, Type
from airdc.basis import ConcurrentMode
from threading import Thread
from multiprocessing.context import SpawnProcess
import logging


class ProcessEventRpcArgs(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    req_event: ProcessEvent = Field(default_factory=get_context("spawn").Event)
    rsp_event: ProcessEvent = Field(default_factory=get_context("spawn").Event)


class ThreadEventRpcArgs(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    req_event: Event = Field(default_factory=Event)
    rsp_event: Event = Field(default_factory=Event)


AsyncEventRpc = ThreadEventRpcArgs


EventRpcArgs = Union[ProcessEventRpcArgs, ThreadEventRpcArgs, AsyncEventRpc]


class EventRpcServer:
    def __init__(self, args: EventRpcArgs):
        self._req_event = args.req_event
        self._rsp_event = args.rsp_event

    def wait(self, timeout=None) -> bool:
        ret = self._req_event.wait(timeout=timeout)
        if self._rsp_event.is_set():
            return False
        return ret

    def respond(self):
        self._req_event.clear()
        self._rsp_event.set()


class EventRpcClient:
    def __init__(self, args: EventRpcArgs):
        self._req_event = args.req_event
        self._rsp_event = args.rsp_event
        # no response to wait at the beginning
        self._rsp_event.set()

    def request(self, timeout: Optional[float] = None) -> bool:
        """Request a response from the server
        Args:
            timeout: Maximum time to wait for the response. If None, wait indefinitely.
                If 0 or negative, do not wait.
        Returns:
            True if the request was successful, False otherwise.
        """
        if self._req_event.is_set():
            self.get_logger().warning("previous response not received yet.")
            return False
        self._rsp_event.clear()
        self._req_event.set()
        return self.wait(timeout=timeout)

    def wait(self, timeout: Optional[float] = None) -> bool:
        """Wait for the response from the server
        Args:
            timeout: Maximum time to wait for the response. If None, wait indefinitely.
                If 0 or negative, do not wait.
        Returns:
            True if the response was received, False otherwise.
        """
        if timeout is None or timeout > 0:
            return self._rsp_event.wait(timeout=timeout)
        return True

    def is_responded(self) -> bool:
        return self._rsp_event.is_set()

    def shutdown(self) -> bool:
        if self._req_event.is_set():
            self.get_logger().warning("previous response not received yet.")
            return False
        self._rsp_event.set()
        self._req_event.set()
        return True

    @classmethod
    def get_logger(cls) -> logging.Logger:
        return logging.getLogger(cls.__name__)


class EventRpcManager:
    """A simple RPC mechanism using events for inter-thread or inter-process communication.

    This class provides a way to perform remote procedure calls (RPC) between threads or processes
    using event signaling. It consists of a server that waits for requests and a client that sends
    requests and waits for responses.

    Attributes:
        server (EventRpcServer): The server instance that handles incoming requests.
        client (EventRpcClient): The client instance that sends requests and waits for responses.
    """

    def __init__(self, args: EventRpcArgs):
        self.server = EventRpcServer(args)
        self.client = EventRpcClient(args)

    @staticmethod
    def get_args(mode: ConcurrentMode) -> EventRpcArgs:
        if mode is ConcurrentMode.thread:
            return ThreadEventRpcArgs()
        elif mode is ConcurrentMode.process:
            return ProcessEventRpcArgs()
        else:
            raise ValueError(f"Unsupported mode: {mode}")

    @staticmethod
    def get_concurrent_cls(
        mode: ConcurrentMode,
    ) -> Union[Type[Thread], Type[SpawnProcess]]:
        if mode is ConcurrentMode.thread:
            return Thread
        elif mode is ConcurrentMode.process:
            return SpawnProcess
        else:
            raise ValueError(f"Unsupported mode: {mode}")

    def shutdown(self) -> bool:
        return self.client.shutdown()
