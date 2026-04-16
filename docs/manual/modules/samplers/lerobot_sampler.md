# LeRobot Sampler 说明（LeRobotDataSampler）

本文档说明 [airdc/common/samplers/lerobot_sampler.py](../../../../airdc/common/samplers/lerobot_sampler.py) 中 `LeRobotDataSampler` / `LeRobotDataSamplerConfig` 的设计目标、运行时调用顺序，以及每个方法的实现逻辑。

> 适用场景
>
> - 你希望把 AIRDC 的 per-step payload 落盘为 HuggingFace/LeRobot 的 dataset 结构（`LeRobotDataset`）。

---

## 1. 与 AIRDC 采集流程的关系

在 AIRDC 中，采样器（`DataSampler`）只负责：接收每一步的 `payload`（来自 demonstrator capture）、可选的轻量处理、按 episode 组织并落盘。

而 `lerobot_record.py` 里包含的 teleop/policy 推理、精确 fps 睡眠、episode reset、UI 展示等逻辑不属于 sampler 范畴，应由 AIRDC 的 `Demonstrator + FSM/Managers` 负责。

因此，本 sampler 的目标是“复刻 lerobot-record 的**数据写入**部分”，并且把不可确定的语义（例如 action 对应哪些键）通过配置显式表达。

注意：本采样器文件在模块顶层直接 `import lerobot`（遵循 airdc/docs/prompts/prepare.md）。如果环境缺少 `lerobot`，会在 import 阶段直接报错；此时请按 prepare.md 的要求用 `pip` 安装依赖。

---

## 1.1 原版 lerobot-record 的图像采集与写盘逻辑（要点）

LeRobot 的 `lerobot_record.py` 把“图像采集”和“图像写盘”拆成两层：

- 采集：发生在 `robot.get_observation()`
  - 典型实现会遍历 `self.cameras`，对每个 camera 调用 `cam.async_read()`，返回 `np.ndarray`。
  - OpenCV 相机默认输出 `(H, W, 3)`，并默认把 BGR 转成 RGB。
  - RealSense 彩色图输出 `(H, W, 3)`；depth 读出来通常是 `(H, W)` 的 `uint16`。

- 写盘：发生在 `LeRobotDataset.add_frame(frame)`
  - `frame` 里的图像 key 使用 LeRobot dataset 的命名：`observation.images.<cam_key>`。
  - 低维数值（关节位置/速度/夹爪等）通常会被组装成 `float32` 的 1D 向量（例如 `observation.state` 或 `action`），与图像一起写入同一帧。
  - 对 dtype 为 `image/video` 的 feature，`add_frame` 会把当前帧**立刻写为 PNG**：
    - 同步写盘：直接写 PNG。
    - 异步写盘：启用 `AsyncImageWriter` 后把写盘任务丢给线程/进程队列，主线程不阻塞，从而保持采集 FPS 稳定。
  - `save_episode()` 负责把 episode buffer 里的索引/路径/数值写入 parquet；若启用 video，会在 episode 结束后把 PNG 编码成 mp4。

在原版脚本中，每个 control tick 的关键顺序是：先 `get_observation()` 采图 → 再计算 action → 再 `send_action()` → 最后把“obs+action”作为同一帧写入 dataset。

---

## 2. 配置项（LeRobotDataSamplerConfig）

- `episode_dirname`
  - episode 目录名模板（在 dataset 目录下），默认 `episode_{episode:06d}`

- `lerobot_repo_id` / `lerobot_fps` / `lerobot_robot_type`
  - 传给 `LeRobotDataset.create(...)` 的元信息

- `lerobot_task`
  - 每帧必需字段 `task`（lerobot 的 `validate_frame` 要求）
  - 为空时会尝试从 `config.task_info` 推断

- `lerobot_features: List[LeRobotFeatureMapping]`
  - 显式把 AIRDC 的 `round_data` 键（`source_key`）映射到 LeRobotDataset 的 feature key（`feature_key`）
  - 这是“用配置解决语义不确定”的核心：例如哪些键是 `action.*`，哪些键是 `observation.*`

- `lerobot_timestamp_key`
  - 用哪个 key 的 list 来推断 episode 的步数（`num_steps`）
  - 若该 key 不存在，会退化为“以映射键里最长的 list 长度”为步数

- `lerobot_streaming_in_update`
  - 是否在 `update()` 阶段就把每一帧写入 `LeRobotDataset.add_frame()`
  - 默认 True（推荐）：图像会在采集过程中写为 PNG（可异步），上层不会缓存整段图像数据，显著降低内存占用
  - 关闭时：退回到“把所有 payload 缓存在 round_data，最后在 save() 批量写入”的模式

---

## 3. 方法调用顺序（运行时）

在 `DemonstrateInterface` 中，采样器的典型调用顺序是：

1) `sampler.set_info(info)`
2) `sampler.configure()` → 内部触发 `on_configure()`
3) 每轮开始：`compose_path(data_dir, episode)`
4) 每步：`update(payload)`
5) 每轮结束：`save(path, round_data)`
6) 保存/删除/丢弃后：`clear()`
7) 退出：`shutdown()`

---

## 4. 各方法实现逻辑

### 4.1 `__init__(self, config=...)`

- 兼容 Hydra：若传入 dict/DictConfig，则用 `LeRobotDataSamplerConfig.model_validate(...)` 转换并保存到 `self.config`。

### 4.2 `on_configure(self) -> bool`

- 当前实现不持有额外资源，直接返回 True。

### 4.3 （无）动态导入

本实现不做动态导入/自动回退逻辑，缺少依赖会直接报错，便于尽早暴露环境问题。

### 4.4 `compose_path(self, directory: Path, episode: int) -> Path`

- 返回当前 episode 的保存路径。
- 关键点：这里不落盘创建目录；采样器会在首次 `update()` 时懒创建 `LeRobotDataset`（其 `root` 必须不存在）。

### 4.5 `update(self, data: Dict[str, Any]) -> Dict[str, Any]`

- 当 `lerobot_streaming_in_update=True`（默认）时：
  - 首次 `update()`：根据当前 payload 推断 feature `dtype/shape`，然后 `LeRobotDataset.create(root=episode_path)`。
  - 每次 `update()`：把 payload 按 `lerobot_features` 映射为 `frame`，调用 `dataset.add_frame(frame)`。
  - 对 `kind=image/video` 的映射项，会在消费后对 payload 做 `pop(source_key)`，尽早释放大数组引用。
  - 返回空 dict：避免 `DemonstrateInterface` 把每步 payload（包含大图）都 append 到 `_round_data` 里。

这与原版 `lerobot_record.py` 的写盘策略一致：图像在 add_frame 阶段就落为 PNG，episode 结束后再做 save/encode。

### 4.6 `save(self, path: Path, data: Any) -> bool`

- 当 `lerobot_streaming_in_update=True` 且本轮已创建 dataset：
  - `save()` 只负责 `dataset.save_episode()` + `dataset.finalize()`，不依赖 `round_data`。
- 否则：退回到 `_save_with_lerobot(path, data)`（批量写入）。

### 4.7 `_save_with_lerobot(self, path: Path, data: Any) -> bool`

- 输入形态：`round_data` 为 `Dict[str, List[Any]]`，list 的元素通常是 stamped dict：`{"data": ..., "t": ...}`（见测试 payload）。

- 关键约束（来自 lerobot 校验逻辑）：
  - frame 中必须包含 `task`
  - frame 中**不能**显式包含 DEFAULT_FEATURES（例如 `timestamp`），它们由 `LeRobotDataset.add_frame` 自动生成
  - 每个 feature 需要在 `features` 字典里声明 `dtype` + `shape`

- 逻辑步骤（简化版）：
  1) 检查 `lerobot_features` 非空
  2) 推断步数（`lerobot_timestamp_key` 优先，否则取映射键的最长 list）
  3) 根据第 1 帧样本推断每个 feature 的 `dtype/shape`（image/video 默认推断为 (C,H,W)）
  4) `LeRobotDataset.create(...)` 创建 episode root
  5) 逐步构造 frame 并 `dataset.add_frame(frame)`
  6) `dataset.save_episode(...)`

### 4.8 `remove(self, path: Path) -> Optional[bool]`

- 删除整个 episode 目录（`rmtree(path)`）。

### 4.9 `clear(self) -> None` / `shutdown(self) -> None`

- 当前实现为空实现（无持久资源）。

---

## 5. 基于测试 payload 的推荐映射示例

参考 [tests/modules/samplers/lerobot_sampler.yaml](../../../../tests/modules/samplers/lerobot_sampler.yaml)。

该示例基于 `tests/modules/test_sampler.py` 的 payload：

- follow 侧 joint position → `observation.*`
- lead 侧 joint position → `action.*`（示例语义）
- `/camera/rgb` → `observation.images.rgb`
- `/camera/depth` 是 2D (H,W)，lerobot 的 image 校验要求 3D，因此作为 numeric `observation.depth` 保存

如果你希望 depth 也走 image 逻辑，建议把 depth 扩展为 (H,W,1) 或 (1,H,W) 再映射为 image。

---

## 6. 原版数据格式（LeRobotDataset 目录结构与图像存储）

一个 LeRobot dataset 根目录（即 `LeRobotDataset.create(..., root=...)` 的 root）通常包含：

- `meta/info.json`：数据集元信息（repo_id、fps、features、robot_type 等）
- `meta/stats.json`：统计信息
- `meta/episodes/...parquet`：episode 索引/区间信息（chunk/file 分片）
- `data/...parquet`：逐帧数据（数值、路径、索引等；图像通常以“文件路径字符串”形式出现）
- `images/<image_key>/...`：逐帧 PNG（通常是录制过程中的**临时文件**）
  - 其中 `<image_key>` 就是 feature 名（例如 `observation.images.rgb`），因此目录名里可能包含点号
- `data/...parquet`：最终数据文件
  - 对 `dtype: image` 的特征：通常会在 parquet 中以 HuggingFace `datasets.Image` 的结构存储（常见是一个 struct，包含 `bytes` 与 `path` 字段）。
  - 这意味着：即使录制过程中写过 PNG，`save_episode()` 之后也**可能会清理**这些临时 PNG，因此你在磁盘上不一定能看到 `images/<image_key>/episode-xxxxxx/` 下的帧文件，但图像内容仍然在 parquet 里。
- `videos/<video_key>/...mp4`：当启用 video 编码时生成

图像 PNG 的默认路径模板是：

- `images/{image_key}/episode-{episode_index:06d}/frame-{frame_index:06d}.png`

如果你需要人工快速检查图像，推荐直接从 `data/...parquet` 的 `bytes` 字段导出 PNG（测试脚本也可以自动导出）。

原版的校验规则（与采样器映射强相关）：

- 每帧必须包含 `task`（自然语言描述）
- 帧里不允许显式包含默认字段（例如 `timestamp/frame_index/...`），这些由 dataset 内部生成
- image/video 特征必须是 3 维（常见为 `(H,W,3)` 或 `(3,H,W)`）
