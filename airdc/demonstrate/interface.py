from concurrent.futures import (
    Executor,
    ProcessPoolExecutor,
    ThreadPoolExecutor,
    Future,
    as_completed,
)
from logging import getLogger
from typing import Any, List, Dict
from airdc.demonstrate.configs import (
    ConcurrentMode,
    DemonstrateAction,
    DemonstrateConfig,
    DemonstrateModule as Module,
)
from airdc.demonstrate.basis import SampleInfo
from airdc.basis import Bcolors
from airdc.utils import get_items_by_ext, zip
from airdc.common.utils.system_info import SystemInfo
from airdc.common.utils.progress import ProgressBar
from airdc.common.demonstrators.basis import Demonstrator
from airdc.state_machine.basis import CallbackEventType
from collections import defaultdict
from functools import partial
from pathlib import Path
import time


class DemonstrateInterface:
    def __init__(self, config: DemonstrateConfig):
        self._config = config
        """init sampler, visualizers and demonstrator"""
        self._modules = config.modules
        """init sample info"""
        start_round = config.sample_limit.start_round
        if start_round < 0:
            data_dir = config.dataset.absolute_directory
            start_round = self._modules.sampler.get_start_episode(data_dir)
        if start_round < 0:
            # detect the number of files in the directory
            start_round = (
                len(get_items_by_ext(data_dir, config.dataset.file_extension))
                + start_round
                + 1
            )
        end_round = config.sample_limit.end_round
        rounds = config.sample_limit.rounds
        if end_round == 0 and rounds > 0:
            end_round = start_round + rounds
        self._sample_limit = config.sample_limit.model_copy(
            update={"start_round": start_round, "end_round": end_round}
        )
        self._sample_info = SampleInfo(episode=start_round)
        """init concurrent actions"""
        concur = self._config.concurrent
        self._action_executors: Dict[DemonstrateAction, Executor] = {}
        mode2executor = {
            ConcurrentMode.thread: ThreadPoolExecutor,
            ConcurrentMode.process: ProcessPoolExecutor,
        }
        for action, mode, max_workers in zip(
            concur.actions, concur.modes, concur.max_workers
        ):
            args = (action.name,) if mode is ConcurrentMode.thread else ()
            self._action_executors[action] = mode2executor[mode](max_workers, *args)
        self._action_futures: Dict[DemonstrateAction, List[Future]] = defaultdict(list)
        self._action_exception = {}
        """store current episode data"""
        self._round_data = defaultdict(list)
        self._metrics = defaultdict(dict)
        self._finished = False
        """other """
        self._register_fsm_callbacks()

    def get_logger(self):
        """
        Get the logger for the demonstration.
        """
        return getLogger(self.__class__.__name__)

    def configure(self) -> bool:
        """
        Configure all the modules.
        """
        # NOTE: the demonstrator is configured by the fsm callback first
        # NOTE: set info before configuring the sampler so that the sampler can use it for configuring
        # TODO: should configure the demonstrator here?
        self._modules.sampler.set_info(
            self._modules.demonstrator.get_info() | {"system": SystemInfo.all_info()}
        )
        return self._configure_modules([Module.VISUALIZER, Module.SAMPLER])

    def _configure_module(self, module: Module) -> bool:
        module_instance = self._modules[module]
        if not module_instance.configure():
            self.get_logger().error(f"Failed to configure {module}: {module_instance}")
            return False
        return True

    def _configure_modules(self, modules: List[Module]) -> bool:
        for module in modules:
            if not self._configure_module(module):
                return False
        return True

    def _register_fsm_callbacks(self):
        """Register FSM callbacks, which will be called automatically by the FSM."""
        self.fsm_callbacks = defaultdict(dict)
        # register send action callbacks
        for cb_type, configs in self._config.send_actions.items():
            for key, action in configs.items():
                self.fsm_callbacks[cb_type][key] = partial(
                    self._modules.demonstrator.send_action, action
                )
        # register react callbacks
        # TODO: Allow both prepare before and after.
        for action in DemonstrateAction:
            self.fsm_callbacks[CallbackEventType.PREPARE_EVENT_BEFORE][action] = (
                partial(self._modules.demonstrator.react, action)
            )

    def activate(self) -> bool:
        self._bar = ProgressBar(
            f"Episode {self._sample_info.episode}",
            self._sample_limit.size,
            leave_mode=-1,
        )
        Path(self._config.dataset.absolute_directory).mkdir(parents=True, exist_ok=True)
        self.get_logger().info("Warming up...")
        self.capture(warm_up=True)
        return True

    def deactivate(self) -> bool:
        return True

    def sample(self) -> bool:
        """
        Start to sample the data (switch the leaders mode to passive)
        """
        if self.is_reached_round:
            self.get_logger().warning("Maximum number of rounds was reached.")
            return False
        self.get_logger().info(
            Bcolors.green(f"Start sampling episode: {self._sample_info.episode}")
        )
        self._save_path = self._modules.sampler.compose_path(
            self._config.dataset.absolute_directory, self._sample_info.episode
        )
        self._bar.reset(desc=f"Episode {self._sample_info.episode}")
        return True

    def capture(self, warm_up: bool = False) -> Dict[str, Any]:
        # TODO: can be called when sampling?
        start = time.perf_counter()
        # TODO: configure each action
        data = self._modules.demonstrator.capture_observation(2)
        data = self._config.key_remap(self._config.key_merge(data))
        self._metrics["durations"]["demonstrate/update/demonstrator"] = (
            time.perf_counter() - start
        )
        self.last_capture = data
        # update the visualizers
        start = time.perf_counter()
        self._modules.visualizer.update(data, self._sample_info, warm_up)
        self._metrics["durations"]["demonstrate/update/visualizers"] = (
            time.perf_counter() - start
        )
        self._metrics["durations"].update(
            self._modules.demonstrator.metrics.get("durations", {})
        )
        return data

    def update(self) -> bool:
        """
        Update the components (including visualizers).
        """
        # TODO: should react and post action in capture and update?
        info = self._sample_info
        if info.index == 0:
            self.start_stamp = time.perf_counter()
        if self.is_reached:
            self.get_logger().warning(
                f"Sample limitation reached: {info.index} samples"
            )
            return False
        else:
            start = time.perf_counter()
            # TODO: Should use a .copy() to avoid the data being updated in-place within the demonstrator, which could lead to data overwriting issues during asynchronous updating?
            data = self.capture()

            if not data.pop("skip", False):
                data.update({"log_stamps": time.time_ns()})

                # update the sampler
                def update_sampler(data: dict):
                    start_sampler = time.perf_counter()
                    for key, value in self._modules.sampler.update(data).items():
                        self._round_data[key].append(value)
                    self._metrics["durations"]["demonstrate/update/sampler"] = (
                        time.perf_counter() - start_sampler
                    )
                    # time.sleep(1 / 10)  # simulate some delay for sampler

                self._submit_action(DemonstrateAction.update, update_sampler, data)
                # update_sampler(data)  # blocking update
                # update the progress bar
                start_bar = time.perf_counter()
                info.index += 1
                self._bar.update(info.index)
                self._metrics["durations"]["demonstrate/update/bar"] = (
                    time.perf_counter() - start_bar
                )
                self._metrics["durations"]["demonstrate/update"] = (
                    time.perf_counter() - start
                )
            return self._action_ok(DemonstrateAction.update)

    def _show_save_info(self, path: str, flag: bool) -> bool:
        if flag:
            self.get_logger().info(Bcolors.green(f"Saved to {path}"))
        else:
            self.get_logger().error(f"Failed to save to {path}")
        return flag

    def save(self) -> None:
        """Save the sampled data and be ready for the next episode."""
        # FIXME: explicitly specifying the action type is coupled with the state machine logic
        self._wait_action_futures(DemonstrateAction.update)
        save_path = self._save_path
        if self._use_executor(DemonstrateAction.save):
            future = self._submit_action(
                DemonstrateAction.save,
                self._modules.sampler.save,
                save_path,
                self._round_data,
            )
            future.add_done_callback(
                lambda f: self._show_save_info(save_path, f.result())
            )
        else:
            if not self._show_save_info(
                save_path, self._modules.sampler.save(save_path, self._round_data)
            ):
                return False
        self._sample_info.episode += 1
        self._clear()
        return True

    def remove(self) -> bool:
        """Remove the last episode saved sample."""
        last_round = self._sample_info.episode - 1
        if last_round >= 0:
            path = self._modules.sampler.compose_path(
                self._config.dataset.absolute_directory, last_round
            )
            self._wait_action_futures(DemonstrateAction.save)
            # try to remove the data
            removed_path = self._modules.sampler.remove(path)
            if removed_path is not None:
                self.get_logger().info(Bcolors.green(f"Removed {removed_path}"))
            else:
                self.get_logger().warning(f"Path does not exist: {path}")
            # the order is important
            self._sample_info.episode -= 1
            self._clear()
        else:
            self.get_logger().warning("Not ever saved yet")
        return True

    def _clear(self) -> None:
        self._round_data = defaultdict(list)
        self._modules.sampler.clear()
        self._sample_info.index = 0
        self._save_path = ""

    def _use_executor(self, action: DemonstrateAction) -> bool:
        return action in self._action_executors

    def _check_future(self, action: DemonstrateAction, future: Future):
        if future.cancelled():
            return
        if future.exception() is not None:
            self._action_exception[action] = True
            raise future.exception()

    def _action_ok(self, action: DemonstrateAction) -> bool:
        return not self._action_exception.get(action)

    def _submit_action(
        self, action: DemonstrateAction, func: Any, *args, **kwargs
    ) -> Future:
        future = self._action_executors[action].submit(func, *args, **kwargs)
        self._action_futures[action].append(future)
        future.add_done_callback(partial(self._check_future, action))
        return future

    def _cancel_action_futures(self, action: DemonstrateAction) -> None:
        futures = self._action_futures.get(action, None)
        if futures:
            for future in futures:
                future.cancel()
            self._action_futures[action] = []

    def _wait_action_futures(self, action: DemonstrateAction) -> None:
        # drop the done futures
        futures = [f for f in self._action_futures.get(action, []) if not f.done()]
        if futures:
            # wait for the remaining futures
            bar = ProgressBar(f"Completing {action.name} futures", len(futures))
            for update_future in as_completed(futures):
                update_future.result()
                bar.update()
            bar.close()
            self._action_futures[action] = []

    def abandon(self) -> bool:
        """Abandon the current episode of sampling."""
        self._cancel_action_futures(DemonstrateAction.update)
        self._modules.sampler.remove(self._save_path)
        self._clear()
        self.get_logger().info(
            Bcolors.green(f"Abandoned the current episode: {self._sample_info.episode}")
        )
        return True

    def finish(self) -> bool:
        """
        Finish the demonstration.
        """
        if self._finished:
            return True
        # Ensure any background save work is complete before shutting modules down.
        self._wait_action_futures(DemonstrateAction.save)
        self.get_logger().info(
            f"Finished the demonstration: from {self._sample_limit.start_round} to {self._sample_info.episode}"
        )
        self._modules.visualizer.shutdown()
        self._modules.sampler.shutdown()
        self._finished = True
        return True

    def log_round(self):
        self.get_logger().info(
            Bcolors.cyan(f"Current sample episode: {self._sample_info.episode}")
        )

    @property
    def is_reached(self) -> bool:
        limit = self._sample_limit
        reach_size = limit.size > 0 and self._sample_info.index >= limit.size
        reach_duration = (
            limit.duration > 0
            and time.perf_counter() - self.start_stamp >= limit.duration
        )
        return reach_size or reach_duration

    @property
    def is_reached_round(self) -> bool:
        end_round = self._sample_limit.end_round
        return end_round > 0 and self._sample_info.episode >= end_round

    @property
    def demonstrator(self) -> Demonstrator:
        return self._modules.demonstrator

    @property
    def metrics(self) -> Dict[str, Any]:
        return self._metrics
