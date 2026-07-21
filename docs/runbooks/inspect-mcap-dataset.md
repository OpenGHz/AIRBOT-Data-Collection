# Runbook：检查 MCAP 数据集

本文档面向需要确认 AIRDC 产出的 MCAP 数据是否完整、可读取、可分析的维护者与数据工程师。

## 前置条件

- 已安装 AIRDC 运行环境
- 数据目录中已经存在 `.mcap` 文件
- 如果要使用命令行摘要，已安装 `mcap` CLI

## 快速查看单个文件

先看结构，不必先写代码：

```bash
mcap info data/<dataset>/<episode>.mcap
```

这个命令适合快速确认：

- topic 列表
- schema / channel 信息
- message 数量
- attachment 是否存在

## 检查整包数据

仓库当前自带了一个面向 MCAP 数据集的检查脚本：

```bash
python airbot_ie/tests/manual/check_mmk_mcap_dataset.py --dir data/<dataset>
```

如果需要打印每个文件的详细报告：

```bash
python airbot_ie/tests/manual/check_mmk_mcap_dataset.py --dir data/<dataset> --print_details
```

如果要忽略缓存重新检查：

```bash
python airbot_ie/tests/manual/check_mmk_mcap_dataset.py --dir data/<dataset> --skip_cache
```

## 当前检查脚本会做什么

`airbot_ie/tests/manual/check_mmk_mcap_dataset.py` 当前会遍历目录中的 `.mcap` 文件，并输出：

- 数据集中文件总数
- 每个文件的错误和告警
- 视频质量问题分布
- 汇总报告

它还会在 `.mcap` 文件旁生成 `.status` 缓存，用于跳过未变化文件的重复检查。

## 读取结果时要注意什么

### 1. 统计信息通常已经随文件写入

AIRDC 当前的 MCAP sampler 在保存阶段会自动写入：

- `component_info` attachment
- `log_stamps` attachment
- topic statistics attachment

因此一般不需要再额外跑一次“统计汇总后处理”。

### 2. 视频可能存在两种存放方式

取决于 sampler 配置，颜色图像可能：

- 直接编码为 MCAP attachment
- 额外落到独立视频目录
- 两者同时存在

检查文件时不要只盯着 `.mcap` 本体，也要确认旁路视频输出是否符合当前配置。

### 3. 真机与仿真 topic 可能不同

- 真机默认更接近 FlatBuffers / AIRDC 自身 topic 组织方式。
- `auto_atom` 或 ROS structured 路径下，topic 和 schema 会更接近 ROS message 语义。

## 推荐排查顺序

1. 用 `mcap info` 看单文件结构是否合理。
2. 用数据集检查脚本看是否存在批量性问题。
3. 如果只有视频异常，重点检查编码设置与旁路视频目录。
4. 如果只有部分 topic 异常，回到对应 demonstrator / sampler 配置排查 key 映射。

## 常见问题

### `mcap info` 看不到预期 topic

- 检查本次采集是否真的启用了对应 demonstrator 组件。
- 检查 key remap 是否把 topic 改名了。
- 检查 sampler 是否把某些高维数据改成了 attachment 或视频文件。

### 数据集检查脚本提示没有 `.mcap` 文件

- 确认 sampler 不是 LeRobot dataset 模式。
- 确认当前目录层级正确，脚本只会检查指定目录下直接存在的 `.mcap` 文件。

### 删除了坏文件，但脚本结果没有变化

- 可能是 `.status` 缓存还在。
- 重新运行时加 `--skip_cache`，或清理对应缓存文件后再试。

## 相关文档

- [数据流说明](../architecture/data-flow.md)
- [数据可视化：Foxglove](../visualize/foxglove.md)
- [常见问题](../troubleshooting/faq.md)
