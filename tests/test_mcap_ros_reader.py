from mcap_data_loader.serialization.ros.mcap import McapROSReader
from mcap_data_loader.serialization.ros.compressed_video import decode_compressed_video
from pathlib import Path
import airdc
from cv_bridge import CvBridge
from matplotlib import pyplot as plt
import numpy as np


path = Path(airdc.__file__).parent.parent / "data/aao_data/door_0/3.mcap"
assert path.exists(), f"Data file does not exist: {path}"


def save_depth(path: Path, depth: np.ndarray) -> None:
    """Save depth as a colorized PNG using the turbo colormap."""
    valid = depth[depth > 0]
    if valid.size == 0:
        plt.imsave(path, np.zeros_like(depth), cmap="turbo")
        return
    vmin, vmax = float(valid.min()), float(valid.max())
    normed = np.where(depth > 0, (depth - vmin) / max(vmax - vmin, 1e-6), 0.0)
    plt.imsave(path, normed, cmap="turbo", vmin=0.0, vmax=1.0)


with open(path, "rb") as f:
    reader = McapROSReader(f)
    bridge = CvBridge()
    key = "/robot/camera/env1/depth/image_raw"
    for sample in reader.iter_samples([key]):
        print(sample.keys())
        # if sample["data"] is not None:
        #     img = decode_compressed_video(sample["data"])

        # print(f"Data size: {len(sample.data)} bytes")
        image_np = bridge.imgmsg_to_cv2(sample[key]["data"])
        save_depth(Path("test_depth.png"), image_np)
        break
