"""Hydra callbacks for airdc."""

from logging import getLogger

from hydra.experimental.callback import Callback
from omegaconf import DictConfig

from airdc.basis import PACKAGE_NAME


logger = getLogger(PACKAGE_NAME)


class JitWarmupCallback(Callback):
    """Pre-build torch JIT-compiled CUDA extensions in the launcher process
    so multirun workers do not race on the shared
    ``~/.cache/torch_extensions`` cache. gsplat unconditionally
    ``os.remove``s the build-dir lock at every module import
    (gsplat/cuda/_backend.py), which can clobber another worker's in-flight
    compile and surface as ``file too short`` / missing-lock errors.
    Building once here populates the .so before joblib spawns workers.

    Set ``AIRDC_SKIP_JIT_WARMUP=1`` to disable.
    """

    def on_multirun_start(self, config: DictConfig, **kwargs) -> None:
        import os

        if os.environ.get("AIRDC_SKIP_JIT_WARMUP") == "1":
            return
        try:
            import gsplat.cuda._backend  # noqa: F401  builds at import
        except ImportError:
            return
        except Exception as exc:
            logger.warning(f"gsplat JIT warmup failed (continuing): {exc!r}")
