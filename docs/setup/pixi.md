# Pixi 环境与工作流指南

Pixi 是 AIRDC 推荐的环境管理工具，自动管理 Python 3.12、conda 包、PyPI 包及多环境隔离（数据采集、训练、推理、ROS）。

## 为什么用 Pixi

- **一致性**：锁文件（`pixi.lock`）确保团队/CI 依赖版本完全一致
- **多环境隔离**：单个 `pixi.toml` 管理 `collect`（采集）、`pi05`/`smolvla`（训练）、`infer-*`（推理）、`ros` 等环境，无需手动切换 conda env
- **跨平台**：macOS/Linux/Windows 统一体验（本项目仅 Linux 测试）
- **性能**：并行下载、缓存复用

## 安装

```bash
bash install/install_pixi.sh
```

离线安装（预先下载 pixi 二进制）：

```bash
bash install/install_pixi_offline.sh
```

## 环境列表

| 环境名 | 用途 | Python | 主要包 |
|--------|------|--------|--------|
| `collect` | 真机数据采集 | 3.12 | airdc[all,airbot], airbot_py SDK |
| `collect-aao` | 仿真数据采集（AAO MuJoCo） | 3.12 | airdc, auto-atomic-operation, gaussian-splat |
| `ros` | ROS 采样器/工作流 | 3.12 | robostack-jazzy, ros-core, foxglove-msgs |
| `pi05` | pi0.5 VLA 训练 | 3.12 | lerobot[pi,peft], torch(cu128), mcap-data-loader |
| `pi05-infer` | pi0.5 真机推理 | 3.12 | pi05 + airbot_py + lerobot_robot_airbot_play |
| `smolvla` | SmolVLA 训练 | 3.12 | lerobot[smolvla], torch(cu128) |
| `smolvla-infer` | SmolVLA 真机推理 | 3.12 | smolvla + airbot_py + lerobot_robot_airbot_play |
| `infer-aao` | 策略在 AAO 仿真中推理 | 3.12 | lerobot + lerobot_robot_aao_sim + AAO |
| `default` | 基础环境（无 ROS/LeRobot） | 3.12 | airdc 核心依赖 |

## 常用命令

```bash
# 安装所有环境依赖（初次或 pixi.toml 更新后）
pixi install

# 列出所有环境
pixi info

# 进入指定环境（交互 shell）
pixi shell -e collect

# 在指定环境运行命令（无需进入 shell）
pixi run -e collect airdc --name config
pixi run -e pi05 mcap-lerobot-train -c airbot_ie/lerobot_plugin/configs/pi05_train.yaml

# 添加依赖（自动更新 pixi.toml + pixi.lock）
pixi add numpy scipy

# 升级依赖
pixi update

# 清理缓存
pixi clean cache
```

## 数据采集工作流

### 真机采集

```bash
# 1. 安装环境
pixi install

# 2. 配置机器人与相机（生成 setup.yaml）
pixi run -e collect python airbot_ie/scripts/setup.py

# 3. 启动采集
pixi run -e collect airdc --path airbot_ie/configs/config.yaml
```

### 仿真自动采集（AAO）

```bash
# 1. 确保 aao_configs 符号链接正确（见下方）
# 2. 启动仿真采集
pixi run -e collect-aao airdc --name aao_config
```

**符号链接约束**：`airbot_ie/configs/managers/auto_atom/aao_configs` 必须指向 `auto-atomic-operation/aao_configs`。如果符号链接丢失：

```bash
bash install/install_auto_atom.sh
```

## LeRobot 训练与推理工作流

详细见 [LeRobot 训练与推理指南](../workflows/lerobot.md)。

### 训练（pi0.5 为例）

```bash
# 1. 下载基础权重（首次）
pixi run -e pi05 pi05-setup

# 2. 编辑训练配置（指定 MCAP 数据路径、topic 映射）
vim airbot_ie/lerobot_plugin/configs/pi05_train.yaml

# 3. 训练
pixi run -e pi05 mcap-lerobot-train -c airbot_ie/lerobot_plugin/configs/pi05_train.yaml
```

checkpoint 保存在 `outputs/train/<job>/checkpoints/<step>/pretrained_model/`。

### 推理（真机）

```bash
# 编辑推理配置（指定 checkpoint 路径、相机、机器人 URL）
vim airbot_ie/lerobot_plugin/configs/pi05_infer_real.yaml

# 推理
pixi run -e pi05-infer mcap-lerobot-infer -c airbot_ie/lerobot_plugin/configs/pi05_infer_real.yaml
```

### 推理（仿真 AAO）

```bash
pixi run -e infer-aao mcap-lerobot-infer -c airbot_ie/lerobot_plugin/configs/aao_sim_infer.yaml
```

## Pixi Tasks

`pixi.toml` 定义的任务（用 `pixi run <task>` 调用）：

| Task | 环境 | 说明 |
|------|------|------|
| `test` | default | 纯软件测试（`pytest -m software`） |
| `test-hardware` | default | 硬件测试（资源缺失自动 skip） |
| `test-all` | default | 全量测试 |
| `pi05-setup` | pi05 | 下载 pi0.5 基础权重 + PaliGemma tokenizer（需 `HF_TOKEN`） |
| `pi05-check` | pi05 | 离线 import 自检 |
| `smolvla-setup` | smolvla | 下载 SmolVLA 基础权重 |
| `smolvla-check` | smolvla | 离线自检 |
| `download-gs` | collect-aao | 下载 Gaussian Splat 场景资产 |

## 镜像与离线模式

`pixi.toml` 默认配置了国内镜像（Tsinghua conda-forge / USTC PyPI / NJU PyTorch cu128 / hf-mirror.com HuggingFace）。如需完全离线：

1. 在有网环境 `pixi install` 一次（填充缓存）
2. 打包 `.pixi/` 和 `pixi.lock`
3. 离线环境解包后 `pixi install` 从缓存恢复

LeRobot 模型权重通过 `HF_ENDPOINT=https://hf-mirror.com` 从镜像站下载（`pi05-setup` / `smolvla-setup`），或手动配置 `HF_HUB_OFFLINE=1` + 预先下载权重到 `~/.cache/huggingface/`。

## 故障排查

**问题：`pixi install` 报错 "failed to solve"**
- 检查 `pixi.lock` 是否损坏（`pixi clean cache && pixi install`）
- 检查镜像是否可达

**问题：训练时 "ModuleNotFoundError: No module named 'lerobot'"**
- 确认在正确环境运行：`pixi run -e pi05 python -c "import lerobot"`

**问题：推理时 "相机打不开"**
- Pixi `collect`/`infer-*` 环境用 `opencv-python`，不兼容 headless 服务器；如需 headless，手动改 `pixi.toml` 为 `opencv-python-headless`

**问题：AAO 仿真 "aao_configs 不存在"**
- `bash install/install_auto_atom.sh` 重建符号链接

## 与 conda 共存

Pixi 与 conda 独立（使用自己的 `.pixi/envs/`），可同时安装。如已有 conda 环境，选择：
- 纯 Pixi：`pixi run -e collect airdc`（推荐，环境隔离）
- 纯 conda：激活 conda env 后 `airdc`（传统方式）
- 混用：不推荐（依赖版本冲突风险）

## 相关文档

- [LeRobot 训练与推理](../workflows/lerobot.md)
- [AAO 仿真数据采集](../workflows/aao.md)
- [本地开发 Runbook](../runbooks/local-dev.md)
