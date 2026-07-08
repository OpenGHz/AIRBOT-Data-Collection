"""ROS/MCAP depth-frame smoke test.

Reads a single depth frame from the bundled sample MCAP through ``McapROSReader``
+ ``cv_bridge`` and asserts it decodes to a 2-D ndarray. Requires a ROS toolchain
(``cv_bridge``), so it is marked ``@ros`` and auto-skips when ROS is absent
(prefer the pixi environment to run it). The ``sample_mcap`` fixture skips the
test if the sample data file is missing.
"""

import numpy as np
import pytest

pytestmark = [pytest.mark.hardware, pytest.mark.ros]

DEPTH_TOPIC = "/robot/camera/env1/depth/image_raw"


def test_reads_depth_frame_from_sample_mcap(sample_mcap):
    # cv_bridge is a finer dependency than $ROS_VERSION: skip (don't fail) when
    # the ROS env is present but cv_bridge isn't installed (e.g. pixi currently
    # comments out ros-jazzy-cv-bridge).
    cv_bridge = pytest.importorskip(
        "cv_bridge",
        reason="cv_bridge 未安装（如需运行请在 pixi 启用 ros-jazzy-cv-bridge）",
    )
    from mcap_data_loader.serialization.ros.mcap import McapROSReader

    bridge = cv_bridge.CvBridge()
    with open(sample_mcap, "rb") as f:
        reader = McapROSReader(f)
        for sample in reader.iter_samples([DEPTH_TOPIC]):
            image = bridge.imgmsg_to_cv2(sample[DEPTH_TOPIC]["data"])
            assert isinstance(image, np.ndarray)
            assert image.ndim == 2, "depth image should be single-channel"
            assert image.size > 0
            break
        else:
            pytest.fail(f"样例 MCAP 中没有话题 {DEPTH_TOPIC} 的样本")
