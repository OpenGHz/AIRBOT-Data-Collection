from mcap_data_loader.serialization.ros.mcap import McapROSReader
from mcap_data_loader.serialization.ros.compressed_video import decode_compressed_video
from pathlib import Path
import airdc
from sensor_msgs.msg import Image

path = Path(airdc.__file__).parent.parent / "data/aao_data/door_0/0.mcap"
assert path.exists(), f"Data file does not exist: {path}"

with open(path, "rb") as f:
    reader = McapROSReader(f)

    for sample in reader.iter_samples([]):
        # print(sample)
        if sample["data"] is not None:
            img = decode_compressed_video(sample["data"])

            # print(f"Data size: {len(sample.data)} bytes")
        break
