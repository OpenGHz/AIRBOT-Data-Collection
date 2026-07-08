if __name__ == "__main__":
    from airdc.common.utils.av_coder import AvCoder

    import time

    av_coder = AvCoder(async_encode=False)

    video_path = "/home/ghz/视频/示教器问题.mp4"

    def test_all_decode():
        def test_decode(video, indices=None):
            """
            Test encoding a single frame.
            """
            start = time.monotonic()
            frames = av_coder.decode(video, indices)
            print(f"Frame resolution: {frames[0].shape}")
            cost_time = time.monotonic() - start
            print(f"Decode cost time: {cost_time:.2f} seconds for {len(frames)} frames")
            print(
                f"Time cost decoding per frame: {cost_time / len(frames):.4f} seconds"
            )
            return frames

        def test_iter_decode(video):
            """
            Test iterating over decoded frames.
            """
            frames = []
            start = time.monotonic()
            for frame, stamp in av_coder.iter_decode(video):
                frames.append(frame)
            print(f"Frame resolution: {frames[0].shape}")
            cost_time = time.monotonic() - start
            print(
                f"Iter decode cost time: {cost_time:.2f} seconds for  {len(frames)} frames"
            )
            print(
                f"Time cost iter decoding per frame: {cost_time / len(frames):.4f} seconds"
            )
            return frames

        # frames = test_decode(video_path)
        frames = test_iter_decode(video_path)

        print("*********Encoding frames...*********")
        start = time.monotonic()
        init_stamp = time.time_ns()
        for i, frame in enumerate(frames):
            stamp = init_stamp + i * 1e9 // 30
            # print(
            #     f"Encoding frame {i} with shape {frame.shape} and dtype {frame.dtype} and timestamp {stamp}"
            # )
            av_coder.encode_frame(frame, stamp)
        encoded_data = av_coder.end()
        print(f"Encoded data size: {len(encoded_data)} bytes")
        print(f"Encoding cost time: {time.monotonic() - start:.2f} seconds")
        print(
            f"Time cost encoding per frame: {(time.monotonic() - start) / len(frames):.4f} seconds"
        )

        print("*********Decoding encoded frames...*********")
        # Test decoding the encoded data
        # frames = test_decode(encoded_data)
        frames = test_iter_decode(encoded_data)
        # test_decode(encoded_data, [0, 2, 4]).keys()

    # test_all_decode()
    AvCoder.seek_frames()
