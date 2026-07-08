from mcap.reader import make_reader
import cv2
from foxglove_schemas_flatbuffer.CompressedImage import CompressedImage
from turbojpeg import TurboJPEG
import argparse


parser = argparse.ArgumentParser(
    description="Convert MCAP compressed image messages to raw video files."
)
parser.add_argument(
    "--topics",
    nargs="+",
    default=["/env_camera/color/image_raw", "/right_camera/color/image_raw"],
    help="List of topics to extract images from.",
)
parser.add_argument(
    "-in",
    "--in_path",
    type=str,
    help="Path to the input MCAP file.",
)
parser.add_argument(
    "-out",
    "--out_path",
    type=str,
    help="Path to the output directory for video files.",
)
args = parser.parse_args()


topics = args.topics
jpeg = TurboJPEG()
in_path = args.in_path
out_path = args.out_path

fourcc = cv2.VideoWriter_fourcc(*"mp4v")
writer: dict[str, cv2.VideoWriter] = {}

with open(in_path, "rb") as f:
    reader = make_reader(f)
    for schema, channel, message in reader.iter_messages(topics=topics):
        image_fb = CompressedImage.GetRootAs(message.data)
        image_bytes = image_fb.DataAsNumpy()
        image = jpeg.decode(image_bytes)
        if channel.topic not in writer:
            video_name = (
                f"{out_path}/{channel.topic.replace('/', '.').removeprefix('.')}.mp4"
            )
            print("video name", video_name)
            writer[channel.topic] = cv2.VideoWriter(
                video_name,
                fourcc,
                30.0,
                (image.shape[1], image.shape[0]),
            )
        writer[channel.topic].write(image)

        # cv2.imshow(channel.topic, image)
        # cv2.waitKey(1)

for w in writer.values():
    w.release()
