from airbot_ie.robots.airbot_play import (
    SystemMode,
    ReferenceMode,
    ObservationConfig,
    InterfaceType,
)
from airbot_ie.robots.airbot_play_mock import AIRBOTPlay, AIRBOTPlayConfig
from airdc.common.configs.control import (
    JointPositionServo,
    JointPositionPlan,
    JointMIT,
    PoseServo,
    PosePlan,
)
from mcap_data_loader.utils.transformations import quaternion_from_euler
from pprint import pprint
import numpy as np
import time


"""Test ABS Joint Position Control (default)"""
airbot_play = AIRBOTPlay()
config = airbot_play.config
# pprint(config.observation)
# pprint(config.as_dict)
# pprint(config.observation_info)
assert airbot_play.configure()
airbot_play.switch_mode(SystemMode.RESETTING)
action = [0.01] * 6 + [0.02]
airbot_play.send_action(action)
obs = airbot_play.capture_observation()
pprint(obs)
assert "eef/pose/position" in obs
assert action[:6] == obs["arm/joint_state/position"]["data"]
assert action[6:] == obs["eef/joint_state/position"]["data"]
airbot_play.switch_mode(SystemMode.SAMPLING)
airbot_play.send_action([0.02] * 6 + [0.01])
pprint(airbot_play.capture_observation())
assert airbot_play.shutdown()

"""Test ABS Pose Control"""
action = [[[0.1, 0.1, 0.1], quaternion_from_euler(0.1, 0, 0).tolist()], 0.02]
airbot_play = AIRBOTPlay(
    AIRBOTPlayConfig(
        action=[
            {
                SystemMode.RESETTING: PosePlan(),
                SystemMode.SAMPLING: PoseServo(),
            },
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
pprint(obs)
assert obs["eef/pose/position"]["data"] == action[0][0]
assert obs["eef/pose/orientation"]["data"] == action[0][1]
assert obs["eef/joint_state/position"]["data"] == action[1:]
airbot_play.switch_mode(SystemMode.SAMPLING)
action = [[[0.2, 0.2, 0.2], quaternion_from_euler(0.2, 0, 0).tolist()], 0.02]
airbot_play.send_action(action)
obs = airbot_play.capture_observation()
pprint(obs)
assert obs["eef/pose/position"]["data"] == action[0][0]
assert obs["eef/pose/orientation"]["data"] == action[0][1]
assert obs["eef/joint_state/position"]["data"] == action[1:]
assert airbot_play.shutdown()


"""Test Rela to init Pose Servo"""
print("Test Rela to init Pose Servo")
action = [[[0.1, 0.1, 0.1], quaternion_from_euler(0.1, 0, 0).tolist()], 0.02]
print("Action:", action)
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
config = airbot_play.config
pprint(config.as_dict)
assert airbot_play.configure()
print(time.perf_counter() * 1000)
airbot_play.switch_mode(SystemMode.RESETTING)
print(time.perf_counter() * 1000)
airbot_play.send_action(action)
print(time.perf_counter() * 1000)
# the action is sent after switching mode, so the refs are not updated
obs = airbot_play.capture_observation()
print(time.perf_counter() * 1000)
pprint(obs)
assert obs["eef/pose/position"]["data"] == action[0][0]
assert obs["eef/pose/orientation"]["data"] == action[0][1]
assert obs["eef/joint_state/position"]["data"] == action[1:]
assert obs["eef/pose/position_rela"]["data"] == action[0][0]
assert obs["eef/pose/orientation_rela"]["data"] == action[0][1]
# switch mode will update the refs, so now the rela will be 0
airbot_play.switch_mode(SystemMode.SAMPLING)
obs = airbot_play.capture_observation()
pprint(obs)
assert obs["eef/pose/position_rela"]["data"] == [0, 0, 0]
assert obs["eef/pose/orientation_rela"]["data"] == [0, 0, 0, 1]
# the action in sampling mode is relative to the init action
airbot_play.send_action(action)
obs = airbot_play.capture_observation()
pprint(obs)
assert obs["eef/pose/position"]["data"] == [0.2, 0.2, 0.2]
assert obs["eef/pose/orientation"]["data"] == quaternion_from_euler(0.2, 0, 0).tolist()
assert obs["eef/joint_state/position"]["data"] == action[1:]
assert obs["eef/pose/position_rela"]["data"] == [0.1, 0.1, 0.1]
assert np.allclose(
    obs["eef/pose/orientation_rela"]["data"], quaternion_from_euler(0.1, 0, 0).tolist()
)
assert airbot_play.shutdown()
