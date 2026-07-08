import os
import pyudev

# 配置路径
SLCAN_RULE_PATH = "/etc/udev/rules.d/99-slcan.rules"
CAN_RULE_PATH = "/etc/udev/rules.d/99-can.rules"


def find_usb_devices():
    context = pyudev.Context()
    devices = []

    # 定义要查找的 USB 设备 ID（vendor:product）
    target_ids = {"0483:0000", "1d50:606f"}

    # 遍历所有 USB 设备
    for device in context.list_devices(subsystem="usb"):
        # 获取设备的 vendor 和 product ID
        vendor_id = device.get("ID_VENDOR_ID")
        product_id = device.get("ID_MODEL_ID")

        if vendor_id and product_id:
            device_id = f"{vendor_id}:{product_id}"
            if device_id in target_ids:
                # 获取总线和设备号
                busnum = device.get("BUSNUM")
                devnum = device.get("DEVNUM")
                if busnum and devnum:
                    devices.append((f"{busnum}/{devnum}", device))

    return devices


def get_device_serial(device):
    """获取设备的序列号，如果无法获取则返回 None"""
    try:
        return device.get("ID_SERIAL_SHORT")
    except Exception:
        return None


def create_slcan_config(can_name, serial):
    """为 SLCAN 设备创建 udev 规则和 systemd 服务"""
    # 创建 udev 规则目录（如果不存在）
    os.makedirs(os.path.dirname(SLCAN_RULE_PATH), exist_ok=True)

    # 添加 udev 规则
    with open(SLCAN_RULE_PATH, "a") as f:
        f.write(
            f'ACTION=="add", SUBSYSTEM=="tty", ATTRS{{idVendor}}=="0483", ATTRS{{idProduct}}=="0000", ATTRS{{serial}}=="{serial}", SYMLINK+="{can_name}", GROUP="dialout", MODE="0777", TAG+="systemd", ENV{{SYSTEMD_WANTS}}="slcan_{can_name}@.service"\n'
        )

    # 设置规则文件权限
    os.chmod(SLCAN_RULE_PATH, 0o755)

    # 创建 systemd 服务文件
    service_content = f"""[Unit]
Description=SocketCAN device {can_name}
After=dev-{can_name}.device
BindsTo=dev-{can_name}.device

[Service]
ExecStart=/usr/local/bin/slcan_add_{can_name}.sh
Type=forking
"""
    service_path = f"/etc/systemd/system/slcan_{can_name}@.service"
    with open(service_path, "w") as f:
        f.write(service_content)
    os.chmod(service_path, 0o755)

    # 创建启动脚本
    script_content = f"""#!/bin/bash
/usr/bin/slcand -o -c -f -s8 -S 3000000 /dev/{can_name} {can_name}
sleep 1
/usr/sbin/ip link set up {can_name}
/usr/sbin/ip link set {can_name} txqueuelen 1000
"""
    script_path = f"/usr/local/bin/slcan_add_{can_name}.sh"
    with open(script_path, "w") as f:
        f.write(script_content)
    os.chmod(script_path, 0o755)

    return f"udev for {can_name} created in {SLCAN_RULE_PATH}"


def create_can_config(can_name, serial):
    """为直接支持 CAN 的设备创建 udev 规则"""
    # 创建 udev 规则目录（如果不存在）
    os.makedirs(os.path.dirname(CAN_RULE_PATH), exist_ok=True)

    # 添加 udev 规则
    with open(CAN_RULE_PATH, "a") as f:
        f.write(
            f'ACTION=="add", SUBSYSTEM=="net", ATTRS{{idVendor}}=="1d50", ATTRS{{idProduct}}=="606f", ATTRS{{serial}}=="{serial}", NAME="{can_name}", RUN+="/sbin/ip link set {can_name} up type can bitrate 1000000", RUN+="/sbin/ip link set {can_name} txqueuelen 1000"\n'
        )

    # 设置规则文件权限
    os.chmod(CAN_RULE_PATH, 0o755)

    return f"udev for {can_name} created in {CAN_RULE_PATH}"


def main():
    # 确保以 root 权限运行
    if os.geteuid() != 0:
        print("错误: 此脚本需要 root 权限运行。请使用 sudo 执行。")
        exit(1)

    # 获取命令行参数中的 BIND_NAME（如果有）
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--bind-name", help="为单个设备指定的 CAN 接口名称")
    args = parser.parse_args()
    bind_name = args.bind_name

    # 查找 USB 设备
    devices = find_usb_devices()

    if not devices:
        print("未检测到 USB2CAN 设备。")
        return

    print("检测到的 USB2CAN 设备:")

    for i, (device_path, device) in enumerate(devices, 1):
        serial = get_device_serial(device)

        if not serial:
            print(f"错误: 无法检测到设备 {device_path} 的序列号")
            continue

        print(f"{i}. {device_path}")
        print(f"  序列号: {serial}")

        # 确定 CAN 接口名称
        if len(devices) > 1 or not bind_name:
            can_name = input(
                f"请为序列号为 {serial} 的设备输入所需的 CAN 接口名称（例如 can_left），或按 Enter 跳过此设备: "
            )
        else:
            can_name = bind_name

        if not can_name:
            print("请输入非空名称")
            continue

        if len(can_name) > 15:
            print("名称太长！请输入 15 个字符或更短的名称")
            continue

        # 获取设备的 vendor 和 product ID
        vendor_id = device.get("ID_VENDOR_ID")
        product_id = device.get("ID_MODEL_ID")

        # 根据设备类型创建相应配置
        if vendor_id == "0483" and product_id == "0000":
            message = create_slcan_config(can_name, serial)
        else:
            message = create_can_config(can_name, serial)

        print(message)
        print()  # 空行分隔每个设备信息


if __name__ == "__main__":
    main()
