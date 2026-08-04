# lerobot_env_aao_sim

LeRobot **Env** plugin: a `gymnasium.Env` over the auto-atomic-operation (aao)
MuJoCo simulator, for **native success-rate evaluation** with `lerobot-eval`.

## Why this exists

`lerobot-rollout` (the Robot path used by `lerobot_robot_aao_sim`) is written for
real hardware — it has no success detection and just runs to `duration`.
`lerobot-eval` drives a gymnasium `VectorEnv` and computes `pc_success` natively
from each env's `step()` returning `info["is_success"]`. This plugin supplies
that env, so you get success rate + mp4 videos out of the box.

LeRobot auto-discovers this by the distribution name prefix `lerobot_env_`, and
`@EnvConfig.register_subclass("aao_sim")` registers `--env.type=aao_sim`.

## Success signal

`step()` reports success via `backend.is_object_displaced(success_object,
initial_pose, threshold)` — the same displacement check the aao task graph uses.
For `open_door` the target is `handle_body_phys` (threshold 0.01 m). Both are
config fields (`success_object`, `displacement_threshold`).

## Usage

```bash
pixi run -e infer-aao lerobot-eval \
  --policy.path=models_open_door/absolute_random_wrist/pretrained_model \
  --env.type=aao_sim \
  --env.task_config=open_door \
  --env.observation_rotation=rot6d \
  --eval.n_episodes=10 \
  --eval.batch_size=1 \
  --policy.device=cuda
```

Outputs: `outputs/eval/<run>/videos/*.mp4` + `metrics.json` with `pc_success`.

## observation_rotation

| Value | observation.state dim | Use when |
|---|---|---|
| `rot6d` (default) | 10 (pos3 + rot6d6 + grip1) | checkpoint trained with 6-D obs (e.g. absolute_random_wrist) |
| `quat` | 8 (pos3 + quat4 + grip1) | checkpoint trained with quaternion obs |

`action_rotation` controls the policy action representation:

| Value | action dim | Execution path |
|---|---|---|
| `quat` (default) | 8 (pos3 + quat4 + grip1) | passed directly to `apply_pose_action` |
| `rot6d` | 10 (pos3 + rot6d6 + grip1) | converted to quaternion before `apply_pose_action` |

## rot6d convention

AAO simulation, MCAP `Rotation6D.quat_to_rot6d()` conversion, and real-robot
data all use the same column-vector convention:

```text
[r00, r10, r20, r01, r11, r21]
```

It is the first two columns of the 3×3 rotation matrix. No observation or action
convention wrapper is required. Checkpoints trained with the old row-major
simulation representation are not compatible with this unified path and must
be converted or retrained.
