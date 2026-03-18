from airdc.common.utils.sim.mujoco.mujoco_env import (
    UnifiedMujocoEnv,
    EnvConfig,
    DataType,
    CameraSpec,
)

if __name__ == "__main__":
    env = UnifiedMujocoEnv(
        EnvConfig(
            model_path="third_party/xml/scene_single_arm.xml",
            arm_mode="single",
            enabled_sensors=[DataType.CAMERA, DataType.POSE],
            cameras=[
                CameraSpec(
                    name="hand_cam",
                    width=640,
                    height=480,
                    enable_color=True,
                    enable_depth=False,
                )
            ],
        )
    )
    env.reset()
    info = env.get_info()
    print(info.keys())

    obs = env.capture_observation()
    print(obs.keys())
