from typing import Union, Literal, Type, Optional, Generic, TypeVar, final
from typing_extensions import Self
from collections.abc import Iterable, Iterator, Callable
from threading import Thread, Event, Lock, current_thread, main_thread
from multiprocessing import get_context, synchronize, current_process
from multiprocessing.context import SpawnProcess
from multiprocessing.process import BaseProcess
from pydantic import BaseModel, ConfigDict, Field
from abc import abstractmethod, ABC
from setproctitle import setproctitle
from airdc.basis import ConcurrentMode, Bcolors
import logging
import asyncio


SpawnEvent = get_context("spawn").Event


class Waitable(ABC):
    def __init__(self):
        self.__pid = current_process().pid

    @abstractmethod
    def wait(self) -> bool:
        """Waits for the progress to start.
        Blocks until the progress is started or not ok (exiting or exited).
        Returns True if the progress has started, False otherwise.
        """

    @abstractmethod
    def __enter__(self) -> Self:
        """Marks the waitable as entered."""

    @abstractmethod
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Marks the waitable as exited."""

    @property
    @final
    def pid_init(self) -> int:
        return self.__pid

    @property
    @final
    def pid_current(self) -> int:
        return current_process().pid

    @final
    def is_same_process(self) -> bool:
        return self.pid_init == self.pid_current

    @staticmethod
    def current_process() -> BaseProcess:
        return current_process()

    @staticmethod
    def set_process_title(title: str):
        setproctitle(title)


class MockWaitable(Waitable):
    def wait(self) -> bool:
        return True

    def __enter__(self) -> Self:
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass


class ThreadWaitableArgs(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    context_event: Event = Event()
    start_event: Event = Event()
    exiting_event: Event = Event()
    exited_event: Event = Event()

    @staticmethod
    def concurrent_cls() -> Type[Thread]:
        return Thread


class ProcessWaitableArgs(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    context_event: synchronize.Event = Field(default_factory=SpawnEvent)
    start_event: synchronize.Event = Field(default_factory=SpawnEvent)
    exiting_event: synchronize.Event = Field(default_factory=SpawnEvent)
    exited_event: synchronize.Event = Field(default_factory=SpawnEvent)

    @staticmethod
    def concurrent_cls() -> Type[SpawnProcess]:
        return SpawnProcess


class ConcurrentWaitable(Waitable):
    def __init__(self, args: Union[ThreadWaitableArgs, ProcessWaitableArgs]):
        super().__init__()
        self.args = args

    def wait(self) -> bool:
        """Waits for the progress to start.
        Blocks until the progress is started or not ok (exiting or exited).
        Returns True if the progress has started, False otherwise.
        """
        if self._is_ok():
            self.args.start_event.wait(timeout=None)
            if self._is_ok():
                return True
        return False

    def __enter__(self) -> Self:
        """Marks the waitable as entered."""
        self.args.context_event.set()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Marks the waitable as exited."""
        self.args.context_event.clear()

    def _is_ok(self) -> bool:
        return (
            not self.args.exiting_event.is_set() and not self.args.exited_event.is_set()
        )


class ProgressHandler(ABC):
    """Handler for progress."""

    def __init__(self):
        self.__lock = Lock()
        self.__callbacks = {"start": [], "stop": []}
        self.__started = False
        self.__exiting = False
        self.__exited = False

    @final
    def start(self) -> bool:
        """Starts the progress."""
        if not self.is_launched():
            raise RuntimeError("progress is not launched.")
        if self.is_stopped():
            self._execute_callbacks(self.start.__name__)
            if self.on_start():
                self.__started = True
                return True
            return False
        self.get_logger().warning("Already started.")
        return True

    @final
    def stop(self) -> bool:
        """Stops the progress."""
        if self.is_stopped():
            self.get_logger().warning("Already stopped.")
            return True
        elif self.__lock.locked():
            self.get_logger().warning(
                "Lock is already acquired (exiting), cannot stop."
            )
        with self.__lock:
            self._execute_callbacks(self.stop.__name__)
            if self.on_stop():
                self.__started = False
                return True
            return False

    @abstractmethod
    def launch(self, *args, **kwargs) -> bool:
        """Launches the progress."""

    @abstractmethod
    def on_start(self) -> bool:
        """Called in start()."""

    @abstractmethod
    def on_stop(self) -> bool:
        """Called in stop()."""

    @abstractmethod
    def on_exit(self) -> bool:
        """Called in exit()"""

    @abstractmethod
    def is_launched(self) -> bool:
        """Checks if the progress is launched."""

    @abstractmethod
    def get_waitable(self) -> Waitable:
        """Gets the waitable for the progress."""

    # @abstractmethod
    # def is_waiting(self) -> bool:
    #     """Checks if the progress is waiting."""

    def is_stopped(self) -> bool:
        """Checks if the progress is stopped."""
        return not self.__started

    def is_exiting(self) -> bool:
        """Checks if the progress is exiting."""
        return self.__exiting

    def is_exited(self) -> bool:
        """Checks if the progress is exited."""
        return self.__exited

    @final
    def ok(self) -> bool:
        """Checks if the demonstrator is OK."""
        return not self.is_exiting() and not self.is_exited()

    @final
    def exit(self) -> bool:
        """Exits the progress."""
        # since the concurrent may wait
        # forever if stop is called during
        # exiting, a lock is needed
        with self.__lock:
            self.__exiting = True
            success = False
            if self.is_launched() and self.is_stopped():
                if not self.start():
                    self.get_logger().warning(
                        "Failed to start, exiting may be blocked."
                    )
            if self.on_exit():
                # after exit `is_stopped` should return True
                if self.on_stop():
                    success = True
            self.__exited = True
            self.__exiting = False
            return success

    @final
    def register_callback(
        self, action: Literal["start", "stop"], callback: Callable[[], bool]
    ):
        """Registers a callback for a specific action, which will
        be executed before the `on_<action>` method."""
        self.__callbacks[action].append(callback)

    @final
    def clear_callbacks(self):
        """Clears all registered callbacks."""
        self.__callbacks.clear()

    def get_logger(self) -> logging.Logger:
        """Gets the logger for the progress."""
        return logging.getLogger(__name__)

    def _execute_callbacks(self, action: str):
        """Executes all callbacks registered for a specific action."""
        for callback in self.__callbacks.get(action, []):
            callback()

    def __del__(self):
        if not self.__exited:
            self.exit()


class MockProgressHandler(ProgressHandler):
    """Mock handler for progress."""

    def __init__(self):
        super().__init__()
        # always launched
        self._launched = True
        self._waitable = MockWaitable()

    def launch(self, *args, **kwargs):
        self._launched = True
        return True

    def on_start(self):
        return True

    def on_stop(self):
        return True

    def on_exit(self):
        return True

    def is_launched(self):
        return self._launched

    def get_waitable(self) -> MockWaitable:
        return self._waitable

    def _execute_callbacks(self, action):
        """Do not execute callbacks in mock handler."""


class ConcurrentProgressHandler(ProgressHandler):
    """Handler for concurrent progress."""

    def __init__(self, mode: ConcurrentMode):
        super().__init__()
        if mode is ConcurrentMode.thread:
            self._args = ThreadWaitableArgs()
        elif mode is ConcurrentMode.process:
            self._args = ProcessWaitableArgs()
        else:
            raise ValueError(f"Invalid mode: {mode}")
        self._mode = mode
        self._concurrent = None
        self._waitable = ConcurrentWaitable(self._args)

    def launch(
        self, group=None, target=None, name=None, args=(), kwargs={}, *, daemon=None
    ):
        self.get_logger().info(Bcolors.blue(f"Starting {name} in {self._mode} mode"))
        self._concurrent = self._args.concurrent_cls()(
            group, target, name, args, kwargs, daemon=daemon
        )
        self._concurrent.start()
        timeout = 5.0
        self.get_logger().info(f"Waiting for {name} to enter waitable {timeout} s...")
        self._args.context_event.wait(timeout=timeout)
        return True

    def on_start(self) -> bool:
        if not self._concurrent.is_alive():
            raise RuntimeError("Concurrent not alive")
        self._args.start_event.set()
        return True

    def on_stop(self):
        self._args.start_event.clear()
        return True

    def is_launched(self):
        return self._concurrent is not None

    def on_exit(self):
        self._args.exiting_event.set()
        if self.is_launched():
            if self._mode is ConcurrentMode.thread or not self._concurrent.daemon:
                self.get_logger().info("Waiting for the concurrent to finish...")
                wait_time = 5.0
                self._concurrent.join(wait_time)
                if self._concurrent.is_alive():
                    self.get_logger().error(
                        f"Concurrent is still alive after waiting {wait_time} s"
                    )
                    return False
                self.get_logger().info("Concurrent finished.")
            elif self._mode is ConcurrentMode.process:
                # daemon process is not joinable so just pass
                # self.get_logger().info("Terminating concurrent...")
                # self._concurrent.terminate()
                # self._concurrent.kill()
                pass
        self._args.exited_event.set()
        self._args.exiting_event.clear()
        return True

    def get_waitable(self) -> ConcurrentWaitable:
        return self._waitable


def create_handler(mode: ConcurrentMode) -> ProgressHandler:
    if mode is ConcurrentMode.none:
        return MockProgressHandler()
    else:
        return ConcurrentProgressHandler(mode)


def run_event_loop() -> asyncio.AbstractEventLoop:
    if current_thread() != main_thread():
        raise RuntimeError("Event loop must be run in the main thread")
    event_loop = asyncio.get_event_loop()
    if not event_loop.is_running():
        event_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(event_loop)
        Thread(target=event_loop.run_forever, daemon=True).start()
    return event_loop


T = TypeVar("T")


class ProgressBar(Generic[T]):
    def __init__(
        self,
        desc: str,
        total: int,
        leave: Optional[bool] = True,
        leave_mode: int = 0,
        iterable: Optional[Iterable[T]] = None,
    ):
        self.total = total
        from tqdm import tqdm
        # from tqdm.asyncio import tqdm

        self.progress_bar = tqdm(
            iterable, desc, total, leave, unit="step", smoothing=1.0
        )
        self.progress_bar.clear()
        self._leave_mode = leave_mode
        self._leave = leave

    def update(self, index: Optional[int] = None):
        bar = self.progress_bar
        bar.n = index if index is not None else bar.n + 1
        bar.set_postfix({"Percentage": f"{bar.n / self.total * 100:.1f}%"})
        bar.refresh()

    def reset(self, total: int = 0, desc: Optional[str] = None):
        self.progress_bar.reset(total=total or self.total)
        if desc is not None:
            self.progress_bar.desc = desc
        self.progress_bar.clear()

    def clear(self):
        # NOTE: sometimes manual cleanup is necessary to avoid terminal remnants.
        self.progress_bar.clear()

    def close(self):
        # NOTE: usually no need to close manually
        # and manually closing may sometimes cause some terminal remnants
        bar = self.progress_bar
        if self._leave_mode < 0:
            bar.leave = bar.n == self.total
        elif self._leave_mode > 0:
            bar.leave = bar.n > 0
        else:
            bar.leave = self._leave
        bar.leave = (
            bar.n == self.total
            if self._leave_mode < 0
            else bar.n > 0
            if self._leave_mode > 0
            else self._leave
        )
        bar.clear()
        bar.close()

    def __iter__(self) -> Iterator[T]:
        return iter(self.progress_bar)


class ProgressBarMock:
    def __init__(self, *args, **kwargs):
        """Do nothing, just for compatibility with ProgressBar."""

    def update(self, index: Optional[int] = None):
        pass

    def reset(self, total: int = 0, desc: Optional[str] = None):
        pass

    def clear(self):
        pass

    def close(self):
        pass

    def __iter__(self) -> Iterator:
        return iter([])
