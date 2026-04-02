from pydantic import (
    BaseModel,
    NonNegativeFloat,
    NonNegativeInt,
    ConfigDict,
    field_validator,
)
from airdc.demonstrate.configs import DemonstrateConfig
from airdc.state_machine.fsm import (
    DemonstrateFSMConfig,
    StateMachineConfig,
)
from airdc.managers.basis import DemonstrateManagerBasis
from typing import Dict, Optional


class DataCollectionConfig(BaseModel, frozen=True):
    """Configuration for the data collection."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    update_rate: NonNegativeFloat = 0
    """the maximum rate for the managers
    # 0 means as fast as possible"""
    fsm: DemonstrateFSMConfig
    """the finite state machine config"""
    managers: Dict[str, Optional[DemonstrateManagerBasis]] = {}
    """managers to control the demonstrate actions"""
    log_metrics: int = -1
    """log metrics every N seconds, -1 to disable"""
    log_jitter: bool = True
    """whether to log jitter statistics"""
    batch_size: NonNegativeInt = 0
    """the batch size for updating the managers, 0 means no batching"""

    @field_validator("managers", mode="after")
    def validate_managers(cls, v: dict):
        for name in list(v.keys()):
            if v[name] is None:
                v.pop(name)
        return v


class DataCollectionArgs(DemonstrateConfig, DataCollectionConfig):
    """Top level arguments for the data collection.
    The structure is similar but not identical to
    `DataCollectionConfig` which is more suitable
    for the CLI configuration.
    """

    # the finite state machine config
    fsm: StateMachineConfig
