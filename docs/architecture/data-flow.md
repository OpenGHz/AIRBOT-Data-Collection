# AIRDC 数据流说明

本文档描述当前 AIRDC 从命令行启动到 episode 落盘的实际数据流。

## 1. 启动入口

开发者或操作员通常通过以下命令启动：

```bash
airdc
```

或者显式指定配置文件并覆写参数：

```bash
airdc --path airbot_ie/configs/config.yaml dataset.directory=example
```

入口位于 `airdc/main.py`，`main()` 会先解析 CLI 和配置文件，再进入 `main_loop()`。

## 2. 配置解析与实例化

`main_argparse(PACKAGE_NAME)(DataCollectionArgs)` 会把：

- Hydra 配置文件
- 命令行覆写
- Pydantic 数据模型

组合成一个 `DataCollectionArgs` 对象。这个对象包含：

- `fsm`：状态机配置
- `managers`：键盘、GUI、自动化等控制器
- `demonstrator`：真实机器人或仿真环境数据源
- `sampler`：数据格式和落盘策略
- `visualizer`：实时显示逻辑
- `dataset`：输出目录和文件后缀策略

## 3. 主循环与 FSM 创建

`main_loop()` 会做三件事：

1. 复制并暂存 managers。
2. 按 `batch_size` 创建一个或多个 `DemonstrateFSM`。
3. 把 FSM 列表交给 managers，再不断调用 `manager.update()`。

如果开启批量模式：

- 第一个 FSM 使用原始目录。
- 之后的 FSM 会被改写到 `<directory>_1`、`<directory>_2` 等目录。
- 只有第一个 FSM 保留 visualizer。

## 4. Manager 如何驱动采集

manager 的职责不是采集数据，而是触发动作。

例如 `SelfManager` 的典型行为是：

1. 在 `unconfigured` 状态触发 `configure`
2. 配置成功后触发 `activate`
3. 当状态进入 `sampling` 时不断触发 `update`
4. 达到样本或轮次限制时触发 `save` 或 `finish`

键盘、GUI、手柄、自动化 manager 也都遵循同一个模式，只是动作来源不同。

## 5. DemonstrateInterface 内部流程

每个 `DemonstrateFSM` 内部都持有一个 `DemonstrateInterface`。当前关键方法如下：

### `configure()`

- 从 demonstrator 获取组件信息
- 追加系统信息 `SystemInfo.all_info()`
- 将这些元信息传给 sampler
- 配置 visualizer 和 sampler

### `activate()`

- 创建目标数据目录
- 做一次 warm-up capture
- 初始化进度条

### `sample()`

- 为当前 episode 生成保存路径
- 通常是 `data/<directory>/<episode>.mcap`
- 重置本轮进度和计数

### `capture()`

- 调用 demonstrator 的 `capture_observation()`
- 对原始数据做 `key_merge` 和 `key_remap`
- 把结果发送给 visualizer 实时显示

### `update()`

- 再次执行一次 `capture()`
- 注入 `log_stamps`
- 调用 sampler 的 `update()`
- 把 sampler 返回的结构缓存在 `_round_data`
- 更新进度条和 metrics

### `save()`

- 等待异步 `update` 完成
- 调用 sampler 的 `save(path, round_data)`
- episode 计数加一
- 清空当前缓存

### `remove()`

- 根据上一轮 episode 重新计算路径
- 调用 sampler 的 `remove()`
- 清理内存中的当前轮缓存

## 6. Sampler 如何落盘

### 默认 MCAP 路径

默认真实采集路径通常使用 `airbot_ie/samplers/mcap_sampler.py`，底层基于：

- `airdc/common/samplers/mcap_samplers/basis.py`
- `airdc/common/samplers/mcap_samplers/sampler_flb.py`

保存时会自动写入：

- 配置 metadata
- 系统信息 metadata
- `component_info` attachment
- `log_stamps` attachment
- topic statistics attachment

这意味着当前 AIRDC 写 MCAP 时会顺带保存统计信息，不需要额外做一次独立的统计后处理。

### 视频数据

对颜色图像，如果配置为 `h264`：

- `update()` 阶段会先送入 `VideoSampler` 编码
- `save()` 阶段再把视频作为 attachment 写入 MCAP，或输出到独立文件夹，取决于 `video_save_to`

### ROS Structured MCAP

在仿真/ROS 风格配置下，会使用 `sampler_ros_struct.py`：

- 把 topic key 映射到 ROS message type
- 对压缩视频、相机参数、姿态等不同消息类型做专门处理
- 最终写成 ROS message 结构兼容的 MCAP

### LeRobot Dataset

如果使用 `LeRobotDataSampler`：

- 数据不会写成单个 `.mcap`
- 而是按 episode 目录写成 LeRobot 数据集格式
- 可以在 `update()` 阶段流式写帧，减少内存占用

## 7. 当前输出产物

根据 sampler 配置不同，当前常见产物包括：

- `<episode>.mcap`
- 与 episode 对应的视频目录或 `.mp4`
- LeRobot episode 目录
- 某些检查脚本生成的 `.status` 缓存文件

## 8. 删除与结束

当用户触发删除或流程结束时：

- manager 会触发 FSM action
- FSM 再调用 interface 的 `remove()` 或 `finish()`
- sampler 负责删除文件或做最终清理
- `shutdown()` 期间会尽量移除无效输出，避免留下损坏数据

## 9. 读这份文档时的边界

这份文档只描述“现在怎么工作”。如果要讨论未来如何改造：

- 产品层面看 `docs/product/`
- 规划层面看 `docs/planning/`
- 技术决策背景看 `docs/decisions/001-config-driven-modular-runtime.md`
