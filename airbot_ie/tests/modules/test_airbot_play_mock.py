"""AIRBOT Play robot logic exercised through the software mock (no real robot).

Reuses ``airbot_ie.robots.airbot_play_mock``, so these run anywhere — pure
software. Each test builds its own AIRBOTPlay instance. Was previously a
top-level assert script (`robot/airbot_play.py`).
"""

import numpy as np
import pytest

# airbot_ie pulls in airbot_hardware_py transitively; in environments without it
# (e.g. the pixi/ROS env) skip the whole module instead of erroring at collection.
pytest.importorskip(
    "airbot_ie.robots.airbot_play_mock",
    reason="airbot_ie 依赖未满足（如 airbot_hardware_py 未安装），跳过",
)

from airbot_ie.robots.airbot_play import (  # noqa: E402
    InterfaceType,
    ObservationConfig,
    ReferenceMode,
    SystemMode,
)
from airbot_ie.robots.airbot_play_mock import (  # noqa: E402
    AIRBOTPlay,
    AIRBOTPlayConfig,
)
from airdc.common.configs.control import (  # noqa: E402
    JointPositionPlan,
    JointPositionServo,
    PosePlan,
    PoseServo,
)
from mcap_data_loader.utils.transformations import (  # noqa: E402
    quaternion_from_euler,
)

pytestmark = pytest.mark.software


def test_abs_joint_position_control():
    """Default config: absolute joint-position control round-trips through obs."""
    airbot_play = AIRBOTPlay()
    assert airbot_play.configure()
    airbot_play.switch_mode(SystemMode.RESETTING)

    action = [0.01] * 6 + [0.02]
    airbot_play.send_action(action)
    obs = airbot_play.capture_observation()
    assert "eef/pose/position" in obs
    assert action[:6] == obs["arm/joint_state/position"]["data"]
    assert action[6:] == obs["eef/joint_state/position"]["data"]

    airbot_play.switch_mode(SystemMode.SAMPLING)
    airbot_play.send_action([0.02] * 6 + [0.01])
    airbot_play.capture_observation()
    assert airbot_play.shutdown()


def test_abs_pose_control():
    """Absolute pose control: eef pose/orientation echo the commanded action."""
    action = [[[0.1, 0.1, 0.1], quaternion_from_euler(0.1, 0, 0).tolist()], 0.02]
    airbot_play = AIRBOTPlay(
        AIRBOTPlayConfig(
            action=[
                {SystemMode.RESETTING: PosePlan(), SystemMode.SAMPLING: PoseServo()},
                {
                    SystemMode.RESETTING: JointPositionPlan(),
                    SystemMode.SAMPLING: JointPositionServo(),
                },
            ]
        )
    )
    assert airbot_play.configure()
    airbot_play.switch_mode(SystemMode.RESETTING)
    airbot_play.send_action(action)
    obs = airbot_play.capture_observation()
    assert obs["eef/pose/position"]["data"] == action[0][0]
    assert obs["eef/pose/orientation"]["data"] == action[0][1]
    assert obs["eef/joint_state/position"]["data"] == action[1:]

    airbot_play.switch_mode(SystemMode.SAMPLING)
    action = [[[0.2, 0.2, 0.2], quaternion_from_euler(0.2, 0, 0).tolist()], 0.02]
    airbot_play.send_action(action)
    obs = airbot_play.capture_observation()
    assert obs["eef/pose/position"]["data"] == action[0][0]
    assert obs["eef/pose/orientation"]["data"] == action[0][1]
    assert obs["eef/joint_state/position"]["data"] == action[1:]
    assert airbot_play.shutdown()


@pytest.mark.xfail(
    reason="pre-existing break: VectorRelaAbs.ref_vec is unset before the first "
    "relative observation with the current mcap_data_loader "
    "(rela_abs.py). Tracks the relative-to-init obs path; see task backlog.",
    strict=False,
)
def test_relative_to_init_pose_servo():
    """Relative-to-init pose servo: rela channels reset to zero after mode switch."""
    action = [[[0.1, 0.1, 0.1], quaternion_from_euler(0.1, 0, 0).tolist()], 0.02]
    airbot_play = AIRBOTPlay(
        AIRBOTPlayConfig(
            action=[
                {
                    SystemMode.RESETTING: PosePlan(),
                    SystemMode.SAMPLING: PoseServo(
                        reference_mode=ReferenceMode.INIT_ACTION
                    ),
                },
                {
                    SystemMode.RESETTING: JointPositionPlan(),
                    SystemMode.SAMPLING: JointPositionServo(),
                },
            ],
            observation=[
                ObservationConfig(
                    reference_mode=ReferenceMode.INIT_STATE,
                    interfaces=InterfaceType.joint_states(),
                ),
                # we only want pose to be relative for eef
                ObservationConfig(
                    interfaces=InterfaceType.joint_states() | {InterfaceType.POSE},
                    kind_ref={"pose": ReferenceMode.INIT_STATE},
                ),
            ],
        )
    )
    assert airbot_play.configure()

    airbot_play.switch_mode(SystemMode.RESETTING)
    airbot_play.send_action(action)
    # the action is sent after switching mode, so the refs are not updated yet
    obs = airbot_play.capture_observation()
    assert obs["eef/pose/position"]["data"] == action[0][0]
    assert obs["eef/pose/orientation"]["data"] == action[0][1]
    assert obs["eef/joint_state/position"]["data"] == action[1:]
    assert obs["eef/pose/position_rela"]["data"] == action[0][0]
    assert obs["eef/pose/orientation_rela"]["data"] == action[0][1]

    # switching mode updates the refs, so now the rela channels are zero
    airbot_play.switch_mode(SystemMode.SAMPLING)
    obs = airbot_play.capture_observation()
    assert obs["eef/pose/position_rela"]["data"] == [0, 0, 0]
    assert obs["eef/pose/orientation_rela"]["data"] == [0, 0, 0, 1]

    # the action in sampling mode is relative to the init action
    airbot_play.send_action(action)
    obs = airbot_play.capture_observation()
    assert obs["eef/pose/position"]["data"] == [0.2, 0.2, 0.2]
    assert (
        obs["eef/pose/orientation"]["data"] == quaternion_from_euler(0.2, 0, 0).tolist()
    )
    assert obs["eef/joint_state/position"]["data"] == action[1:]
    assert obs["eef/pose/position_rela"]["data"] == [0.1, 0.1, 0.1]
    assert np.allclose(
        obs["eef/pose/orientation_rela"]["data"],
        quaternion_from_euler(0.1, 0, 0).tolist(),
    )
    assert airbot_play.shutdown()
