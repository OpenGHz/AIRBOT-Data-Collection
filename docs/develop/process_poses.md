# `process_poses.py` 使用指南

`airdc.scripts.process_poses` 是一个用于从录制的 MCAP 数据生成派生姿态话题的工具。

它目前支持：

- 相对姿态话题（带 `_rela` 后缀）
- 从四元数（`orientation`）话题转换的 `rotation_6d` 话题

脚本通过 `McapFlbDataSampler` 将处理后的 episode 写入新的输出目录。

## 输入

`path` 参数接受**单个 `.mcap` 文件**或**包含多个 `.mcap` 文件的目录**：

```text
data/example/          # 目录输入 -> 每个 *.mcap 是一个 episode
  0.mcap
  1.mcap
  2.mcap

data/example/0.mcap    # 单文件输入 -> 一个 episode
```

你可以：

- 显式提供 `--keys`
- 省略 `--keys` 让脚本自动提取与姿态相关的键

姿态键通过话题的**最后一段路径**的精确匹配来识别（所以 `.../disposition` 不会被误认为 `position` 话题）。识别的段名有：

- `position`
- `orientation`
- `rotation_6d`
- 以上任意一个加 `_rela` 后缀

无论 `--keys` 如何设置，`log_stamps` 始终会被读取（写入输出时需要）。

## 输出

默认情况下，处理后的文件会写入到：

```text
<path>_processed/
```

例如，`data/example` 生成 `data/example_processed/`，单文件 `data/example/0.mcap` 生成 `data/example/0.mcap_processed/0.mcap`。
每个输出文件名与源文件名一致。使用 `--out_dir` 可以覆盖输出目录。

派生话题包括：

- `xxx_rela`
- `.../rotation_6d`
- `.../rotation_6d_rela`

相对值在 `position`、`orientation` 和 `rotation_6d` 上一致使用**世界坐标系**（`rela = abs * ref^{-1}`），
因此 `rotation_6d_rela` 与相对 `orientation` 匹配。

## 示例

为目录生成相对姿态和 `rotation_6d` 话题：

```bash
python3 -m airdc.scripts.process_poses \
  data/example \
  --keys /follow/arm/pose/position /follow/arm/pose/orientation \
  --targets rela rotation_6d
```

处理单个文件并写入自定义目录：

```bash
python3 -m airdc.scripts.process_poses \
  data/example/0.mcap \
  --targets rela rotation_6d \
  --out_dir data/example_processed
```

仅生成 `rotation_6d` 话题：

```bash
python3 -m airdc.scripts.process_poses \
  data/example \
  --keys /follow/arm/pose/orientation \
  --targets rotation_6d
```

## 编程调用

模块可以直接导入使用：

```python
from airdc.scripts.process_poses import convert

produced, ok = convert("data/example/0.mcap")
# produced == [PosixPath("data/example/0.mcap_processed/0.mcap")], ok == True
```

`convert(path, keys=None, targets=("rela", "rotation_6d"), out_dir=None)` 返回
`(produced_paths, ok)`。对于单文件输入，`produced_paths` 恰好包含一个元素。如果任何 episode 失败，
`ok` 为 `False`；其余 episode 仍会被处理（坏帧会记录警告并跳过，而不是中止）。

## 元数据

源元数据会传播到处理后的输出，因此派生文件保持自描述性：

- **`component_info`**（JSON attachment）从源读取并重新附加。
- **`task_info`**（语言指令元数据记录）从源读回并通过 sampler config 重新发出。

`system` 来源信息**不会**往返传递：在保存时它会被扁平化为许多单独的元数据记录，忠实地重建它
不值得付出代价。将源数据集视为 `system` 来源的权威。

## 参数

- `path`: 输入 `.mcap` 文件或包含 `.mcap` 文件的目录
- `--keys`: 要处理的姿态相关键（默认：自动检测）
- `--targets`: 要生成的派生目标，可用值为 `rela` 和 `rotation_6d`
- `--out_dir`: 输出目录（默认：`<path>_processed`）

## 注意事项

- 脚本独立处理每个 episode。
- 相对值使用每个 episode 的第一帧作为参考计算。
- 该脚本专为姿态类低维话题设计，不适用于通用话题转换。
