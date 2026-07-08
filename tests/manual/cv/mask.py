import cv2
import numpy as np
import os


def extract_mask_regions(mask, output_dir="mask_regions"):
    # os.makedirs(output_dir, exist_ok=True)

    mask_rgb = cv2.cvtColor(mask, cv2.COLOR_BGR2RGB)

    unique_colors = np.unique(mask_rgb.reshape(-1, mask_rgb.shape[2]), axis=0)
    num_colors = len(unique_colors)

    for i, color in enumerate(unique_colors):
        binary_mask = np.all(mask_rgb == color, axis=-1).astype(np.uint8) * 255

        color_name = f"color_{i + 1}"
        # output_path = os.path.join(output_dir, f"{color_name}.png")
        # cv2.imwrite(output_path, binary_mask)
        # print(f"{i + 1}. 颜色: {color} -> 保存为: {output_path}")
        cv2.imshow(color_name, binary_mask)
    cv2.waitKey(0)
    return num_colors


def extract_merged_mask(mask_path, color_groups, output_dir="merged_mask"):
    mask = cv2.imread(mask_path)

    os.makedirs(output_dir, exist_ok=True)

    mask_rgb = cv2.cvtColor(mask, cv2.COLOR_BGR2RGB)

    base_name = os.path.splitext(os.path.basename(mask_path))[0]

    for group_idx, color_group in enumerate(color_groups):
        merged_mask = np.zeros(mask_rgb.shape[:2], dtype=np.uint8)

        for color in color_group:
            color_mask = np.all(mask_rgb == color, axis=-1).astype(np.uint8)
            merged_mask = cv2.bitwise_or(merged_mask, color_mask)

        merged_mask = (merged_mask * 255).astype(np.uint8)
        _, binary_mask = cv2.threshold(merged_mask, 1, 255, cv2.THRESH_BINARY)

        output_path = os.path.join(output_dir, f"{base_name}.png")
        cv2.imwrite(output_path, binary_mask)

    return


# 使用示例
if __name__ == "__main__":
    # data_root = "/home/ghz/Work/Research/manipulate-anything/data/GT_12T_100EP"
    data_root = (
        "/home/ghz/Work/Research/manipulate-anything/data/GT_12T_data/train_12_GT"
    )
    task_name = "lamp_on"
    # task_name = "close_box"

    raw_mask_image = cv2.imread(
        f"{data_root}/{task_name}/all_variations/episodes/episode0/front_mask/0.png"
    )
    raw_rgb_image = cv2.imread(
        f"{data_root}/{task_name}/all_variations/episodes/episode0/front_rgb/0.png"
    )

    # 查看各部分对应掩码
    mask_path = "./episode0/front_mask/0.png"
    num_colors = extract_mask_regions(raw_mask_image)

    # # 获取想要的掩码
    # color_groups = [
    #     [(138, 0, 0), (133, 0, 0)],
    # ]

    # root_path = "./"
    # for path in os.listdir(root_path):
    #     mask_path = os.path.join(path, "front_mask")
    #     if os.path.isdir(mask_path):
    #         for mask_file in os.listdir(mask_path):
    #             if mask_file.endswith(".png"):
    #                 mask_path = os.path.join(mask_path, mask_file)
    #                 num_colors = extract_merged_mask(mask_path, color_groups)

    print("done!")
