# Persona：数据 / 算法工程师

## Who They Are

- 负责消费 AIRDC 采集结果，用于训练、回放、数据诊断或格式转换
- 更关心数据格式、topic 语义、时间戳和元信息完整性
- 不一定直接参与真机搭建

## Pain Points

- 不清楚不同采集配置最终落成什么格式
- 很难快速判断 MCAP 中的 topic、attachment 和统计信息是否齐全
- 当数据格式从 MCAP 扩展到 LeRobot 或 ROS 结构时，理解成本升高

## Journey

1. 获取数据目录和对应采集配置
2. 用 CLI 或脚本检查 `.mcap` 文件结构
3. 用可视化工具或数据读取脚本确认 topic 和视频质量
4. 进入训练、转换或回放流程

## Content Needs

- 数据流文档
- MCAP 检查 runbook
- 可视化与数据检查文档
- sampler 行为说明
