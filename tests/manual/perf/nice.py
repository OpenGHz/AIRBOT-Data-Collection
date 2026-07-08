import multiprocessing as mp
import os
import psutil
import time
import platform


def set_priority(proc: psutil.Process, mode: str):
    """设置进程优先级"""
    system = platform.system()
    if system == "Windows":
        if mode == "high":
            proc.nice(psutil.HIGH_PRIORITY_CLASS)
        elif mode == "low":
            proc.nice(psutil.IDLE_PRIORITY_CLASS)
    else:  # Linux / macOS
        if mode == "high":
            proc.nice(-15)
        elif mode == "low":
            proc.nice(10)


def worker():
    """子进程执行 CPU 密集任务"""
    p = psutil.Process(os.getpid())
    print(f"sub proc: {p.pid}, 名称: {p.name()}, 优先级: {p.nice()}")
    set_priority(p, "low")  # 子进程优先级调低
    while True:
        # 模拟计算压力
        sum(i * i for i in range(50_000))


def run_test(use_priority=False, duration=5):
    """运行一轮测试，返回主循环 FPS"""
    if use_priority:
        set_priority(psutil.Process(os.getpid()), "high")

    proc = mp.get_context("spawn").Process(target=worker)
    proc.start()

    frame_count = 0
    t0 = time.time()

    while time.time() - t0 < duration:
        # 主循环模拟任务
        sum(i * i for i in range(100_000))
        frame_count += 1

    proc.terminate()
    proc.join()

    return frame_count / duration


if __name__ == "__main__":
    print("测试中，请稍候...")

    fps_default = run_test(use_priority=False)
    print(f"默认优先级：主循环平均 {fps_default:.2f} FPS")

    fps_priority = run_test(use_priority=True)
    print(f"主高子低优先级：主循环平均 {fps_priority:.2f} FPS")
