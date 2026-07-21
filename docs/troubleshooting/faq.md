# 常见问题

错误一般由命令行参数配置修改不当引起。所以请仔细检查配置是否与实际设备的连接情况一致。

## 帧率差异

使用`mcap info`命令或`Foxglove`查看保存的MCAP文件时，可能会发现视频帧率与预期不符。这是因为数据采集时显示的帧率是数据的实际帧率，而前者为了简化计算同时更好支持远程文件读取，采用了mcap文件写入起始和结束时间计算的平均帧率，而不是按各个话题的`log_time`/`publish_time`计算的实际帧率。通常两者差异不大，但由于数据写入是在一个独立子线程中完成，不会阻塞数据更新，因此当数据更新频率远大于数据写入频率时，会导致数据本身的结束时间戳和文件结束时间戳有较大差距。这是正常现象，一般不影响数据的实际使用。

## 键盘屏蔽

默认情况下，键盘管理器会捕获全局键盘输入以进行数据采集的流程控制。如果需要其它键盘操作，可先按`F2`暂时关闭数据采集程序的键盘响应，否则容易发生异常。后续可再按`F2`恢复键盘响应。

## OpenCV

### headless冲突

OpenCV的`headless`如果与完整版`opencv-python`同时安装，会导致可视化功能无法使用，通常会报如下错误：

```
cv2.error: OpenCV(4.12.0) /io/opencv/modules/highgui/src/window.cpp:1301: error: (-2:Unspecified error) The function is not implemented. Rebuild the library with Windows, GTK+ 2.x or Cocoa support. If you are on Ubuntu or Debian, install libgtk2.0-dev and pkg-config, then re-run cmake or configure script in function 'cvShowImage'
```
或
```
AttributeError: module 'cv2' has no attribute 'WINDOW_NORMAL'
```
此时需要卸载`opencv-headless`并重新安装`opencv-python`，可使用如下命令：

```bash
pip uninstall opencv-headless
pip install opencv-python --force-reinstall
```

## 相机

- 如果出现某个相机显示的图像是纯黑，且帧率异常，一个可能的原因是因为错误地启用了电脑自身的摄像头，
并且电脑有硬件相机屏蔽的开关（通常在电脑右侧边），此时可将尝试其他的相机ID，包括尝试ID为0的情况，因为
有些设备的电脑内置摄像头ID未必为0。
- 如果出现无法同时开启多个相机，请尝试将相机尽可能分散到电脑的不同USB口中（充分利用Type-C口），尽量不要再一个拓展坞上
连接多个相机。如果仍然无法同时开启，考虑使用如下命令临时修改uvc内核模块配置：
`sudo rmmod uvcvideo && sudo modprobe uvcvideo nodrop=1 timeout=5000 quirks=0x80`，然后重新尝试。
如果上述修改后仍然无效，可以考虑调整每个相机的视频流格式，默认为`MJPEG`，可尝试将不同相机改为`YUYV`，特别是不同
型号的相机混用的情况下，可能型号1的相机设置为`MJPEG`，型号2的相机设置为`YUYV`的情况下才能同时使用。
如果上述修改有效，最后可以考虑执行如下命令永久调整uvc内核配置：`echo "options uvcvideo nodrop=1 timeout=5000 quirks=0x80" | sudo tee -a /etc/modprobe.d/uvcvideo.conf >/dev/null`
- RealSense相机也会占用`/dev/video`号，因此当与USB相机一起连接到电脑上时需要注意区分。

更多相机相关问题请参考[USB相机常见问题](usb_cam.md)。

## 资源占用

数据采集程序可能会同时启动多个进程，为了更直观地监控相关进程的资源占用情况，可使用如下脚本（需额外安装：`pip install psutil`）：

```bash
python3 scripts/process_analysis.py airdc
```

该脚本默认会每隔1秒刷新数据采集主进程及其子进程的CPU和内存占用情况（使用了具有可读性的进程名称）。按`Ctrl+C`退出。

通常可看到如下几个主要进程：

- `airdc`主进程：非采集时典型占用CPU约`10%`，采集时约`200% - 700%`，取决于数据量和频率
- `OpenCV`可视化进程（如果启动）：典型占用约`150%`
- 遥操作跟随控制进程（如果启用）
- 相机进程（如果启用并发；每个相机独占一个）

## 启动配置失败

首次配置失败（相机未找到、CAN 未连接、相机端口变化等）时，默认会自动结束并退出程序（`exit_on_configure_failure=true`）。若希望修复后原地重试而不退出，可设置 `managers.self_manager.exit_on_configure_failure=false`：此时程序停留在 `unconfigured` 状态，修复设备 / 配置后按 `c` 键重试配置，或按 `Ctrl+C` 退出。详见[常见配置调整](../configure/common.md)的「配置失败处理」一节。

## 启动卡死

默认启用`OpenCV`的可视化功能，其与默认的键盘控制库`pynput`可能存在冲突，导致图像显示卡死无法正常显示图像窗口，解决方法是优先导入并调用可视化，抢占控制权。为此可在配置文件中默认额外增加一个`prepare_cv2`字段，参考`airbot_ie/configs/basis.yaml`（默认已注释）。

## 其他

- [数据检查](data_checking.md)
