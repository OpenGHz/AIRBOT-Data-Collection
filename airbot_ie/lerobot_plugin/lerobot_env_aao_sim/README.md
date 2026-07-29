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

Action is always 8-dim quaternion (pos3 + quat4 + grip1), regardless of
`observation_rotation`, because `apply_pose_action` consumes quaternions.

## rot6d convention conversion

When `observation_rotation=rot6d`, the simulator natively emits **row-major**
rot6d (`rot9d[:6]` = first 2 rows of R).  Policies trained on **real-robot**
data expect **column-major** rot6d (first 2 columns of R, produced by
`Rotation6D.quat_to_rot6d()`).  Two config flags bridge this gap:

### `obs_convention` — what the policy *receives*

| Value | Effect | Use when |
|---|---|---|
| `sim` (default) | No conversion; policy sees row-major obs | checkpoint trained on **sim** data |
| `real` | Sim obs converted to col-major before policy | checkpoint trained on **real-robot** data |

### `action_convention` — what the policy *outputs* (only for `action_rotation=rot6d`)

| Value | Effect | Use when |
|---|---|---|
| `real` (default) | No conversion; `rot6d_to_quat()` receives col-major directly | checkpoint outputs col-major rot6d action |
| `sim` | Action converted from row-major to col-major before `step()` | checkpoint outputs row-major rot6d action |

> `action_convention` has no effect when `action_rotation=quat` (the default).

### Quick-reference: which flags to set

| Checkpoint origin | `obs_convention` | `action_rotation` | `action_convention` |
|---|---|---|---|
| Real-robot data, **quat** action *(e.g. absolute_random_wrist)* | `real` | `quat` (default) | — |
| Real-robot data, **rot6d** action | `real` | `rot6d` | `real` (default) |
| Sim data, **quat** action | `sim` (default) | `quat` (default) | — |
| Sim data, **rot6d** action | `sim` (default) | `rot6d` | `sim` |

### Example — ACT checkpoint trained on real data, quat action

```bash
pixi run -e infer-aao lerobot-eval \
  --policy.path=models_open_door/absolute_random_wrist/pretrained_model \
  --env.type=aao_sim \
  --env.task_config=open_door \
  --env.observation_rotation=rot6d \
  --env.obs_convention=real \
  --eval.n_episodes=10 \
  --eval.batch_size=1 \
  --policy.device=cuda
```

### Example — ACT checkpoint trained on sim data, quat action

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

*(no `--env.obs_convention` needed; default `sim` passes obs through unchanged)*

### How to tell which convention your checkpoint uses

If you are unsure: run both and compare `pc_success`.  A policy receiving the
wrong convention will produce erratic, near-zero success even if inference
runs without errors.

Alternatively, check the MCAP training data source:
- Data recorded on the **real robot** → col-major (`obs_convention=real`)
- Data recorded from the **simulator** → row-major (`obs_convention=sim`)
