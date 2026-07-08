# 测试规范（Testing Specification）

本项目的测试架构围绕一个核心原则：**把软件逻辑与硬件状态解耦**。机器人代码依赖相机、机械臂、Redis、ROS 等物理硬件与外部服务，本规范通过「**环境自适应（缺硬件自动 Skip 不报红）+ 标签化过滤（软/硬隔离）+ 增量/全量 CI**」把硬件状态对软件质量评估的噪声降到最低。

> 一句话：**红灯永远意味着「软件坏了」，而不是「这台机器没插相机」。**

---

## 1. 分层与测试矩阵

| 目录 | 层次 | 硬件依赖 | marker | 何时跑 |
|---|---|---|---|---|
| `tests/unit/` | 纯软件单元 | 无 | `software` | 每次提交、PR、CI 默认 |
| `tests/modules/` | 基于 Mock 的模块/集成 | 无（用 Mock 替代硬件） | `software` | 每次提交、PR、CI 默认 |
| `tests/codec/` | 编解码 | CPU 或 GPU/ROS | `software` / `hardware+gpu` / `hardware+ros` | 视资源自动跳过 |
| `tests/hardware/` | 真机/服务冒烟 | 相机/Redis/ROS 等 | `hardware` + 细分 | 有资源才跑，否则 Skip |
| `tests/manual/` | 演示/交互/CLI 脚本 | 各种 | 不被 pytest 收集 | `python …` 手动运行 |
| `airbot_ie/tests/{unit,modules,manual}/` | 同上（airbot_ie 包域） | 同上 | 同上 | 同上 |

`tests/manual/` 与 `airbot_ie/tests/manual/` 里是**可运行的脚本**（相机查看器、Redis 生产者/消费者、点云可视化、基准测试等），它们不是 pytest 用例，通过 `norecursedirs` 被排除，不参与收集。直接运行：`python tests/manual/cameras/realsense.py -h`。

---

## 2. 标签（marker）体系

全部 marker 注册在 `pyproject.toml` 的 `[tool.pytest.ini_options].markers`，配合 `--strict-markers`（未注册的 marker 直接报错，防拼写）。

| marker | 含义 | 探针（缺失即自动 Skip） |
|---|---|---|
| `software` | 纯软件，任何环境都应通过 | —（不跳过） |
| `hardware` | 需真机/服务（伞标签，与下面细分同挂） | 见细分 |
| `realsense` | Intel RealSense 相机 | `pyrealsense2` 且枚举到设备 |
| `camera` | `/dev/video*`（v4l2/USB） | 存在 `/dev/video*` |
| `gpu` | NVIDIA GPU（nvenc/cuda） | `nvidia-smi` 在 PATH |
| `redis` | 本地 Redis 服务 | 能连 `localhost:6379`（`AIRDC_REDIS_HOST/PORT` 可覆盖） |
| `ros` | ROS 环境 | `$ROS_VERSION` 或 `$ROS_DISTRO` 已设置 |
| `display` | 图形显示 | `$DISPLAY` / `$WAYLAND_DISPLAY` |
| `slow` | 耗时/基准，默认不跑 | —（用 `-m slow` 显式选） |
| `manual` | 交互/演示 pytest 用例，默认不收集 | —（用 `--run-manual`） |

一个硬件用例通常**同时**挂伞标签与细分标签，例如：

```python
import pytest

pytestmark = [pytest.mark.hardware, pytest.mark.realsense]
```

---

## 3. 硬件探针与自动跳过（框架核心）

逻辑集中在仓库根 [`conftest.py`](../../conftest.py)，对 `tests/` 与 `airbot_ie/tests/` 同时生效：

1. **探针函数**（`functools.lru_cache`，每会话最多探一次）：`has_display / has_realsense / has_camera / has_gpu / has_redis / has_ros`。
2. **`pytest_collection_modifyitems`**：收集后遍历每个用例——若挂了某个资源 marker 而对应探针为假，就给它补一个 `pytest.mark.skip`，并附上**中文原因**（如 `⏭️ 跳过[realsense]：未检测到 Intel RealSense 相机`）。这正是「缺硬件→Skip 而非 Failed」的落点。
3. **opt-in 开关**：`--run-hardware`（缺硬件也强制跑，用于真机台架）、`--run-manual`。

> **重要约束：import 时不能有副作用。** 收集阶段会 import 每个用例模块，此时 marker 的 skip 还没生效。因此硬件相关的 import（`cv_bridge`、`pyrealsense2`、`mcap_data_loader.serialization.ros` 等）要放进**测试函数体内**，或用 `pytest.importorskip("cv_bridge")`，否则会在收集期直接报错、无法被跳过。

---

## 4. 运行方式

测试有两个环境（见根 `CLAUDE.md`）：

- **默认/软件测试** → conda 环境 `airbot_play_data`（Python 3.10，已装 pytest 与全部硬件库）。
- **ROS 相关测试** → 项目 `pixi` 环境（Python 3.12，robostack-jazzy，`ROS_VERSION=2`）。

```bash
PY=/home/ghz/.mini_conda3/envs/airbot_play_data/bin/python

# 纯软件（CI 目标）：硬件用例自动 Skip，绝不报红
$PY -m pytest -m software

# 默认全量：软件跑 + 硬件按探针自动 Skip（本机有相机/Redis 就会真跑）
$PY -m pytest

# 只跑硬件/服务用例；无资源则全部 Skip，不 fail
$PY -m pytest -m hardware

# 真机台架：即使探针没探到也强制跑
$PY -m pytest -m hardware --run-hardware

# 只看会跑什么，不执行（确认 manual/ 未被收集、无收集错误）
$PY -m pytest --collect-only -q

# ROS 用例在 pixi 环境跑
pixi run python -m pytest -m ros
```

也可用 pixi 任务：`pixi run test`（= `pytest -m software`）、`pixi run test-hardware`、`pixi run test-all`。

**环境变量：** `AIRDC_TEST_CLEANUP_OUTPUTS=1` 让 `test_sampler` 跑完清掉输出目录；`AIRDC_REDIS_HOST` / `AIRDC_REDIS_PORT` 指定 Redis 服务地址。

---

## 5. Mock / 仿真（不连硬件也能测）

纯软件测试**优先复用项目已有的 Mock 层**，不要直接调硬件驱动：

| 真实硬件 | Mock 替身 |
|---|---|
| 相机（RealSense/v4l2） | `airdc.common.devices.cameras.mock.MockCamera` |
| 采集系统 | `airdc.common.systems.mock` |
| 机器人 AIRBOT Play | `airbot_ie.robots.airbot_play_mock` |
| 采样器 | `airdc.common.samplers.basis.MockDataSampler`（配置：`tests/modules/samplers/mock_sampler.yaml`） |

conftest 提供了开箱即用的 fixture：`mock_camera`（配置好的 MockCamera）、`sample_payload`（关节+RGB/Depth 的合成观测）、`sample_mcap`（样例 MCAP，缺失则 Skip）、`tmp_output_dir`。

范式参考：[`tests/modules/test_sampler.py`](../../tests/modules/test_sampler.py)（Mock 配置 + hydra `instantiate`）、[`tests/modules/test_discover_replay_repeats.py`](../../tests/modules/test_discover_replay_repeats.py)（`unittest.mock` 打桩 + `pytest.raises`）、[`airbot_ie/tests/modules/test_airbot_play_mock.py`](../../airbot_ie/tests/modules/test_airbot_play_mock.py)（用 mock 机器人跑控制逻辑）。

---

## 6. 增量测试 / 全量测试

| 类型 | 频率 | 触发 | 命令 |
|---|---|---|---|
| 纯软增量 | 极高（每次 Push） | 开发者提交 | `pytest -m software <改动相关路径>` |
| 纯软全量 | 高（每次 PR） | 合并请求 | `pytest -m software`（CI 的 `software-test` job） |
| 硬件/仿真增量 | 中 | 改动驱动层 | `pytest -m hardware --run-hardware`（真机/台架） |
| 全量真机回归 | 低（Nightly/发布前） | 定时或版本发布 | 真机环境 `pytest --run-hardware` |

- **增量**：只对本次改动相关的用例/路径跑测，例如 `pytest -m software tests/codec airbot_ie/tests`。
- **CI**：`.gitlab-ci.yml` 的 `software-test` job 在 `test` 阶段跑 `pytest -m software -ra`。⚠️ 该 job 当前用 `python:3.10` 镜像并 `allow_failure: true`，**需把 `image:` 指向含依赖的 CI 镜像后去掉 `allow_failure`**，才能作为硬门禁。

---

## 7. 写新测试的规范（Checklist）

1. **命名与位置**：真用例放对应分层目录，文件名 `test_*.py`、函数名 `test_*`；演示/交互脚本放 `manual/`（不加 `test_` 前缀）。
2. **挂 marker**：纯软件挂 `pytestmark = pytest.mark.software`；需硬件/服务的挂 `[pytest.mark.hardware, pytest.mark.<资源>]`，让它能被探针自动跳过。
3. **禁止 import 时副作用**：不要在模块顶层打开相机、连服务、跑死循环、`argparse`。硬件/ROS 的 import 放进函数体或用 `pytest.importorskip(...)`。
4. **用 fixture 与 `tmp_path`**：输出写到临时目录，别污染工作区；能用 `mock_*` fixture 就别碰真硬件。
5. **软件依赖缺失也要优雅降级**：跨环境可能缺某个包（如 pixi 没 `cv_bridge`、conda 没 ROS）——用 `pytest.importorskip` 让它 Skip 而非报错。
6. **已知坏点用 `xfail`**：依赖/上游的已知缺陷，用 `@pytest.mark.xfail(reason=..., strict=False)` 标注并留线索，别静默删测试。

---

## 8. 参考

- 框架实现：仓库根 [`conftest.py`](../../conftest.py)
- 配置：`pyproject.toml` 的 `[tool.pytest.ini_options]`；`pixi.toml` 的 `[tasks]`
- 目录索引：[`tests/README.md`](../../tests/README.md)
