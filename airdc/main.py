import os
import time
from pathlib import Path
from logging import getLogger
from importlib.metadata import version
from collections import deque, defaultdict
from pprint import pformat
from setproctitle import setproctitle
from airdc.config import DataCollectionArgs
from airdc.state_machine.fsm import (
    DemonstrateFSM,
    DemonstrateFSMConfig,
    DemonstrateState,
)
from airdc.basis import PACKAGE_NAME, Bcolors
from mcap_data_loader.configurers.basis import main_argparse
from typing import Optional


logger = getLogger(PACKAGE_NAME)


def main_loop(config: DataCollectionArgs, job_id: Optional[int] = None) -> int:
    """
    The main manager of data collection.
    """
    if job_id is not None:
        job_id += config.job_id_bias
    elif config.job_id is not None:
        job_id = config.job_id + config.job_id_bias

    main_name = f"{PACKAGE_NAME}[{job_id}]" if job_id is not None else PACKAGE_NAME
    setproctitle(main_name)
    logger = getLogger(PACKAGE_NAME)
    logger.info(f"Version: {version(PACKAGE_NAME)}")

    batch_size = config.batch_size
    fsm_cnt = 0
    raw_directory = config.dataset.directory
    # NOTE: Currently, pydantic's model_copy update is always performed after the copy is complete. Therefore, it is not possible to avoid copying issues by clearing fields in the update. The only solution is to manually clear them beforehand.
    managers = config.managers.copy()
    config.managers.clear()

    def create_fsm():
        nonlocal fsm_cnt
        fsm_cnt += 1
        # NOTE: if there are multiple FSMs, we only keep the visualizer for the first one to avoid duplicated visualization
        if batch_size > 0 and fsm_cnt == 1:
            new_dir = raw_directory
            if job_id is not None:
                new_dir += f"_{job_id}"
            new_dir += "_0"
            object.__setattr__(config.dataset, "directory", new_dir)
        if fsm_cnt > 1:
            new_dir = raw_directory
            if job_id is not None:
                new_dir += f"_{job_id}"
            new_dir += f"_{fsm_cnt - 1}"
            config_copy = config.model_copy(
                update={
                    "visualizer": None,
                    "dataset": config.dataset.model_copy(
                        update={"directory": new_dir},
                        deep=True,
                    ),
                    "managers": {},
                },
                deep=True,
            )
        else:
            config_copy = config
        return DemonstrateFSM(
            DemonstrateFSMConfig(state_machine=config_copy.fsm, interface=config_copy)
        )

    logger.info(f"Creating {batch_size} FSMs.")
    fsms = [create_fsm() for _ in range(batch_size or 1)]

    for name, manager in managers.items():
        manager.set_fsms(fsms)
        if not manager.configure():
            raise RuntimeError(f"Failed to configure manager: {name}.")
    # Announce once, after initialization completes and before the first
    # collection tick, where episodes will be written. With batching each FSM
    # gets its own suffixed directory, so report their common parent as the
    # save root; a single FSM reports its own directory.
    save_dirs = sorted({fsm.dataset_config.absolute_directory for fsm in fsms})
    save_root = (
        save_dirs[0]
        if len(save_dirs) == 1
        else Path(os.path.commonpath([str(p) for p in save_dirs]))
    )
    logger.info(Bcolors.green(f"Data will be saved under: {save_root}"))
    interval = 1.0 / config.update_rate if config.update_rate > 0 else 0.0
    logger.info(f"Update rate: {config.update_rate} Hz")
    manager_update_every = dict(config.manager_update_every)
    unknown = set(manager_update_every) - set(managers)
    if unknown:
        logger.warning(
            f"manager_update_every references unknown manager(s) {sorted(unknown)}; "
            f"known managers: {sorted(managers)}."
        )
    if manager_update_every:
        logger.info(f"Per-manager update dividers (ticks): {manager_update_every}")
    # start updating the managers
    # TODO: use async io to update asynchronously?
    time_queue = deque(maxlen=20)
    total_start = time.perf_counter()
    metrics = defaultdict(dict)
    try:
        tick = 0
        while True:
            start_time = time.perf_counter()
            for name, manager in managers.items():
                # Per-manager tick divider. `tick` is a single loop-wide counter
                # that is NOT reset per episode, so this schedule is phase-aligned
                # to global tick 0 (not to each episode's first sampling tick):
                # an episode entering sampling on a tick where tick % N != 0 will
                # have its first frame(s) skipped. See
                # DataCollectionConfig.manager_update_every for the full caveat
                # and the episode-local `sample_every` alternative.
                if tick % manager_update_every.get(name, 1) != 0:
                    continue
                m_start = time.perf_counter()
                if not manager.update():
                    logger.warning(f"Failed to update manager: {name}.")
                metrics["durations"][f"update/manager/{name}"] = (
                    time.perf_counter() - m_start
                )
            if all(fsm.get_state() is DemonstrateState.finalized for fsm in fsms):
                logger.info("Data collection finished.")
                break
            if config.log_metrics >= 0:
                logger.info(
                    "\nManager Metrics:\n"
                    + pformat(dict(metrics))
                    + "\n"
                    + "FSM Metrics:\n"
                    + pformat([dict(fsm.metrics) for fsm in fsms])
                )
            cost_time = time.perf_counter() - start_time
            time_queue.append(cost_time)
            if interval > 0:
                sleep_time = interval - cost_time
                if sleep_time > 0:
                    time.sleep(sleep_time)
                elif sleep_time < 0 and config.log_jitter:
                    logger.warning(
                        f"The main loop takes too long, timeout {-sleep_time:.4f} s."
                    )
            tick += 1
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received. Exiting...")
    finally:
        # shutdown the managers
        for name, manager in managers.items():
            logger.info(f"Shutting down manager: {name}.")
            if not manager.shutdown():
                logger.error(f"Failed to shutdown: {name}.")
        # shutdown the FSMs
        for fsm in fsms:
            if fsm.get_state() is not DemonstrateState.finalized:
                logger.info("Shutting down FSM.")
                fsm.shutdown()

    summary = {"Total time taken": f"{time.perf_counter() - total_start:.4f} s"}
    if time_queue:
        avg_time = sum(time_queue) / len(time_queue)
        summary.update(
            {
                "Average update time": f"{avg_time:.4f} s",
                "Average update freq": f"{1.0 / avg_time:.4f} Hz",
            }
        )
    logger.info("Summary:\n" + pformat(summary))
    logger.info("Done.")
    return 0


def main() -> int:
    configurer = main_argparse(PACKAGE_NAME)(DataCollectionArgs)
    multirun = configurer.parse()
    if multirun:
        print("Using multirun mode.")
        try:
            return configurer.configure(main=main_loop)
        except KeyboardInterrupt:
            logger.info("Keyboard interrupt received.")
            return 0
    else:
        return main_loop(configurer.configure())


def main_desktop() -> int:
    import os
    from pathlib import Path

    work_dir = Path(__file__).parent.parent
    if not (work_dir / "airdc.desktop").exists():
        raise RuntimeError(
            f"Cannot find `airdc.desktop` in {work_dir}. Make sure the package is installed in editable mode."
        )
    logger.info(f"Changing working directory to {work_dir}.")
    os.chdir(work_dir)
    return main()


if __name__ == "__main__":
    import sys

    sys.exit(main())
