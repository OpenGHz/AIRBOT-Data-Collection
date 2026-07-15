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

Both the arm and the camera can be fully mocked: `mock=True` swaps the gRPC arm
backend for `AIRBOTArmMock`, and pointing a camera spec at the airdc `MockCamera`
gives synthetic frames — so the whole obs/action loop runs without any device.

```bash
pixi run -e infer python - <<'PY'
from lerobot_robot_airbot_play import (
    AIRBOTPlayRobot, AIRBOTPlayRobotConfig, AirdcCameraSpec,
)

robot = AIRBOTPlayRobot(AIRBOTPlayRobotConfig(
    mock=True,
    cameras={
        # airdc MockCamera -> synthetic (H, W, 3) uint8 frames
        "observation.images.rgb": AirdcCameraSpec(
            target="airdc.common.devices.cameras.mock.MockCamera",
            width=320, height=240, fps=30, extra={"random": True},
        ),
    },
))
robot.connect()
print(robot.observation_features)          # includes observation.images.rgb: (240, 320, 3)
obs = robot.get_observation()
print({k: getattr(v, "shape", v) for k, v in obs.items()})
robot.send_action({f"joint_{i}.pos": 0.0 for i in range(1, 7)} | {"gripper.pos": 0.0})
robot.disconnect()
PY
```

## Cameras (reused airdc devices)

Cameras are `airdc` sensor devices, referenced by import path. Any airdc camera
works — swap `target` (and `extra`) for the device you have:

- `airdc.common.devices.cameras.mock.MockCamera` — synthetic frames (testing)
- `airdc.common.devices.cameras.v4l2.V4L2Camera` — USB / V4L2, `extra={"camera_index": 0}`
- `airdc.common.devices.cameras.intelrealsense.*` — RealSense

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

The image observation key is exactly the dict key you choose (here
`observation.images.rgb`), and its `observation_features` shape is
`(height, width, 3)`.

## Policy inference

This LeRobot build deploys policies via `lerobot-rollout` (not `lerobot-record`,
which is data-collection only):

```bash
lerobot-rollout --robot.type=airbot_play --robot.url=localhost --robot.port=50050 \
  --policy.path=<your_checkpoint> ...
```
