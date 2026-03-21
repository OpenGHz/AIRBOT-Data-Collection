#+#+#+#+#+#+#+#+#+#+#+#+#+#+#+#+#+#+#+#+
# Modules

本页用于说明 AIRDC 的模块化扩展方式。

## Sampler

`Sampler` 用于在采集/演示过程中对数据做“收集/处理/落盘”。在 AIRDC 中采样器基类位于
`airdc/airdc/common/samplers/basis.py`，核心抽象类是 `DataSampler`（继承自 `ConfigurableBasis`）。

### 必要方法/属性

由于 `DataSampler` 继承自 `ConfigurableBasis`，一个可通过配置系统/代码正确使用的采样器通常需要：

- `def __init__(self, config: DataSamplerConfig) -> None`：
	将配置保存到 `self.config`（推荐使用 Pydantic 的 `DataSamplerConfig` 或其子类）。
	如果采样器不需要任何配置，可在类作用域声明 `config: None`。

- `def on_configure(self) -> bool`：
	在 `configure()` 期间被调用，用于完成最终初始化（例如创建 writer、打开文件句柄、准备缓存等）。
	成功返回 `True`，失败返回 `False`。

以及 `DataSampler` 本身必须实现的抽象方法：

- `def on_compose_path(self, directory: Path, episode: int) -> Path`：
	生成本轮（episode）数据的保存路径。该方法会在开始采样时被调用，也会在删除已保存数据时被调用。

- `def save(self, path: Path, data: Any) -> bool`：
	将本轮采集到的缓存数据 `data` 持久化到 `path`。成功返回 `True`，失败返回 `False`。
    对于多个episode共用一个数据文件的采样器，path可能是一个被忽略的参数。

### 可选方法/属性

这些方法在基类中有默认行为/默认空实现，可按需覆盖：

- `def get_start_round(self, directory: Path) -> int`：
	返回起始 episode。默认返回 `-1`，表示让上层演示接口根据数据目录中符合所配置后缀的文件数量推断起始 episode。

- `def update(self, data: Dict[str, Any]) -> Dict[str, Any]`：
	对单帧/单次观测数据进行轻量处理并返回。默认原样返回；返回值会被演示接口追加进本轮缓存。
    可以通过pop等方式从data中删除项目，删除的项目不会存储在本轮缓存中，通常用于实时保存降低内存占用。

- `def remove(self, path: Path) -> Optional[bool]`：
	删除已保存的数据。
	- 返回 `None`：交由演示接口执行默认删除逻辑（删除文件/目录，或丢进系统回收站）。
	- 返回 `True`：表示子类已自行完成删除。
	- 返回 `False`：表示删除失败，演示接口会视为删除失败。

- `def clear(self) -> None`：
	清理本轮的内部缓存/状态。演示接口在每轮执行保存操作、执行删除操作、执行丢弃操作之后会调用。

- `def shutdown(self) -> None`：
	释放资源（例如关闭文件句柄、停止后台线程等）。

此外，演示接口会在配置采样器前调用：

- `def set_info(self, info: Dict[str, Any]) -> None`：
	设置采集系统/任务等元信息，供采样器在 `on_configure`/`save` 时使用（例如写入 metadata）。

### 方法调用时机

以演示接口 `DemonstrateInterface` 的流程为例，采样器方法的典型调用顺序如下：

1) 实例化：通过配置系统（例如 hydra 的 `_target_`）或直接构造采样器对象。

2) 配置：演示接口先调用 `sampler.set_info(...)`，随后调用 `sampler.configure()`；
	 `configure()` 内部会触发 `on_configure()` 完成最终初始化。

3) 确定起始轮次：如果 `start_round < 0`，会调用 `get_start_round(data_dir)`；
	 若仍返回负数，上层会根据目录中文件数量推断起始 episode。

4) 开始一轮采样：进入采样状态时调用 `compose_path(data_dir, episode)` 生成保存路径。

5) 采集过程中：每次更新会调用 `update(frame_dict)`，其返回值会被追加到本轮缓存。

6) 保存：结束一轮后调用 `save(path, round_data)`。

7) 清理：保存成功后调用 `clear()` 清空内部状态。

8) 删除：触发删除时会再次调用 `compose_path(data_dir, last_round)` 得到路径，
	 随后调用 `remove(path)`；若返回 `None`，上层会执行默认路径删除。
