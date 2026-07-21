# Runbook：本地开发

本文档面向当前 AIRDC 维护者，目标是在本地完成代码修改、基础验证和依赖排查。

## 适用范围

- 修改 `airdc/` 核心框架
- 修改 `airbot_ie/` 的默认配置、机器人适配或 sampler
- 对接 `auto-atomic-operation`
- 做不依赖完整生产硬件链路的本地验证

## 前置条件

- Linux 环境
- Python 3.10 左右的可用虚拟环境
- 按需安装 AIRBOT SDK、RealSense、USB 相机等硬件依赖
- 如果要使用仿真/自动采集模式，需要额外准备 `auto-atomic-operation`

## 路径一：标准 Python 可编辑安装

适合只维护当前仓库，或先从最小依赖开始。

```bash
conda create -n airdc python=3.10
conda activate airdc
bash install/install.sh
pip install pre-commit
pre-commit install
```

说明：

- `install/install.sh` 会安装系统依赖并执行 `pip install -e ."[all,airbot]"`。
- 真机采集前，仍需按 [AIRBOT Play/PTK/TOK 安装指南](../setup/airbot_play.md) 配置机器人 SDK。

## 路径二：Pixi 集成工作区

适合需要同时联调 AIRDC、`auto-atomic-operation` 和 `mcap-data-loader` 的维护者。

```bash
bash install/install_pixi.sh
pixi install
```

当前 `pixi.toml` 会把以下包按 editable 方式接入工作区：

- 当前仓库 `airdc`
- `third_party/auto-atomic-operation`
- `third_party/MCAP-DataLoader`

如果这些目录不存在，或版本不匹配，`pixi install` 会失败。

## 关键本地约束

### `aao_configs` 是符号链接

当前仓库中的：

```text
airbot_ie/configs/managers/auto_atom/aao_configs
```

是一个指向外部工程的符号链接。当前工作区里它指向：

```text
/home/ghz/Work/OpenGHz/auto-atomic-operation/aao_configs
```

如果你本地没有这个路径：

1. 准备对应的 `auto-atomic-operation` checkout。
2. 重新创建符号链接，或调整相关配置路径。

否则 `aao_config.yaml` 及相关自动采集配置会失效。

## 推荐验证步骤

### 1. 代码风格与静态检查

```bash
pre-commit run --all-files
```

### 2. 轻量级功能验证

```bash
python tests/modules/test_sampler.py --cfg tests/modules/samplers/mock_sampler.yaml
python tests/unit/test_topic_natural_sort.py
```

说明：

- `test_sampler` 覆盖 sampler 的基础契约：`configure`、`compose_path`、`update`、`save`、`remove`。
- `test_topic_natural_sort.py` 是一个非常轻量的排序逻辑检查脚本。

### 3. 硬件相关自检

只有在本机接好了对应硬件后再执行：

```bash
python3 scripts/list_cameras.py
python3 scripts/multi_capture.py 2 4 6 -ff MJPEG MJPEG MJPEG
airdc --path airbot_ie/configs/config.yaml dataset.directory=local_smoke
```

## 联调外部依赖

如果需要和外部工程一起更新：

```bash
bash install/update.sh
```

该脚本当前会：

1. 切换本仓库 tag / 版本上下文。
2. 继续执行 `install/install_auto_atom.sh`。

## 常见问题

### `airdc` 能启动，但自动采集配置失效

- 优先检查 `aao_configs` 符号链接是否有效。
- 再检查 `third_party/auto-atomic-operation` 是否存在且版本匹配。

### MCAP 相关导入失败

- 检查 `mcap-data-loader` 是否安装成功。
- 如果走 Pixi 路径，检查 `third_party/MCAP-DataLoader` 是否存在。

### 真机链路只在部分机器上可用

- 这是当前系统的正常约束之一。
- AIRDC 核心是 Python 框架，但硬件链路依赖机器人 SDK、驱动、USB 带宽和 Linux 环境。

## 相关文档

- [架构总览](../architecture/overview.md)
- [数据流说明](../architecture/data-flow.md)
- [模块扩展说明](../develop/modules.md)
- [AIRBOT Play/PTK/TOK 安装指南](../setup/airbot_play.md)
