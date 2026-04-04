import uuid
from pydantic import BaseModel, ConfigDict
from typing import Dict
from logging import getLogger
from airdc.basis import Bcolors
from airdc.common.samplers.mcap_samplers.sampler_flb import (
    McapFlbDataSampler,
    McapFlbDataSamplerConfig,
)


try:
    from dataloop import DataLoopClient

    DATALOOP_AVAILABLE = True
except ImportError:
    DATALOOP_AVAILABLE = False
    getLogger(__name__).warning(
        "It is detected that the `UPLOAD` package is not installed, and the cloud upload function will not be available. If you need to use the upload function, please contact us to install it.",
    )


class UploadConfig(BaseModel, frozen=True):
    model_config = ConfigDict(extra="forbid")

    enable: bool = False
    endpoint: str = ""
    username: str = ""
    password: str = ""


class AIRBOTMcapDataSamplerConfig(McapFlbDataSamplerConfig):
    upload: UploadConfig = UploadConfig()


class AIRBOTMcapDataSampler(McapFlbDataSampler):
    config: AIRBOTMcapDataSamplerConfig
    _info: Dict[str, Dict[str, str]]

    def on_configure(self):
        """Configure the airbot mcap data sampler."""
        self._init_upload()
        return super().on_configure()

    def save(self, path: str, data: dict) -> str:
        """Save the data to a MCAP file."""
        path = super().save(path, data)
        # Upload to cloud after saving
        if self.config.upload.enable:
            self._upload_to_cloud(path)
        return path

    def _init_upload(self):
        """Enable upload to cloud storage."""
        if self.config.upload.enable:
            assert DATALOOP_AVAILABLE, "DataLoopClient is not available"
            self.dataloop_client = DataLoopClient(
                endpoint=self.config.upload.endpoint,
                username=self.config.upload.username,
                password=self.config.upload.password,
            )
            self.get_logger().info(
                Bcolors.cyan(f"Will upload to task id: {self.config.task_info.task_id}")
            )

    def _upload_to_cloud(self, file_path: str) -> bool:
        """Upload the saved file to cloud storage."""
        # Convert task_id to int if it's a string
        project_id = self.config.task_info.task_id
        if isinstance(project_id, str):
            project_id = int(project_id)
        message = self.dataloop_client.samples.upload_sample(
            project_id=project_id,
            sample_id=str(uuid.uuid4()),
            sample_type="Sequential",
            file_path=file_path,
        )
        self.get_logger().info(Bcolors.green(f"Uploaded to cloud: {message}"))
        return True
