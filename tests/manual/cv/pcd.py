import open3d as o3d
import numpy as np
import time
from pathlib import Path
import cv2


def numpy_to_open3d(points, colors=None):
    pcd = o3d.geometry.PointCloud()
    pcd.points = o3d.utility.Vector3dVector(points)
    if colors is not None:
        pcd.colors = o3d.utility.Vector3dVector(colors.astype(np.float64))
    return pcd


pcd_dir = Path("/home/ghz/Work/airbot/DISCOVERSE/data/lift_block/000/point_cloud/0")
points = np.load(pcd_dir / "0.npy")
colors = None

pcd = numpy_to_open3d(points, colors)

# create visualizer
vis = o3d.visualization.Visualizer()
vis.create_window(window_name="Open3D", width=800, height=600)
vis.add_geometry(pcd)

opt = vis.get_render_option()
opt.point_size = 10
opt.background_color = [0] * 3


for npy_file in pcd_dir.glob("*.npy"):
    start = time.time()
    print(f"Loading {npy_file}")
    points = np.load(npy_file)
    depth_path = pcd_dir.parent.parent / "depth/0" / npy_file.name
    print(depth_path)
    depth = np.load(depth_path)
    cv2.imshow("Depth", depth)
    cv2.waitKey(1)
    # points = np.load(npy_file)[..., (0, 1, 2)]
    # print(points[0])
    # points = points[:5000]
    # assert points.shape == (5000, 3), f"{points.shape}"
    # print(points.dtype)
    pcd.points = o3d.utility.Vector3dVector(points)
    vis.update_geometry(pcd)
    if not vis.poll_events():
        break
    vis.update_renderer()
    end = time.time()
    print(f"Frame time: {end - start:.3f} s")
    time.sleep(0.2)
else:
    while True:
        if not vis.poll_events():
            break
        vis.update_renderer()
vis.destroy_window()
