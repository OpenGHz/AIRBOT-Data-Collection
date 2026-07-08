import av
import time

path = "/home/ghz/视频/20230611094314-葛海洲预定的会议-视频-1.mp4"

container = av.open(path)
video_stream = container.streams.video[0]
video_stream.thread_type = "AUTO"
total_frame_count = video_stream.frames

start_time = video_stream.start_time
duration = video_stream.duration
end_time = start_time + duration
time_base = video_stream.time_base

print(
    f"Total frames: {total_frame_count}; Start time: {start_time}; End time: {end_time}; Time base: {time_base}"
)

# should seek to nearest keyframe before target_timestamp
# target_stamp = start_time + int(duration * 0.5)  # e.g., seek to the middle of the video
target_stamp = 259623990  # e.g., seek to the end of the video
start = time.monotonic()
container.seek(target_stamp, stream=video_stream, backward=True, any_frame=False)
print(
    f"Seeked to target timestamp {target_stamp} in {time.monotonic() - start:.4f} seconds"
)

start = time.monotonic()
last_frame = None
frame_cnt = 0
for packet in container.demux(video_stream):
    for frame in packet.decode():
        frame_cnt += 1
        # print(frame.pts)
        if frame.pts >= target_stamp:
            if last_frame is not None:
                # print("Last frame pts:", last_frame.pts)
                last_delta = target_stamp - last_frame.pts
                current_delta = frame.pts - target_stamp
                if last_delta < current_delta:
                    target_frame = last_frame
                    # print("Found frame before target timestamp")
                else:
                    target_frame = frame
                    # print("Found frame after target timestamp")
            else:
                target_frame = frame
                # print("Found first frame after target timestamp")
            break
        last_frame = frame
    else:
        continue
    break
else:
    target_frame = None
    print(
        "No frame found after seeking to target timestamp. The last frame pts is:",
        frame.pts,
    )
print("Total frames processed:", frame_cnt)

print(
    f"Found target frame pts: {target_frame.pts if target_frame else None} in {time.monotonic() - start:.4f} seconds"
)
