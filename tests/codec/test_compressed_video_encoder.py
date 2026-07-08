import numpy as np
import pytest

# The encoder lives in mcap_data_loader's ROS serialization subpackage, whose
# __init__ reads $ROS_VERSION at import time — so this is ROS-gated, not pure
# software. Marked @ros (auto-skips without a ROS env) and imported lazily inside
# the test so the skip applies before the import runs (import errors during
# collection cannot be skipped by markers).
pytestmark = [pytest.mark.hardware, pytest.mark.ros]


def test_compressed_video_encoder_first_frame_has_payload():
    from mcap_data_loader.serialization.ros.compressed_video import (
        CompressedVideoEncoder,
        CompressedVideoEncoderConfig,
    )

    encoder = CompressedVideoEncoder(CompressedVideoEncoderConfig())
    frame = np.zeros((64, 64, 3), dtype=np.uint8)

    msg = encoder.encode(frame, timestamp_sec=0.0)

    assert len(msg.data) > 0
