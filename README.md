# AIRDC: Collecting Multimodal Data For Your Robots

<div align="center">

[![Docs](https://img.shields.io/badge/docs-online-brightgreen.svg)](https://openghz.github.io/AIRBOT-Data-Collection/)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.9%2B-blue.svg)](https://www.python.org/)
</div>

## 文档导航

📖 **在线文档站点：<https://openghz.github.io/AIRBOT-Data-Collection/>**（推荐，支持搜索与侧边栏导航）

其他文档入口：

- [文档地图](docs/README.md)
- [架构总览](docs/architecture/overview.md)
- [数据流说明](docs/architecture/data-flow.md)
- [本地开发运行手册](docs/runbooks/local-dev.md)
- [MCAP 数据检查手册](docs/runbooks/inspect-mcap-dataset.md)

## 环境配置

### 环境要求
为确保本项目正常运行，请确认您的系统环境满足以下要求：

- **Python** `>= 3.9`（**推荐使用 Pixi 管理环境，已固定 Python 3.12**；传统 pip/conda 安装支持 Python 3.9+）

- **操作系统**
  - 支持：Linux（含Docker容器；推荐使用Ubuntu，其他系统未经测试）
  - 不支持：Windows，macOS
  - 未测试：Windows Subsystem for Linux (WSL)

- **系统架构**
  - x86_64（64 位 Intel/AMD）
  - ARM64（如 NVIDIA Jetson等）

- **依赖工具**
  - `POSIX shell`（用于运行一键安装脚本等，如`sh`等）
  - （推荐）[Pixi](https://pixi.sh) — 现代跨平台包与环境管理工具
  - （可选）虚拟环境管理工具，如 `conda`、`venv`等

- **其他**
  - 至少 2 GB 可用内存
  - 磁盘空间：视采集数据量而定

注意，系统环境主要受限于所使用的具体后端，如机器人 SDK 和相机驱动等，请确保这些后端软件的系统要求也得到满足。

### 安装方式

#### 方式一：Pixi（推荐）

Pixi 是现代跨平台包管理工具，自动管理 Python 3.12 环境及所有依赖（包括 conda 和 PyPI 包），支持多环境隔离（数据采集、训练、推理）。

```bash
# 1. 安装 Pixi
bash install/install_pixi.sh

# 2. 安装项目依赖（自动创建并配置环境）
pixi install

# 3. 进入数据采集环境（或直接用 pixi run）
pixi shell -e collect
```

详细说明见 [Pixi 环境与工作流指南](docs/setup/pixi.md)。

#### 方式二：传统 pip/conda 安装

适合单一用途或已有 Python 环境的场景。

```bash
# 1. 创建虚拟环境（可选但推荐）
conda create -n airdc python=3.12 && conda activate airdc
# 或使用 venv: python3.12 -m venv .venv && source .venv/bin/activate

# 2. 克隆仓库
git clone https://github.com/DISCOVER-Robotics/AIRBOT-Data-Collection.git --depth 1 -b <tag/branch> data-collection
cd data-collection

# 3. 安装系统依赖与 Python 包
bash install/install.sh
```

`install.sh` 会安装系统依赖（`libturbojpeg`、`gcc` 等）并执行 `pip install -e .[all,airbot]`。

### 机器人 SDK 安装

数据采集依赖机器人的 Python SDK。部分机器人安装参考：

- [AIRBOT Play/PTK/TOK](docs/setup/airbot_play.md)

`$SHELL`一般可简单用`bash`代替（下同）。安装结束后终端可能有红色报错提示部分依赖问题，一般可忽略，进行后续操作即可。

<a id="cam_info"></a>
### 相机信息

可以通过如下命令查看已连接相机的信息：

```bash
python3 scripts/list_cameras.py
```

在终端输出中可以看到每个相机的名称、设备路径（含ID）、USB端口（总线）信息、支持的图像格式和对应的分辨率和帧率，以及设备总数等信息。

### 相机检查

连接所需的全部相机，对于USB相机，可以执行如下命令进行检查：

```bash
python3 scripts/multi_capture.py 2 4 6 -ff MJPEG MJPEG MJPEG
```

其中`2 4 6`指定了相机的ID号，可通过`ls /dev/video*`命令查看并做相应修改，一般来说使用偶数的ID，奇数的ID不可用。
`-ff`后面的参数指定了每个相机的视频流格式，一般使用`MJPEG`。常见问题见[常见问题](docs/troubleshooting/faq.md#相机)。

#### RealSense相机支持

对于Intel-RealSense相机，安装 `pyrealsense2` 依赖后，执行如下命令查看已连接相机的序列号：

```bash
python3 airdc/common/devices/cameras/intelrealsense.py
```

## 程序配置

数据采集程序默认基于`Hydra`框架进行配置，支持通过`yaml`文件配置默认参数以及通过命令行对参数进行覆写。
<!-- 若需更换其他配置框架，请参考[配置框架自定义](docs/configure/cfger.md)。 -->

数据采集的配置选项主要包括示教器/遥操系统（Demonstrator）、采样器（Sampler）、管理器（Manager）、可视化器（Visualizer）、状态机（FSM）以及其他基本配置（如logging、数据保存路径等）。

由于配置参数较多，因此提供了默认配置文件夹`airbot_ie`，一般可在此基础上进行修改。该配置分为真机和仿真两部分：

- 真机（config.yaml）：
  - 示教器：使用`grouped demonstrator`分组指定leader、follower和observer三种角色将分散的设备进行组合，完成遥操控制和数据采集。
  - 采样器：使用`mcap sampler`将episode数据保存为基于`FlatBuffers` Schema的`.mcap`格式文件。
  - 管理器：使用`keyboard manager`结合`self manager`通过键盘进行数据采集的流程控制。
  - 可视化器：使用`OpenCV visualizer`进行数据的实时显示和监控。
- 仿真（aao_config.yaml）：
  - 示教器：使用`SingleBatchedComponentDemonstrator`按batch_size对数据进行分组，底层使用了`auto-atomic-operation`的`MuJoCo`仿真环境。
  - 采样器：使用`mcap_ros_struct sampler`将episode数据保存为基于`ROS` 消息结构体的`.mcap`格式文件（自动根据环境变量选择`ROS1/ROS2`）。
  - 管理器：使用`auto_atom manager`结合`self manager`通过不同任务各自的配置进行自动化采集。
  - 可视化器：默认在配置文件中将可视化设置为null不进行可视化，可自行取消null设置。可视化支持两种模式：一种是基于`mujoco-viewer`的环境内置可视化（可交互式调整），另一种是与真机一样的外置可视化（仅支持`demonstrator.component.structured=false`观测格式）。

部分机器人相关配置说明链接如下：

- [AIRBOT Play/PTK/TOK](docs/configure/airbot_play.md)

部分配置调整说明链接如下：

- [常见配置调整](docs/configure/common.md)

## 启动遥操

请根据实际机器人的使用方式进行启动。部分机器人遥操作说明链接如下：

- [AIRBOT Play/PTK/TOK](docs/teleop/airbot_play.md)

## 采集流程

### 启动程序

完成前述准备工作后，可执行如下命令运行数据采集程序（终端在`data-collection`目录）：

```bash
airdc
```

上述命令将使用默认配置文件中的配置。此外，也可以在命令行中重新指定配置文件，或对配置文件中的参数进行覆写，例如：

```bash
airdc --path airbot_ie/configs/config.yaml dataset.directory=example
```

其中`--path`指定了配置文件路径（这里就是默认路径），`dataset.directory=example`指定了数据保存目录为`data`目录下的`example`文件夹。更多命令行参数覆写规则见[配置调整说明](docs/configure/common.md#命令行参数覆盖)。

启动后，默认可以使用键盘进行数据采集的流程控制，键盘使用说明在可在终端打印中上滚看到，或者按键盘`i`键重新打印。

### 采集建议

提供了一些可能有助于提高所采集的数据质量的建议：[数据采集建议](docs/suggestion/collect.md)

## 数据可视化

视保存的数据格式不同，可使用不同工具进行数据可视化。部分数据可视化说明链接如下：

- [Foxglove](docs/visualize/foxglove.md)
- [AIRBOT MCAP Data Viewer](docs/visualize/airbot.md)
- [PlotJuggler](docs/visualize/plot_juggler.md)

## 性能测试

请参考[性能测试](docs/troubleshooting/performance.md)页面。

## 常见问题

请参考[常见问题](docs/troubleshooting/faq.md)页面。
