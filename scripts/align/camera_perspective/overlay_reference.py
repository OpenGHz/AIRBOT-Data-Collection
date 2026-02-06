import cv2
import sys


def main():
    # 可通过命令行传入参考图像路径，否则使用默认
    if len(sys.argv) < 2:
        print("Usage: python overlay_reference.py <reference_image_path>")
        return

    ref_img_path = sys.argv[1]
    video_id = int(sys.argv[2]) if len(sys.argv) > 2 else 0  # 默认使用摄像头

    # 读取参考图像
    ref_img = cv2.imread(ref_img_path)
    if ref_img is None:
        print(f"Error: Cannot load reference image from {ref_img_path}")
        return

    # 打开摄像头
    cap = cv2.VideoCapture(video_id)
    if not cap.isOpened():
        print("Error: Cannot open camera.")
        return

    # 设置透明度（0.0 ~ 1.0），值越小参考图越透明
    alpha = 0.1  # 可根据需要调整

    print("Press 'q' to quit.")

    while True:
        ret, frame = cap.read()
        if not ret:
            print("Failed to grab frame from camera.")
            break

        # 获取当前视频帧的尺寸
        h, w = frame.shape[:2]

        if ref_img.shape[0] != h or ref_img.shape[1] != w:
            print(
                f"Warning: Reference image size ({ref_img.shape[1]}x{ref_img.shape[0]}) does not match video frame size ({w}x{h}). Resizing reference image."
            )

        # 调整参考图像大小以匹配视频帧
        ref_resized = cv2.resize(ref_img, (w, h))

        # 线性融合：dst = alpha * ref + (1 - alpha) * frame
        blended = cv2.addWeighted(ref_resized, alpha, frame, 1 - alpha, 0)

        # 显示结果
        cv2.imshow("Reference Overlay (for alignment)", blended)

        # 按 'q' 退出
        if cv2.waitKey(1) & 0xFF == ord("q"):
            break

    # 释放资源
    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
