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
    "eef_x.pos",
    "eef_y.pos",
    "eef_z.pos",
    "eef_qx.pos",
    "eef_qy.pos",
    "eef_qz.pos",
    "eef_qw.pos",
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
            "eef_x.pos": 0.1,
            "eef_y.pos": 0.2,
            "eef_z.pos": 0.3,
            "eef_qx.pos": 0.0,
            "eef_qy.pos": 0.0,
            "eef_qz.pos": 0.0,
            "eef_qw.pos": 1.0,
            "gripper.pos": 0.02,
        }
        robot.send_action(action)
        obs = robot.get_observation()

        assert set(obs) == set(_POSE_FEATURES)
        assert obs["eef_x.pos"] == pytest.approx(0.1)
        assert obs["eef_y.pos"] == pytest.approx(0.2)
        assert obs["eef_z.pos"] == pytest.approx(0.3)
        assert obs["eef_qw.pos"] == pytest.approx(1.0)
        assert obs["gripper.pos"] == pytest.approx(0.02)
    finally:
        robot.disconnect()


def test_features_survive_lerobot_pos_filter():
    """Every scalar feature must end in '.pos' or LeRobot silently drops it.

    Mirrors lerobot/rollout/context.py, which builds observation.state and the
    action key order with ``v is float and k.endswith(".pos")`` (observation)
    and ``k.endswith(".pos")`` (action). A key failing this filter does NOT
    raise — it shrinks observation.state / the action vector (once reducing this
    8-dim pose contract to just the 1-dim gripper), so guard it here.
    """
    robot = _pose_robot()
    action_hw = [k for k in robot.action_features if k.endswith(".pos")]
    obs_hw = [
        k
        for k, v in robot.observation_features.items()
        if isinstance(v, tuple) or (v is float and k.endswith(".pos"))
    ]
    assert action_hw == _POSE_FEATURES
    assert obs_hw == _POSE_FEATURES


def test_pose_mode_requires_eef_component():
    """pose mode without `eef` fails loudly: there is no eef/pose/* to read."""
    with pytest.raises(ValueError, match="requires 'eef' in components"):
        AIRBOTPlayRobot(
            AIRBOTPlayRobotConfig(
                mock=True, control_mode="pose", components=["arm"], cameras={}
            )
        )


def test_joint_mode_default_unchanged():
    """Default control_mode stays joint: features are the <joint>.pos contract."""
    robot = AIRBOTPlayRobot(
        AIRBOTPlayRobotConfig(mock=True, components=["arm", "eef"], cameras={})
    )
    expected = [f"joint_{i}.pos" for i in range(1, 7)] + ["gripper.pos"]
    assert list(robot.action_features) == expected
