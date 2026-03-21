from abc import abstractmethod
from typing import Any, Dict, Optional, final
from pathlib import Path
from pydantic import BaseModel, ConfigDict
from typing import Literal, Union, List
from airdc.basis import ConfigurableBasis
from airdc import __version__ as collector_version
from mcap_data_loader.utils.dict import CallableKeyMappingDict, MappingCall
from mcap_data_loader.utils.file import remove_path


class Subtask(BaseModel, frozen=True):
    skill: str
    """Skill template with placeholders like "pick {A} from {B}"."""
    description: str
    """English description of the subtask."""
    description_zh: str
    """Chinese description of the subtask."""


class TaskInfo(BaseModel, frozen=True):
    model_config = ConfigDict(extra="forbid")

    task_name: str = ""
    """Name of the task being performed. Used for identification and logging."""
    task_description: str = ""
    """Detailed description of the task in English."""
    task_description_zh: str = ""
    """Detailed description of the task in Chinese."""
    task_id: Union[str, int] = ""
    """Unique identifier for the task, used for tracking and management."""
    station: str = ""
    """Identifier for the station where the task is performed, useful for multi-station setups."""
    operator: str = ""
    """ID of the operator performing the task, useful for logging and accountability."""
    skill: Union[str, List[str]] = ""
    """Skill(s) being demonstrated or performed during the task."""
    object: Union[str, List[str]] = ""
    """Object(s) involved in the task."""
    scene: str = ""
    """Scene or environment description for the task."""
    subtasks: List[Subtask] = []
    """List of subtasks that compose the main task."""


class SaveType(BaseModel, frozen=True):
    model_config = ConfigDict(extra="forbid")

    color: Literal["raw", "jpeg", "h264"] = "h264"
    """Color image saving type."""
    depth: Literal["raw"] = "raw"
    """Depth image saving type."""


class Version(BaseModel, frozen=True):
    model_config = ConfigDict(extra="forbid")

    collector: str = collector_version
    """Version of the data collection codebase."""
    data_schema: str = "0.0.1"
    """Version of the data schema used for organizing and storing collected data."""


class DataSamplerConfigBasis(BaseModel, frozen=True):
    """Base configuration for data sampler."""

    model_config = ConfigDict(extra="forbid")

    key_remap: MappingCall[str] = CallableKeyMappingDict()
    """Key remapping for data fields."""
    remove_mode: Literal["permanent", "trash"] = "permanent"
    """Data removal mode."""


class DataSamplerConfig(DataSamplerConfigBasis):
    """Configuration for data sampler."""

    version: Version = Version()
    """Version information for the data collection."""
    task_info: TaskInfo = TaskInfo()
    """Task information for the data collection."""
    save_type: SaveType = SaveType()
    """Data saving types for different modalities."""


class DataSampler(ConfigurableBasis):
    """Data sampler for sampling kinds of data."""

    def __init__(self, config: DataSamplerConfig):
        self.config = config

    def config_post_init(self):
        super().config_post_init()
        self._path: Optional[Path] = None

    def get_start_episode(self, directory: Path) -> int:
        """Get the starting episode number from the given data directory.
        Args:
            directory (Path): The directory where the data are saved.
        Returns:
            int: The starting episode number.
                -1 means it's up to the demonstrate interface to decide.
        """
        return -1

    @abstractmethod
    def on_compose_path(self, directory: Path, episode: int) -> Path:
        """Compose the path to the data file. It will be called
        at starting sampling and removing. Before returning, file
        handler can be created to save data in `update` during sampling.
        Args:
            directory (Path): The directory where the data will be saved.
            episode (int): The episode number of the data.
        Returns:
            Path: The path to the data file.
        """

    @final
    def compose_path(self, directory: Path, episode: int) -> Path:
        self._path = self.on_compose_path(directory, episode)
        return self._path

    def clear(self) -> None:
        """Clear the inner data buffer if any.
        Please be careful to avoid asynchronous saving
        exceptions caused by asynchronous clearing of data"""

    def update(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Process the data and return.
        Args:
            data (Dict[str, Any]): The data to be processed.
        Returns:
            Dict[str, Any]: The processed data, which
            will be append to the data buffer in the
            demonstration interface.
        """
        return data

    def remove(self, path: Path) -> Optional[Path]:
        """Remove the data from the given or last saved path.
        Args:
            path (Path): The path to the data file.
        Returns:
            Optional[Path]: The path if removed successfully, None if the path does not exist.
        """
        if remove_path(path, self.config.remove_mode, False):
            return path

    def set_info(self, info: Dict[str, Any]) -> None:
        """Set the info of the data collector.
        The info is a dict that contains the information
        of the data collector, such as the name, type, etc."""
        self._info = info

    @abstractmethod
    def save(self, path: Path, data: Any) -> bool:
        """Save the data to the given path.
        Args:
            path (Path): The path to the data file.
            data (Any): The data to be saved. If used in
            demonstration, the data are those stored in the
            data buffer of the demonstration interface.
        Returns:
            bool: True if the data was saved successfully, False otherwise.
        """

    def _check_path(self, path: Path) -> bool:
        """Check if the data in the given path is valid"""
        return True

    def shutdown(self) -> None:
        """Shutdown the data sampler, release all resources."""
        # remove the last invalid episode
        if self._path and self._path.exists() and not self._check_path(self._path):
            self.get_logger().warning(f"Removing invalid data at {self._path}")
            self.remove(self._path)


class MockDataSampler(DataSampler):
    """Mock data sampler for testing purpose."""

    config: None

    def on_configure(self):
        return True

    def save(self, path: Path, data: Any):
        return True

    def remove(self, path: Path):
        return path

    def on_compose_path(self, directory: Path, episode: int):
        return directory / f"mock_{episode}.data"
