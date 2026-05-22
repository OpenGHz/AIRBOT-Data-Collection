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
    heavy initialization that races on shared resources.

    Two distinct races are addressed:

    1. ``gsplat`` unconditionally ``os.remove``s the build-dir lock at every
       module import (``gsplat/cuda/_backend.py``), so concurrent worker
       imports clobber each other's intermediate ``.o`` files and the link
       step fails with ``file format not recognized`` / ``file too short``.
       The launcher-side warmup alone is not enough because joblib workers
       spawn fresh Python processes that re-import gsplat. We wrap the
       import in an airdc-owned ``flock`` so only one worker at a time is in
       gsplat's compile critical section; once the first worker finishes,
       subsequent imports hit the cached ``.so``.

    2. ``BatchedGSUnifiedMujocoEnv.__init__`` loads ~30 PLY files into numpy
       and pushes them to GPU. With N workers doing this in parallel, peak
       CPU memory / ``/dev/shm`` get crushed and numpy assignment SIGBUS's
       on a page fault that can't be backed (manifests as ``Fatal Python
       error: Bus error`` in ``load_ply_3dgs``). We monkey-patch the
       constructor to serialize the heavy init phase via a second flock;
       once each worker is past init, normal steady-state work runs in
       parallel as before.

    Set ``AIRDC_SKIP_JIT_WARMUP=1`` to disable warmup and serialization.
    """

    _GSPLAT_LOCK_PATH = Path.home() / ".cache" / "airdc" / "gsplat_jit.lock"
    _GS_INIT_LOCK_PATH = Path.home() / ".cache" / "airdc" / "gs_env_init.lock"

    @contextmanager
    def _file_lock(self, lock_path: Path):
        import fcntl

        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with open(lock_path, "w") as lock_file:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    def _warmup_gsplat(self) -> None:
        with self._file_lock(self._GSPLAT_LOCK_PATH):
            try:
                import gsplat.cuda._backend  # noqa: F401  builds at import
            except ImportError:
                return
            except Exception as exc:
                logger.warning(f"gsplat JIT warmup failed (continuing): {exc!r}")

    def _patch_gs_env_init(self) -> None:
        try:
            from auto_atom.basis.mjc import gs_mujoco_env as _mod
        except ImportError:
            return
        cls = getattr(_mod, "BatchedGSUnifiedMujocoEnv", None)
        if cls is None or getattr(cls.__init__, "_airdc_locked", False):
            return
        original_init = cls.__init__
        callback = self

        def wrapped(self_env, *args, **kwargs):
            with callback._file_lock(callback._GS_INIT_LOCK_PATH):
                original_init(self_env, *args, **kwargs)

        wrapped._airdc_locked = True
        cls.__init__ = wrapped

    def _run(self) -> None:
        import os

        if os.environ.get("AIRDC_SKIP_JIT_WARMUP") == "1":
            return
        self._warmup_gsplat()
        self._patch_gs_env_init()

    def on_multirun_start(self, config: DictConfig, **kwargs) -> None:
        self._run()

    def on_job_start(self, config: DictConfig, **kwargs) -> None:
        self._run()
