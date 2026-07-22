"""AAOSimRobot LeRobot plugin: EEF-pose feature contract.

Only exercises the feature contract and its validation, which are callable while
disconnected — so this needs neither MuJoCo/auto_atom nor a running sim.

The contract that matters here: LeRobot's rollout builds observation.state and
the action key order by keeping ONLY scalar features whose key ends in ".pos"
(lerobot/rollout/context.py). Keys failing that filter are dropped silently, so
a stray name shrinks the state/action vector with no error at all.
"""

import pytest

# The plugin imports lerobot.robots.Robot; auto_atom/mujoco are imported lazily
# inside connect(), so they are not needed here.
pytest.importorskip("lerobot.robots", reason="lerobot not installed")
pytest.importorskip(
    "lerobot_robot_aao_sim", reason="aao_sim plugin not installed in this env"
)

from lerobot_robot_aao_sim import AAOSimRobot, AAOSimRobotConfig  # noqa: E402

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


def test_default_pose_feature_contract():
    """Defaults are the 8-dim EEF-pose contract, in [position, orientation, gripper] order."""
    robot = AAOSimRobot(AAOSimRobotConfig())
    assert list(robot.action_features) == _POSE_FEATURES
    # No sim_cameras configured, so observation == state features.
    assert list(robot.observation_features) == _POSE_FEATURES


def test_features_survive_lerobot_pos_filter():
    """All 8 scalar features survive lerobot's `.pos` filter (none silently dropped)."""
    robot = AAOSimRobot(AAOSimRobotConfig())
    action_hw = [k for k in robot.action_features if k.endswith(".pos")]
    obs_hw = [
        k
        for k, v in robot.observation_features.items()
        if isinstance(v, tuple) or (v is float and k.endswith(".pos"))
    ]
    assert action_hw == _POSE_FEATURES
    assert obs_hw == _POSE_FEATURES


def test_non_pos_feature_name_rejected():
    """A feature key without the `.pos` suffix fails loudly instead of being dropped."""
    with pytest.raises(ValueError, match=r"must end in '\.pos'"):
        AAOSimRobot(AAOSimRobotConfig(position_keys=["eef.x", "eef.y", "eef.z"]))


def test_no_gripper_gives_seven_dims():
    """has_gripper=False yields the 7-dim pose-only contract."""
    robot = AAOSimRobot(AAOSimRobotConfig(has_gripper=False))
    assert list(robot.action_features) == _POSE_FEATURES[:-1]
