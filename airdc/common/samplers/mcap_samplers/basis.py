import json
from typing import Tuple, Dict
from mcap.writer import Writer, CompressionType, IndexType
from pathlib import Path
from abc import abstractmethod
from flatten_dict import flatten
from collections.abc import Mapping
from mcap_data_loader.utils.mcap_utils import McapTool, MediaType
from mcap_data_loader.serialization.basis import McapWriterBasis
from airdc.common.samplers.basis import DataSampler
from airdc.common.samplers.basis import DataSamplerConfig
from time import time_ns
from pydantic import BaseModel, PositiveInt, field_validator


class McapWriterConfig(BaseModel):
    """Configuration for the MCAP writer."""

    chunk_size: PositiveInt = 1024 * 1024  # 1 MB
    """The maximum size of individual data chunks in a chunked file."""
    compression: CompressionType = CompressionType.ZSTD
    """Compression to apply to chunk data, if any."""
    index_types: IndexType = IndexType.ALL
    """Indexes to write to the file. See IndexType for possibilities."""
    repeat_channels: bool = True
    """Repeat channel information at the end of the file."""
    repeat_schemas: bool = True
    """Repeat schemas at the end of the file."""
    use_chunking: bool = True
    """Group data in chunks."""
    use_statistics: bool = True
    """Write statistics record."""
    use_summary_offsets: bool = True
    """Write summary offset records."""
    enable_crcs: bool = True
    """Enable CRCs for data integrity."""
    enable_data_crcs: bool = False
    """Enable CRCs for data integrity on individual data records."""

    @field_validator("chunk_size", mode="before")
    def validate_chunk_size(cls, value):
        if isinstance(value, str):
            return eval(value)
        return value


class McapDataSamplerBasisConfig(DataSamplerConfig):
    """Basic configuration for MCAP data sampler."""

    writer: McapWriterConfig = McapWriterConfig()


class McapDataSamplerBasis(DataSampler):
    """McapDataSamplerBasis is an abstract base class for MCAP data samplers, defining the interface for creating a MCAP writer."""

    _info: Dict[str, Dict[str, str]]

    def __init__(self, config: McapDataSamplerBasisConfig):
        self.config = config

    def on_configure(self):
        """Configure the mcap data sampler."""
        self._data_writer = self._create_writer()
        return True

    @abstractmethod
    def _create_writer(self) -> McapWriterBasis:
        """Create a custom MCAP writer based on the provided configuration."""

    def _create_mcap_writer(self, path: Path) -> Tuple[Writer, bool]:
        return Writer(str(path), **self.config.writer.model_dump()), True

    def on_compose_path(self, directory: Path, episode: int) -> Path:
        path = Path(directory) / f"{episode}.mcap"
        # unset here to ensure a fresh writer for each file
        # but the writer is finished in save()
        self._data_writer.unset_writer()
        self._data_writer.set_writer(*self._create_mcap_writer(path))
        return path

    @classmethod
    def add_config_metadata(cls, writer: Writer, config: DataSamplerConfig):
        config_dict = config.model_dump(mode="json")
        for key, value in config_dict.items():
            # Convert all values in dict to strings for MCAP metadata
            # MCAP add_metadata expects dict with string values
            if isinstance(value, dict):
                string_dict = {k: json.dumps(v) for k, v in value.items()}
            else:
                string_dict = {"value": json.dumps(value)}
            writer.add_metadata(name=key, data=string_dict)

    @staticmethod
    def _check_path(path):
        return McapTool.validate_file(path, True)

    def save(self, path: Path, data: dict) -> bool:
        """Save the data to a MCAP file."""
        writer = self._data_writer.get_writer()
        mcap_tool = McapTool(writer)
        info = self._info.copy()
        # add metadata
        self.add_config_metadata(writer, self.config)
        # Handle system info safely
        # TODO: save system info to attachment?
        # TODO: should remap info keys?
        system_info = info.pop("system", {})
        for key, value in system_info.items():
            flattened_value = (
                flatten(value, "path")
                if isinstance(value, Mapping)
                else {"value": value}
            )
            # Convert all values to strings
            string_dict = {k: json.dumps(v) for k, v in flattened_value.items()}
            writer.add_metadata(key, string_dict)

        writer.add_attachment(
            time_ns(),
            time_ns(),
            "component_info",
            MediaType.APPLICATION_JSON,
            json.dumps(info, default=lambda array: array.tolist()).encode("utf-8"),
        )
        mcap_tool.add_log_stamps_attachment(data["log_stamps"])
        mcap_tool.add_topic_statistics_attachment(self._data_writer.topic_statistics)
        # call the hook for saving additional data, such as messages, videos, etc.
        if self._on_save(path, data):
            writer.finish()
            return True
        return False

    def _on_save(self, path: Path, data: dict) -> bool:
        """Hook for saving data, can be overridden by subclasses to handle specific data types.
        Args:
            path (Path): The path to the data file.
            data (dict): The data to be saved. If used in demonstration, the data are those stored in the data buffer of the demonstration interface.
        """
        return True
