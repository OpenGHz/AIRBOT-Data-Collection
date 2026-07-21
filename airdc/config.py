from pydantic import (
    BaseModel,
    NonNegativeFloat,
    NonNegativeInt,
    PositiveInt,
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
    manager_update_every: Dict[str, PositiveInt] = {}
    """Per-manager tick divider, keyed by the manager name in ``managers``.

    A manager mapped to ``N`` runs once every ``N`` main-loop iterations;
    managers absent from the map run every tick. This decouples the update
    frequency of different modules on the single main loop: e.g.
    ``{self_manager: 3}`` steps the simulation (``auto_atom``) every tick while
    capturing/saving only every 3rd tick, so state update and sampling run at
    independent rates without downsampling the replayed trajectory.

    Phase caveat — the divider is evaluated as ``global_tick % N`` against a
    single loop-wide counter that keeps counting across episodes; it is NOT
    reset when an episode/round starts. So the fire schedule is aligned to
    global tick 0, not to each episode's first sampling tick: an episode that
    enters the sampling state on a tick where ``global_tick % N != 0`` will
    have its first frame(s) skipped, so the recorded initial state can be
    dropped for some episodes. If you need every episode's first frame captured
    regardless of phase, use the episode-local ``DemonstrateConfig.sample_every``
    instead (its counter is reset per episode), or leave the sampler at ``N=1``
    here and downsample on the runner side via ``replay.demo_stride``."""
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

    fsm: StateMachineConfig
    """the finite state machine config"""
    job_id: Optional[int] = None
    """the job id for the data collection, if not provided, a random one will be generated"""
    job_id_bias: NonNegativeInt = 0
    """the bias for the job id"""
