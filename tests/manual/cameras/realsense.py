from airdc.common.devices.cameras.intelrealsense import (
    IntelRealSenseCamera,
    IntelRealSenseCameraConfig,
    find_camera_indices,
)
import cv2
import argparse
from pprint import pprint
import time


parser = argparse.ArgumentParser(description="Intel RealSense Camera Test")
parser.add_argument(
    "-ci",
    "--camera_indices",
    type=str,
    nargs="*",
    help="Camera indices to connect to (default: None, auto-detect)",
)
parser.add_argument(
    "-si",
    "--show_info",
    action="store_true",
    help="Show camera information",
)
args = parser.parse_args()

if args.camera_indices:
    sns = args.camera_indices
else:
    sns = find_camera_indices()


cameras: list[IntelRealSenseCamera] = []

for sn in sns:
    cam = IntelRealSenseCamera(
        IntelRealSenseCameraConfig(
            camera_index=sn,
            width=1280,
            height=720,
            fps=30,
            enable_depth=True,
            align_depth=True,
        )
    )
    assert cam.configure(), f"Camera should be connected: {sn}"
    print(f"Camera connected successfully: {sn}")
    if args.show_info:
        pprint(cam.get_info())
    cameras.append(cam)

print("Press 'q' or 'Esc' to quit")

while True:
    start = time.perf_counter()
    for sn, cam in zip(sns, cameras):
        obs = cam.capture_observation()
        for key, image in obs.items():
            cv2.imshow(f"{sn}/{key}", image)
    end = time.perf_counter()
    if cv2.waitKey(1) & 0xFF in [ord("q"), 27]:  # Press 'q' or 'Esc' to quit
        break
    print(f"fps: {1 / (end - start):.2f}")

assert cam.shutdown()
print("Camera disconnected successfully")
cv2.destroyAllWindows()
