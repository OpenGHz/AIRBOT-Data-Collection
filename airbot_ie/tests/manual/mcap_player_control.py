# NOTE (broken dependency): this manual script imports `McapSinglePosePlayer`
# from `airdc.tests.test_mcap_player`, a module that no longer exists anywhere in
# the repo (the whole `airdc/tests/` tree is gone). It is quarantined here as a
# manual/hardware script and is NOT collected by pytest. To run it again, restore
# or reimplement `McapSinglePosePlayer` and fix the import below.
if __name__ == "__main__":
    import argparse
    from airdc.tests.test_mcap_player import McapSinglePosePlayer
    from airbot_ie.robots.airbot_play import (
        AIRBOTPlay,
        AIRBOTPlayConfig,
        ActionConfig,
        InterfaceType,
        SystemMode,
    )
    from airdc.common.utils.transformations import (
        quaternion_from_euler,
    )
    import time
    import numpy as np

    parser = argparse.ArgumentParser(
        description="Play a single pose from an MCAP file."
    )
    parser.add_argument(
        "file_path",
        type=str,
        help="Path to the MCAP file containing the pose data.",
    )
    args = parser.parse_args()

    test = McapSinglePosePlayer(args.file_path)
    airbot_play = AIRBOTPlay(
        AIRBOTPlayConfig(
            port=50051, action=[ActionConfig(interfaces={InterfaceType.POSE})]
        )
    )
    assert airbot_play.configure()

    test.set_pose_bias(
        position=np.array([0.0, 0.0, 0.0]),
        orientation=quaternion_from_euler(0.0, 0.0, 0.0),
    )
    # test.set_eef_threshold(0.03, 0.0, 0.072)
    for i in range(1):
        test.seek(0)
        input(f"Press Enter to move to starting pose for iteration {i}...")
        assert airbot_play.switch_mode(SystemMode.RESETTING)
        airbot_play.send_action(test.update())
        input(f"Press Enter to start iteration {i}...")
        assert airbot_play.switch_mode(SystemMode.SAMPLING)
        period = 1 / 20.0
        while True:
            start = time.perf_counter()
            action = test.update()
            if not action:
                break
            print(action)
            airbot_play.send_action(action)
            time_elapsed = time.perf_counter() - start
            sleep_time = period - time_elapsed
            if sleep_time > 0:
                time.sleep(sleep_time)
        print(f"Finished iteration {i}.")
    assert airbot_play.shutdown()
    print("Finished iterating through the dataset.")
