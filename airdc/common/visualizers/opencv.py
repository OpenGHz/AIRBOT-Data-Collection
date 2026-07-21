import logging
import cv2
import numpy as np
import time
from pydantic import BaseModel
from threading import current_thread, main_thread
from airdc.common.visualizers.basis import (
    GUIVisualizerConfig,
    SampleInfo,
    VisualizerBasis,
    ConcurrentMode,
)
from airdc.common.utils.shareable_numpy import ShareableNumpy
from airdc.utils import init_logging
from airdc.basis import DictDataStamped
from mcap_data_loader.utils.vis import make_heatmap_rgb
from multiprocessing.context import SpawnProcess
from multiprocessing.managers import SharedMemoryManager
from multiprocessing import get_context, current_process
from multiprocessing.synchronize import Event
from setproctitle import setproctitle
from typing import Dict, Callable, Optional, Union


ImageType = Union[np.ndarray, bytes]


def prepare_cv2_imshow(logger: Optional[logging.Logger] = None) -> bool:
    """Prepare OpenCV imshow for displaying images before import pynput.
    Otherwise, the imshow will block and not show the image.
    """

    if logger is None:
        logger = logging.getLogger("prepare_cv2_imshow")

    logger.info("Preparing cv2.imshow")
    image = np.zeros((480, 640, 3), np.uint8)

    def show_image(name):
        cv2.imshow(name, image)
        cv2.waitKey(1)
        cv2.destroyWindow(name)

    try:
        show_image("Prepared image")
    except Exception as e:
        logger.warning(
            f"cv2.imshow preparation failed. You can ignore this when in `headless` mode: {e}"
        )
        return False
    logger.info("cv2.imshow is ready")
    return True


def decode_image(
    data: bytes, pixel_format: str, width: int = 0, height: int = 0
) -> np.ndarray:
    """Decode the image data based on the pixel format."""
    if pixel_format == "MJPEG":
        return cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    elif pixel_format == "YUYV":
        assert width > 0 and height > 0, (
            "Width and height must be provided for YUYV format"
        )
        return cv2.cvtColor(
            np.frombuffer(data, np.uint8).reshape((height, width, 2)),
            cv2.COLOR_YUV2BGR_YUYV,
        )
    else:
        raise ValueError(f"Unsupported pixel format: {pixel_format}")


class OpenCVVisualizerConfig(GUIVisualizerConfig):
    """Configuration for OpenCV visualizer."""

    window_type: int = cv2.WINDOW_NORMAL
    # -1 means do not wait key
    wait_key: int = 1


class TextConfig(BaseModel):
    """Configuration for text overlay on the image."""

    text: str = ""
    fontFace: int = cv2.FONT_HERSHEY_SIMPLEX
    fontScale: int = 1
    thickness: int = 1
    color: tuple[int, int, int] = (0, 0, 0)
    org: tuple[int, int] = (0, 0)


class OpenCVVisualizer(VisualizerBasis):
    """Visualizer based on OpenCV."""

    config: OpenCVVisualizerConfig

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Initialize attributes that shutdown() depends on
        self._concurrent: SpawnProcess = None
        self._smm: SharedMemoryManager = None
        self._stop_event = None
        self._is_concurrent = False
        self.current_key = None

    def on_configure(self) -> bool:
        if not self.config.ignore_info:
            self.text_config = TextConfig()
            self.info_image_base = (
                np.ones((self.config.height, self.config.width, 3), dtype=np.uint8)
                * 255
            )
        spawn_ctx = get_context("spawn")
        self._smm = SharedMemoryManager(ctx=spawn_ctx)
        self._stop_event = spawn_ctx.Event()
        self._is_concurrent = self.config.concurrent_mode != ConcurrentMode.none
        return True

    @classmethod
    def update_loop_shm(
        cls, rate: float, data_shm: Dict[str, ShareableNumpy], stop_event: Event
    ):
        init_logging()
        period = 1 / rate if rate > 0 else 0
        setproctitle(current_process().name)
        cls.get_logger().info("Update loop started")
        while not stop_event.is_set():
            start = time.perf_counter()
            for key, shm_array in data_shm.items():
                cv2.imshow(key, shm_array.array)
            cv2.waitKey(1)
            sleep_time = period - (time.perf_counter() - start)
            if sleep_time > 0:
                time.sleep(sleep_time)
        cv2.destroyAllWindows()
        cls.get_logger().info("Update loop stopped")

    def on_update(
        self, data: DictDataStamped[ImageType], info: SampleInfo, warm_up: bool = False
    ) -> bool:
        """Show the data on the QT window."""
        if warm_up or not self._is_concurrent:
            self._images = {}
            images = self._get_images(data, info, self._assign_images)
            if self._is_concurrent:
                self._smm.start()
                ShareableNumpy.from_array_dict(
                    self._images, smm=self._smm, replace=True
                )
                self._concurrent = SpawnProcess(
                    target=self.update_loop_shm,
                    args=(self.config.rate, self._images, self._stop_event),
                    name=self.__class__.__name__,
                )
                self._concurrent.start()
        else:
            images = self._get_images(data, info, self._update_images)
        if not self._is_concurrent:
            self.current_key = self.show_images(images, self.config.wait_key)
        return True

    @classmethod
    def show_images(cls, images: Dict[str, np.ndarray], wait_key: int) -> Optional[int]:
        # TODO: add concatenation for the data?
        if current_thread() is not main_thread():
            cls.get_logger().warning("Not running in the main thread, skipping imshow")
            return -1
        for key, image in images.items():
            cv2.imshow(key, image)
        if wait_key > 0:
            return cv2.waitKey(wait_key)

    def _get_images(
        self, data: DictDataStamped[ImageType], info: SampleInfo, func: Callable
    ) -> Dict[str, np.ndarray]:
        for key, value_dict in data.items():
            value = value_dict["data"]
            if isinstance(value, bytes):
                value = decode_image(value, self.config.pixel_format)
            # TODO: why the value is None?
            shape = value.shape if value is not None else (0, 0)
            if shape[0] == 0 or shape[1] == 0:
                self.get_logger().warning(
                    f"Received wrong image: {value} for key {key}, skipping imshow"
                )
                continue
            if shape[2] != 3:
                value = make_heatmap_rgb(value)
            elif self.config.swap_rgb_bgr:
                value = value[..., ::-1]
            func(key, value)
        if not self.config.ignore_info:
            image = self._put_info(self.info_image_base.copy(), info)
            func("info", image)
        return self._images

    def _assign_images(self, key: str, value: np.ndarray) -> None:
        self._images[key] = value

    def _update_images(self, key: str, value: np.ndarray) -> None:
        self._images[key][:] = value

    def shutdown(self):
        if self._concurrent is not None:
            self._stop_event.set()
            if self._concurrent.is_alive():
                self._concurrent.join(5)
        if self._smm is not None and hasattr(self._smm, "shutdown"):
            # SharedMemoryManager.shutdown() only exists after start() is called
            # It's dynamically added as a Finalize object during start()
            self._smm.shutdown()
        if not self._is_concurrent:
            cv2.destroyAllWindows()

    def _put_info(self, image: np.ndarray, info: SampleInfo) -> None:
        """Put the current episode and step information on the image.

        This function overlays the episode and step text on the image background,
        and then displays the image with the updated text using OpenCV.
        """
        text_top = f"Episode: {info.episode}"
        text_bottom = f"Index: {info.index}"
        image = image

        # Calculate text size for centering the text
        self.text_width_top, self.text_height_top = cv2.getTextSize(
            text_top,
            self.text_config.fontFace,
            self.text_config.fontScale,
            self.text_config.thickness,
        )[0]
        self.text_width_bottom, self.text_height_bottom = cv2.getTextSize(
            text_bottom,
            self.text_config.fontFace,
            self.text_config.fontScale,
            self.text_config.thickness,
        )[0]

        x_top = (self.config.width - self.text_width_top) // 2
        y_top = int(self.config.height * 0.25)
        x_bottom = (self.config.width - self.text_width_bottom) // 2
        y_bottom = int(self.config.height * 0.75)

        text_cfg_dict = self.text_config.model_dump()
        text_cfg_dict["text"] = text_top
        text_cfg_dict["org"] = (x_top, y_top)
        cv2.putText(image, **text_cfg_dict)
        text_cfg_dict["text"] = text_bottom
        text_cfg_dict["org"] = (x_bottom, y_bottom)
        cv2.putText(image, **text_cfg_dict)
        return image


if __name__ == "__main__":
    visualizer = OpenCVVisualizer(
        OpenCVVisualizerConfig(concurrent_mode=ConcurrentMode.process, rate=30)
    )
    assert visualizer.on_configure()
    video_name = 12
    # cap = cv2.VideoCapture(video_name)
    # assert cap.isOpened(), "Cannot open camera"
    # ret, frame = cap.read()
    frame = np.ones((480, 640, 3), dtype=np.uint8) * 100
    ret = True
    assert ret, "Cannot read camera frame"
    video_name = str(video_name)
    visualizer.update({video_name: frame}, SampleInfo(episode=0, index=0), warm_up=True)
    for i in range(330):
        start = time.perf_counter()
        # ret, frame = cap.read()
        if not ret:
            print("Can't receive frame (stream end?). Exiting ...")
            break
        visualizer.update({video_name: frame}, SampleInfo(episode=i, index=i))
        if visualizer.current_key == 27:
            break
        print(f"Frame {i} displayed in {(time.perf_counter() - start) * 1000:.3f} ms")
        time.sleep(0.033)
    visualizer.shutdown()
