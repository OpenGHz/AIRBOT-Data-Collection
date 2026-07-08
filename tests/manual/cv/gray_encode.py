import av
import numpy as np
import os


# 参数
H, W = 480, 640
N_FRAMES = 179  # 保存多少帧
RAW_FILE = "depth_raw.avi"
FFV1_FILE = "depth_ffv1.mkv"
JP2_FILE = "depth_jpeg2000.avi"


# 生成模拟深度图数据 (uint16)
def generate_depth_frame():
    return (np.random.rand(H, W) * 65535).astype(np.uint16)


# 保存 rawvideo
def save_rawvideo():
    container = av.open(RAW_FILE, mode="w")
    stream = container.add_stream("rawvideo")
    stream.width = W
    stream.height = H
    stream.pix_fmt = "gray16le"

    for _ in range(N_FRAMES):
        depth = generate_depth_frame()
        frame = av.VideoFrame.from_ndarray(depth, format="gray16le")
        packet = stream.encode(frame)
        if packet:
            container.mux(packet)

    # 刷新缓存
    packet = stream.encode(None)
    if packet:
        container.mux(packet)

    container.close()


# 保存 FFV1
def save_ffv1():
    container = av.open(FFV1_FILE, mode="w")
    stream = container.add_stream("ffv1")
    stream.width = W
    stream.height = H
    stream.pix_fmt = "gray16le"

    for _ in range(N_FRAMES):
        depth = generate_depth_frame()
        frame = av.VideoFrame.from_ndarray(depth, format="gray16le")
        packet = stream.encode(frame)
        if packet:
            container.mux(packet)

    # 刷新缓存
    packet = stream.encode(None)
    if packet:
        container.mux(packet)

    container.close()


def save_jpeg2000():
    container = av.open(JP2_FILE, mode="w", format="avi")
    # 使用 JPEG2000 编码器
    stream = container.add_stream("jpeg2000")
    stream.width = W
    stream.height = H
    stream.pix_fmt = "gray16le"  # JPEG2000 支持 16bit 灰度

    for _ in range(N_FRAMES):
        depth = generate_depth_frame()
        frame = av.VideoFrame.from_ndarray(depth, format="gray16le")
        packet = stream.encode(frame)
        if packet:
            container.mux(packet)

    # 刷新缓存
    packet = stream.encode(None)
    if packet:
        container.mux(packet)

    container.close()


if __name__ == "__main__":
    print("Saving rawvideo...")
    save_rawvideo()
    print("Saving FFV1...")
    save_ffv1()
    print("Saving JPEG2000...")
    save_jpeg2000()

    raw_size = os.path.getsize(RAW_FILE) / (1024 * 1024)
    ffv1_size = os.path.getsize(FFV1_FILE) / (1024 * 1024)
    jp2_size = os.path.getsize(JP2_FILE) / (1024 * 1024)

    print(f"Rawvideo size: {raw_size:.2f} MB")
    print(f"FFV1 size:    {ffv1_size:.2f} MB")
    print(f"JPEG2000 size: {jp2_size:.2f} MB")
    # print(f"Compression ratio: {raw_size / ffv1_size:.2f}x")
