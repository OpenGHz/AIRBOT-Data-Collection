# tests/

硬件感知的测试树。完整规范见 [`docs/develop/testing.md`](../docs/develop/testing.md)。

## 目录

| 目录 | 内容 | marker |
|---|---|---|
| `unit/` | 纯软件单元测试 | `software` |
| `modules/` | 基于 Mock 的模块/集成测试 | `software` |
| `codec/` | 视频编解码测试 | `software` / `hardware+gpu` / `hardware+ros` |
| `hardware/` | 真机/服务冒烟测试（缺资源自动 Skip） | `hardware` + 细分 |
| `manual/` | 演示/交互/CLI 脚本，**不被 pytest 收集**，用 `python …` 直接运行 | — |

> `airbot_ie/` 包下另有一套同结构的 `airbot_ie/tests/`（`unit/ modules/ manual/`）。

## 快速开始

```bash
PY=/home/ghz/.mini_conda3/envs/airbot_play_data/bin/python

$PY -m pytest -m software      # 纯软件（CI 目标），硬件用例自动 Skip
$PY -m pytest                  # 全量：软件跑 + 硬件按探针自动 Skip
$PY -m pytest -m hardware --run-hardware   # 真机台架强制跑硬件用例
pixi run python -m pytest -m ros           # ROS 用例（pixi 环境）
```

核心原则：**缺硬件 → Skip（附中文原因），绝不 Failed。红灯永远意味着软件坏了。**
探针与自动跳过逻辑在仓库根 [`conftest.py`](../conftest.py)。
