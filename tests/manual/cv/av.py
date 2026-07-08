import av
import av.error
import numpy as np
import random
from fractions import Fraction


av.logging.set_level(av.logging.VERBOSE)

print("av version:", av.__version__)


# Monkey-patch av.error to decode FFmpeg messages as UTF-8
def _patched_err_check(res, filename=None):
    print(res)
    if res < 0:
        # Fetch error string from FFmpeg
        buf = av.error.strerror(res)  # bytes in UTF-8
        if buf is None:
            msg = f"FFmpeg error {res}"
        else:
            msg = buf.decode("utf-8", errors="replace")
        raise av.error.FFmpegError(msg, res, filename)
    return res


av.error.err_check = _patched_err_check


def random_frame(height: int, width: int) -> np.ndarray:
    """
    返回一张随机的 uint8 BGR 图像 (H, W, 3)。
    """
    return np.random.randint(0, 256, (height, width, 3), dtype=np.uint8)


def generate_random_video(
    output_file: str,
    width: int = 640,
    height: int = 480,
    fps: int = 25,
    num_frames: int = 100,
    codec: str = "libx264",
    crf: int = 23,
):
    """
    生成一段随机噪声视频并保存为 output_file。
    """
    # 创建输出容器
    container = av.open(output_file, mode="w")

    # 新建 H.264 视频流
    stream = container.add_stream(codec)
    stream.width = width
    stream.height = height
    stream.pix_fmt = "yuv420p"  # 兼容性好
    stream.options = {"crf": str(crf)}  # 质量因子，越小越清晰
    stream.time_base = Fraction(1, int(1e6))

    # 逐帧编码
    for _ in range(num_frames):
        bgr = random_frame(height, width)
        # PyAV 需要 RGB24（即 RGB 顺序），所以要转换
        frame = av.VideoFrame.from_ndarray(bgr[:, :, ::-1], format="rgb24")
        for packet in stream.encode(frame):
            # frame.pts = 1e12
            frame.time_base = stream.time_base
            container.mux(packet)

    # Flush 编码器
    for packet in stream.encode():
        container.mux(packet)

    # 关闭文件
    container.close()
    print(
        f"已生成视频: {output_file} ({width}x{height}, {fps}fps, {num_frames} frames)"
    )


if __name__ == "__main__":
    random.seed()
    generate_random_video(
        output_file="random视频.mp4",
        width=641,
        height=481,
        fps=25,
        num_frames=120,  # 5 秒的视频
        crf=23,  # 0-51，数值越小质量越高
    )
