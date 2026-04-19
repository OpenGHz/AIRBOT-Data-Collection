from mcap_data_loader.datasets.mcap_dataset import (
    McapFlatBuffersEpisodeDataset,
    McapFlatBuffersEpisodeDatasetConfig,
    DataRearrangeConfig,
    RearrangeType,
)
from mcap_data_loader.serialization.video.pyav import DecodeConfig
from pathlib import Path
import argparse
import logging
import numpy as np
import cv2


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


parser = argparse.ArgumentParser()
parser.add_argument(
    "path",
    type=str,
    help="path to mcap files",
)
parser.add_argument(
    "--imshow",
    action="store_true",
    help="whether to show video frames using cv2.imshow",
)
parser.add_argument(
    "--start-episode",
    "-se",
    type=int,
    default=0,
    help="the episode index to start checking from",
)
args = parser.parse_args()
path = args.path
start_episode = args.start_episode

dataset = McapFlatBuffersEpisodeDataset(
    McapFlatBuffersEpisodeDatasetConfig(
        data_root=path,
        rearrange=DataRearrangeConfig(dataset=RearrangeType.SORT),
        media_configs=[DecodeConfig(mismatch_tolerance=5)],
        with_step=False,
    )
)

output_dir = Path("outputs")
output_dir.mkdir(exist_ok=True)

image_path = output_dir / "checked_image.jpg"


for index, episode in enumerate(dataset):
    if index < start_episode:
        continue

    logger.info(f"Episode {index}: {episode.config.data_root}")
    ep_reader = episode.reader
    all_attachments = ep_reader.all_attachment_names()
    color_topics = [att for att in all_attachments if "color" in att]
    # re-configure dataset to load color keys
    episode.config.keys.update(color_topics)
    for sample in episode:
        images = []
        for key, value in sample.items():
            img = value["data"]
            images.append(img)
        if index == 0:
            logger.info(f"Saved checked image to {image_path}")
        cv2.imwrite(image_path, np.hstack(images))
        break
    if input("Press Enter to continue to next episode, or any key to quit: "):
        break
