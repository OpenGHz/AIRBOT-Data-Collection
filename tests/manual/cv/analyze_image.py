import cv2
from matplotlib import pyplot as plt
import numpy as np
from pathlib import Path


def extract_rgb_mask(
    data_root,
    task_name,
    peak_choices: list,
    show=False,
    save=True,
    unique_gray=False,
    rgb_choices=None,
    camera_predix=("front",),
):
    ep_dir = f"{data_root}/{task_name}/all_variations/episodes"
    ep_length = len(list(Path(ep_dir).glob("episode*")))
    for ep_index in range(0, ep_length):
        episode = Path(ep_dir) / f"episode{ep_index}"
        print(f"Processing {episode}...")
        for prefix in camera_predix:
            rgb_length = len(list(episode.glob(f"{prefix}_rgb/*.png")))
            mask_length = len(list(episode.glob(f"{prefix}_mask/*.png")))
            assert rgb_length == mask_length, (
                f"RGB ({rgb_length}) and mask ({mask_length}) counts do not match in {episode}"
            )
        peaks_num = 0

        for prefix in camera_predix:
            if save:
                output_dir = episode / f"{prefix}_rgb_mask"
                output_dir.mkdir(parents=True, exist_ok=True)
            for index in range(0, rgb_length):
                rgb = episode / f"{prefix}_rgb" / f"{index}.png"
                mask = episode / f"{prefix}_mask" / f"{index}.png"
                raw_mask_image = cv2.imread(str(mask))
                raw_rgb_image = cv2.imread(str(rgb))

                if False:
                    gray_image = (
                        (raw_mask_image[..., 0].astype(np.uint32) << 16)
                        | (raw_mask_image[..., 1].astype(np.uint32) << 8)
                        | (raw_mask_image[..., 2].astype(np.uint32))
                    )
                else:
                    gray_image = cv2.cvtColor(raw_mask_image, cv2.COLOR_BGR2GRAY)
                # print(raw_mask_image.shape)
                hist = cv2.calcHist([gray_image], [0], None, [256], [0, 256])
                # print(hist.shape)
                # print(hist[0:3])

                peak_start = -1
                peaks = []
                for i, point in enumerate(hist):
                    if point > 0:
                        if peak_start < 0:
                            peak_start = i
                    else:
                        if peak_start >= 0:
                            peaks.append((peak_start, i))
                            peak_start = -1
                assert peaks_num == 0 or len(peaks) == peaks_num, (
                    f"Expected {peaks_num} peaks, but found {len(peaks)} in {episode}"
                )
                print(f"{index}: {len(peaks)} Peaks found at:", peaks)

                cur_peak_choices = peak_choices.copy()
                for i, pc in enumerate(peak_choices.copy()):
                    if isinstance(pc, int):
                        cur_peak_choices[i] = peaks[pc]
                    elif isinstance(pc, slice):
                        cur_peak_choices.pop(i)
                        cur_peak_choices.extend(peaks[pc])
                print(f"Using peak choices: {cur_peak_choices}")

                mask = np.zeros_like(gray_image)
                for peak in cur_peak_choices:
                    roi = (gray_image >= peak[0]) & (gray_image < peak[1])
                    mask[roi] = 1
                for color in rgb_choices or []:
                    roi = np.all(
                        (raw_rgb_image >= color[0]) & (raw_rgb_image <= color[1]),
                        axis=-1,
                    )
                    mask[roi] = 1
                masked_image = (mask[..., np.newaxis] * raw_rgb_image).astype(np.uint8)

                if show:
                    plt.plot(hist)
                    cv2.imshow("RGB Image", raw_rgb_image)
                    cv2.imshow("Gray Image", gray_image)
                    cv2.imshow("Original Image", raw_mask_image)
                    cv2.imshow("Masked RGB Image", masked_image)
                    plt.xlim([0, 256])
                    plt.show(block=False)
                    if cv2.waitKey(0) == 27:  # Wait for ESC key to exit
                        cv2.destroyAllWindows()
                        exit(0)
                if save:
                    output_file = (output_dir / f"{index}.png").absolute()
                    # print(output_file)
                    cv2.imwrite(str(output_file), masked_image)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Process some images.")
    parser.add_argument(
        "-d",
        "--data_root",
        type=str,
        default="/home/ghz/Work/Research/manipulate-anything/data/GT_12T_data/train_12_GT",
    )
    args = parser.parse_args()

    data_root = args.data_root

    task_peaks = {
        "lamp_on": [(7, 14), slice(4, None)],
        "open_box": [(7, 14), slice(4, None)],
        "open_wine_bottle": [(7, 14), slice(4, None)],
        "pick_and_lift": [(7, 14)],
        "pick_up_cup": [(7, 14)],
        "play_jenga": [(7, 14), slice(4, None)],
        "put_knife_on_chopping_board": [(7, 14), slice(4, None)],
        "slide_block_to_target": [(7, 14), slice(4, None)],
        "take_umbrella_out_of_umbrella_stand": [(7, 14), slice(4, None)],
        # ignore the tasks below
        # "put_objects_in_container": [(7, 14), slice(4, None)],  # task demos are not so good
        # "open_jar": [(7, 14), slice(4, None)],  # mask is hard to separate
    }

    # unique_gray = {"pick_and_lift": True}
    rgb_choices = {
        "pick_and_lift": [((0, 0, 135), (0, 0, 255))],
        "pick_up_cup": [((0, 0, 110), (0, 0, 255))],
    }
    # rgb_choices = {}

    # task_name = "close_box"
    # extract_rgb_mask(data_root, task_name, [(11, 14), (37, 41)], show=False, save=True)

    for task_name in task_peaks:
        extract_rgb_mask(
            data_root,
            task_name,
            task_peaks[task_name],
            show=True,
            save=False,
            rgb_choices=rgb_choices.get(task_name, None),
        )
