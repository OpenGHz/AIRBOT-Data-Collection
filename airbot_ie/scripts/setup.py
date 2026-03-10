from airdc.common.devices.cameras.v4l2 import (
    V4L2Camera,
    V4L2CameraConfig,
)
from airdc.common.visualizers.opencv import (
    OpenCVVisualizer,
    OpenCVVisualizerConfig,
)
from airdc.common.devices.cameras.utils import (
    find_video_capture_devices,
)
from airdc.utils import (
    init_logging,
    execute_shell_script,
    get_can_interfaces,
    zip,
    BaseModelWithFieldAliases,
)
from airdc.common.utils.system_info import SystemInfo
from airdc.basis import PACKAGE_NAME, Bcolors
from collections import defaultdict
from pprint import pformat
from pydantic import Field
from pydantic_settings import CliApp
from typing import List, Dict
from importlib.metadata import version
from pathlib import Path
from ruamel.yaml import YAML
import logging
import cv2
import subprocess
import time


yaml = YAML()
init_logging()
logger = logging.getLogger(f"{PACKAGE_NAME}-setup")
logger.info(f"Version: {version(PACKAGE_NAME)}")

try:
    from airdc.common.devices.cameras.intelrealsense import (
        IntelRealSenseCamera,
        IntelRealSenseCameraConfig,
        find_camera_device_ids,
    )

    USE_REALSENSE = True
except ImportError as e:
    logger.warning(e)
    USE_REALSENSE = False


def list_to_nested_tuples(lst):
    return [(lst[i], lst[i + 1]) for i in range(0, len(lst), 2)]


def check_can_interfaces(expected_interfaces: list[str]) -> bool:
    result = subprocess.run(
        ["ip", "l"],
        capture_output=True,
        text=True,
        check=True,
    )
    output = result.stdout

    found_interfaces = [line for line in output.splitlines() if "can_" in line]
    found_names = [line.split(":")[1].strip() for line in found_interfaces]

    missing = [name for name in expected_interfaces if name not in found_names]
    if not missing:
        return True
    else:
        return False


cur_dir = Path(__file__).parent.resolve()


class SetupConfig(BaseModelWithFieldAliases):
    """Configuration for the setup script of airbot data collection."""

    ignore_cameras: List[str] = Field(
        [],
        validation_alias="ic",
        description="Ignore cameras by their bus_info or serial_number",
    )
    can_interfaces: List[str] = Field(
        [],
        validation_alias="can",
        description="List of CAN interfaces to use. If not provided, all available CAN interfaces will be used.",
    )
    ignore_cans: List[str] = Field(
        [],
        validation_alias="ii",
        description="Ignore CAN interfaces by their names.",
    )
    ref_cfg_dir: List[Path] = Field(
        [Path("airbot_ie/configs") / name for name in ["demonstrators", "samplers"]],
        validation_alias="rcd",
        description="Directories containing the base configuration files.",
    )
    ref_cfg_name: Path = Field(
        "basis",
        validation_alias="rcn",
        description="Name of the base configuration file.",
    )
    ref_arm_cfg_dir: Path = Field(
        "airbot_ie/configs/robots",
        validation_alias="racd",
        description="Directory containing the base configuration files for the robotic arms.",
    )
    ref_arm_cfg_name: str = Field(
        "",
        validation_alias="racn",
        description="Name of the base configuration file for the robotic arms.",
    )
    drag: bool = False
    """Whether to use drag teaching mode."""
    depth: bool = False
    """Whether to enable depth cameras."""
    concurrent: bool = Field(
        False,
        description="Whether to use concurrent camera instantiation.",
        validation_alias="cc",
    )


args = CliApp.run(SetupConfig)

logger.info("Getting system information...")
hw_uuid = SystemInfo.get_product(True).get("uuid", "unknown")
logger.info(f"Hardware uuid: {hw_uuid}")

"""Process Configs"""
ref_cfgs = []
for ref_cfg_dir in args.ref_cfg_dir:
    ref_cfg_path = ref_cfg_dir / args.ref_cfg_name.with_suffix(".yaml")
    if ref_cfg_path.exists():
        ref_cfgs.append(ref_cfg_path)
if not ref_cfgs:
    raise FileNotFoundError(f"Base config file not found: {ref_cfg_path.absolute()}")
elif len(ref_cfgs) > 1:
    logger.warning(
        f"Multiple base config files found: {ref_cfgs}. Using the first one."
    )
ref_cfg_path = ref_cfgs[0]

station_config_path = cur_dir / "station_config.yaml"
station_config = yaml.load(open(station_config_path))
NAME_CHOICES = station_config["choices"][args.drag]
BUS_NAME_MAPPINGS = defaultdict(dict, station_config["bus_name_mapping"])
CAN_NAME_MAPPINGS = (
    {
        2: ["can_lead", "can_follow"],
        4: ["can_left_lead", "can_left", "can_right_lead", "can_right"],
    }
    if not args.drag
    else {
        1: ["can_follow"],
        2: ["can_left", "can_right"],
    }
)

"""Process CAN Interfaces"""

can_itfs = args.can_interfaces or sorted(
    set(get_can_interfaces()) - set(args.ignore_cans)
)
logger.info(f"CAN interfaces: {can_itfs}")
can_num = len(can_itfs)
if can_num not in CAN_NAME_MAPPINGS:
    raise ValueError(f"Not correct can number: {can_itfs} for drag={args.drag}")
arm_names = (
    ["lead", "follow"] * (can_num // 2)
    if not args.drag
    else {1: [""], 2: ["left", "right"]}[can_num]
)
arm_groups = (
    {
        2: ["/"] * can_num,
        4: ["left"] * 2 + ["right"] * 2,
    }[can_num]
    if not args.drag
    else ["/"] * can_num
)
arm_roles = ["l", "f"] * (can_num // 2) if not args.drag else ["l"] * can_num

if hw_uuid not in BUS_NAME_MAPPINGS[can_num]:
    BUS_NAME_MAPPINGS[can_num][hw_uuid] = {}
bus_name_mapping: dict = BUS_NAME_MAPPINGS[can_num][hw_uuid]
target_cans = CAN_NAME_MAPPINGS[can_num]
name_choices = NAME_CHOICES[can_num]

if set(target_cans) != set(can_itfs):
    logger.info(
        Bcolors.cyan(
            f"Binding CAN group {can_itfs} to target interfaces {target_cans}..."
        )
    )
    execute_shell_script(
        f"{cur_dir}/bind_can_udev.sh",
        args=[
            "--target",
            *target_cans,
        ],
        with_sudo=True,
    )
    # TODO: detect whether the CAN interfaces are bound correctly
    logger.info(
        Bcolors.cyan(
            "Please reconnect the robotic arms and press `Enter` to continue..."
        )
    )
    input()
    logger.info("Waiting for the system to stabilize after reconnection...")
    time.sleep(4)
    if check_can_interfaces(target_cans):
        logger.info(Bcolors.green("Successfully bound."))
    else:
        logger.error("Failed to bind. Please check the connections.")
        exit(1)
else:
    logger.info(f"CAN {can_itfs} already bound correctly.")

"""Process Cameras"""

all_cam_devices = find_video_capture_devices(True)
realsense_buses = []
logger.info(Bcolors.cyan(f"Found v4l2 devices: \n{pformat(all_cam_devices)}"))
for device_key in list(all_cam_devices.keys()):
    bus_id = device_key[1]
    if bus_id in args.ignore_cameras:
        all_cam_devices.pop(device_key)
    elif "RealSense" in device_key[0]:
        # remove realsense cameras from the v4l2 devices
        # since we will use their serial numbers
        all_cam_devices.pop(device_key)
        realsense_buses.append(bus_id)
used_camera_indices = [cam_ids[0] for cam_ids in all_cam_devices.values()]
# add realsene camera serial numbers
realsense_serials = set()
if USE_REALSENSE:
    realsense_cams = find_camera_device_ids(True)
    for bus, serial in realsense_cams.items():
        if bus not in args.ignore_cameras and serial not in realsense_serials:
            realsense_serials.add(serial)
    used_camera_indices.extend(realsense_serials)
else:
    logger.warning(
        f"Ignoring Intel RealSense cameras since the package is not installed: {realsense_buses}."
    )
    args.ignore_cameras.extend(realsense_buses)
assert used_camera_indices, "No used cameras. Please check the args and connections."
logger.info(Bcolors.blue(f"All ignored cameras: {args.ignore_cameras}"))
logger.info(Bcolors.blue(f"Used camera indices: {used_camera_indices}"))

cameras: list[V4L2Camera] = []
camera_vis_keys: list[str] = []
camera_bus_serials: list[str] = []
visualizers: list[OpenCVVisualizer] = []
camera_types: dict[str, str] = {}
camera_indices = []
camera_filenames = []
camera_params = defaultdict(dict)

cfged_indices = []
cfged_bus_serials = []
cfged_names = []
cfged_camera_types = []
no_cfg_buses_indexes: list[int] = []
for i, index in enumerate(list(used_camera_indices)):
    is_realsense = index in realsense_serials
    camera_config = {
        "width": 640,
        "height": 480,
    }
    if is_realsense:
        camera_config["fps"] = 30
        config = IntelRealSenseCameraConfig(
            camera_index=index, enable_depth=False, **camera_config
        )
        camera = IntelRealSenseCamera(config)
        camera_type = "realsense"
    else:
        config = V4L2CameraConfig(camera_index=index, **camera_config)
        camera = V4L2Camera(config)
        camera_type = "v4l2"
    visualizer = OpenCVVisualizer(OpenCVVisualizerConfig(ignore_info=True, wait_key=-1))
    if camera.configure():
        if visualizer.configure():
            if is_realsense:
                bus = index
                file_name = camera_type
                camera_params[bus] = {
                    "fps": 30,
                }
                cls_path = (
                    "airdc.common.devices.cameras.intelrealsense.IntelRealSenseCamera"
                )
                if args.concurrent:
                    target = "airdc.common.systems.wrappers.concurrent_instantiate"
                    camera_params[bus]["interface_cls"] = cls_path
                else:
                    target = cls_path
                if args.depth:
                    camera_params[bus]["enable_depth"] = True
                    camera_params[bus]["align_depth"] = True
            else:
                bus = camera.device.info.bus_info
                file_name = camera.device.filename
                target = "airdc.common.devices.cameras.v4l2.V4L2Camera"
            camera_config["_target_"] = target
            camera_params[bus].update(camera_config)
            logger.info(f"Camera {index} bus/serial info: {bus}")
            prefix = bus_name_mapping.get(bus, "None")
            if prefix == "None":
                logger.info(
                    Bcolors.blue(
                        f"Camera {index} bus/serial info {bus} not found in bus/serial name mapping."
                    )
                )
                no_cfg_buses_indexes.append(i)
            else:
                cfged_bus_serials.append(bus)
                cfged_names.append(prefix)
                cfged_indices.append(index)
                cfged_camera_types.append(camera_type)
            vis_key = f"{prefix} : {file_name} : {bus}"
            cameras.append(camera)
            camera_vis_keys.append(vis_key)
            camera_bus_serials.append(bus)
            visualizers.append(visualizer)
            camera_indices.append(index)
            camera_types[bus] = camera_type
            camera_filenames.append(file_name)
        else:
            logger.error(f"Failed to configure visualizer for camera index {index}.")

if camera_indices:
    logger.info(f"Opened cameras: {camera_indices}")
else:
    logger.error("No camera opened. Please check the camera indices.")
    exit(1)

logger.info(
    Bcolors.blue(
        "\n"
        + pformat(
            {
                "q or ESC": "Quit the setup script without saving configs.",
                "c": "Configure cameras with names.",
                "s": "Save the current configuration and exit.",
            }
        )
        + "\nNote: Click any of the image windows and then press the key"
    )
)
while True:
    for camera, vis_key, visualizer in zip(cameras, camera_vis_keys, visualizers):
        obs = camera.capture_observation(2.0)
        if isinstance(obs, dict):
            obs = obs["color/image_raw"]
        visualizer.update({vis_key: obs}, None)
    key = cv2.waitKey(1) & 0xFF
    if key == ord("q") or key == 27:  # ESC or 'q' to quit
        logger.info("Exiting setup script.")
        break
    elif key == ord("c"):
        if not no_cfg_buses_indexes:
            logger.warning(
                "No need to configure since all cameras are mapped to their names"
            )
            logger.info(Bcolors.blue("Do you want to re-configue? (y/n)"))
            if cv2.waitKey(0) & 0xFF == ord("y"):
                no_cfg_buses_indexes = list(range(len(camera_bus_serials)))
                # clear the previous configuration
                cfged_names.clear()
                cfged_bus_serials.clear()
                cfged_indices.clear()
                cfged_camera_types.clear()
                camera_vis_keys.clear()
                for cam_fn, cam_bus_ser in zip(
                    camera_filenames,
                    camera_bus_serials,
                ):
                    camera_vis_keys.append(f"None : {cam_fn} : {cam_bus_ser}")
            else:
                continue
        unused_name = list(set(name_choices) - set(cfged_names))
        if len(unused_name) < len(no_cfg_buses_indexes):
            logger.error(
                f"Not enough names to configure cameras: {unused_name=} {no_cfg_buses_indexes=}."
                "Please remove the extra camera or update the `choices` field in the `station_config.yaml` config file with more name choices."
            )
            break
        logger.info(f"Configuring cameras {unused_name=} {cfged_names=}...")
        old_vis_keys = set()
        for bus_index in no_cfg_buses_indexes:
            bus = camera_bus_serials[bus_index]
            if len(unused_name) == 1:
                final_name = unused_name[0]
            else:
                hint_str = ""
                for i, name in enumerate(unused_name):
                    hint_str += f"{name}[{i}] | "
                logger.info(
                    Bcolors.cyan(
                        f"Name the camera on {bus} (press the digital number in []): {hint_str.removesuffix('| ')}"
                    )
                )
                index = cv2.waitKey(0) & 0xFF - ord("0")
                final_name = unused_name.pop(index)
            old_vis_key = camera_vis_keys[bus_index]
            # old_vis_keys.add(old_vis_key)
            camera_vis_keys[bus_index] = old_vis_key.replace("None", final_name)
            cfged_names.append(final_name)
            cfged_bus_serials.append(bus)
            cfged_indices.append(camera_indices[bus_index])
            cfged_camera_types.append(camera_types[bus])
            bus_name_mapping[bus] = final_name
            logger.info(Bcolors.green(f"Camera {bus} renamed to {final_name}"))
        with open(station_config_path, "w") as f:
            yaml.dump(station_config, f)
        logger.info(f"Updated station config: {station_config_path}")
        cv2.destroyAllWindows()
        no_cfg_buses_indexes.clear()
    elif key == ord("s"):
        with open(ref_cfg_path) as f:
            config: dict = yaml.load(f)
            ref_arm_cfg_name = args.ref_arm_cfg_name
            cfg_name = None
            print(pformat(config))
            if not ref_arm_cfg_name:
                for cfg in config.get("defaults", []):
                    if isinstance(cfg, dict):
                        cfg_name = cfg.get("/robots")
                        if cfg_name is not None:
                            break
            ref_arm_cfg_name = ref_arm_cfg_name or cfg_name or "airbot_play"
            logger.info(f"Using arm ref cfg name: {ref_arm_cfg_name}")
            if ref_arm_cfg_name:
                arm_ref_cfg_path = args.ref_arm_cfg_dir / Path(
                    ref_arm_cfg_name
                ).with_suffix(".yaml")
                with open(arm_ref_cfg_path) as f:
                    arm_ref_cfg = yaml.load(f)
            components: Dict[str, list] = {
                "instances": [
                    (arm_ref_cfg | {"port": 50050 + i}) for i in range(len(can_itfs))
                ]
                + [
                    {"camera_index": bus} | camera_params.get(bus, {})
                    for bus in cfged_bus_serials
                ],
                "names": arm_names + cfged_names,
                "roles": arm_roles + ["o"] * len(cfged_indices),
                "groups": arm_groups + ["/"] * len(cfged_indices),
            }
            ref_cfg_dir = ref_cfg_path.parent

            param_dict: dict = config["demonstrator"]
            raw_comps = param_dict.get("components")
            if isinstance(raw_comps, dict):
                for key, value in raw_comps.items():
                    components[key].extend(value)
            logger.info(f"Components: {pformat(components)}")
            param_dict["components"] = components
            # config["defaults"].append(
            #     {"post_capture@demonstrator.instance": str(can_num)}
            # )
        # post_capture_path = f"{ref_cfg_dir}/post_capture/{can_num}.yaml"
        # with open(post_capture_path) as f:
        #     param_dict.update(yaml.load(f))
        with open(ref_cfg_dir / "setup.yaml", "w") as f:
            yaml.dump(config, f)
        logger.info(Bcolors.green("Setup completed successfully."))
        break
cv2.destroyAllWindows()

# disconnect all cameras,
# or the realsense camera may not be able to connect again1
logger.info("Shutting down cameras...")
for camera in cameras:
    camera.shutdown()
