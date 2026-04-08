import numpy as np

from mcap_data_loader.serialization.ros.compressed_video import (
    CompressedVideoEncoder,
    CompressedVideoEncoderConfig,
)


def test_compressed_video_encoder_first_frame_has_payload():
    encoder = CompressedVideoEncoder(CompressedVideoEncoderConfig())
    frame = np.zeros((64, 64, 3), dtype=np.uint8)

    msg = encoder.encode(frame, timestamp_sec=0.0)

    assert len(msg.data) > 0
