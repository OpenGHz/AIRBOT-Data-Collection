"""Natural-sort of ROS topic names: camera topics grouped last, natural order within.

Pure software — no hardware. Was previously a print-only demo script.
"""

import pytest
from natsort import natsort_keygen, natsorted

pytestmark = pytest.mark.software


TOPICS = [
    "/robot/tactile/gripper/finger1/points",
    "/robot/camera/env2/mask/heat_map",
    "/robot/camera/wrist/video_encoded",
    "/robot/camera/env2/camera_info",
    "/robot/camera/wrist/mask/heat_map",
    "/robot/camera/wrist/depth/image_raw",
    "/robot/camera/env1/hand_eye/transform",
    "/robot/tactile/gripper/finger2/points",
    "/robot/arm/pose/rotation_6d",
    "/robot/action/arm/joint_state",
    "/robot/camera/wrist/camera_info",
    "/robot/camera/env1/mask/heat_map",
    "/robot/gripper/joint_state",
    "/robot/action/gripper/joint_state",
    "/robot/action/arm/pose",
    "/robot/arm/joint_state",
    "/robot/camera/env2/video_encoded",
    "/robot/camera/env1/camera_info",
    "/robot/camera/env2/depth/image_raw",
    "/robot/arm/pose/rotation",
    "/robot/camera/env1/video_encoded",
    "/robot/camera/env1/depth/image_raw",
    "/robot/arm/pose",
    "/robot/camera/env2/hand_eye/transform",
    "/robot/camera/wrist/hand_eye/transform",
]

_natsort_key = natsort_keygen()


def natural_sort(values: list[str]) -> list[str]:
    """Sort topics naturally, pushing every ``/camera/`` topic to the end."""
    return sorted(values, key=lambda topic: ("/camera/" in topic, _natsort_key(topic)))


def test_camera_topics_are_grouped_last():
    result = natural_sort(TOPICS)
    non_camera = [t for t in result if "/camera/" not in t]
    camera = [t for t in result if "/camera/" in t]

    # Every non-camera topic must precede every camera topic.
    last_non_camera = max(result.index(t) for t in non_camera)
    first_camera = min(result.index(t) for t in camera)
    assert last_non_camera < first_camera

    # Within each group, ordering is the natural sort of that group.
    assert non_camera == natsorted(non_camera)
    assert camera == natsorted(camera)


def test_natural_sort_is_a_permutation():
    result = natural_sort(TOPICS)
    assert sorted(result) == sorted(TOPICS)
    assert len(result) == len(TOPICS)
