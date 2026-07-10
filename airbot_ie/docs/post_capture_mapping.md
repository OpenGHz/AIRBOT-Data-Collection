# Post-Capture 映射：`_default_limit` 与 `_default_range`

本文解释 `airbot_ie/robots/airbot_play.py` 中主从遥操作（leader → follower）时，
主手数据是如何被重新映射到从手的，以及 `_default_limit` 和 `_default_range`
这两个字典各自的职责。

## 背景：主手数据直接当作从手指令

一控一遥操作里，从手并不做任何后处理，它直接执行**主手被采集到的观测值**
（capture observation）。也就是说，主手采集到的值必须**已经是从手的单位/量程**，
否则就会出现「主手夹爪开到最大，从手却没开满」这类问题。

因此，重映射发生在**读取主手观测**的时刻（`_get_joint_state` / `_get_pose`），
由 `set_post_capture` 预先安装好的 `_post_capture` 回调完成。

## 核心：`linear_map`

夹爪等标量字段用线性重映射（`airdc/utils.py`）：

```python
def linear_map(x, raw_range, target_range):
    a, b = raw_range
    c, d = target_range
    return (x - a) * (d - c) / (b - a) + c
```

即把 `x` 从 `raw_range (a, b)` 线性映射到 `target_range (c, d)`。
`set_post_capture` 为每个字段/索引绑定好这两个参数：

```python
self._post_capture[key][index] = partial(
    linear_map,
    raw_range=default_limit[index],   # 来自 _default_limit
    target_range=target_range,        # 来自 range_mapping（config 或默认推导）
)
```

## 两个字典的职责

| | `_default_limit` → `raw_range` | `_default_range` → `target_range` |
|---|---|---|
| 含义 | **物理事实**：某型号硬件实际能输出/驱动的量程 | **`config.range_mapping` 的默认值**：映射目标量程 |
| 用途 | 提供 `linear_map` 的输入域 | 提供 `linear_map` 的输出域 |
| 谁的量程 | 读数方（**主手**）的物理极限 | 目标方（**从手**）的期望量程 |
| 配置覆盖通道 | `config.limit` | `config.range_mapping` |
| 缺项时 | —— | **回退到从手的 `_default_limit`** |

### 为什么要分成两个字典（真实动机）

关键不在「物理 vs 策略」，而在**配置解耦**：

- `_default_range` 的存在**主要是为了配 `config.range_mapping` 这个配置项**，
  它是 `range_mapping` 的**内置默认值**。
- 之所以和 `_default_limit` 分开，是因为走 `range_mapping` 配置映射时，
  **不希望去改动 `limit`（物理量程）**。`limit` 是客观硬件事实，
  `range_mapping` 是可配置的映射目标，两条通道各走各的，
  **配映射不污染 limit**。

### 历史

最初代码**不会自动获取 follower 的信息**，所以映射目标只能在配置里**手动**写
`range_mapping`，`_default_range` 就是那时的默认兜底。后来改成
**自动获取 follower 的臂/夹爪型号**并推导目标量程（见下），一般情况下不用再手配。

## `_default_range` 现为纯 override（B 重构）

由于「默认就是映射到从手满行程」，而从手满行程本就等于从手的
`_default_limit`，把它重复写进 `_default_range` 是冗余的。重构后：

- `_default_range` 是一个**纯 override 字典**，**默认为空** `{}`。
- **只有当目标量程 ≠ 物理极限时**（例如软限位、归一化）才往里加条目。
- 映射到从手满行程**不需要任何条目**——缺项时自动回退到从手的 `_default_limit`。

```python
self._default_range: Dict[str, Dict[str, Dict[int, list]]] = {}
```

## 选择逻辑（`set_post_capture`）

```python
arm_type  = self._component_types["arm"]   # 主手臂型号
eef_type  = self._component_types["eef"]   # 主手夹爪型号
# raw_range：按【主手】型号取物理量程（读到的原始值的域）
default_limits = self._get_default(arm_type, eef_type, self._default_limit)

# target_range：按【从手】型号取，默认=从手物理量程，再被 _default_range 覆盖
follower_arm = info["product_type"]        # info 为从手信息
follower_eef = info["eef_types"][0]
default_range = (
    self._get_default(follower_arm, follower_eef, self._default_limit)   # 默认：从手满行程
    | self._get_default(follower_arm, follower_eef, self._default_range) # 覆盖：特例
)
```

- `default_limits`（raw_range）按**主手**型号选，与从手是谁无关。
- `default_range`（target_range）按**从手**型号选：**先取从手物理量程作默认**，
  再让 `_default_range` 覆盖。这样「主手 E2B → 从手 G2」自动把 `0–0.0471`
  映射到 `0–0.0720`，从手正确开满。
- `info` 是从手的 `get_info()`；若组内无从手则退化为主手自身信息，
  此时主从同型，映射为恒等。

> 注意：`range_mapping` 同时决定「**哪些**字段会被安装映射」。回退到从手
> `_default_limit` 后，从手每种夹爪/臂型都天然有条目，所以不再需要像旧代码那样
> 在 `_default_range` 里为每种从手夹爪手动补齐。

## 夹爪示例（E2B 主手 → G2 从手）

| | 量程 | 来源 |
|---|---|---|
| 主手 E2B（raw_range，采集到的原始值） | `0 – 0.0471 m` | 主手 `_default_limit` |
| 从手 G2（target_range，希望驱动到的量程） | `0 – 0.0720 m` | 从手 `_default_limit`（默认） |

`linear_map(0.0471, (0, 0.0471), (0, 0.0720)) = 0.0720` → 主手开满，从手也开满；
`linear_map(0, …) = 0` → 闭合对闭合。

`_default_range` 为空，四种主/从夹爪组合仍都靠「回退到从手物理量程」正确开满：

| 主手 | 从手 | 指令值 | 结果 |
|---|---|---|---|
| E2B | G2  | 0.0720 | 开满 |
| G2  | G2  | 0.0720 | 开满 |
| E2B | E2B | 0.0471 | 开满 |
| G2  | E2B | 0.0471 | 开满 |

## 位姿变换（`eef/pose`）

除了标量的 `linear_map`，`eef/pose` 走另一条路：`_tf_buffer.lookup_transform`
查找「主手 eef 帧 → 从手 eef 帧」的静态变换，补偿两种夹爪的工具长度差异。
该变换所需的 `ref → eef` 偏置定义在 `tf_dict` 中，按臂型号（`play` / `play_pro`
/ `play_lite`）与夹爪型号索引。若主从同夹爪，`source == target`，
`lookup_transform` 直接返回单位阵，不查图。

## 配置覆盖（可选）

若在 demonstrator 配置里提供了 `post_capture` 块（例：
`airbot_ie/configs/demonstrators/post_capture/2.yaml`），则 `config` 非空，
`range_mapping` 直接采用 `config.range_mapping`，跳过上面基于从手类型的默认推导，
由使用者自行指定，例如：

```yaml
post_capture:
  /:
    range_mapping:
      eef/joint_state/position:
        0: [0, 0.072]   # 目标量程（从手 G2）
```

此时 `raw_range` 仍来自 `_default_limit`（可再由 `config.limit` 覆盖）。
这正是 `_default_range` 与 `_default_limit` 分离的初衷：配 `range_mapping`
不会动到 `limit`。

## 小结

- **`_default_limit`** = 各型号的物理量程（`raw_range`）；主手侧提供输入域。
- **`_default_range`** = `config.range_mapping` 的默认值（`target_range`）；
  与 `limit` 分开是为了「配映射不改物理量程」。
- B 重构后 `_default_range` 是纯 override（默认空），缺项回退到**从手**的
  `_default_limit`，因此「映射到从手满行程」零配置即可，只有需要
  软限位/归一化这类「目标 ≠ 物理极限」时才往里加条目。
