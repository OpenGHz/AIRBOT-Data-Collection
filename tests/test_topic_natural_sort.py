from natsort import natsort_keygen


TOPICS = [
    "/robot/tactile/gripper/finger1/points",
    "/robot/camera/env2/mask/heat_map",
    "/robot/camera/wrist/video_encoded",
    "/robot/camera/env2/camera_info",
    "/robot/camera/wrist/mask/heat_map",
    "/robot/camera/wrist/depth/image_raw",
    "/robot/camera/env1/hand_eye/transform",
    "/robot/tactile/gripper/finger2/points",
    "/robot/arm/pose/rotation_6d",
    "/robot/action/arm/joint_state",
    "/robot/camera/wrist/camera_info",
    "/robot/camera/env1/mask/heat_map",
    "/robot/gripper/joint_state",
    "/robot/action/gripper/joint_state",
    "/robot/action/arm/pose",
    "/robot/arm/joint_state",
    "/robot/camera/env2/video_encoded",
    "/robot/camera/env1/camera_info",
    "/robot/camera/env2/depth/image_raw",
    "/robot/arm/pose/rotation",
    "/robot/camera/env1/video_encoded",
    "/robot/camera/env1/depth/image_raw",
    "/robot/arm/pose",
    "/robot/camera/env2/hand_eye/transform",
    "/robot/camera/wrist/hand_eye/transform",
]


natsort_key = natsort_keygen()


def natural_sort(values: list[str]) -> list[str]:
    # return natsorted(values)
    return sorted(values, key=lambda topic: ("/camera/" in topic, natsort_key(topic)))


def main() -> int:
    sorted_topics = natural_sort(TOPICS)

    print("Original topics:")
    for index, topic in enumerate(TOPICS, start=1):
        print(f"{index:2d}. {topic}")

    print("\nNatural sorted topics:")
    for index, topic in enumerate(sorted_topics, start=1):
        print(f"{index:2d}. {topic}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
