# AIRBOT Play/PTK/TOK 遥操作指南

初次使用请参考 [初次点亮 AIRBOT Play](http://docs.qiuzhi.tech/5.1.6/airbot-play/quick-start/running.html) 熟悉机械臂的基本使用。

数据采集整体上可分为拖动示教和遥操作示教两种方式。对于前者通常使用1至2台机械臂（安装有末端执行器或特制的示教器），而后者每组至少需要用到2台机械臂，一台作为示教臂（可以是安装有末端示教器的 AIRBOT Play 或 AIRBOT Replay），另一台作为执行臂（安装有末端执行器）。

## 遥操作示教方式

### 手动依次启动

依次启动两台机械臂，注意根据实际情况修改`CAN`号接口和端口号：

- 在终端 1 中执行如下命令启动示教臂：
    - 2 控 2 绑定情况：
      ```bash
      airbot_server -i can_left_lead -p 50050
      ```
    - 1 控 1 绑定情况：
      ```bash
      airbot_server -i can_lead -p 50050
      ```
- 在终端 2 中执行如下命令启动执行臂：
    - 2 控 2 绑定情况：
    ```bash
    airbot_server -i can_left -p 50051
    ```
    - 1 控 1 绑定情况：
    ```bash
    airbot_server -i can_follow -p 50051
    ```
- 同理，如果是两组遥操作（2 控 2 绑定），继续启动剩下的两条臂：

    ```bash
    airbot_server -i can_right_lead -p 50052
    airbot_server -i can_right -p 50053
    ```

### 一键启动

为了简化操作，我们提供了基于`terminator`的一键在多个终端中并行启动多个机械臂服务的方法。首先请确保已经安装`terminator`，如果尚未安装，可以通过如下命令安装：

```bash
sudo apt install terminator -y
```

然后请确保Docker具有root权限。通常无多用户权限安全考虑情况下，只需执行如下命令修改全局默认权限即可：

```bash
sudo chmod a+rw /var/run/docker.sock
```

一键启动命令如下（执行该命令的终端被称为主终端，启动的多个终端被称为子终端）：

```bash
terminator -u -g airbot_ie/configs/terminators/default -l <layout>
```
其中`layout`需根据不同场景替换为如下名称：

- 一控一：`ptk_half`
- 二控二：`ptk`


命令执行后，会自动打开多个终端并启动对应的机械臂服务。

> [!WARNING]
> - 上述命令分别使用了对应场景下的默认机械臂CAN名称，如果名称与实际不符，可以修改`default`配置中的相应命令行参数，或者重写一份配置，并修改上述命令中的配置路径。
> - 由于多个机械臂服务并行启动，如果CPU的性能差，可能导致启动变慢或失败等问题。
> - 尽管自动启动的终端会打印执行的命令，但是并不会有命令的记录，因此如果要重新执行命令，可以手动复制粘贴命令执行。
> - 运行过程中，不要关闭主终端。若要退出所有服务，请先依次退出各个子终端，最后再关闭主终端，否则将导致子终端被挂起，服务在后台运行，需要额外手动执行命令来停止。


## 拖动示教方式

- 单臂示教
    ```bash
    airbot_server -i can_follow -p 50050
    ```
- 双臂示教
    - 在终端 1 中执行如下命令启动左臂：
      ```bash
      airbot_server -i can_left -p 50050
      ```
    - 在终端 2 中执行如下命令启动右臂：
      ```bash
      airbot_server -i can_right -p 50051
      ```

<a id="teleop"></a>
## 启动遥操作

上述命令仅仅启动各个机械臂独立的控制服务，如果要进行遥操作控制，可通过如下脚本启动：

- 一控一：
    ```bash
    python3 airbot_ie/scripts/task_follow.py -lp 50050 -fp 50051
    ```

- 二控二：
    ```bash
    python3 airbot_ie/scripts/task_follow.py -lp 50050 50052 -fp 50051 50053
    ```

特别地，对于拖动示教方式，需要首先启动数据采集程序，然后再通过机械臂上的按键控制机械臂进入重力补偿模式。并且，当采集程序退出后，也需要通过臂上按键将机械臂退出重力补偿模式，否则下次无法正常启动数据采集程序。
