"""Hydra callbacks for airdc."""

from contextlib import contextmanager
from logging import getLogger
from pathlib import Path

from hydra.experimental.callback import Callback
from omegaconf import DictConfig

from airdc.basis import PACKAGE_NAME


logger = getLogger(PACKAGE_NAME)


class JitWarmupCallback(Callback):
    """Pre-build torch JIT-compiled CUDA extensions and serialize per-worker
    gsplat imports behind a file lock.

    gsplat unconditionally ``os.remove``s the build-dir lock at every module
    import (``gsplat/cuda/_backend.py``), so concurrent worker imports can
    clobber each other's intermediate ``.o`` files and the link step fails
    with ``file format not recognized``. The launcher-side warmup alone is
    not enough because joblib workers spawn fresh Python processes that
    re-import gsplat, and the stagger between workers is shorter than the
    first compile (~45s). We wrap the import in an airdc-owned ``flock`` so
    only one worker at a time is in gsplat's compile critical section; once
    the first worker finishes, subsequent imports hit the cached ``.so``.

    Set ``AIRDC_SKIP_JIT_WARMUP=1`` to disable.
    """

    _LOCK_PATH = Path.home() / ".cache" / "airdc" / "gsplat_jit.lock"

    @contextmanager
    def _gsplat_jit_lock(self):
        import fcntl

        self._LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(self._LOCK_PATH, "w") as lock_file:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    def _warmup(self) -> None:
        import os

        if os.environ.get("AIRDC_SKIP_JIT_WARMUP") == "1":
            return
        with self._gsplat_jit_lock():
            try:
                import gsplat.cuda._backend  # noqa: F401  builds at import
            except ImportError:
                return
            except Exception as exc:
                logger.warning(f"gsplat JIT warmup failed (continuing): {exc!r}")

    def on_multirun_start(self, config: DictConfig, **kwargs) -> None:
        self._warmup()

    def on_job_start(self, config: DictConfig, **kwargs) -> None:
        self._warmup()
