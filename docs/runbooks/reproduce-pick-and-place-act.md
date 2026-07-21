# Runbook：复现固定目标台 pick_and_place ACT 训练

本文档记录固定目标台 `pick_and_place` 的通用复现流程，以及本轮排查中遇到的坑。它默认面向普通本地机器或有图形界面的工作站；无图形界面的服务器只需要看“Headless 服务器附录”。

目标：

- 让模型稳定学习固定目标台位置。
- 让评估能识别“没抓住”“掉了”“没放上去”“放歪了”等失败。
- 保证训练、评估、数据检查能被别人复现，而不是依赖某一台服务器的特殊路径。

## 路径约定

后续命令尽量使用变量。请按自己的机器修改：

```bash
export AIRDC_ROOT=/path/to/airdc
export AAO_ROOT=/path/to/auto-atomic-operation
export RUN_ROOT=/path/to/airdc_runs
export CKPT="$AIRDC_ROOT/outputs/best_pick_and_place_fixed_target_100000/pretrained_model"
```

如果 `auto-atomic-operation` 是本仓库里的软链接，也可以这样：

```bash
export AIRDC_ROOT=/path/to/airdc
export AAO_ROOT="$AIRDC_ROOT/third_party/auto-atomic-operation"
export RUN_ROOT="$AIRDC_ROOT/outputs/train_runs"
```

这台服务器上的历史路径仅作为例子：

```text
AIRDC_ROOT=/root/shared-nvme/airdc
AAO_ROOT=/root/shared-nvme/airdc/third_party/auto-atomic-operation
RUN_ROOT=/root/airdc_fixed_runs
```

## 本地环境

普通本地机器或有桌面环境时，不需要设置 EGL/headless 变量。

```bash
cd "$AIRDC_ROOT"
source .venv/bin/activate
```

确认 CUDA 可用：

```bash
python - <<'PY'
import torch
print(torch.__version__)
print(torch.cuda.is_available())
print(torch.cuda.get_device_name(0) if torch.cuda.is_available() else None)
PY
```

如果只是 CPU 机器，也可以跑数据检查和小步数 smoke test，但正式训练会很慢。

## 任务配置

AAO 配置文件：

```text
$AAO_ROOT/aao_configs/pick_and_place.yaml
```

当前任务固定目标台，只随机 source block：

```yaml
randomization:
  source_block:
    x: [-0.03, 0.03]
    y: [-0.03, 0.03]
    collision_radius: 0.04
  # target_pedestal:
  #   x: [-0.03, 0.03]
  #   y: [-0.03, 0.03]
  #   collision_radius: 0.04
```

必须保留严格放置判定，否则内部 evaluator 可能把“释放了但没放上去”算成功：

```yaml
placed_tolerance:
  position: [0.01, 0.01, null]
  orientation: [0.087, 0.087, null]
```

含义：

- `position` 只约束目标台 XY，容差 1 cm。
- Z 不约束，因为释放后高度由接触求解决定。
- `orientation` 约束 roll/pitch，容差约 5 度。
- yaw 不约束，因为绕竖直轴旋转不影响竖直放置。

## 数据集

本轮使用的数据：

```text
$AIRDC_ROOT/data/aao_data_fast_0
```

它满足固定目标台任务。历史检查结果：

```text
episodes=200
frames=49372
release_xy 唯一值=[0.12, 0.0]
max error=2.68e-09 m
```

复查命令：

```bash
cd "$AIRDC_ROOT"
source .venv/bin/activate

python - <<'PY'
from pathlib import Path
import numpy as np
from mcap_data_loader.datasets.mcap_dataset import McapFlatBuffersSampleDataset, McapFlatBuffersSampleDatasetConfig

root = Path("data/aao_data_fast_0")
files = sorted(root.glob("*.mcap"), key=lambda p: int(p.stem))
place = []
bad = []
frames = 0

for p in files:
    cfg = McapFlatBuffersSampleDatasetConfig(
        data_root=str(p),
        topics={"action/arm/pose/position", "action/gripper/joint_state/position"},
        attachments=set(),
        with_timestamp=False,
    )
    ds = McapFlatBuffersSampleDataset(cfg)
    pos = []
    grip = []
    for sample in ds.read_stream():
        pos.append(sample["action/arm/pose/position"])
        grip.append(float(sample["action/gripper/joint_state/position"][0]))
    pos = np.asarray(pos)
    grip = np.asarray(grip)
    frames += len(pos)
    changes = np.where(np.abs(np.diff(grip)) > 1e-6)[0] + 1
    if len(changes) < 2:
        bad.append(p.name)
        continue
    place.append(pos[changes[-1]:, :2])

place = np.concatenate(place, axis=0)
print("episodes", len(files), "bad", len(bad), "frames", frames)
print("release_xy_min", place.min(axis=0).tolist())
print("release_xy_max", place.max(axis=0).tolist())
print("unique_release_xy_rounded_6", len(np.unique(np.round(place, 6), axis=0)))
print("max_abs_err_to_0.12_0", float(np.abs(place - np.array([0.12, 0.0])).max()))
PY
```

## 训练配置

训练配置文件：

```text
$AIRDC_ROOT/configs/config.yaml
```

当前基线的关键项：

```yaml
batch_size: 8
num_workers: 2
steps: 100000

policy:
  type: act
  chunk_size: 30
  n_action_steps: 30

dataset:
  root: data
  repo_id:
    - aao_data_fast_0
  streaming: true

mcap:
  action_position_delta: true
  state_position_key: arm/pose/position
  action_position_key: action/arm/pose/position
  states:
    - arm/pose/position
    - arm/pose/rotation_6d
    - gripper/joint_state/position
  actions:
    - action/arm/pose/position
    - action/arm/pose/orientation
    - action/gripper/joint_state/position
  images:
    - wrist_cam/color/image_raw
    - env1_cam/color/image_raw
```

注意：当前 `action_position_delta` 的语义是“ACT 整个 action chunk 相对同一个观测起点”，不是“每一步相对当前末端”。训练和评估必须保持一致。

如果希望把闭环重规划作为默认训练/推理形态，下一轮训练建议尝试：

```yaml
policy:
  chunk_size: 30
  n_action_steps: 1
```

这样模型仍学习未来 30 步，但每次只执行第一个动作，更接近 `--replan-every-step` 的行为。

## 训练命令

从零训练：

```bash
cd "$AIRDC_ROOT"
source .venv/bin/activate

RUN_DIR="$RUN_ROOT/fast_fixed_$(date +%Y%m%d_%H%M%S)_act"
mkdir -p "$RUN_DIR"

mcap_lerobot_train -c configs/config.yaml \
  --steps=100000 \
  --batch_size=8 \
  --num_workers=2 \
  --policy.use_amp=true \
  --save_freq=20000 \
  --log_freq=1000 \
  --wandb.enable=false \
  --output_dir="$RUN_DIR"
```

从某个 checkpoint 续训到 100K：

```bash
cd "$AIRDC_ROOT"
source .venv/bin/activate

RUN_DIR="$RUN_ROOT/fast_fixed_20260612_120719_act"

mcap_lerobot_train -c configs/config.yaml \
  --config_path="$RUN_DIR/checkpoints/060000/pretrained_model/train_config.json" \
  --resume=true \
  --steps=100000 \
  --batch_size=8 \
  --num_workers=2 \
  --policy.use_amp=true \
  --save_freq=20000 \
  --log_freq=1000 \
  --wandb.enable=false \
  --output_dir="$RUN_DIR"
```

`--resume=true` 时，LeRobot 会从 `--config_path` 所在 checkpoint 读取训练状态。`--steps=100000` 是总步数，不是额外再跑 100K。

## 评估命令

普通本地环境先用这个命令。默认关闭 viewer，方便批量跑；如果要看图形界面，去掉 `--override '+env.viewer.disable=true'`。

```bash
cd "$AAO_ROOT"
source "$AIRDC_ROOT/.venv/bin/activate"

python3 examples/act_policy_eval.py \
  --checkpoint "$CKPT" \
  --config-name pick_and_place \
  --batch-size 1 \
  --num-rollouts 20 \
  --max-steps 260 \
  --override '+env.viewer.disable=true' \
  --delta-position-action \
  --lock-vertical-orientation \
  --replan-every-step
```

必须加：

- `--delta-position-action`，因为训练标签是 delta position。
- `--lock-vertical-orientation`，因为训练数据中的姿态是固定竖直姿态，此选项能避免模型输出四元数的小噪声影响放置。
- `--replan-every-step`，因为这个模型的 delta 是相对 chunk 起点的；每步重规划能让模型基于最新观测重新预测，抓取和放置更稳。

评估脚本默认还会做最终物体位姿硬检查：

```text
strict_final_placement = true
final_place_xy_tol = 0.01 m
final_place_tilt_tol = 5 deg
final_place_min_z_over_target = 0.03 m
```

输出里的 `evaluator_success` 是 AAO 内部阶段结果，`final_place` 是额外检查真实 `source_block` 是否最终落在 `target_pedestal` 上。最终成功率使用二者的交集，能避免“没抓住/掉了但 released 了”被算作成功。

不要在最终汇报成功率时加：

- `--place-xy-from-target`

这个选项只用于诊断，会在 place 阶段强行把 XY 对准目标台，不能代表模型真实能力。

## 保存最佳模型

把最佳 checkpoint 复制到项目输出目录：

```bash
BEST_SRC="$RUN_ROOT/fast_fixed_20260612_120719_act/checkpoints/100000/pretrained_model"
BEST_DST="$AIRDC_ROOT/outputs/best_pick_and_place_fixed_target_100000/pretrained_model"
mkdir -p "$BEST_DST"
rsync -a "$BEST_SRC"/ "$BEST_DST"/
```

确认文件完整：

```bash
find "$BEST_DST" -maxdepth 1 -type f -printf '%f %s\n' | sort
sha256sum "$BEST_DST/model.safetensors" "$BEST_SRC/model.safetensors"
```

两个 `model.safetensors` 的哈希应一致。

## 必做检查

### 1. 检查训练 batch 里的图像

之前遇到过视频解码或 key 映射问题，导致模型训练时看到黑图或静态图。使用仓库脚本检查：

```bash
cd "$AIRDC_ROOT"
source .venv/bin/activate

python scripts/check_lerobot_image_batch.py \
  -c configs/config.yaml \
  --batches=2 \
  --batch-size=8 \
  --num-workers=0 \
  --output-dir="$RUN_ROOT/image_check_fast0" \
  --no-fail
```

正常结果应满足：

- `all_black_samples=0`
- `near_constant_samples=0`
- 两路图像 key 存在：`observation.images.wrist_cam`、`observation.images.env1_cam`

### 2. 检查 normalizer

之前最致命的问题是图像 stats 为空，`std=0`，导致预处理后输入爆炸到 `1e7` 级别。当前修复后的 checkpoint 应该是 ImageNet stats，并且 state std 有下限。

```bash
cd "$AIRDC_ROOT"
source .venv/bin/activate

python - <<'PY'
import os
from safetensors.torch import load_file

ckpt = os.environ["CKPT"]
p = f"{ckpt}/policy_preprocessor_step_3_normalizer_processor.safetensors"
d = load_file(p)

for key in ["observation.images.env1_cam", "observation.images.wrist_cam"]:
    print(key, "count", float(d[key + ".count"]))
    print(key, "mean", d[key + ".mean"].flatten().tolist())
    print(key, "std", d[key + ".std"].flatten().tolist())

print("state_std_min", float(d["observation.state.std"].min()))
PY
```

正常结果：

```text
image count > 0
image mean = [0.485, 0.456, 0.406]
image std = [0.229, 0.224, 0.225]
state_std_min = 0.01
```

### 3. 检查 GPU 是否真的在训练

```bash
nvidia-smi
```

训练中应看到 Python 进程和 GPU 利用率。当前 RTX 3090 基线训练约：

```text
显存约 3.4 GB
GPU util 约 75% 到 85%
速度约 9 到 10 step/s
```

如果 `nvidia-smi` 没有进程，先确认 torch CUDA：

```bash
python - <<'PY'
import torch
print(torch.__version__)
print(torch.cuda.is_available())
print(torch.cuda.get_device_name(0) if torch.cuda.is_available() else None)
PY
```

## 常见坑

### LFS 下载慢

如果另一台机器已经完整拉过 LFS，可以直接传到目标机器。`rsync` 出现权限设置失败不一定影响数据内容：

```text
failed to set permissions ... Operation not permitted
rsync error code 23
```

这种通常是目标文件系统不允许设置某些权限。重传时可用：

```bash
rsync -av --no-perms --no-owner --no-group <local_path>/ <target_path>/
```

传完后用文件数、大小、关键 checkpoint 或数据检查脚本确认内容，而不是只看 `rsync` 的退出码。

### 不建议直接搬 `.venv`

只有在两边系统、Python 小版本、CUDA、glibc、CPU/GPU 架构非常接近时，直接传 `.venv` 才相对安全。否则更推荐传 wheelhouse 或在目标环境里安装依赖。

### `batch_size` 变大不一定更快

当前模型显存使用不高，但瓶颈可能在模型更新、视频解码或 Python pipeline。盲目增大 `batch_size` 可能导致每步更慢，吞吐未必提升。本轮稳定配置是：

```yaml
batch_size: 8
num_workers: 2
```

### `num_workers` 太高可能触发 DataLoader worker 崩溃

之前遇到过 worker segmentation fault。当前稳定配置是 `num_workers=2`。如果再遇到 worker crash，先降到：

```bash
--num_workers=0
```

确认数据能跑通，再尝试 `2` 或 `4`。

### 磁盘 quota

checkpoint 会占空间。共享盘或网络盘上容易遇到：

```text
Disk quota exceeded
```

建议把训练输出放到空间更充足的本地盘，并定期检查：

```bash
df -h "$AIRDC_ROOT" "$RUN_ROOT"
```

### `mcap_lerobot_train` 的 resume 参数

这个 wrapper 仍然要求 `-c configs/config.yaml`。续训时不是用 `--config_path` 替代 `-c`，而是两者都要传：

```bash
mcap_lerobot_train -c configs/config.yaml \
  --config_path=<checkpoint>/pretrained_model/train_config.json \
  --resume=true
```

### delta action 的语义

当前不是逐步 delta：

```text
action_chunk[k].pos = absolute_target_pos[t+k] - eef_pos[t]
```

也就是 chunk 内所有未来目标都相对同一个观测起点。评估脚本按这个语义还原：

```text
absolute_pos[k] = chunk_start_eef_pos + predicted_delta[k]
```

不要只在推理端改成逐步累加，否则训练和推理语义不一致，会漂移。

### 看到“到蓝色木块上方停住”

优先排查：

1. 图像 stats 是否为空或 `std=0`。
2. 图像 batch 是否黑屏或静态。
3. `--delta-position-action` 是否忘了加。
4. `action_position_delta` 训练配置和评估参数是否一致。
5. 是否需要 `--replan-every-step` 或把下一轮训练改成 `n_action_steps: 1`。

## Headless 服务器附录

只有在没有图形界面、没有 `DISPLAY`、或者评估/渲染报 GLFW/X11 错误时，才需要本节。

典型错误：

```text
GLFWError: X11: The DISPLAY environment variable is missing
ERROR: could not initialize GLFW
```

服务器上可以关闭 viewer：

```bash
--override '+env.viewer.disable=true'
```

如果还需要 MuJoCo headless GPU 渲染，使用 EGL：

```bash
unset DISPLAY
export LD_LIBRARY_PATH=/usr/local/nvidia-550.54.14/lib64:$LD_LIBRARY_PATH
export __EGL_VENDOR_LIBRARY_FILENAMES=/usr/share/glvnd/egl_vendor.d/10_nvidia.json
export PYOPENGL_PLATFORM=egl
export MUJOCO_GL=egl
export SDL_VIDEODRIVER=dummy
```

上面的 NVIDIA driver 路径是这台服务器的路径，其他机器要按实际路径调整。普通本地/有桌面环境不要照搬这段。

确认不是 CPU llvmpipe：

```bash
cd "$AIRDC_ROOT"
source .venv/bin/activate

PYOPENGL_PLATFORM=egl MUJOCO_GL=egl \
python -c "import mujoco; from OpenGL import GL; m=mujoco.MjModel.from_xml_string('<mujoco><visual><global offwidth=\"640\" offheight=\"480\"/></visual><worldbody><geom type=\"sphere\" size=\"0.1\"/></worldbody></mujoco>'); d=mujoco.MjData(m); r=mujoco.Renderer(m,480,640); r.update_scene(d); r.render(); print(GL.glGetString(GL.GL_VENDOR)); print(GL.glGetString(GL.GL_RENDERER))"
```

正确输出应包含 NVIDIA；如果看到 `Mesa` 或 `llvmpipe`，说明在 CPU 软件渲染。

`MUJOCO_GL=osmesa` 是 CPU 软件渲染，不会用 GPU。

## 当前历史结果

旧版只看 AAO 内部 evaluator 的严格评估曾得到：

```text
20K: 6/20 = 30%
40K: 11/20 = 55%
60K: 15/20 = 75%
100K: 20/20 = 100%
```

后来发现内部 evaluator 在某些 released-only 场景下会把“没抓住/掉了”误算成功，所以现在必须同时看 `final_place=True`。在加入最终物体位姿硬检查后，历史 100K 模型需要重新按新口径评估，不要直接把旧 `20/20` 当成真实最终成功率。

## 相关文件

- [MCAP 数据检查手册](./inspect-mcap-dataset.md)
- [性能测试](../troubleshooting/performance.md)
- 训练配置：`configs/config.yaml`
- AAO 任务配置：`$AAO_ROOT/aao_configs/pick_and_place.yaml`
- 图像 batch 检查：`scripts/check_lerobot_image_batch.py`
