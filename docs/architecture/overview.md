# AIRDC 架构总览

本文档描述 AIRDC 当前代码库中的实际运行结构，重点回答三个问题：

1. 入口在哪里。
2. 采集流程由哪些核心模块组成。
3. 开发者通常应该到哪个目录扩展功能。

## 一句话概览

AIRDC 是一个“配置驱动、状态机协调、模块化扩展”的机器人数据采集框架。默认入口 `airdc` 读取配置后，会组装 `Demonstrator`、`Sampler`、`Visualizer`、`Manager` 和 FSM，并由 manager 在主循环中驱动整个采集流程。

## 仓库分层

| 路径 | 角色 |
| --- | --- |
| `airdc/` | 核心运行时框架，包含入口、FSM、manager、通用 demonstrator/sampler/visualizer 抽象与实现。 |
| `airbot_ie/` | AIRBOT 相关的集成层，提供默认配置、机器人适配、示教器和 sampler 组合。 |
| `scripts/` | 运维、检查、性能分析和工具脚本。 |
| `tests/` | 单元测试、契约测试、硬件相关实验脚本。 |
| `docs/` | 用户文档、架构文档、runbook、规划文档。 |
| `install/` | 环境安装、更新、外部依赖同步脚本。 |

## 运行时组成

当前主流程可以概括为：

```text
airdc CLI
  -> main_argparse(...)(DataCollectionArgs)
  -> DataCollectionArgs / Hydra 配置实例化
  -> main_loop()
     -> 创建 1..N 个 DemonstrateFSM
     -> 注入 managers
     -> managers.update() 驱动 FSM 动作
     -> DemonstrateInterface 协调 demonstrator / sampler / visualizer
     -> sampler.save() 将 episode 落盘
```

## 核心模块职责

### 1. 入口与顶层配置

- `airdc/main.py`
  - 定义 `main()`、`main_desktop()` 与 `main_loop()`。
  - 调用 `main_argparse(PACKAGE_NAME)(DataCollectionArgs)` 将 CLI 参数和配置文件组装为运行时对象。
- `airdc/config.py`
  - `DataCollectionArgs` 是顶层参数模型。
  - 除了数据集、演示模块配置外，还定义了 `fsm`、`managers`、`update_rate`、`batch_size` 等主循环参数。

### 2. FSM 与演示接口

- `airdc/state_machine/fsm.py`
  - `DemonstrateFSM` 将状态机配置与 `DemonstrateInterface` 绑定。
  - 每个动作最终都映射到 interface 上的同名方法，如 `configure`、`activate`、`sample`、`update`、`save`、`remove`、`finish`。
- `airdc/demonstrate/interface.py`
  - 负责真正的采集动作编排。
  - `configure()` 会配置 sampler 和 visualizer，并把 demonstrator 信息与系统信息传给 sampler。
  - `capture()` 负责抓取观测并驱动可视化。
  - `update()` 会继续采样并把数据提交给 sampler。
  - `save()`、`remove()`、`finish()` 管理 episode 生命周期。

### 3. Managers

- `airdc/managers/`
  - manager 不直接处理硬件数据，而是负责“触发什么动作”。
  - `SelfManager` 会在 FSM 进入不同状态时自动触发 `configure`、`activate`、`update`、`save`、`finish`。
  - 其他 manager 如 `keyboard`、`tk`、`joy`、`vrcontrol`、`auto_atom` 负责把键盘、GUI、手柄或自动化策略转换为 FSM action。

### 4. Demonstrator / Sampler / Visualizer

- `airdc/common/demonstrators/`
  - 负责和机器人、相机、仿真环境等数据源交互，产生时序观测。
- `airdc/common/samplers/`
  - 负责缓存、编码、格式转换与持久化。
  - 当前重要实现包括：
    - FlatBuffers MCAP sampler
    - ROS structured MCAP sampler
    - LeRobot dataset sampler
    - video-only sampler
- `airdc/common/visualizers/`
  - 当前包含 OpenCV、Tk、Matplotlib、Web(FastAPI) 等可视化实现。

### 5. AIRBOT 集成层

- `airbot_ie/configs/`
  - 保存默认配置组合，是当前最重要的“产品化入口”。
  - `config.yaml` 是真机采集默认入口。
  - `aao_config.yaml` 对接 `auto-atomic-operation` 仿真/自动采集。
- `airbot_ie/robots/`
  - 保存 AIRBOT 机器人与其他设备的适配逻辑。
- `airbot_ie/samplers/mcap_sampler.py`
  - 在通用 MCAP sampler 基础上增加上传能力等 AIRBOT 侧扩展。

## 配置如何装配运行时

当前默认配置入口为 `airbot_ie/configs/config.yaml`：

```yaml
defaults:
  - basis
  - managers: keyboard
  - demonstrators: setup
  - samplers: mcap
  - override hydra/job_logging: custom
```

这意味着 AIRDC 当前采用“基础配置 + manager + demonstrator + sampler”分层组合的方式装配系统。开发者大多数时候不需要改主程序，只需要：

1. 新增一个模块实现。
2. 为该模块写一个 Hydra 配置。
3. 在顶层配置里替换对应 defaults。

## 当前支持的主要运行模式

### 真机手动采集

- 默认入口：`airbot_ie/configs/config.yaml`
- 典型组合：AIRBOT demonstrator + keyboard manager + MCAP sampler + OpenCV visualizer

### 自动化 / 仿真采集

- 默认入口：`airbot_ie/configs/aao_config.yaml`
- 典型组合：`auto_atom` manager + `auto-atomic-operation` 环境 + ROS structured MCAP sampler

### 多 FSM 批量采集

- 当 `batch_size > 0` 时，`main_loop()` 会复制配置并创建多个 FSM。
- 数据目录会自动变为 `<directory>_0`、`<directory>_1` 等后缀，避免不同实例互相覆盖。
- 除第一个 FSM 外，后续 FSM 默认关闭 visualizer，减少重复显示开销。

## 开发者扩展入口

- 想扩展采样器：先看 [模块扩展说明](../develop/modules.md)
- 想理解状态转移：先看 [状态机配置说明](../fsm.md)
- 想理解完整运行过程：看 [数据流说明](./data-flow.md)

## 需要持续关注的当前约束

- 真机能力强依赖 AIRBOT SDK、相机驱动和 Linux 运行环境。
- `auto_atom` 模式依赖外部 `auto-atomic-operation` 工程。
- 仓库当前已有用户文档较多，但此前缺少单独的架构/ADR/规划层，因此维护时需要特别注意“当前状态”和“未来规划”的分离。
