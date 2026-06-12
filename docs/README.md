# AIRDC 文档地图

本文档目录将“当前状态”和“规划信息”分开，避免把未来设想与已实现行为混在一起。

## 当前状态

### 入门与使用

- [项目简介](./intro.md)
- [快速开始](./quik_start.md)
- [README 中的安装与采集流程](../README.md)
- [AIRBOT Play/PTK/TOK 安装指南](./setup/airbot_play.md)
- [常见配置调整](./configure/common.md)
- [AIRBOT Play/PTK/TOK 遥操说明](./teleop/airbot_play.md)

### 架构与开发

- [架构总览](./architecture/overview.md)
- [数据流说明](./architecture/data-flow.md)
- [模块扩展说明](./develop/modules.md)
- [状态机配置说明](./fsm.md)

### 运维与数据检查

- [本地开发运行手册](./runbooks/local-dev.md)
- [MCAP 数据检查手册](./runbooks/inspect-mcap-dataset.md)
- [固定目标台 pick_and_place ACT 复现手册](./runbooks/reproduce-pick-and-place-act.md)
- [数据可视化：Foxglove](./visualize/foxglove.md)
- [数据可视化：AIRBOT MCAP Data Viewer](./visualize/airbot.md)
- [数据可视化：PlotJuggler](./visualize/plot_juggler.md)
- [常见问题](./troubleshooting/faq.md)
- [性能测试](./troubleshooting/performance.md)

## 决策记录

- [ADR-001：配置驱动的模块化 Python + MCAP 架构](./decisions/001-config-driven-modular-runtime.md)

## 规划信息

这些文档用于讨论“接下来做什么”，不应作为当前行为的唯一依据。

- [产品概览](./product/overview.md)
- [功能清单](./product/features.md)
- [Persona：采集操作员 / 集成工程师](./product/personas/robot-operator.md)
- [Persona：数据 / 算法工程师](./product/personas/data-engineer.md)
- [Persona：平台维护者 / 扩展开发者](./product/personas/platform-maintainer.md)
- [路线图（草案）](./planning/roadmap.md)
- [规划规格目录](./planning/specs/README.md)

## 维护约定

- `docs/architecture/`、`docs/runbooks/` 记录当前代码库已经存在的结构、流程和操作方式。
- `docs/product/`、`docs/planning/` 用于表达产品视角和未来工作，不直接替代代码或运行结果。
- 如果当前实现与规划文档冲突，应优先修正文档或代码，使两者重新对齐。
