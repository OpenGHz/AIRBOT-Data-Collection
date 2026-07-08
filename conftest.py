"""Root pytest configuration shared by ``tests/`` and ``airbot_ie/tests/``.

This file is the heart of the "environment-adaptive" test architecture:

* **Hardware probes** detect whether a physical device or external service is
  actually present (a RealSense camera, a ``/dev/video*`` node, an NVIDIA GPU,
  a reachable Redis, a ROS toolchain, a display).
* **Auto-skip** (`pytest_collection_modifyitems`) turns a *missing* resource into
  a **Skipped** test — never a **Failed** one. A red test therefore always means
  "the software is broken", not "this machine has no camera".
* **Opt-in flags** (`--run-hardware`, `--run-manual`) let a real robot rig or a
  developer force those tests to run.
* **Shared fixtures** reuse the project's existing Mock layer so pure-software
  tests never touch hardware.

See ``docs/develop/testing.md`` for the full specification.
"""

from __future__ import annotations

import functools
import glob
import os
import shutil
import socket
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent

# --------------------------------------------------------------------------- #
# Hardware / service probes (cached: each probe runs at most once per session)
# --------------------------------------------------------------------------- #


@functools.lru_cache(maxsize=None)
def has_display() -> bool:
    """True if a graphical display is available (for cv2.imshow / tk / open3d)."""
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


@functools.lru_cache(maxsize=None)
def has_realsense() -> bool:
    """True if pyrealsense2 is importable AND at least one device is connected."""
    try:
        import pyrealsense2 as rs
    except Exception:
        return False
    try:
        return len(rs.context().devices) > 0
    except Exception:
        return False


@functools.lru_cache(maxsize=None)
def has_camera() -> bool:
    """True if any V4L2 / USB camera node is present."""
    return len(glob.glob("/dev/video*")) > 0


@functools.lru_cache(maxsize=None)
def has_gpu() -> bool:
    """True if an NVIDIA GPU is visible (nvidia-smi on PATH)."""
    return shutil.which("nvidia-smi") is not None


@functools.lru_cache(maxsize=None)
def has_redis() -> bool:
    """True if a Redis server accepts a TCP connection.

    Host/port are overridable via ``AIRDC_REDIS_HOST`` / ``AIRDC_REDIS_PORT`` so
    CI can point at a service container.
    """
    host = os.environ.get("AIRDC_REDIS_HOST", "localhost")
    port = int(os.environ.get("AIRDC_REDIS_PORT", "6379"))
    try:
        with socket.create_connection((host, port), timeout=0.3):
            return True
    except OSError:
        return False


@functools.lru_cache(maxsize=None)
def has_ros() -> bool:
    """True if a ROS environment is sourced.

    We probe ``$ROS_VERSION`` / ``$ROS_DISTRO`` because the mcap_data_loader ROS
    serialization stack reads ``ROS_VERSION`` at import time; without it those
    imports raise. In practice this is True in the pixi (robostack) environment
    and False in the plain conda environment.
    """
    return bool(os.environ.get("ROS_VERSION") or os.environ.get("ROS_DISTRO"))


# marker name -> (probe, human-readable reason shown on skip)
_RESOURCE_PROBES = {
    "realsense": (has_realsense, "未检测到 Intel RealSense 相机"),
    "camera": (has_camera, "未检测到 /dev/video* 摄像头"),
    "gpu": (has_gpu, "未检测到 NVIDIA GPU（nvidia-smi 不在 PATH）"),
    "redis": (
        has_redis,
        "无法连接 Redis（localhost:6379，可用 AIRDC_REDIS_HOST 覆盖）",
    ),
    "ros": (has_ros, "未检测到 ROS 环境（$ROS_DISTRO 未设置且 cv_bridge 不可导入）"),
    "display": (has_display, "无图形显示（$DISPLAY / $WAYLAND_DISPLAY 未设置）"),
}


# --------------------------------------------------------------------------- #
# CLI opt-in flags
# --------------------------------------------------------------------------- #


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("airdc", "AIRDC hardware-aware testing")
    group.addoption(
        "--run-hardware",
        action="store_true",
        default=False,
        help="即使探针检测不到硬件/服务，也强制运行 hardware 相关用例。",
    )
    group.addoption(
        "--run-manual",
        action="store_true",
        default=False,
        help="收集并运行标记为 manual 的交互/演示脚本（默认不收集）。",
    )


# --------------------------------------------------------------------------- #
# Auto-skip: a missing resource -> Skipped, never Failed
# --------------------------------------------------------------------------- #


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    run_hardware = config.getoption("--run-hardware")
    run_manual = config.getoption("--run-manual")

    for item in items:
        keywords = item.keywords

        # 1) manual/interactive scripts: opt-in only.
        if "manual" in keywords and not run_manual:
            item.add_marker(
                pytest.mark.skip(reason="⏭️ manual 用例：加 --run-manual 才运行")
            )
            continue

        # 2) hardware/service resources: skip when the probe says it's absent.
        if run_hardware:
            continue
        for name, (probe, reason) in _RESOURCE_PROBES.items():
            if name in keywords and not probe():
                item.add_marker(
                    pytest.mark.skip(
                        reason=f"⏭️ 跳过[{name}]：{reason}（--run-hardware 可强制运行）"
                    )
                )
                break


# --------------------------------------------------------------------------- #
# Shared fixtures (reuse the project's existing Mock layer)
# --------------------------------------------------------------------------- #


@pytest.fixture
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture
def mock_camera():
    """A configured software MockCamera — no physical device required.

    Reuses ``airdc.common.devices.cameras.mock.MockCamera``.
    """
    from airdc.common.devices.cameras.mock import MockCamera, MockCameraConfig

    camera = MockCamera(MockCameraConfig(enable_color=True, enable_depth=True))
    assert camera.configure()
    yield camera
    camera.shutdown()


@pytest.fixture
def sample_payload() -> dict:
    """A synthetic robot observation payload (joint states + RGB/Depth frames).

    Mirrors the shape produced by real samplers so sampler/pipeline tests can run
    with zero hardware. Kept in sync with ``tests/modules/test_sampler.py``.
    """
    import numpy as np
    from time import time_ns

    stamp = time_ns()
    size = 64
    return {
        "/left/follow/arm/joint_state/position": {"data": [0.0] * 6, "t": stamp},
        "/left/follow/eef/joint_state/position": {"data": [0.04], "t": stamp + 1000},
        "/right/follow/arm/joint_state/position": {
            "data": [0.0] * 6,
            "t": stamp + 2000,
        },
        "/right/follow/eef/joint_state/position": {"data": [0.01], "t": stamp + 3000},
        "/left_camera/color/image_raw": {
            "data": np.zeros((size, size, 3), dtype=np.uint8),
            "t": stamp + 4000,
        },
        "/left_camera/aligned_depth_to_color/image_raw": {
            "data": np.zeros((size, size), dtype=np.uint16),
            "t": stamp + 5000,
        },
    }


@pytest.fixture
def sample_mcap() -> Path:
    """Path to the bundled sample MCAP; skips the test if it is not present."""
    path = REPO_ROOT / "data/aao_data/door_0/3.mcap"
    if not path.exists():
        pytest.skip(f"缺少样例 MCAP：{path}")
    return path


@pytest.fixture
def tmp_output_dir(tmp_path: Path) -> Path:
    """A temporary directory for test artifacts (episodes, encoded files, ...)."""
    out = tmp_path / "airdc_out"
    out.mkdir()
    return out
