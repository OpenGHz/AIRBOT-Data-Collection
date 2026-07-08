"""Camera hardware smoke tests — connect to a real device and capture one frame.

``@hardware`` + a fine-grained marker means the conftest probe auto-skips these
when no device is present, so they never turn red on a hardware-less machine.
The pure-software equivalent is the ``mock_camera`` fixture (see conftest.py).
"""

import numpy as np
import pytest


def _as_array(value):
    """A camera observation value may be a bare ndarray or {'t':..., 'data': ndarray}."""
    if isinstance(value, dict) and "data" in value:
        return value["data"]
    return value


def _assert_has_frame(obs) -> None:
    assert isinstance(obs, dict) and obs, "observation should be a non-empty dict"
    arrays = [_as_array(v) for v in obs.values()]
    has_image = any(isinstance(a, np.ndarray) and a.size > 0 for a in arrays)
    assert has_image, "expected at least one non-empty image ndarray in observation"


@pytest.mark.hardware
@pytest.mark.realsense
def test_realsense_captures_one_color_frame():
    from airdc.common.devices.cameras.intelrealsense import (
        IntelRealSenseCamera,
        IntelRealSenseCameraConfig,
        find_camera_indices,
    )

    serials = find_camera_indices()
    assert serials, "probe reported a RealSense but none were enumerated"

    camera = IntelRealSenseCamera(
        IntelRealSenseCameraConfig(
            camera_index=serials[0],
            width=640,
            height=480,
            fps=30,
            enable_depth=False,
        )
    )
    assert camera.configure()
    try:
        _assert_has_frame(camera.capture_observation())
    finally:
        camera.shutdown()


@pytest.mark.hardware
@pytest.mark.camera
def test_v4l2_camera_captures_one_frame():
    from airdc.common.devices.cameras.v4l2 import V4L2Camera, V4L2CameraConfig

    camera = V4L2Camera(V4L2CameraConfig(width=640, height=480, fps=30))
    assert camera.configure()
    try:
        _assert_has_frame(camera.capture_observation())
    finally:
        camera.shutdown()
