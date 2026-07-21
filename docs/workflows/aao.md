# AAO 仿真数据采集

AIRDC 通过 `auto-atomic-operation` (AAO) 集成支持 **MuJoCo 仿真环境自动数据采集**，用于无需真机硬件的大规模并行数据生成、sim-to-real 训练、算法验证。

## 架构

- **仿真引擎**：MuJoCo（AAO 封装）+ Gaussian Splatting 渲染
- **Manager**：`AutoAtomManager`（rule-based）或 `AutoAtomDataReplayManager`（Redis-driven replay）
- **Demonstrator**：`SingleBatchedComponentDemonstrator`（批量环境并行采样）
- **Sampler**：`McapDataSamplerROSStruct`（ROS-struct MCAP）或 `McapFlbDataSampler`
- **配置入口**：`airbot_ie/configs/aao_config.yaml`（纯仿真）或 `aao_config_real.yaml`（topic 重命名为 real 约定）

## 前置要求

- Pixi 已安装（见 [Pixi 指南](../setup/pixi.md)）
- `aao_configs` 符号链接正确（指向 `auto-atomic-operation/aao_configs`）
- GPU（Gaussian Splat 渲染；CPU-only 模式需禁用 gsplat）

## 环境与符号链接

仿真采集需 `pixi` 的 `collect-aao` 环境：

```bash
pixi install  # 自动安装 collect-aao 环境
```

**符号链接约束**：`airbot_ie/configs/managers/auto_atom/aao_configs` 必须链接到 `auto-atomic-operation/aao_configs`（场景/任务/机器人配置）。验证：

```bash
ls -l airbot_ie/configs/managers/auto_atom/aao_configs
# 应显示：... -> /path/to/auto-atomic-operation/aao_configs
```

如果符号链接丢失或指向错误：

```bash
bash install/install_auto_atom.sh
```

该脚本会克隆 `auto-atomic-operation` v0.3.3 到 `third_party/` 并创建符号链接。

## 配置：纯仿真 vs sim→real

### `aao_config.yaml`（纯仿真）

topic 名使用仿真约定（`arm/pose`, `action/arm/pose`, `camera/env2_cam`），适合纯仿真闭环。

```yaml
defaults:
  - basis
  - managers: self
  - managers/auto_atom: basis
  - managers/auto_atom/class: rule_based
  - managers/auto_atom/task: open_door_airbot_play_g2p  # ← 任务名
  - samplers: ros_struct

# batch 并行（每个 worker 一个环境）
batch_size: 4
```

### `aao_config_real.yaml`（sim→real bridge）

在 `aao_config.yaml` 基础上额外应用 **`key_remap: aao_to_real`**，采集时自动重命名 topic：

| 仿真 topic | 重命名为 |
|-----------|----------|
| `arm/pose` | `/observation/state` |
| `action/arm/pose` | `/action/state` |
| `camera/eef_wrist_cam` | `observation.images.camera1` |
| `camera/env2_cam` | `observation.images.camera2` |

这样仿真 MCAP 与真机 MCAP 的 topic 名完全一致，**同一个 LeRobot checkpoint 可同时用于 sim 和 real 推理**。

```yaml
defaults:
  - aao_config
  - key_remap: aao_to_real  # ← 唯一区别
```

## 任务配置

任务定义在两处（必须同时存在）：

1. **Manager 配置**：`airbot_ie/configs/managers/auto_atom/task/<task_name>.yaml`
2. **AAO 场景配置**：`aao_configs/<task_name>_*.yaml`（通过符号链接访问）

例如 `open_door_airbot_play_g2p` 任务：

- Manager 配置：`airbot_ie/configs/managers/auto_atom/task/open_door_airbot_play_g2p.yaml`
- AAO 场景：`aao_configs/open_door_airbot_play_g2p.yaml`

添加新任务时，需在这两处同步创建配置。

## 启动仿真采集

### 单进程采集（调试）

```bash
pixi run -e collect-aao airdc --name aao_config_real batch_size=1
```

### 并行采集（生产）

```bash
# 4 个并行环境，共采 100 轮
pixi run -e collect-aao airdc --name aao_config_real batch_size=4 sample_limit.rounds=100
```

每个 batch 的数据保存到独立目录：

```
data/<directory>/         # batch 0
data/<directory>_1/       # batch 1
data/<directory>_2/       # batch 2
data/<directory>_3/       # batch 3
```

合并所有 batch 到一个目录：

```bash
python scripts/merge_batch_folders.py --root data/<directory>
```

### 多进程并行（跨 GPU）

利用 `scripts/parallel_bench.py` 在多 GPU 上启动多个独立 `airdc` 进程：

```bash
python scripts/parallel_bench.py -n 4 --gpus 0,1 \
  --command "pixi run -e collect-aao airdc --name aao_config_real batch_size=2 sample_limit.rounds=50"
```

这会启动 4 个进程（每进程 `batch_size=2`），分配到 GPU 0 和 1，每个进程采 50 轮，共 200 轮数据。

## Manager 类型

### Rule-based（默认）

`managers/auto_atom/class: rule_based` — 按固定规则采样（如随机初始化、固定轨迹）。适合快速生成大量数据。

### Data Replay（Redis-driven）

`managers/auto_atom/class: data_replay` — 从 Redis（Pub/Sub 或 Stream-group）读取真机 MCAP 路径，在仿真中回放并做数据增强（随机扰动、domain randomization）。适合 sim-to-real 训练。

配置 Redis 连接：

```yaml
managers:
  auto_atom:
    redis:
      host: "localhost"
      port: 6379
      channel: "demo_files"  # Pub/Sub channel 或 Stream key
```

然后在另一终端推送 MCAP 路径到 Redis：

```bash
python tests/manual/redis/redis_filepath_publisher.py --files data/real_task/*.mcap
```

仿真 manager 会自动拉取路径并回放。

## Gaussian Splat 场景资产

部分 AAO 场景使用 Gaussian Splatting 渲染真实背景。首次运行需下载资产：

```bash
pixi run -e collect-aao download-gs
```

或手动下载到 `third_party/auto-atomic-operation/gaussian_splat_scenes/`。

无 GPU 或禁用 gsplat 时，在任务配置中设置 `use_gaussian_splatting: false`。

## 性能与吞吐

仿真采集吞吐取决于：

- `batch_size`：越大越好（受显存限制）
- `update_rate`：设为 `0`（全速）
- GPU 性能：Gaussian Splat 渲染耗 VRAM
- 进程数：`parallel_bench.py` 跨多 GPU 扩展

典型吞吐（NVIDIA RTX 3090）：
- `batch_size=4` 单进程：~40 FPS（4 环境并行）
- `batch_size=2` × 4 进程（2 GPU）：~120 FPS 总吞吐

## 常见问题

**Q：启动报 "aao_configs not found"**
A：符号链接丢失，运行 `bash install/install_auto_atom.sh`。

**Q：MuJoCo 报 "GLEW initialization error"**
A：无显示环境（headless 服务器）需设置 `EGL_DEVICE_ID` 或用 `xvfb-run`。

**Q：Gaussian Splat 场景渲染黑屏**
A：资产未下载（`pixi run -e collect-aao download-gs`）或 CUDA 不可用。

**Q：如何在 sim 数据上训练 real 策略**
A：用 `aao_config_real.yaml` 采集（topic 重命名），与真机数据混合训练，详见 [LeRobot 训练指南](./lerobot.md#四跨域训练与推理simreal)。

**Q：如何自定义任务**
A：在 `aao_configs/` 定义场景（需熟悉 AAO），在 `airbot_ie/configs/managers/auto_atom/task/` 定义 manager 参数，两边用相同名字。

## 相关文档

- [Pixi 环境指南](../setup/pixi.md) — `collect-aao` 环境安装
- [LeRobot 训练与推理](./lerobot.md) — sim→real 训练流程
- `airbot_ie/configs/aao_config.yaml` — 纯仿真配置入口
- `airbot_ie/configs/aao_config_real.yaml` — sim→real bridge 配置
- `airbot_ie/configs/key_remap/aao_to_real.yaml` — topic 重命名规则
