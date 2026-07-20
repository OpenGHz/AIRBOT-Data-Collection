# LeRobot 训练与推理

在本仓库用 [LeRobot](https://github.com/huggingface/lerobot) 训练策略、并在 AIRBOT Play 机械臂（真机或 mock）上推理的统一流程。

> 前置：安装 pixi（一次性）。若尚未安装，运行 `bash install/install_pixi.sh` 完成 pixi 的安装。

流程对所有策略一致，**唯一的差异是策略名**。用一个环境变量 `POLICY` 指定策略，其余命令原样复用：

```bash
export POLICY=smolvla     # 轻量 ~450M，8G 显卡可训可推
# export POLICY=pi05      # ~3.6B，需大显存（8G 显卡推理会 OOM）
```

命名约定（三者同名，故可被 `$POLICY` 参数化）：

| 名称 | 值 |
|---|---|
| pixi 训练环境 | `$POLICY`（如 `smolvla`） |
| pixi 推理环境 | `$POLICY-infer`（如 `smolvla-infer`） |
| 训练配置 | `airbot_ie/lerobot_plugin/configs/${POLICY}_train.yaml` |
| 推理配置（mock） | `airbot_ie/lerobot_plugin/configs/${POLICY}_infer_mock.yaml` |
| 一次性配置任务 | `$POLICY-setup` |

训练与推理都用同一种方式驱动：**一个命令 + `-c <config>.yaml`**。命令入口 `mcap-lerobot-train` / `mcap-lerobot-infer` 由 `mcap-data-loader` 提供，内部分别调用 `lerobot-train` / `lerobot-rollout`，与策略无关。

运行时环境变量（`WANDB_MODE`、`HF_HUB_OFFLINE` 等）写在配置文件的顶层 `env:` 块里，由 `mcap-data-loader` 在启动时用 `os.environ.setdefault` 应用（**shell 里已设的同名变量优先**），不会传给下游 lerobot：

```yaml
env:
  HF_HUB_OFFLINE: "1"        # 权重已在 HF 缓存时安全；首次下载权重时去掉此行
  TRANSFORMERS_OFFLINE: "1"
  WANDB_MODE: disabled
```

---

## 0. 前置：拉取基座权重（一次性）

策略基座与其骨干是运行时 HF 权重，不是 python 包，需先下载到本地 HF 缓存：

```bash
pixi run -e $POLICY $POLICY-setup
```

> `$POLICY-setup` 会拉取该策略所需的全部权重。pi0.5 还包含门控的 PaliGemma tokenizer，需要已接受许可的 `HF_TOKEN`；SmolVLA 无此步。
>
> 下载默认走 `HF_ENDPOINT=https://hf-mirror.com`；改此环境变量可切官方源。

自检（离线导入整套栈，验证环境就绪）：

```bash
pixi run -e $POLICY $POLICY-check
```

---

## 1. 训练

1. 按数据集的实际情况修改配置`airbot_ie/lerobot_plugin/configs/${POLICY}_train.yaml`里的 `mcap.*`（状态/动作/相机 topic）与 `task_*`。

2. 启动训练（离线、关闭 wandb 等由配置里的 `env:` 块提供）：

   ```bash
   pixi run -e $POLICY mcap-lerobot-train -c airbot_ie/lerobot_plugin/configs/${POLICY}_train.yaml
   ```

   追加/覆盖任意 `lerobot-train` 参数，例如：

   ```bash
   pixi run -e $POLICY mcap-lerobot-train -c .../${POLICY}_train.yaml \
     --batch_size=8 --steps=20000 --output_dir=outputs/train/my_run
   ```

产物（含 checkpoint）默认写到 `outputs/train/<job>/checkpoints/<step>/pretrained_model/`。

---

## 2. 推理（在机械臂上运行策略）

推理需要**推理环境** `$POLICY-infer`（= 策略栈 + AIRBOT Play 机器人插件）。

### 2a. Mock（无硬件，验证链路/显存）

```bash
pixi run -e $POLICY-infer mcap-lerobot-infer \
  -c airbot_ie/lerobot_plugin/configs/${POLICY}_infer_mock.yaml
```

mock 配置里 `robot.mock: true` 用假机械臂，相机用 `MockCamera` 合成帧；机器人与相机键需匹配策略的 `input_features`（见各 mock yaml 内注释）。

### 2b. 真机

真机配置已提供模板 `airbot_ie/lerobot_plugin/configs/${POLICY}_infer_real.yaml`。按注释改三处即可：`robot.url/port`（机械臂 gRPC 地址）、`robot.components` 与 `cameras`（键/维度要与训练时一致）、`policy.path`（指向你的 checkpoint）。

```bash
pixi run -e $POLICY-infer mcap-lerobot-infer \
  -c airbot_ie/lerobot_plugin/configs/${POLICY}_infer_real.yaml
```

### 2c. 仿真（MuJoCo，无硬件）

在 auto-atomic-operation 仿真里跑策略，用 `infer-aao` 环境 + `aao_sim` 机器人（纯本体 EEF 位姿状态，暂无相机）：

```bash
pixi run -e infer-aao mcap-lerobot-infer \
  -c airbot_ie/lerobot_plugin/configs/aao_sim_infer.yaml
```

观测 = EEF 位姿（位置+四元数+夹爪）+ 仿真渲染的相机帧（默认带 `eef_wrist_cam`/`env2_cam` 两路 `(352,640,3)`）。改 `robot.task_config`（仿真场景/机型）、`policy.path`、`position_keys`/`orientation_keys`/`gripper_key` 与 `sim_cameras`（对齐 checkpoint 的特征）。相机走 MuJoCo 离屏渲染：有显示器用 `mujoco_gl: glfw`，无头用 `egl`/`osmesa`。`sim_cameras` 的相机名须在该 `task_config` 的 `env.cameras` 中，`camera_shape` 对上其分辨率。

---

## 要点

- **特征契约必须对齐**：`observation.state` 维度、相机键名/尺寸、`action` 维度，训练与推理要一致，否则归一化/加载会报错。相机键在插件里用**裸名**（如 `camera1`），LeRobot 会自动加 `observation.images.` 前缀。
- **机械臂状态维度**由插件 `components` 决定：`[arm]`→6 维，`[arm, eef]`→7 维。
- **显存**：SmolVLA 推理峰值 ~1.1 GiB（8G 卡富余）；pi0.5 需 ~7.8 GiB，8G 卡装不下 → 小显卡选 SmolVLA。
- **视频解码**用 PyAV（`torchcodec` 有意不装）；日志里的 pyav 回退提示是预期行为。
- **换策略**只需改 `export POLICY=...`，本文所有命令不变。
