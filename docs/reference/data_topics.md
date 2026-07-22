# 数据 Topic 命名与物理含义

本文档解释 AIRDC 采集的 MCAP 文件中，各 topic（数据键）名称与其**后缀字段的默认物理含义**，帮助读取、可视化、训练时正确理解每一路数据。

用 `mcap info` 查看一个单臂遥操作采集文件时，典型的 topic 列表如下：

```text
/follow/arm/joint_state/effort      /lead/arm/joint_state/effort
/follow/arm/joint_state/position    /lead/arm/joint_state/position
/follow/arm/joint_state/velocity    /lead/arm/joint_state/velocity
/follow/eef/joint_state/effort      /lead/eef/joint_state/position
/follow/eef/joint_state/position    /lead/eef/joint_state/velocity
/follow/eef/joint_state/velocity    /lead/eef/pose/orientation
/follow/eef/pose/orientation        /lead/eef/pose/position
/follow/eef/pose/position           /lead/eef/pose/rot6d
/follow/eef/pose/rot6d
```

## 名称结构

数据键默认由 `grouped demonstrator` 按层级用 `/` 拼接而成：

```text
[/<group>]/<name>/<component>/<data_type>/<field>[_rela]
```

单臂 / 单工位采集时，`group` 通常为根 `/`（会被省略），因此**最前面的一段就是组件实例名**（`follow` / `lead`）。多工位（如双臂）时才会出现 `group` 段，例如 `/left/follow/arm/joint_state/position`。

> 名称拼接逻辑见 `airdc/common/systems/grouped.py` 的 `_get_component_data_prefix`；如需将其改写成 ROS 习惯的命名（如 `/robot/arm_left_leader/joint_states`），见[常见配置调整 · 名称重映射](../configure/common.md#名称重映射)。

### `group`：工位 / 分组

多机器人协同时用于区分左右臂、多工位等。单臂时为 `/`。

### `name`：组件实例名（角色）

约定两个语义化名称，对应遥操作的主从关系（角色由配置中的 `roles` 字段 `l`/`f`/`o` 指定，见 `grouped.py` 的 `ComponentRole`）：

| 名称 | 角色 | 含义 | 在模型中的用途 |
|------|------|------|----------------|
| `follow` | follower（从臂 `f`） | 实际执行任务、被记录的机器人当前状态 | **观测** observation / state |
| `lead` | leader（主臂 `l`） | 遥操作主端（人操作），其状态即目标指令 | **动作** action（监督目标） |
| `*_camera` 等 | other（`o`） | 相机等传感器 | 观测（图像等） |

> 因此一个遥操作数据集里，`follow/*` 是「机器人做了什么」，`lead/*` 是「应该做什么」。跨域重映射（`key_remap/aao_to_real.yaml`）也据此把 `follow` 映射到 `observation.state`、`lead` 映射到 `action`。

### `component`：机器人部件

| 部件 | 含义 |
|------|------|
| `arm` | 机械臂本体（各关节，通常 6 / 7 个自由度） |
| `eef` | 末端执行器 end-effector（夹爪，通常 1 个自由度） |

### `data_type` 与 `field`：数据类型与字段

分为 `joint_state`（关节空间）与 `pose`（笛卡尔空间）两类。

## `joint_state`：关节空间数据

数组长度等于该部件的自由度数（`arm` 为关节数，`eef` 通常为 1）。

| 字段 | 物理含义 | 单位 |
|------|----------|------|
| `position` | 关节位置。`arm` 为各关节角度；`eef` 为夹爪开合量 | `arm`: rad（弧度）；`eef`: 取决于夹爪型号的行程（如 G2 约 `0~0.072 m`、E2B 约 `0~0.0471 m`，见 `airbot_ie/robots/airbot_play.py` 中的 `limits`） |
| `velocity` | 关节速度 | rad/s |
| `effort` | 关节力矩 / 出力 | N·m（或由驱动器返回、表征力矩的电流值，取决于硬件接口） |

> **注意（`eef/*/velocity` 恒为 0）**：夹爪速度是占位值，代码中 `eef` 的 `velocity` 字段固定返回全 `0`（`airbot_play.py` 的 `_get_joint_state`），并非真实测量，训练 / 分析时应忽略。
>
> **`joint_state/name`（关节名称）** 默认不进观测（通过 `info` 接口获取）。如需将关节名随数据实时写入，见[常见配置调整 · 数据种类](../configure/common.md#数据种类)。

## `pose`：末端笛卡尔位姿

描述末端执行器（TCP）在机器人基坐标系下的位姿，仅在 `eef`（及配置了 `pose` 观测的部件）下出现。

| 字段 | 物理含义 | 维度 / 约定 |
|------|----------|-------------|
| `position` | 末端位置 | `[x, y, z]`，3 维，单位 m |
| `orientation` | 末端姿态（四元数） | `[x, y, z, w]`，4 维，**`w` 在末尾** |
| `rot6d` | 末端姿态的 6D 连续旋转表示 | `[b1(3), b2(3)]`，6 维 |

### 关于 `rot6d`

`rot6d` 是 `orientation` 四元数的**等价姿态表示**，由 `mcap_data_loader.utils.rot6d.Rotation6D.quat_to_rot6d` 生成：将四元数转成 3×3 旋转矩阵后，**取前两列并展平为 6 维向量**（Zhou et al., 2019，"On the Continuity of Rotation Representations in Neural Networks"）。

相比四元数 / 欧拉角，6D 表示对旋转是**连续、无奇异**的（没有万向节死锁，也没有四元数 `q` 与 `-q` 的双覆盖歧义），因此更适合作为策略网络的回归目标 / 输入。它与 `orientation` 承载**相同信息**，可按需二选一使用（用 `rot6d_to_matrix` 可还原旋转矩阵）。

## `_rela` 后缀：相对量

带 `_rela` 后缀的键（如 `pose/position_rela`、`pose/rot6d_rela`、`joint_state/position_rela`）是**相对参考位姿的相对量**，默认参考系为该轮采集的**初始状态**（`ReferenceMode.INIT_STATE`）。

- 是否生成 `_rela` 由该组件的 `kind_ref` 配置决定：`INIT_STATE` 会额外产出 `_rela` 变体；`ABSOLUTE` 则不产出（见 `airbot_ie/robots/airbot_play.py` 的 `_get_rela_obs`）。
- 上例文件未出现 `_rela` 键，说明该次采集使用的是绝对量。
- 相对量常用于让策略对初始位姿不敏感（每轮从「相对起点」的位移 / 转动学习）。

## 相关文档

- [MCAP 数据检查手册](../runbooks/inspect-mcap-dataset.md) — 用 `mcap info` 查看 topic 列表
- [数据检查与 MCAP CLI](../troubleshooting/data_checking.md) — MCAP CLI 常用命令
- [常见配置调整 · 名称重映射](../configure/common.md#名称重映射) — 改写数据键为 ROS 等其它命名习惯
- [AAO 仿真数据采集](../workflows/aao.md) — 仿真 topic 与 `aao_to_real` 重映射
