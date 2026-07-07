# 常见配置调整说明

本文档以`airbot_ie`默认配置为例介绍了一些常见的配置调整说明，帮助用户更好地理解和使用数据采集系统（无特殊说明，文件路径均相对于`airbot_ie`目录）。

## 基本配置

- `update_rate`: 数据采集频率。数据采集时按此频率将全部组件的观测数据添加到采样器中
- `sample_limit.start_round`: 数据采集的起始轮数。如果已经采集有数据，请对应修改，避免覆盖已有数据。默认设置为`-1`，自动根据保存目录下已采集的数据文件数量自动确定起始轮数（不会自动判断文件序号，因此如果文件编号不连续，会导致起始轮数判断错误）。
- `sample_limit.size`: 采样帧数的上限。一方面，有些算法程序要求采集的数据帧数一致，另一方面，可以避免忘记停止采集而导致采集数据量过大内存溢出。默认设置为1000

## 动作回调

支持配置在数据采集状态变化时自动执行指定动作，例如在每次开始采集前自动将机器人重置到初始位姿等，可参考`configs/demonstrators/test.yaml`中的`send_actions`字段进行配置（注意不要直接在`test.yaml`中修改）。

## 相机功能

### 深度数据
默认情况下深度相机不采集深度数据（体积较大），如果需要采集，可参考`configs/demonstrators/realsense.yaml`中的参数，在相应相机配置字段下添加`enable_depth`和`align_depth`字段并设置为`true`。点云数据不支持也不建议直接采集，请自行结合相机参数信息从深度图像中生成。

### 非阻塞取图
相机支持非阻塞取图模式，可在相机配置中增加`blocking`字段并设置为`false`，这样可以避免因相机帧率不足影响整体数据采集频率，不过会导致相机数据中出现重复帧（目前暂不支持相机端异步不等长采集，但可通过配置视频编码器端的采集策略实现最终不等长的数据存储，见[视频编码参数](#视频编码参数)）。

### RealSense可选配置
RealSense相机的分辨率和帧率等配置受USB口是否为USB3.0影响，可通过安装使用`rs-enumerate-devices`命令查看相机支持的分辨率和帧率，并在配置文件中进行相应修改。

### 相机信息覆盖

可在对应相机的配置下，增加如下参数以覆盖默认相机信息：
```yaml
rgb_camera:
    intrinsics:
        distortion_model: plumb_bob
        d: [0.0, 0.0, 0.0, 0.0, 0.0]
        k: [615.0, 0.0, 320.0, 0.0, 615.0, 240.0, 0.0, 0.0, 1.0]
        binning_x: 0
        binning_y: 0
    calibration:
        r: [1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0]
        p: [615.0, 0.0, 320.0, 0.0, 0.0, 615.0, 240.0, 0.0, 0.0, 0.0, 1.0, 0.0]
        roi:
          x_offset: 0
          y_offset: 0
          height: 0
          width: 0
          do_rectify: false
```

深度模组的配置类似，只是字段名称替换为`depth_module`即可。

## 示教器

内置的`GroupedDemonstrator`示教器通常可满足大部分数据采集需求，常见配置如下：

### 自动遥操

默认情况下，需要根据机器人实际使用方式手动启动遥操作控制。若要开启自动遥操作控制，需调整`demonstrator.instance.auto_control`下的如下字段：
  - `groups`字段设置为`null`（注意不是列表`[null]`）；
  - 增加`modes`字段并设置为列表`[process]`（`process`表示以子进程的方式启动控制程序）；
  - 增加`rates`字段并设置为列表`[100]`（`100`是默认的遥操控制频率，理论上数据采集的更新频率不应超过该值）。
前提是要保证`follower`的`send_action`方法能正确处理`leader`的`capture_observation`方法的返回值。

### 观测后处理

支持对采集到的`leader`观测数据进行后处理配置，例如对关节位置数据进行范围限制，或对位姿数据进行坐标变换等。可通过在`demonstrator.post_capture`字段下增加对应的配置实现，具体可参考`configs/demonstrators/post_capture`目录下的配置示例。将整个字段设置为`null`表示对所有`leader`组件启用内置的默认自动后处理。同理，将某个组的`leader`名称对应的值设置为`null`表示对该组启用默认后处理。此外，`transform`参数也支持设置为`null`，表示使用内置的默认坐标变换处理。注意，目前通常手动覆盖部分配置会导致全部默认配置失效，因此对于存在默认配置的情况应小心修改，避免遗漏必要的配置项。

### 并发调用

默认情况下，各个组件的观测是依次按顺序被获取的。在阻塞模式下，如果某些组件的调用时间较长，可能会影响整体的数据采集频率；尽管非阻塞模式下可以避免该问题，但是失去了数据获取的同步性，并且多个组件在同一进程中也会互相竞争资源降低整体性能。为避免上述问题，可以将组件类通过`airdc.common.systems.wrappers.concurrent_instantiate`函数进行并发包裹和实例化，将原类型的观测获取转换为基于共享内存的多进程调用，从而提升整体性能。目前已测试了各种相机的并发获取（图像类型为`NDArray`），具体可参考`configs/demonstrators/concurrent.yaml`中的配置示例。注意，并发调用需要额外的系统资源开销，请仅对真正有需要的组件使用。

## 可视化器

- 数据过滤：支持通过`key_filtering`字段配置可视化器的数据过滤规则，以筛选出支持可视化的数据进行显示，省去额外的无效数据处理代码逻辑。参考`airbot_ie/configs/basis.yaml`中的配置示例。
- 交换颜色通道：支持通过`swap_rgb_bgr`字段支持`RGB`和`BGR`颜色通道的互转，以适配不同的相机和显示设备。
- 编码格式：支持通过`pixel_format`字段指定图像数据的编码格式，如`MJPEG`、``YUYV``等，以适配不同的相机输出格式的解码。

### OpenCV

支持可视化`NDArray`和`bytes`类型的图像。`NDArray`类型支持shape为`(H, W, 3)`的彩色图像和`(H, W)`的灰度、深度图像，以及`(H, W, C)`任意通道维度（C不等于3）的图像（例如`heatmap`图像）。

### 无头模式

如果需要在`headless`模式下运行，即不显示`GUI`窗口，可在配置文件中去除`visualizers`字段，或将`visualizers.names`设置为空列表`[]`。

## 采样器

### 采样器类型

除了默认采样器，还支持：

- ROS-MCAP采样器：`airdc.common.samplers.mcap_sampler_ros.McapDataSamplerROS`。该采样器会根据`ROS_VERSION`环境变量选择相应版本的后端。各后端说明如下：
  - ROS1：尽管ROS1本身不支持MCAP格式，但是其保存的MCAP文件可以支持`Foxglove`可视化以及通过`mcap-ros1-support`包读取。使用虚拟环境时，通常需额外安装以下依赖：`pip install rospkg catkin_pkg empy`。 <!-- codespell:ignore empy -->
  - ROS2：其保存的MCAP的消息格式与录制的Bag文件兼容。但需注意虚拟环境的Python版本需与ROS2版本对应的Python版本匹配。

### 任务信息

不同任务一般需要手动配置一些基本信息，可通过`sampler.instance.task_info`字段配置，这些信息将可能在后续用作区分不同类型数据，以及可能用作模型的`prompt`。常见配置可参考`configs/demonstrators/airbot_play.yaml`中的注释内容。

### 独立保存视频文件

为sampler增加配置：`video_save_to: folder`，这样视频数据将不保存到mcap文件中，而是独立保存为`.mp4`文件到文件夹中。

### 视频编码参数

为sampler增加配置`av_coder`，常用字段如下：

- `non_monotonic_mode`用于设置非单调递增的视频帧的处理方式，可选值如下：
  - `adjust`：调整时间戳以保证单调递增（增加一个微小量）。默认值。
  - `drop`：丢弃。适用于对视频数据的异步非等长采集场景。
  - `raise`：抛出异常
  - `none`：不做处理，可能导致一些视频编解码问题。
- `non_monotonic_log`用于控制是否打印非单调递增的日志信息，默认值为`true`。

## 数据合并

默认情况下各个组件的数据拥有自己独立的键名，例如`arm`和`eef`分别拥有自己的`joint_state`数据。ROS通常会将这些数据合并到同一个`joint_sates`话题下发布，因此在采集时需要将这些数据合并。这可以通过在根配置下增加`key_merge`字段，可配置自定义的函数（输入为原始字典，输出为合并后的字典）或分别指定合并方式函数`method`和合并指示函数`pred`，经由内置合并器根据该配置进行合并（适用于大多数情况）。具体可参考：`configs/demonstrators/ros.yaml`。

## 名称重映射

默认的`grouped demonstrator`示教器通过`group name`、`component name`和`data key`三层名称通过`/`连接形成最终的数据名称，其中`data key`一般遵循：`<sub component name>/<data type>/<field name[optional]>`结构。例如`/left/leader/arm/joint_state`。但ROS通常期望数据名称为：`/robot/arm_left_leader/joint_states`。为此，可通过在`sampler.instance`字段下增加`key_remap`配置，指定一个映射函数，具体可参考：`configs/key_remap/example.yaml`。

## 数据种类

机器人通常可以获取多种数据，例如各种传感器实时数据，以及机器人关节名称信息等。通常，非实时的数据默认通过`info`接口获取而不被加入观测数据中，但ROS有时会要求将这些数据实时发布以保持完整性，例如`JointState`消息中包含固定的关节名称信息。为此，可通过在机器人配置文件中的观测接口中增加对应数据类型的接口，具体可参考：`configs/robots/airbot_play_with_name.yaml`。

## 日志

### 取消性能警告

当实际采集频率低于设定值时，程序默认会以警告级别打印超时提示，可以通过命令行或者配置文件中设置`log_jitter`为`false`来关闭该提示，保持终端整洁。


## 命令行参数覆盖

所有配置均可通过命令行参数进行覆写，默认基于`Hydra`框架，有如下规则：
- 使用`.`分隔层级关系，例如`dataset.directory`表示配置文件中`dataset`字段下的`directory`字段；
- 布尔类型使用`true`或`false`表示（首字母小写）；
- 不同参数之间使用空格隔开；
- 列表类型使用`"[]"`括起，注意使用双引号包裹以避免shell解释错误；元素之间使用英文逗号分隔。
- 通过`airdc -h`查看可覆盖命令行参数及其当前值。
