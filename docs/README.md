# AIRDC 文档地图

本文档目录将“当前状态”和“规划信息”分开，避免把未来设想与已实现行为混在一起。

## 当前状态

### 入门与使用

- [项目简介](./intro.md)
- [快速开始](./quik_start.md)
- [README 中的安装与采集流程](../README.md)
- [Pixi 环境与工作流指南](./setup/pixi.md)
- [AIRBOT Play/PTK/TOK 安装指南](./setup/airbot_play.md)
- [AIRBOT Play/PTK/TOK 配置说明](./configure/airbot_play.md)
- [常见配置调整](./configure/common.md)
- [配置框架说明](./configure/cfger.md)
- [AIRBOT Play/PTK/TOK 遥操说明](./teleop/airbot_play.md)
- [数据采集建议](./suggestion/collect.md)

### 训练与推理

- [LeRobot 训练与推理](./workflows/lerobot.md)
- [AAO 仿真数据采集](./workflows/aao.md)

### 架构与开发

- [架构总览](./architecture/overview.md)
- [数据流说明](./architecture/data-flow.md)
- [模块扩展说明](./develop/modules.md)
- [测试规范](./develop/testing.md)
- [状态机配置说明](./fsm.md)
- [采样器：LeRobot Sampler](./manual/modules/samplers/lerobot_sampler.md)

### 运维与数据检查

- [本地开发运行手册](./runbooks/local-dev.md)
- [MCAP 数据检查手册](./runbooks/inspect-mcap-dataset.md)
- [数据可视化：Foxglove](./visualize/foxglove.md)
- [数据可视化：AIRBOT MCAP Data Viewer](./visualize/airbot.md)
- [数据可视化：PlotJuggler](./visualize/plot_juggler.md)
- [数据上传（DataLoop）](./upload.md)
- [常见问题](./troubleshooting/faq.md)
- [数据检查与 MCAP CLI](./troubleshooting/data_checking.md)
- [USB 相机与并发](./troubleshooting/usb_cam.md)
- [日志与运行记录](./troubleshooting/logging.md)
- [性能测试](./troubleshooting/performance.md)

### 参考

- [Scripts 工具集](./reference/scripts.md)

## 规划信息

这些文档用于讨论”接下来做什么”，不应作为当前行为的唯一依据。

- [产品概览](./product/overview.md)
- [功能清单](./product/features.md)
- [Persona：采集操作员 / 集成工程师](./product/personas/robot-operator.md)
- [Persona：数据 / 算法工程师](./product/personas/data-engineer.md)
- [Persona：平台维护者 / 扩展开发者](./product/personas/platform-maintainer.md)

## 维护约定

- `docs/architecture/`、`docs/runbooks/` 记录当前代码库已经存在的结构、流程和操作方式。
- `docs/product/` 用于表达产品视角和未来工作，不直接替代代码或运行结果。
- 如果当前实现与文档冲突，应优先修正文档或代码，使两者重新对齐。
