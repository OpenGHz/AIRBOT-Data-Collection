from abc import abstractmethod
from typing import Optional, Protocol, Union, runtime_checkable, final
from pydantic import BaseModel, NonNegativeInt, PositiveInt
from airdc.basis import ConfigurableBasis, ConcurrentMode
from airdc.basis import DictDataStamped
from airdc.common.utils.dict_utils import (
    DictKeyFilter,
    DictKeyFilterConfig,
)
from airdc.demonstrate.basis import SampleInfo


class VisualizerConfig(BaseModel, frozen=True):
    key_filtering: DictKeyFilterConfig = DictKeyFilterConfig()


class GUIVisualizerConfig(VisualizerConfig):
    """Configuration for GUI visualizer."""

    single_window: bool = False
    """Whether to display all images in a single window with subplots."""
    concatenate: bool = False
    """Whether to concatenate all images into a single image."""
    width: NonNegativeInt = 640
    height: NonNegativeInt = 480
    """
    the width and height of the GUI
    window when single_window or concatenate
    is set to True
    0 means auto
    """
    title: str = ""
    """
    the tile of the GUI window when
    the single_window or concatenate
    is set to True
    """

    axis: NonNegativeInt = 1
    """
    the direction of the subplots increment
    when single_window or concatenate
    is set to True
    0: row-wise, 1: column-wise
    """
    max_num: NonNegativeInt = 0
    """
    the max number of subplots in a row / column
    before the next row / column, which should be
    adjusted according to the image size and the
    screen resolution
    when single_window or concatenate
    is set to True
    if zero, will automatically calculate
    based on the screen resolution
    and the image resolution
    """
    ignore_info: bool = False
    """do not display the sample info"""
    screen_width: PositiveInt = 1920
    """ the width of the screen"""
    screen_height: PositiveInt = 1080
    """ the height of the screen"""
    swap_rgb_bgr: bool = False
    """whether to swap the R and B channels of the image"""
    pixel_format: str = "MJPEG"  # MJPEG, YUYV
    """
    the pixel format of the image used when the data type is bytes
    TODO: should and how to pass the image info
    automatically to the visualizer from the image
    data or the camera component?
    """
    concurrent_mode: ConcurrentMode = ConcurrentMode.none
    """
    TODO: and for the YUYV format, the width and height
    of the image should be passed to the visualizer
    and it is hard to configure here
    concurrent mode for updating the GUI
    """
    rate: NonNegativeInt = 0
    """update rate in Hz, 0 means no limit"""


class WebVisualizerConfig(VisualizerConfig):
    """Configuration for web visualizer."""

    host: str = "127.0.0.0"
    port: NonNegativeInt = 8000
    log_level: Optional[Union[str, int]] = None
    access_log: bool = False


class VisualizerBasis(ConfigurableBasis):
    """VisualizerBasis for visualizing the data."""

    config: VisualizerConfig

    def __init__(self, config: Optional[VisualizerConfig] = None, **kwargs):
        super().__init__(config, **kwargs)
        self._filter = DictKeyFilter(self.config.key_filtering)

    @final
    def update(
        self, data: DictDataStamped, info: Optional[SampleInfo], warm_up: bool = False
    ) -> None:
        return self.on_update(self._filter(data), info, warm_up)

    @abstractmethod
    def on_update(
        self, data: DictDataStamped, info: Optional[SampleInfo], warm_up: bool = False
    ) -> None:
        """Update the visualizer with the new data."""

    @abstractmethod
    def shutdown(self) -> None:
        """Shutdown the visualizer."""


class MockVisualizer(VisualizerBasis):
    """A mock visualizer for testing."""

    config: VisualizerConfig

    def on_configure(self):
        return True

    def on_update(
        self, data: DictDataStamped, info: Optional[SampleInfo], warm_up: bool = False
    ) -> None:
        pass

    def shutdown(self) -> None:
        pass


@runtime_checkable
class Visualizer(Protocol):
    """Visualizer for visualizing the data."""

    def configure(self) -> bool: ...
    def update(
        self, data: DictDataStamped, info: SampleInfo, warm_up: bool = False
    ) -> None: ...
    def shutdown(self) -> None: ...
