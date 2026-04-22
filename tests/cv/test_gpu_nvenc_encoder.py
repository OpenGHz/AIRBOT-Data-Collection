from __future__ import annotations

from fractions import Fraction
from io import BytesIO

import av
import numpy as np
import pytest


def _has_nvenc(codec_name: str = "h264_nvenc") -> bool:
    return codec_name in av.codecs_available


def _make_rgb_frame(index: int, width: int, height: int) -> np.ndarray:
    """Generate a deterministic RGB frame that is easy to verify after decode."""
    frame = np.zeros((height, width, 3), dtype=np.uint8)
    frame[..., 0] = (index * 31) % 256
    frame[..., 1] = np.linspace(0, 255, width, dtype=np.uint8)
    frame[..., 2] = np.linspace(255, 0, height, dtype=np.uint8).reshape(height, 1)
    return frame


def encode_h264_nvenc_annexb(
    frames: list[np.ndarray],
    *,
    fps: int = 30,
) -> bytes:
    """Encode RGB frames with NVIDIA NVENC and return raw H.264 Annex B bytes.

    This sample intentionally mirrors the shape of the current MCAP
    CompressedVideo path: one encoded H.264 byte stream is produced from RGB
    frames, and the resulting bytes are suitable for foxglove compressed video
    payloads. The PyAV binding still accepts CPU ndarrays as input; replacing
    this with a zero-copy CUDA-input encoder is the next integration step.
    """
    if not frames:
        raise ValueError("frames must not be empty")

    height, width = frames[0].shape[:2]
    output = BytesIO()
    container = av.open(output, mode="w", format="h264")
    stream = container.add_stream(
        "h264_nvenc",
        rate=fps,
        options={
            # p1/ull are NVIDIA low-latency settings. Some FFmpeg builds accept
            # only a subset, so keep the option set intentionally small.
            "preset": "p1",
            "tune": "ull",
        },
    )
    stream.width = width
    stream.height = height
    stream.pix_fmt = "yuv420p"
    stream.time_base = Fraction(1, fps)
    stream.gop_size = fps
    stream.max_b_frames = 0

    try:
        for index, frame_array in enumerate(frames):
            if frame_array.shape != (height, width, 3):
                raise ValueError(
                    f"All frames must share shape {(height, width, 3)}, "
                    f"got {frame_array.shape}"
                )
            if frame_array.dtype != np.uint8:
                raise TypeError(f"Expected uint8 frames, got {frame_array.dtype}")

            frame = av.VideoFrame.from_ndarray(frame_array, format="rgb24")
            frame.pts = index
            frame.time_base = stream.time_base
            for packet in stream.encode(frame):
                container.mux(packet)

        for packet in stream.encode():
            container.mux(packet)
    finally:
        container.close()

    return output.getvalue()


@pytest.mark.skipif(
    not _has_nvenc(),
    reason="PyAV/FFmpeg in this environment does not expose h264_nvenc",
)
def test_h264_nvenc_gpu_encoder_round_trip():
    encoded, decoded = _run_round_trip_smoke()

    assert encoded.startswith(b"\x00\x00\x00\x01")
    assert len(encoded) > 0
    assert len(decoded) == 8
    assert decoded[0].width == 320
    assert decoded[0].height == 240


def _run_round_trip_smoke():
    width = 320
    height = 240
    frame_count = 8
    frames = [_make_rgb_frame(i, width, height) for i in range(frame_count)]

    encoded = encode_h264_nvenc_annexb(frames)

    assert encoded.startswith(b"\x00\x00\x00\x01")
    assert len(encoded) > 0

    with av.open(BytesIO(encoded), mode="r", format="h264") as container:
        decoded = list(container.decode(video=0))

    return encoded, decoded


if __name__ == "__main__":
    if not _has_nvenc():
        raise SystemExit("h264_nvenc is not available in this PyAV/FFmpeg build")

    encoded, decoded = _run_round_trip_smoke()
    print(
        "h264_nvenc round trip ok: "
        f"{len(encoded)} encoded bytes, "
        f"{len(decoded)} decoded frames, "
        f"{decoded[0].width}x{decoded[0].height}"
    )
