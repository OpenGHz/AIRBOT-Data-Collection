# Scripts 工具集

本页面列举 `scripts/` 目录下的实用脚本及其用法。这些脚本用于相机检查、数据处理、性能分析、标定等运维与开发任务。

## 相机工具

### `list_cameras.py`

列出所有 V4L2 相机的完整信息（设备路径、capabilities、controls、支持的格式/分辨率/帧率）。

```bash
python scripts/list_cameras.py
```

**需要**：`airdc[v4l2]`（`linuxpy`）。

### `check_cameras.py`

快速检查所有 `/dev/video*` 设备，列出卡类型、支持格式、USB 路径，并标记 USB 总线冲突。

```bash
python scripts/check_cameras.py
```

**需要**：系统 `v4l2-ctl` 命令。

### `multi_capture.py`

并发打开多个 V4L2 相机并实时显示解码后的预览（OpenCV imshow）。用于验证多相机配置与带宽。

```bash
python scripts/multi_capture.py 0 2 4 -ff MJPEG MJPEG MJPEG --frame-size 640x480
```

**参数**：
- `0 2 4`：相机设备号（`/dev/video0`, `/dev/video2`, `/dev/video4`）
- `-ff`：每个相机的 FourCC 格式（`MJPEG` / `YUYV` 等）
- `--mode`：capture 模式（`auto` / `mmap` / `read`）
- `--frame-size`：分辨率

## 数据处理

### `check_first_image.py`

从 MCAP episode 数据集中加载并检查第一帧图像，可选显示（`--imshow`）。

```bash
python scripts/check_first_image.py data/my_task/episode_000000.mcap --imshow
```

### `merge_batch_folders.py`

合并并行采集的 batch 子目录（`data/task/`, `data/task_1/`, `data/task_2/`, ...）到单个根目录，文件按序重命名。

```bash
python scripts/merge_batch_folders.py --root data/my_task --start-index 0 --dry-run
```

**参数**：
- `--root`：根目录路径
- `--start-index`：起始文件编号（默认 0）
- `--dry-run`：预览操作，不实际移动文件

## 性能分析

### `parallel_bench.py`

启动 N 个并行 `airdc` 进程（分配到多 GPU），并聚合吞吐统计（"Average update freq"）。用于仿真/无硬件基准测试。

```bash
python scripts/parallel_bench.py -n 4 --gpus 0,1 \
  --command "pixi run -e collect-aao airdc --name aao_config batch_size=2 samplers=mock"
```

**参数**：
- `-n`：进程数
- `--gpus`：GPU ID 列表（逗号分隔）
- `--command`：要并行运行的命令（默认为 `airdc` 仿真 mock 采样器基准）

### `process_analysis.py`

实时监控匹配命令片段的进程（类似 `top`），显示 CPU/内存/GPU 使用率。

```bash
python scripts/process_analysis.py airdc -i 1.0 -n 5
```

**参数**：
- `airdc`：命令片段（匹配所有包含 `airdc` 的进程）
- `-i`：刷新间隔（秒）
- `-n`：迭代次数（0 = 无限）

**需要**：`psutil`。

## 标定

### `calibration/camera/calibrate_intrinsic.py`

从棋盘格视频标定相机内参（焦距、畸变），输出 `calibration.yaml` 和去畸变图像。

```bash
python scripts/calibration/camera/calibrate_intrinsic.py
```

**交互式**：脚本会提示选择视频文件、输入棋盘格尺寸（行×列、方格边长 mm）。

**输出**：
- `calibration.yaml`：内参矩阵与畸变系数
- `undistorted_*.png`：去畸变示例帧

详细说明见 [scripts/calibration/camera/README.md](../../scripts/calibration/camera/README.md)（中文）。

## 对齐工具

### `align/camera_perspective/overlay_reference.py`

在实时相机预览上叠加半透明参考图像（用于调整相机视角，使其与仿真/设计图对齐）。

```bash
python scripts/align/camera_perspective/overlay_reference.py sim_env.jpg 0
```

**参数**：
- `sim_env.jpg`：参考图像路径（项目自带 `sim_*.jpg` 示例）
- `0`：相机 video ID

按 `q` 退出。

## tmux 会话管理

### `tmux/run_panes.sh`

创建单个 tmux 窗口，按配置分割成多个 pane，每个 pane 运行一个命令。

**用法**：编辑脚本中的 `COMMANDS` 和 `SPLIT_DIRECTIONS` 数组，然后运行：

```bash
bash scripts/tmux/run_panes.sh
```

### `tmux/run_winds.sh`

创建 tmux 会话，每个命令独占一个窗口。

```bash
bash scripts/tmux/run_winds.sh
```

## UI 工具

### `ui_launcher.py`

启动 Tkinter GUI 控制面板（基于 `airbot_ie/configs/ui.yaml`），提供 "Auto Configure" / "Modify Configuration" / "Start Data Collection" 按钮。

```bash
python scripts/ui_launcher.py
```

**注意**："Modify Configuration" 按钮引用的 `airbot_ie.scripts.modify_config` 脚本 **不存在**，需自行实现或禁用该按钮。

## 相关文档

- [相机检查 FAQ](../troubleshooting/faq.md#相机)
- [USB 相机并发](../troubleshooting/usb_cam.md)
- [性能测试](../troubleshooting/performance.md)
- [标定详细指南](../../scripts/calibration/camera/README.md)
