import os
import shutil
import numpy as np
import unittest
from pathlib import Path
from hydra.utils import instantiate
from omegaconf import OmegaConf
from collections import defaultdict
from time import time_ns

import pytest

pytestmark = pytest.mark.software

_CFG_OVERRIDE: str | None = None


def _get_outputs_run_dir(cfg_path: Path) -> Path:
    base_dir = Path(__file__).resolve().parent / "outputs"
    base_dir.mkdir(parents=True, exist_ok=True)

    run_id = time_ns()
    run_dir = base_dir / f"{cfg_path.stem}-run-{run_id}"
    run_dir.mkdir(parents=True, exist_ok=False)
    return run_dir


def _get_cfg_path() -> Path:
    if _CFG_OVERRIDE is not None:
        return Path(_CFG_OVERRIDE)

    import argparse

    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument(
        "--cfg",
        type=str,
        default="tests/modules/samplers/mock_sampler.yaml",
        help="Path to the configuration file.",
    )
    args, _unknown = parser.parse_known_args()
    return Path(args.cfg)


def _make_payload() -> dict:
    stamp = time_ns()
    size = 64
    payload = {
        "/left/follow/arm/joint_state/position": {
            "data": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            "t": stamp,
        },
        "/left/follow/eef/joint_state/position": {
            "data": [0.042676811087298046],
            "t": stamp + 1000,
        },
        "/left/lead/arm/joint_state/position": {
            "data": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            "t": stamp + 2000,
        },
        "/left/lead/eef/joint_state/position": {
            "data": [0.038898526876328846],
            "t": stamp + 3000,
        },
        "/right/follow/arm/joint_state/position": {
            "data": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            "t": stamp + 4000,
        },
        "/right/follow/eef/joint_state/position": {
            "data": [0.04263859970960877],
            "t": stamp + 5000,
        },
        "/right/lead/arm/joint_state/position": {
            "data": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            "t": stamp + 6000,
        },
        "/right/lead/eef/joint_state/position": {
            "data": [0.010088901680831866],
            "t": stamp + 7000,
        },
        # RGB/Depth mock frames (common shape conventions)
        "/left_camera/color/image_raw": {
            "data": np.zeros((size, size, 3), dtype=np.uint8),
            "t": stamp + 8000,
        },
        "/left_camera/aligned_depth_to_color/image_raw": {
            "data": np.zeros((size, size), dtype=np.uint16),
            "t": stamp + 9000,
        },
    }
    return payload


class TestDataSampler(unittest.TestCase):
    def test_instantiate_and_contract(self):
        cfg_path = _get_cfg_path()
        cfg = OmegaConf.load(cfg_path)
        from airdc.common.samplers.basis import DataSampler

        sampler: DataSampler = instantiate(cfg)
        self.assertIsInstance(sampler, DataSampler)
        sampler.set_info({})
        # ConfigurableBasis contract: should be configurable.
        self.assertTrue(sampler.configure())

        data_dir = _get_outputs_run_dir(cfg_path)
        print(f"[airdc] sampler test outputs: {data_dir}")

        # By default we KEEP saved episodes for manual inspection.
        # Set AIRDC_TEST_CLEANUP_OUTPUTS=1 to clean up the whole run directory.
        cleanup = os.environ.get("AIRDC_TEST_CLEANUP_OUTPUTS", "0") == "1"

        try:
            # Keep the first two rounds for inspection.
            for cur_round in range(2):
                path = sampler.compose_path(data_dir, cur_round)
                self.assertIsInstance(path, Path)
                self.assertTrue(str(path).startswith(str(data_dir)))

                round_data = defaultdict(list)
                for _ in range(2):
                    payload = _make_payload()
                    updated = sampler.update(payload)
                    self.assertIsInstance(updated, dict)
                    for key, value in updated.items():
                        round_data[key].append(value)

                self.assertTrue(sampler.save(path, round_data))
                sampler.clear()

            # Still cover the remove() contract by creating an extra episode and deleting it.
            removable_round = 999
            path = sampler.compose_path(data_dir, removable_round)
            round_data = defaultdict(list)
            for _ in range(2):
                payload = _make_payload()
                updated = sampler.update(payload)
                for key, value in updated.items():
                    round_data[key].append(value)
            self.assertTrue(sampler.save(path, round_data))
            # remove() may return True, None, or the removed Path — the contract
            # that matters is that the episode is actually deleted (asserted next).
            self.assertNotEqual(sampler.remove(path), False)
            self.assertFalse(
                path.exists(), "remove() should delete the episode directory"
            )
            sampler.clear()

        finally:
            if cleanup and data_dir.exists():
                shutil.rmtree(data_dir)

        sampler.shutdown()


if __name__ == "__main__":
    # Allow running as a script with a custom sampler config:
    #   python tests/modules/test_sampler.py --cfg tests/modules/samplers/xxx.yaml
    import argparse
    import sys

    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--cfg", type=str)
    args, remaining = parser.parse_known_args()
    if args.cfg:
        _CFG_OVERRIDE = args.cfg
    unittest.main(argv=[sys.argv[0]] + remaining)
