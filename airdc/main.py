import time
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
from airdc.basis import PACKAGE_NAME
from mcap_data_loader.configurers.basis import main_argparse


def main() -> int:
    configurer = main_argparse(PACKAGE_NAME)(DataCollectionArgs)
    configurer.parse()

    logger = getLogger(PACKAGE_NAME)

    setproctitle(PACKAGE_NAME)

    def main_loop(config: DataCollectionArgs) -> int:
        """
        The main manager of data collection.
        """
        logger.info(f"Version: {version(PACKAGE_NAME)}")
        fsm = DemonstrateFSM(
            DemonstrateFSMConfig(state_machine=config.fsm, interface=config)
        )
        managers = config.managers
        for name, manager in managers.items():
            manager.set_fsm(fsm)
            if not manager.configure():
                raise RuntimeError(f"Failed to configure manager: {name}.")
        interval = 1.0 / config.update_rate if config.update_rate > 0 else 0.0
        logger.info(f"Update rate: {config.update_rate} Hz")
        # start updating the managers
        # TODO: use async io to update asynchronously?
        time_queue = deque(maxlen=20)
        total_start = time.perf_counter()
        metrics = defaultdict(dict)
        try:
            while True:
                start_time = time.perf_counter()
                for name, manager in managers.items():
                    m_start = time.perf_counter()
                    if not manager.update():
                        logger.warning(f"Failed to update manager: {name}.")
                    metrics["durations"][f"update/manager/{name}"] = (
                        time.perf_counter() - m_start
                    )
                if fsm.get_state() is DemonstrateState.finalized:
                    logger.info("Data collection finished.")
                    break
                if config.log_metrics >= 0:
                    logger.info(
                        "\nManager Metrics:\n"
                        + pformat(dict(metrics))
                        + "\n"
                        + "FSM Metrics:\n"
                        + pformat(dict(fsm.metrics))
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
        except KeyboardInterrupt:
            logger.info("Keyboard interrupt received. Exiting...")
        finally:
            for name, manager in managers.items():
                logger.info(f"Shutting down: {name}.")
                if not manager.shutdown():
                    logger.error(f"Failed to shutdown manager: {name}.")
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

    return main_loop(configurer.configure())


def main_desktop() -> int:
    import os
    from pathlib import Path

    logger = getLogger(PACKAGE_NAME)
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
