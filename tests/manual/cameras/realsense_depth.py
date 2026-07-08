def main():
    """示例: 同时查看多台 RealSense 相机的彩色与对齐深度图。

    用法:
        python test_realsense_depth.py                        # 自动发现全部设备
        python test_realsense_depth.py -d 12345678 87654321    # 指定多台序列号(空格分隔)
        python test_realsense_depth.py -d 12345678 -a          # 只指定一台并开启对齐
        python test_realsense_depth.py --headless             # 无界面运行(仅打印 FPS)

    增强点:
        1. --device_id 现在支持 0/多参数 (nargs="*")；不提供则自动发现全部设备。
        2. 多设备并行: 为每台设备建立独立 pipeline + align (可选)。
        3. 将所有设备的 (color | depth_colormap) 按列拼接，再把多设备行上下堆叠显示。
    4. 支持 --headless 无窗口模式; GUI 模式按 q 退出。
    """
    import argparse
    import cv2
    import numpy as np
    import pyrealsense2 as rs
    import time
    from collections import defaultdict

    parser = argparse.ArgumentParser(description="Intel RealSense 多设备深度测试")
    parser.add_argument(
        "-d",
        "--device_id",
        nargs="*",
        help="一个或多个相机序列号(空格分隔)。缺省: 自动发现全部已连接设备。",
    )
    parser.add_argument(
        "-a",
        "--align",
        action="store_true",
        help="将深度帧对齐到彩色帧 (默认关闭)",
    )
    parser.add_argument(
        "-wd", "--width", type=int, default=640, help="彩色/深度流宽度 (默认640)"
    )
    parser.add_argument(
        "-hi", "--height", type=int, default=480, help="彩色/深度流高度 (默认480)"
    )
    parser.add_argument("--fps", type=int, default=30, help="帧率 (默认30)")
    parser.add_argument(
        "-hl",
        "--headless",
        action="store_true",
        help="无界面模式: 不显示窗口, 周期性打印帧率",
    )
    parser.add_argument(
        "--log-interval",
        type=float,
        default=2.0,
        help="headless 模式下打印 FPS 的时间间隔(秒, 默认2.0)",
    )
    parser.add_argument(
        "-st",
        "--stack",
        action="store_true",
        help="将多台设备的图像按列堆叠显示 (默认关闭)",
    )
    parser.add_argument(
        "-dc",
        "--depth-color",
        action="store_true",
        help="将深度图像应用伪彩色 (默认关闭)",
    )
    args = parser.parse_args()

    # 发现设备
    ctx = rs.context()
    connected = [d.get_info(rs.camera_info.serial_number) for d in ctx.query_devices()]
    if not connected:
        print("未发现任何 RealSense 设备。")
        return

    if args.device_id and len(args.device_id) > 0:
        # 过滤: 只保留实际存在的
        device_ids = []
        for did in args.device_id:
            if did in connected:
                device_ids.append(did)
            else:
                print(f"警告: 指定的设备 {did} 未连接, 忽略。")
        if not device_ids:
            print("未找到任一指定设备, 退出。")
            return
    else:
        device_ids = connected

    print(f"将使用设备: {device_ids}")

    width, height, fps = args.width, args.height, args.fps
    align_enabled = args.align
    headless = args.headless

    # 为每台设备构建 pipeline
    pipelines = []  # list[(serial, pipeline, align_or_None)]
    try:
        for serial in device_ids:
            pipeline = rs.pipeline()
            cfg = rs.config()
            cfg.enable_device(serial)
            cfg.enable_stream(rs.stream.color, width, height, rs.format.bgr8, fps)
            cfg.enable_stream(rs.stream.depth, width, height, rs.format.z16, fps)
            print(f"启动设备 {serial}...")
            profile = pipeline.start(cfg)
            aligner = rs.align(rs.stream.color) if align_enabled else None
            # 预热: 丢弃前几帧
            for _ in range(5):
                pipeline.wait_for_frames()
            pipelines.append((serial, pipeline, aligner))
            time.sleep(0.05)

        if headless:
            print("全部设备已启动 (headless 模式)。按 Ctrl+C 结束。")
        else:
            print("全部设备已启动, 按 q / ESC 退出。")

        # headless 统计
        per_device_counts = {serial: 0 for serial, *_ in pipelines}
        images = defaultdict(dict)
        last_log = time.perf_counter()

        while True:
            per_device_cols = [] if not headless else None
            now = time.perf_counter()
            for serial, pipeline, aligner in pipelines:
                try:
                    frames = pipeline.wait_for_frames(timeout_ms=1000)
                except Exception as e:  # noqa: BLE001
                    print(f"设备 {serial} 获取帧失败: {e}")
                    continue
                if aligner is not None:
                    frames = aligner.process(frames)
                color_frame = frames.get_color_frame()
                depth_frame = frames.get_depth_frame()
                if not color_frame or not depth_frame:
                    continue
                per_device_counts[serial] += 1

                if headless:
                    # 仅统计，不做图像处理
                    continue

                color_img = np.asanyarray(color_frame.get_data())
                depth_img = np.asanyarray(depth_frame.get_data())

                if not headless:
                    if args.depth_color:
                        depth_color = cv2.applyColorMap(
                            cv2.convertScaleAbs(depth_img, alpha=0.03), cv2.COLORMAP_JET
                        )
                        if color_img.shape[:2] != depth_color.shape[:2]:
                            depth_color = cv2.resize(
                                depth_color, (color_img.shape[1], color_img.shape[0])
                            )
                    else:
                        depth_color = depth_img
                        if args.stack:
                            raise NotImplementedError(
                                "堆叠彩色图和纯深度图的显示功能尚未实现"
                            )
                    # cv2.putText(
                    #     color_img,
                    #     f"{serial}",
                    #     (10, 25),
                    #     cv2.FONT_HERSHEY_SIMPLEX,
                    #     0.8,
                    #     (0, 255, 0),
                    #     2,
                    # )
                    if args.stack:
                        col = np.vstack((color_img, depth_color))
                        per_device_cols.append(col)
                    else:
                        images[serial]["color"] = color_img
                        images[serial]["depth"] = depth_img

            # headless 日志输出
            if (now - last_log) >= args.log_interval:
                elapsed = now - last_log
                fps_info = [
                    f"{serial}:{per_device_counts[serial] / elapsed:.1f}fps"
                    for serial in per_device_counts
                ]
                print(" | ".join(fps_info))
                for k in per_device_counts:
                    per_device_counts[k] = 0
                last_log = now

            if headless:
                continue

            if args.stack:
                if not per_device_cols:
                    continue
                canvas = np.hstack(per_device_cols)
                cv2.imshow("RealSense Multi-Depth", canvas)
            else:
                for serial, imgs in images.items():
                    color_img = imgs.get("color")
                    depth_img = imgs.get("depth")
                    if color_img is not None and depth_img is not None:
                        cv2.imshow(f"RealSense {serial} Color", color_img)
                        cv2.imshow(f"RealSense {serial} Depth", depth_img)
            if cv2.waitKey(1) & 0xFF in {ord("q"), 27}:
                break
    except (KeyboardInterrupt, NotImplementedError):
        print("用户中断, 退出。")
    finally:
        for serial, pipeline, _ in pipelines:
            print(f"停止设备 {serial}")
            try:
                pipeline.stop()
            except Exception:  # noqa: BLE001
                pass
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
