# AIRDC: Collecting Multimodal Data For Your Robots

<div align="center">

[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.9%2B-blue.svg)](https://www.python.org/)
</div>

## 环境配置

### 环境要求
为确保本项目正常运行，请确认您的系统环境满足以下要求：

- **Python** `>= 3.9`（推荐使用 Python 3.10，其他版本未经完整测试）

- **操作系统**
  - 支持：Linux（含Docker容器；推荐使用Ubuntu，其他系统未经测试）
  - 不支持：Windows，macOS
  - 未测试：Windows Subsystem for Linux (WSL)

- **系统架构**
  - x86_64（64 位 Intel/AMD）
  - ARM64（如 NVIDIA Jetson等）

- **依赖工具**
  - `POSIX shell`（用于运行一键安装脚本等，如`sh`等）
  - （可选）虚拟环境管理工具，如 `conda`、`venv`等

- **其他**
  - 至少 2 GB 可用内存
  - 磁盘空间：视采集数据量而定

注意，系统环境主要受限于所使用的具体后端，如机器人 SDK 和相机驱动等，请确保这些后端软件的系统要求也得到满足。

### 虚拟环境
建议创建独立的Python虚拟环境进行数据采集环境安装，以满足Python版本要求同时避免与其他项目的依赖冲突。以`conda`为例，可执行如下命令创建并激活虚拟环境：

```bash
conda create -n airdc python=3.10 && conda activate airdc
```

### 机器人 Setup

!!! warning "环境要求"

    请使用上述创建的Python虚拟环境（如果使用的话）进行后续依赖安装！

数据采集程序依赖于机器人的基本软件环境，请自行安装并配置好对应机器人的驱动程序和Python SDK。部分机器人软件安装参考链接如下：

- [AIRBOT Play/PTK/TOK](docs/setup/airbot_play.md)

### 数据采集

!!! warning "环境要求"

    - 请使用上述安装好机器人相关软件的`Python`环境进行后续依赖安装！
    - 一键安装脚本默认分别使用`apt`和`pip`进行系统和`Python`依赖安装，如果使用其他包管理工具，请手动安装对应依赖，或者修改安装脚本后再执行。对于前者，也可以在执行安装脚本时传入安装命令作为参数，例如`$SHELL ./install.sh sudo yum install -y`。
    - 仓库clone注意指定分支/标签，以保证版本一致性。若不指定则默认使用`main`分支，是最新的稳定版本。`develop`分支为最新开发版本，可能存在不稳定情况。如需固定版本，请指定特定标签。

```bash
git clone https://github.com/DISCOVER-Robotics/AIRBOT-Data-Collection.git --depth 1 -b <tag/branch> data-collection
cd data-collection
conda activate airdc
$SHELL install/install.sh
```

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

对于Intel-RealSense相机，可以运行`$SHELL install/install_realsense.sh`安装相关依赖，并执行如下命令查看已连接相机的序列号：

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
