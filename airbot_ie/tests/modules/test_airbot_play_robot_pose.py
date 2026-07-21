"""AIRBOTPlayRobot LeRobot plugin: EEF-pose control mode (software mock).

Exercises the ``control_mode="pose"`` path of the LeRobot ``Robot`` adapter end
to end through the airbot software mock (no real robot, no policy): the 8-dim
feature contract (EEF pose + gripper) and a send_action -> get_observation
round-trip that routes through the airdc System's ``servo_cart_pose``.

This is the inference-side counterpart to the pose training contract in
``configs/{smolvla,pi05}_train.yaml`` (observation.state / action =
position[3] + orientation xyzw[4] + gripper[1]).
"""

import pytest

# The plugin imports lerobot.robots.Robot (needs a LeRobot install, e.g. the
# pixi smolvla-infer env) and the airbot mock (needs airbot_ie deps). Skip
# cleanly where either is unavailable rather than erroring at collection.
pytest.importorskip("lerobot.robots", reason="lerobot not installed")
pytest.importorskip(
    "airbot_ie.robots.airbot_play_mock",
    reason="airbot_ie deps unmet (e.g. airbot_hardware_py missing)",
)

from lerobot_robot_airbot_play import (  # noqa: E402
    AIRBOTPlayRobot,
    AIRBOTPlayRobotConfig,
)

pytestmark = pytest.mark.software

_POSE_FEATURES = [
    "eef.x",
    "eef.y",
    "eef.z",
    "eef.qx",
    "eef.qy",
    "eef.qz",
    "eef.qw",
    "gripper.pos",
]


def _pose_robot() -> AIRBOTPlayRobot:
    return AIRBOTPlayRobot(
        AIRBOTPlayRobotConfig(
            mock=True,
            control_mode="pose",
            components=["arm", "eef"],
            cameras={},
        )
    )


def test_pose_feature_contract():
    """observation/action features are the 8-dim EEF-pose contract, in order."""
    robot = _pose_robot()
    # Order must match the training concat order: position, orientation, gripper.
    assert list(robot.action_features) == _POSE_FEATURES
    # No cameras here, so observation == state features.
    assert list(robot.observation_features) == _POSE_FEATURES


def test_pose_send_action_roundtrips_through_observation():
    """send_action drives servo_cart_pose; get_observation echoes pose + gripper."""
    robot = _pose_robot()
    robot.connect()  # switches the mock System into SAMPLING (pose servo)
    try:
        action = {
            "eef.x": 0.1,
            "eef.y": 0.2,
            "eef.z": 0.3,
            "eef.qx": 0.0,
            "eef.qy": 0.0,
            "eef.qz": 0.0,
            "eef.qw": 1.0,
            "gripper.pos": 0.02,
        }
        robot.send_action(action)
        obs = robot.get_observation()

        assert set(obs) == set(_POSE_FEATURES)
        assert obs["eef.x"] == pytest.approx(0.1)
        assert obs["eef.y"] == pytest.approx(0.2)
        assert obs["eef.z"] == pytest.approx(0.3)
        assert obs["eef.qw"] == pytest.approx(1.0)
        assert obs["gripper.pos"] == pytest.approx(0.02)
    finally:
        robot.disconnect()


def test_joint_mode_default_unchanged():
    """Default control_mode stays joint: features are the <joint>.pos contract."""
    robot = AIRBOTPlayRobot(
        AIRBOTPlayRobotConfig(mock=True, components=["arm", "eef"], cameras={})
    )
    expected = [f"joint_{i}.pos" for i in range(1, 7)] + ["gripper.pos"]
    assert list(robot.action_features) == expected
