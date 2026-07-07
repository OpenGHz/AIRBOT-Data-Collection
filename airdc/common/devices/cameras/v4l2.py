import asyncio
import numpy as np
import time
from threading import Event
from typing import Union, Optional
from linuxpy.video.device import (
    BufferFlag,
    Capability,
    Device,
    PixelFormat,
    VideoCapture,
    Frame,
)
from linuxpy.ctypes import timeval
from turbojpeg import TurboJPEG
from pydantic import field_validator, model_validator
from airdc.common.systems.basis import Sensor, DictDataStamped
from airdc.common.devices.cameras.utils import (
    ColorCameraConfig,
    find_camera_indices,
    get_camera_index_by_bus_info,
    get_video_device_bus_info,
    CameraInfo,
    CameraControl,
)
from airdc.common.visualizers.basis import VisualizerBasis
from airdc.common.utils.progress import run_event_loop
from airdc.common.utils.error import check_support


class V4L2CameraConfig(ColorCameraConfig):
    """Configuration for V4L2 camera device."""

    nb_buffers: int = 2
    mode: Optional[Union[str, int]] = None

    @field_validator("mode", mode="after")
    def validate_mode(cls, v):
        return {
            "mmap": Capability.STREAMING,
            "read": Capability.READWRITE,
        }.get(v, v)

    @model_validator(mode="after")
    def validate_rgb_camera(self):
        object.__setattr__(
            self.rgb_camera, "pixel_format", self.rgb_camera.pixel_format or "BGR24"
        )
        check_support(
            "pixel format",
            self.rgb_camera.pixel_format.upper(),
            "V4L2 camera",
            list(PixelFormat.__members__.keys()),
        )
        return self


class V4L2Camera(Sensor):
    """
    V4L2 camera class for Linux systems.
    """

    def __init__(self, config: V4L2CameraConfig):
        self.config = config
        self._shutdown = False
        self._visualizer = None
        self._frame = None
        self._swap_color = False
        self._jpeg = None
        self._ok_frame: Optional[Frame] = None

    def on_configure(self) -> bool:
        config = self.config
        color_config = config.rgb_camera
        cam_id = config.camera_index
        if cam_id is None:
            cam_id = find_camera_indices()[0]
        if isinstance(cam_id, int) or cam_id.isdigit():
            self.device = Device.from_id(int(cam_id))
        else:
            if "usb" in cam_id:
                cam_id = get_camera_index_by_bus_info(cam_id)[0]
            self.device = Device(cam_id)
        try:
            self.device.open()
        except FileNotFoundError as e:
            raise FileNotFoundError(
                f"Available cameras: {get_video_device_bus_info()}"
            ) from e

        if self.device.closed:
            return False
        self._capture = VideoCapture(self.device, config.nb_buffers, config.mode)
        cap_format = self._capture.get_format()
        pixel_format = PixelFormat[color_config.pixel_format.upper()]
        self._capture.set_format(
            color_config.width or cap_format.width,
            color_config.height or cap_format.height,
            pixel_format,
        )
        if color_config.fps:
            self._capture.set_fps(color_config.fps)
        self._capture.open()
        self._format = self._capture.get_format()
        if pixel_format != self._format.pixel_format:
            if self._format.pixel_format is PixelFormat.MJPEG:
                if pixel_format in {PixelFormat.BGR24, PixelFormat.RGB24}:
                    # use turbojpeg for MJPG to BGR conversion
                    self._jpeg = TurboJPEG()
                    if pixel_format is PixelFormat.RGB24:
                        self._swap_color = True
            else:
                # self.get_logger().warning(
                raise ValueError(
                    f"Warning: Pixel format set to {self._format.pixel_format.name}, "
                    f"but requested {pixel_format.name}."
                )
        # NOTE: do not move to __init__ to avoid deepcopy error
        self._event = Event()
        self._read_fut = asyncio.run_coroutine_threadsafe(
            self._read_frame(), run_event_loop()
        )
        self._init_info()
        return True

    def capture_observation(
        self, timeout: Optional[float] = None
    ) -> DictDataStamped[Union[bytes, np.ndarray]]:
        if self.config.blocking or self._frame is None:
            if not self._event.wait(timeout):
                raise TimeoutError(f"Timeout waiting for camera frame: {timeout} s.")
            self._event.clear()
        key = "color/image_raw"
        frame = self._frame
        try:
            frame_array = self._jpeg.decode(frame.data) if self._jpeg else frame.array
        except OSError as e:
            self.get_logger().error(
                f"Failed to decode MJPEG frame: {e}. The frame will be replaced with the last known good frame."
            )
            frame = self._ok_frame
            frame_array = self._jpeg.decode(frame.data)
        else:
            self._ok_frame = frame
        obs = {key: {"t": self._get_stamp(frame)}}
        if len(frame_array.shape) > 1:
            image = frame_array[:, :, ::-1] if self._swap_color else frame_array
        else:
            image = frame.data
        obs[key]["data"] = image
        return obs

    def shutdown(self) -> bool:
        self._shutdown = True
        self._read_fut.result()
        # NOTE: without a short sleep period, there is a high probability of a shutdown error occurring
        time.sleep(0.01)
        self._capture.close()
        self.device.close()
        return self.device.closed

    def _init_info(self):
        cam_format = self._capture.get_format()
        camera_info = CameraInfo(
            width=cam_format.width, height=cam_format.height
        ).model_dump(mode="json")
        config = self.config.rgb_camera
        if config.intrinsics is not None:
            camera_info.update(config.intrinsics.model_dump(mode="json"))
        if config.calibration is not None:
            camera_info.update(config.calibration.model_dump(mode="json"))
        color_info = {"camera_info": camera_info}
        self.device.controls._init_if_needed()
        id_to_name = {}
        for ctrl in self.device.info.controls:
            id_to_name[ctrl.id] = ctrl.name.decode().lower().replace(" ", "_")
        ctrl_info = {}
        for key, ctrl in self.device.controls.items():
            ctrl_info[id_to_name[key]] = ctrl.value
        fps = self._capture.get_fps().as_integer_ratio()
        color_info.update(
            {"fps": str(fps[0] / fps[1]), "pixel_format": cam_format.pixel_format.name}
        )
        color_info.update(ctrl_info)
        dev_info = self.device.info
        self._info = {
            "driver": dev_info.driver,
            "card": dev_info.card,
            "bus_info": dev_info.bus_info,
            "version": dev_info.version,
            "color": color_info,
        }

    def get_info(self):
        return self._info

    def set_visualizer(self, visualizer: VisualizerBasis, prefix: str = ""):
        """TODO: should use this method?
        Set the visualizer for this camera for self control.
        :param visualizer: VisualizerBasis instance to visualize the camera data.
        :param prefix: Prefix for the visualizer key.
        """
        self._visualizer = visualizer

    @staticmethod
    def _get_stamp(frame: Frame) -> int:
        timestamp: timeval = frame.buff.timestamp
        stamp_ns = timestamp.secs * int(1e9) + timestamp.usecs * int(1e3)
        # V4L2 buffer timestamps use CLOCK_MONOTONIC (nanoseconds since boot), while the
        # rest of airdc (joint_states stamp, log_time) uses wall clock via time.time_ns().
        # Convert the monotonic capture instant to wall clock so every stamp shares one
        # clock domain; otherwise image stamps are off by years relative to the rest.
        #
        # The offset is recomputed on every frame on purpose, not cached once:
        #   - It is not constant. monotonic (adjtime slewing) and realtime (NTP steps /
        #     manual changes) drift apart over time, so a cached offset goes stale on long
        #     recordings.
        #   - joint_states call time.time_ns() fresh each sample; recomputing keeps images
        #     on the same wall clock even across an NTP step (a cached offset would diverge).
        #   - Cost is negligible: clock_gettime is a vDSO read (~20-30ns, no syscall).
        # The only thing lost is exact frame-to-frame monotonic deltas (sub-microsecond
        # jitter between the two clock reads), which is irrelevant at 30-100Hz.
        if (
            frame.buff.flags & BufferFlag.TIMESTAMP_MASK
            == BufferFlag.TIMESTAMP_MONOTONIC
        ):
            return stamp_ns + (time.time_ns() - time.monotonic_ns())
        # Unknown/copied timestamp source (or driver left it unset): use wall clock now.
        return time.time_ns()

    async def _read_frame(self):
        async for frame in self._capture:
            self._frame = frame
            self._event.set()
            if self._shutdown:
                break


if __name__ == "__main__":
    import time
    import cv2
    import logging

    logging.basicConfig(level=logging.INFO)

    def test(show: bool = True):
        camera = V4L2Camera(V4L2CameraConfig(width=1280, height=720, fps=30))
        assert camera.configure()
        while True:
            start = time.monotonic()
            image = camera.capture_observation()["color/image_raw"]["data"]
            if show:
                print(f"time cost: {time.monotonic() - start}s", end="\r")
                cv2.imshow("image", image)
                if cv2.waitKey(1) & 0xFF in (ord("q"), 27):  # 27 is the ESC key
                    cv2.destroyAllWindows()
                    break
            else:
                break
        assert camera.shutdown()

    test(True)
    # test to ensure no shutdown error
    # for i in range(50):
    #     print(i)
    #     test(False)
