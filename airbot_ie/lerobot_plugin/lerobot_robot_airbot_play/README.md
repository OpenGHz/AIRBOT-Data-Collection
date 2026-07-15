# lerobot_robot_airbot_play

A [LeRobot](https://github.com/huggingface/lerobot) `Robot` plugin that wraps the
AIRBOT Play arm (`airbot_ie.robots.airbot_play.AIRBOTPlay`, an `airdc` `System`)
so trained LeRobot policies can be run on the real hardware.

## What it does

It adapts the `airdc` control surface to the LeRobot `Robot` contract:

| LeRobot | airdc `AIRBOTPlay` |
|---|---|
| `connect()` | `System.configure()` + cameras + `switch_mode(SAMPLING)` |
| `disconnect()` | cameras `shutdown()` + `System.shutdown()` |
| `get_observation()` | `capture_observation()` → flat `"<joint>.pos"` + camera frames |
| `send_action()` | flat action dict → airdc stamped dict → `send_action()` |

Feature keys follow the LeRobot tutorial default: `joint_1.pos … joint_6.pos`,
`gripper.pos`, and each camera under its dict key. **To run a specific
checkpoint, the feature keys must match the ones it was trained on** — adjust
`arm_joint_names` / `gripper_joint_name` / camera keys in the config accordingly.

## Install

Runs in the same environment as `airbot_ie` / `airdc` / `airbot_py` / `lerobot`.

### Recommended: the repo's pixi `infer` environment

The parent repo ships a pixi `infer` environment that already bundles this
plugin (editable), `lerobot` (py≥3.12), `airbot_py`, and torch (CUDA 12.8):

```bash
# from the repo root
pixi run -e infer python -c "import lerobot_robot_airbot_play"
pixi shell -e infer      # or run commands with `pixi run -e infer ...`
```

Note: `lerobot` requires Python ≥ 3.12, so it cannot share the legacy py3.10
`airbot_play_data` conda env — use the pixi `infer` env (py3.12).

### Manual (other environments)

```bash
cd airbot_ie/lerobot_plugin/lerobot_robot_airbot_play
pip install -e .
```

## Offline smoke test (no hardware)

```bash
pixi run -e infer python - <<'PY'
from lerobot_robot_airbot_play import AIRBOTPlayRobot, AIRBOTPlayRobotConfig

robot = AIRBOTPlayRobot(AIRBOTPlayRobotConfig(mock=True))
robot.connect()
print(robot.observation_features)
print(robot.get_observation())
robot.send_action({f"joint_{i}.pos": 0.0 for i in range(1, 7)} | {"gripper.pos": 0.0})
robot.disconnect()
PY
```

## Cameras (reused airdc devices)

Cameras are `airdc` sensor devices, referenced by import path:

```python
from lerobot_robot_airbot_play import AIRBOTPlayRobotConfig, AirdcCameraSpec

cfg = AIRBOTPlayRobotConfig(
    url="localhost", port=50050,
    cameras={
        "observation.images.rgb": AirdcCameraSpec(
            target="airdc.common.devices.cameras.v4l2.V4L2Camera",
            width=640, height=480, fps=30, extra={"camera_index": 0},
        ),
    },
)
```

## Policy inference

This LeRobot build deploys policies via `lerobot-rollout` (not `lerobot-record`,
which is data-collection only):

```bash
lerobot-rollout --robot.type=airbot_play --robot.url=localhost --robot.port=50050 \
  --policy.path=<your_checkpoint> ...
```
