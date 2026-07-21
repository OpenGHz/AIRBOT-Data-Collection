# LeRobot 训练与推理工作流

AIRDC 通过 `airbot_ie/lerobot_plugin/` 支持基于 MCAP 数据的 VLA（视觉-语言-动作）模型训练与推理。当前支持 **SmolVLA**（~450M 参数，8 GiB 显存）和 **pi0.5**（~3.6B 参数，需 ~8 GiB 显存）两种模型。

## 架构

- **训练后端**：`mcap-data-loader` 包提供的 MCAP 数据集适配器，直接读 AIRDC 生成的 MCAP 文件，无需转换
- **推理后端**：两个 LeRobot `Robot` 插件
  - `lerobot_robot_airbot_play`：真机/Mock 推理（wraps `airbot_ie.robots.airbot_play.AIRBOTPlay`）
  - `lerobot_robot_aao_sim`：AAO MuJoCo 仿真推理（state-only EEF pose）
- **模型**：
  - SmolVLA：MEAN_STD 归一化，开箱即用
  - pi0.5：QUANTILES 归一化，需下载 gated PaliGemma tokenizer（`HF_TOKEN`）

## 前置要求

- Pixi 已安装（见 [Pixi 指南](../setup/pixi.md)）
- 已采集 MCAP 数据（真机或仿真）
- GPU（训练 + 推理）

## 一、训练流程

### 1. 环境选择

| 模型 | Pixi 环境 | 说明 |
|------|-----------|------|
| SmolVLA | `smolvla` | 适合 8 GiB 显存；训练快 |
| pi0.5 | `pi05` | 需 ~8 GiB+ 显存；LoRA 微调 |

以下以 **pi0.5** 为例（SmolVLA 流程相同，只需替换 `pi05` → `smolvla`）。

### 2. 下载基础权重（首次）

```bash
# pi0.5 需下载 gated tokenizer，设置 HF_TOKEN
export HF_TOKEN=hf_xxxxxxxxxxxxx

pixi run -e pi05 pi05-setup
# 等价于：pixi run -e pi05 pi05-download-base && pixi run -e pi05 pi05-download-tokenizer
```

SmolVLA：

```bash
pixi run -e smolvla smolvla-setup
```

权重缓存在 `~/.cache/huggingface/`（镜像站 `hf-mirror.com`）。

### 3. 配置训练参数

编辑 `airbot_ie/lerobot_plugin/configs/pi05_train.yaml`（或 `smolvla_train.yaml`）：

```yaml
env:
  # 可选：离线模式（需预先下载权重）
  # HF_HUB_OFFLINE: "1"
  HF_ENDPOINT: "https://hf-mirror.com"

policy:
  type: "pi0"  # 或 "smolvla" for SmolVLA

dataset:
  repo_id: "mcap"  # 固定值，指示使用 MCAP 后端
  backend: mcap
  mcap:
    # MCAP 数据目录（支持通配符，多轮数据）
    data_dir:
      - "data/my_task_001"
      - "data/my_task_002"

    # 状态 topic（机器人本体状态：关节角、EEF 位姿等）
    states:
      - "/observation/state"  # 或其他，取决于采集配置

    # 图像 topic（相机观测）
    images:
      - "observation.images.camera1"
      - "observation.images.camera2"

    # 动作 topic（示教动作：关节目标、EEF 增量等）
    actions:
      - "/action/state"

# 其他训练超参（学习率、batch size、steps 等）
training:
  offline_steps: 20000
  batch_size: 8
  # ...
```

**Topic 映射规则**：
- MCAP 中 topic 名如 `/observation/state`，配置中用完整路径
- 嵌套字典访问用 `.`，如 `observation.images.camera1`（对应 MCAP 中 `observation` attachment 里的 `images.camera1` 键）

### 4. 启动训练

```bash
pixi run -e pi05 mcap-lerobot-train -c airbot_ie/lerobot_plugin/configs/pi05_train.yaml
```

训练 log 和 checkpoint 保存在 `outputs/train/<job_name>/`：

```
outputs/train/pi05_smoke/
├── checkpoints/
│   ├── 000010/
│   │   └── pretrained_model/  # ← 这是推理用的 checkpoint 路径
│   ├── 000020/
│   └── ...
├── config.yaml
└── train.log
```

**注意**：checkpoint 数字是训练步数（不是 epoch）；`pretrained_model/` 是 LeRobot 标准格式。

### 5. 监控训练

训练日志打印到终端；也可用 TensorBoard / WandB（需额外配置 `training.log_freq` / `wandb` 块）。

## 二、推理流程

### 1. 配置推理参数

#### 真机推理（以 pi0.5 为例）

编辑 `airbot_ie/lerobot_plugin/configs/pi05_infer_real.yaml`：

```yaml
policy:
  path: "outputs/train/pi05_smoke/checkpoints/000010/pretrained_model"  # ← checkpoint 路径
  type: "pi0"

robot:
  type: "airbot_play"  # 或 "airbot_play_mock" 用于无硬件测试
  url: "192.168.1.100"  # AIRBOT Play gRPC 地址
  port: 50051
  components: 6  # 6-dof arm（不含夹爪）或 7（含夹爪）

  cameras:
    camera1:
      _target_: airdc.common.devices.cameras.v4l2.V4L2Camera
      index: 0
      width: 256
      height: 256
    camera2:
      _target_: airdc.common.devices.cameras.v4l2.V4L2Camera
      index: 2
      width: 256
      height: 256

# 推理超参
rollout:
  steps: 500
  fps: 10
```

**Mock 推理**（无硬件冒烟测试）：

```yaml
robot:
  type: "airbot_play_mock"
  cameras:
    camera1:
      _target_: airdc.common.devices.cameras.mock.MockCamera
      width: 256
      height: 256
```

#### 仿真推理（AAO MuJoCo）

编辑 `airbot_ie/lerobot_plugin/configs/aao_sim_infer.yaml`：

```yaml
policy:
  path: "outputs/train/pi05_smoke/checkpoints/000010/pretrained_model"

robot:
  type: "aao_sim"
  task: "open_door_airbot_play_g2p"  # AAO 场景名
  # state-only robot，渲染的相机图像作为观测
```

### 2. 运行推理

```bash
# 真机
pixi run -e pi05-infer mcap-lerobot-infer -c airbot_ie/lerobot_plugin/configs/pi05_infer_real.yaml

# Mock（无硬件）
pixi run -e pi05-infer mcap-lerobot-infer -c airbot_ie/lerobot_plugin/configs/pi05_infer_mock.yaml

# 仿真
pixi run -e infer-aao mcap-lerobot-infer -c airbot_ie/lerobot_plugin/configs/aao_sim_infer.yaml
```

推理会实时运行，打印动作、状态信息，视配置保存 rollout 视频/数据。

## 三、特征契约（Feature Contract）

训练和推理的 **state 维度、camera 键名/尺寸、action 维度** 必须完全匹配。

| 配置 | state | cameras | action |
|------|-------|---------|--------|
| pi05_train.yaml | `["/observation/state"]` 6-dim EEF pose | `camera1` 256×256, `camera2` 256×256 | `["/action/state"]` 6-dim |
| pi05_infer_real.yaml | 同上（robot 自动输出） | 同上（V4L2Camera 配置） | 同上（robot 消费） |

不匹配会在加载 checkpoint 时报错（`shape mismatch`）。

## 四、跨域训练与推理（sim→real）

**`aao_config_real.yaml` + `key_remap/aao_to_real.yaml`** 实现 sim 数据重命名为 real topic 名，使同一个 checkpoint 同时适配 sim 和 real：

1. 仿真采集用 `airdc --name aao_config_real`（topic 自动重命名为 `/observation/state` / `/action/state` 等 real 约定）
2. 真机采集用标准 `config.yaml`（topic 本就是 real 约定）
3. 训练时混合两者数据（或单独训练）
4. 推理时同一 checkpoint 既可 `aao_sim_infer` 又可 `pi05_infer_real`

详细见 [AAO 仿真数据采集](./aao.md)。

## 五、常见问题

**Q：训练时 "CUDA out of memory"**
A：减小 `training.batch_size`；或用 SmolVLA（更小）；或用 LoRA（pi0.5 已默认）。

**Q：推理时相机打不开**
A：检查 `cameras` 配置中的 `index`（`ls /dev/video*`）；确认不在 headless 环境（或改用 `opencv-python-headless`）。

**Q：checkpoint 加载报 "shape mismatch"**
A：训练与推理的 state/camera/action 维度不匹配；检查配置的 `mcap.states/images/actions` topic 是否一致。

**Q：SmolVLA vs pi0.5 如何选**
A：SmolVLA 更快、显存小、开箱即用；pi0.5 能力更强但需大显存 + gated tokenizer。

## 相关文档

- [Pixi 环境指南](../setup/pixi.md) — 环境安装与切换
- [AAO 仿真数据采集](./aao.md) — sim→real 跨域训练
- `airbot_ie/lerobot_plugin/lerobot.md` — 插件详细设计（中文）
- `airbot_ie/lerobot_plugin/lerobot_robot_airbot_play/README.md` — 真机插件（英文）
- `airbot_ie/lerobot_plugin/lerobot_robot_aao_sim/README.md` — 仿真插件（英文）
