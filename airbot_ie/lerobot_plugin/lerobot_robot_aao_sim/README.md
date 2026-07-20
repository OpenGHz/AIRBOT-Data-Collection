# lerobot_robot_aao_sim

A [LeRobot](https://github.com/huggingface/lerobot) `Robot` plugin that runs a
trained LeRobot policy inside the **auto-atomic-operation (aao)** MuJoCo
simulator — no real hardware. It wraps `auto_atom`'s `UnifiedMujocoEnv`:

| LeRobot | aao MuJoCo env |
|---|---|
| `connect()` | build task backend from a config + `reset()` (batch=1) |
| `get_observation()` | `capture_observation()` → flat EEF-pose state |
| `send_action()` | flat action → `apply_pose_action(pos, quat, gripper)` + step |
| `disconnect()` | backend `teardown()` |

**State-only (EEF pose)** for now: `observation.state` = end-effector
position(3) + orientation(4, xyzw) [+ gripper], and `action` the same. This
matches eef-pose checkpoints (e.g. the MCAP-trained pi0.5/SmolVLA configs) and
avoids the headless-EGL dependency that camera rendering needs. Cameras can be
added later.

## Run (pixi `infer-aao` env)

```bash
pixi run -e infer-aao mcap-lerobot-infer \
  -c airbot_ie/lerobot_plugin/configs/aao_sim_infer.yaml
```

or via LeRobot's native CLI:

```bash
pixi run -e infer-aao lerobot-rollout \
  --robot.type=aao_sim --robot.task_config=<aao_scene> \
  --policy.path=<your_checkpoint> --task="..."
```

Match `state_keys`/`action_keys` and `task_config` to whatever the checkpoint
was trained on.
