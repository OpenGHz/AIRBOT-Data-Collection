import json
import os
import socket
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Optional, Union

from airdc.managers.auto_atom import (
    AutoAtomDataReplayConfig,
    AutoAtomDataReplayManager,
    DAction,
    State,
)
from pydantic import BaseModel, NonNegativeInt, ConfigDict, model_validator
from setproctitle import getproctitle
from airdc.scripts.reorganize_data_by_episode import (
    ReorganizeDataByEpisodeConfig,
    reorganize_data_by_episode,
)
from auto_atom.basis.mjc.gs_mujoco_env import BatchedGSUnifiedMujocoEnv


try:
    import redis
    from redis.exceptions import (
        ConnectionError as RedisConnectionError,
        ResponseError,
        TimeoutError,
    )
except ImportError:
    print(
        "The `redis` package is required for Redis-based AutoAtom managers. "
        "Please install it with `pip install redis`."
    )


class RedisConfig(BaseModel, frozen=True):
    """Configuration for Redis connection."""

    model_config = ConfigDict(extra="forbid")

    host: str = "localhost"
    """Redis host address (default: localhost)"""
    port: int = 6379
    """Redis port number (default: 6379)"""
    mode: Literal["pubsub", "stream_group"] = "pubsub"
    """Redis receive mode: pubsub or stream_group (default: pubsub)"""
    channel: str = "file_path"
    """Redis Pub/Sub channel name when mode=pubsub (default: file_path)"""
    message_buffer: bool = True
    """Whether to keep a persistent Redis Pub/Sub subscription (default: True)"""
    stream_key: str
    """Redis Stream key when mode=stream_group (default: stream:file_path)"""
    group_name: Optional[str] = None
    """Redis Stream consumer group name when mode=stream_group. None means one group per process title (group:auto_atom:<process_name>)"""
    consumer_name: Optional[str] = None
    """Redis Stream consumer name when mode=stream_group. None means one consumer per process (consumer:auto_atom:<hostname>:<process_name>)"""
    group_start_id: Union[str, NonNegativeInt] = 0
    """Start ID used when creating a new consumer group (default: 0)"""
    read_count: NonNegativeInt = 1
    """Maximum number of messages read per XREADGROUP call (default: 1)"""
    block_ms: NonNegativeInt = 2000
    """Blocking timeout in milliseconds for XREADGROUP (default: 2000)"""


@dataclass
class RedisFilePathMessage:
    """A normalized file-path message received from Redis."""

    file_path: str
    """File path of the source data contained in the Redis message"""
    ack_id: Optional[str] = None
    """ACK ID for Redis Stream messages, None for Pub/Sub messages"""
    episode_id: Optional[str] = None
    """Optional episode ID associated with the file path, if provided in the Redis message."""
    output_dir: Optional[str] = None
    """Optional output directory for reorganized data. When provided, existing links in that episode slot may be replaced."""
    door_lock_id: Optional[str] = None
    """The ID of the door lock in the environment, if applicable. """


class DataExhausted(RuntimeError):
    """Raised when the folder data source has no more files and exit-on-exhaustion is configured."""


class DiscoverAutoAtomDataReplayConfig(AutoAtomDataReplayConfig):
    """Configuration for discovering the demonstration data"""

    redis_cfg: Optional[RedisConfig] = None
    """Redis connection configuration. Mutually exclusive with `data_dir`."""
    data_dir: Optional[Path] = None
    """Directory to read .mcap files from. Mutually exclusive with `redis_cfg`. Each file is consumed at most once per run, in sorted-name order."""
    data_dir_on_exhausted: Literal["block", "exit"] = "block"
    """Behavior when `data_dir` has no remaining files: 'block' polls for new files, 'exit' raises DataExhausted."""
    data_dir_poll_interval_s: float = 1.0
    """Seconds between directory scans when blocking on an empty/exhausted `data_dir`."""
    max_episodes: NonNegativeInt = 0
    """Maximum number of episodes to save before waiting for new data (default: 0, meaning no limit)"""
    reorganized_dir: Optional[Path] = None
    """Optional directory to save reorganized demonstration data. Missing output directories are created automatically."""

    @model_validator(mode="after")
    def _validate_data_source(self):
        if self.redis_cfg is None and self.data_dir is None:
            raise ValueError(
                "At least one of `redis_cfg` or `data_dir` must be set on DiscoverAutoAtomDataReplayConfig."
            )
        return self

    def model_post_init(self, context):
        self.replay.load_on_initialize = False


class DiscoverAutoAtomDataReplayManager(AutoAtomDataReplayManager):
    """Manager for discovering demonstration data from Redis Pub/Sub or Stream groups."""

    def __init__(self, config: DiscoverAutoAtomDataReplayConfig):
        self.config = config
        self._client = None
        self._pubsub = None
        self._stream_group_name = None
        self._stream_consumer_name = None
        self._current_message = None
        self._door_lock_id = ""
        self._consumed_paths: set[str] = set()
        self._recorded_names: set[str] = set()
        self._reorganized_message_id: Optional[int] = None

    _CONSUMED_RECORD_FILENAME = ".consumed.json"

    def on_configure(self):
        config = self.config
        if self._use_folder:
            if config.redis_cfg is not None:
                self.get_logger().info(
                    f"`data_dir` is set ({config.data_dir}); ignoring `redis_cfg`."
                )
            self._load_recorded_names()
        else:
            redis_cfg = config.redis_cfg
            self._connect_and_subscribe(
                redis_cfg.host, redis_cfg.port, redis_cfg.channel
            )
        # set initial demo path
        configured = super().on_configure()
        self._update_data_path()
        data_roots = {fsm.dataset_config.absolute_directory.parent for fsm in self.fsms}
        if len(data_roots) != 1:
            raise ValueError(
                f"Expected all FSMs to use the same data root, but found: {data_roots}"
            )
        self._data_root = data_roots.pop()
        if configured and not config.max_episodes:
            self._ack_current_message()
        return configured

    @property
    def _use_folder(self) -> bool:
        return self.config.data_dir is not None

    @property
    def _use_stream_group(self) -> bool:
        return not self._use_folder and self.config.redis_cfg.mode == "stream_group"

    def _connect_and_subscribe(self, host: str, port: int, channel: str) -> None:
        retry_interval_s = 1.0
        while True:
            try:
                self.get_logger().info(f"Connecting to Redis at {host}:{port}...")
                self._client = redis.Redis(
                    host=host,
                    port=port,
                    decode_responses=True,
                    socket_timeout=None,
                    socket_connect_timeout=None,
                )
                self._client.ping()
                self.get_logger().info("Connected")
                if self._use_stream_group:
                    self._setup_stream_group()
                elif self.config.redis_cfg.message_buffer:
                    self._pubsub = self._client.pubsub()
                    self._pubsub.subscribe(channel)
                return
            except (RedisConnectionError, TimeoutError) as exc:
                self.get_logger().warning(
                    f"Redis unavailable at {host}:{port}: {exc}. "
                    f"Retrying in {retry_interval_s:.1f}s..."
                )
                if self._pubsub:
                    self._pubsub.close()
                    self._pubsub = None
                if self._client:
                    self._client.close()
                    self._client = None
                time.sleep(retry_interval_s)

    def _setup_stream_group(self) -> None:
        redis_cfg = self.config.redis_cfg
        self._stream_group_name = redis_cfg.group_name or self._default_group_name()
        self._stream_consumer_name = (
            redis_cfg.consumer_name or self._default_consumer_name()
        )
        try:
            self._client.xgroup_create(
                redis_cfg.stream_key,
                self._stream_group_name,
                id=redis_cfg.group_start_id,
                mkstream=True,
            )
            self.get_logger().info(
                "Created Redis Stream group "
                f"[{self._stream_group_name}] on [{redis_cfg.stream_key}]"
            )
        except ResponseError as exc:
            if "BUSYGROUP" in str(exc):
                self.get_logger().info(
                    f"Redis Stream group already exists: [{self._stream_group_name}]"
                )
            else:
                raise
        self.get_logger().info(
            "Using Redis Stream consumer "
            f"[{self._stream_consumer_name}] in group "
            f"[{self._stream_group_name}] on [{redis_cfg.stream_key}]"
        )

    def _default_group_name(self) -> str:
        process_name = getproctitle().strip()
        if not process_name:
            process_name = str(os.getpid())
        return f"group:auto_atom:{process_name}"

    def _default_consumer_name(self) -> str:
        process_name = getproctitle().strip()
        if not process_name:
            process_name = str(os.getpid())
        return f"consumer:auto_atom:{socket.gethostname()}:{process_name}"

    def _read_pubsub_message(self, pubsub) -> RedisFilePathMessage:
        for message in pubsub.listen():
            if message["type"] != "message":
                continue
            file_path = str(message["data"]).strip()
            self.get_logger().info(f"<- Received file path: {file_path}")
            return RedisFilePathMessage(file_path=file_path)

    def _read_stream_group_message(self) -> RedisFilePathMessage:
        redis_cfg = self.config.redis_cfg
        while True:
            messages = self._client.xreadgroup(
                groupname=self._stream_group_name,
                consumername=self._stream_consumer_name,
                # NOTE: streams={key: ">"} 中的 ">" 表示只读取该 consumer 尚未投递过的新消息;若改成具体 ID,则会读 pending list 中的历史消息(用于崩溃恢复场景)
                streams={redis_cfg.stream_key: ">"},
                count=max(1, redis_cfg.read_count),
                block=redis_cfg.block_ms,
            )
            if not messages:
                continue
            stream_name, msg_list = messages[0]
            for msg_id, data in msg_list:
                data: dict
                file_path = data.get(self.config.redis_cfg.channel)
                door_lock_id = data.get("door_lock_id")
                if not file_path and not door_lock_id:
                    self.get_logger().warning(
                        "Received Redis Stream message without a usable file path or door lock ID: "
                        f"id={msg_id}, data={data}. Leaving it pending."
                    )
                    continue
                episode_id = data.get("sample_id")
                output_dir = data.get("output_dir")
                self.get_logger().info(
                    f"<- Received file path from [{stream_name}] {msg_id}: {file_path} -> {output_dir}"
                )
                return RedisFilePathMessage(
                    file_path=file_path,
                    ack_id=msg_id,
                    episode_id=episode_id,
                    output_dir=output_dir,
                    door_lock_id=door_lock_id,
                )

    def _record_path(self) -> Path:
        return self.config.data_dir / self._CONSUMED_RECORD_FILENAME

    def _load_recorded_names(self) -> None:
        record_path = self._record_path()
        if not record_path.exists():
            return
        try:
            with record_path.open() as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            self.get_logger().warning(
                f"Failed to read consumed record at {record_path}: {e}. Starting fresh."
            )
            return
        if isinstance(data, list):
            self._recorded_names = {str(name) for name in data}
            self.get_logger().info(
                f"Loaded {len(self._recorded_names)} recorded entries from {record_path}"
            )
        else:
            self.get_logger().warning(
                f"Consumed record at {record_path} is not a JSON list; ignoring."
            )

    def _persist_recorded_names(self) -> None:
        record_path = self._record_path()
        tmp_path = record_path.with_suffix(record_path.suffix + ".tmp")
        try:
            record_path.parent.mkdir(parents=True, exist_ok=True)
            with tmp_path.open("w") as f:
                json.dump(sorted(self._recorded_names), f, indent=2)
            tmp_path.replace(record_path)
        except OSError as e:
            self.get_logger().warning(
                f"Failed to persist consumed record at {record_path}: {e}"
            )
            try:
                tmp_path.unlink(missing_ok=True)
            except OSError:
                pass

    def _read_folder_message(self) -> RedisFilePathMessage:
        data_dir = self.config.data_dir
        poll_interval_s = max(self.config.data_dir_poll_interval_s, 0.0)
        announced_empty = False
        while True:
            available = sorted(
                p
                for p in data_dir.glob("*.mcap")
                if p.is_file() and str(p.resolve()) not in self._consumed_paths
            )
            unrecorded = [p for p in available if p.name not in self._recorded_names]
            pool = unrecorded if unrecorded else available
            if pool:
                picked = pool[0]
                resolved = str(picked.resolve())
                self._consumed_paths.add(resolved)
                is_new = picked.name not in self._recorded_names
                if is_new:
                    self._recorded_names.add(picked.name)
                    self._persist_recorded_names()
                self.get_logger().info(
                    f"<- Picked file from {data_dir}: {resolved} "
                    f"({'unrecorded' if is_new else 'replaying recorded'}; "
                    f"{len(self._consumed_paths)} consumed this run)"
                )
                return RedisFilePathMessage(
                    file_path=resolved,
                    output_dir=self.config.reorganized_dir / picked.stem
                    if self.config.reorganized_dir
                    else None,
                )
            if self.config.data_dir_on_exhausted == "exit":
                raise DataExhausted(
                    f"data_dir {data_dir} has no more unconsumed .mcap files"
                )
            if not announced_empty:
                self.get_logger().info(
                    f"No unconsumed .mcap files in {data_dir}, polling every "
                    f"{poll_interval_s:.1f}s..."
                )
                announced_empty = True
            time.sleep(poll_interval_s)

    def _waiting_for_data_path_once(self) -> RedisFilePathMessage:
        if self._use_folder:
            return self._read_folder_message()
        if self._use_stream_group:
            return self._read_stream_group_message()
        channel = self.config.redis_cfg.channel
        if self._pubsub:
            return self._read_pubsub_message(self._pubsub)
        pubsub = self._client.pubsub()
        pubsub.subscribe(channel)
        try:
            return self._read_pubsub_message(pubsub)
        finally:
            pubsub.unsubscribe()
            pubsub.close()

    def _wait_for_valid_data_path(self) -> RedisFilePathMessage:
        self.get_logger().info("Waiting for demonstration data file path...")
        while True:
            message = self._waiting_for_data_path_once()
            file_path = message.file_path
            door_lock_id = message.door_lock_id
            if door_lock_id and door_lock_id != self._door_lock_id:
                # update the knob and lock
                env: BatchedGSUnifiedMujocoEnv = self._runner.get_env()
                body_gaussians = env.config.gaussian_render.body_gaussians
                handle_gs_frame = Path(body_gaussians["handle_gs_frame"])
                lock_gs_frame = Path(body_gaussians["lock_gs_frame"])
                candidate_ids = [door_lock_id]
                stripped_id = door_lock_id.lstrip("0")
                if stripped_id and stripped_id != door_lock_id:
                    candidate_ids.append(stripped_id)
                new_handle = None
                new_lock = None
                attempted = []
                for cid in candidate_ids:
                    cand_handle = handle_gs_frame.with_stem(f"real_knob{cid}")
                    cand_lock = lock_gs_frame.with_stem(f"real_lock{cid}")
                    attempted.append((cid, cand_handle, cand_lock))
                    if cand_handle.exists() and cand_lock.exists():
                        new_handle = cand_handle
                        new_lock = cand_lock
                        break
                if new_handle is None or new_lock is None:
                    missing = [
                        str(p)
                        for _, h, lk in attempted
                        for p in (h, lk)
                        if not p.exists()
                    ]
                    self.get_logger().warning(
                        f"Target door lock ply files not found for id={door_lock_id} "
                        f"(tried {[cid for cid, _, _ in attempted]}): {missing}. "
                        f"Keeping current door lock id={self._door_lock_id!r}."
                    )
                    if not file_path:
                        continue
                else:
                    body_gaussians.update(
                        {
                            "handle_gs_frame": str(new_handle),
                            "lock_gs_frame": str(new_lock),
                        }
                    )
                    self._door_lock_id = door_lock_id
                    self.get_logger().info(
                        f"Updating door lock ID to {door_lock_id} based on Redis message. "
                        f"Waiting for next data with matching door lock ID..."
                    )
                    env.update_gaussian_render(env.config.gaussian_render)
                    # prepare resetting
                    if not file_path:
                        env.reset()
                        self.get_logger().info("Waiting for next data...")
                        continue
            if file_path:
                path = Path(file_path).expanduser()
                if path.exists():
                    message.file_path = str(path.resolve())
                    self._current_message = message
                    if message.output_dir:
                        Path(message.output_dir).mkdir(parents=True, exist_ok=True)
                    return message
                self.get_logger().warning(
                    f"Received file path does not exist: {path.resolve(strict=False)}. "
                    "Waiting for next data..."
                )
            else:
                self.get_logger().warning(
                    "Received empty file path. Waiting for next data..."
                )

    def _ack_message(self, message: RedisFilePathMessage) -> bool:
        if not message.ack_id:
            return True
        acknowledged = self._client.xack(
            self.config.redis_cfg.stream_key,
            self._stream_group_name,
            message.ack_id,
        )
        if acknowledged:
            self.get_logger().info(f"ACKed Redis Stream message: {message.ack_id}")
            return True
        else:
            self.get_logger().warning(
                f"Failed to ACK Redis Stream message: {message.ack_id}"
            )
            return False

    def _ack_current_message(self) -> bool:
        if not self._current_message:
            return True
        if self._ack_message(self._current_message):
            self._current_message = None
            return True
        return False

    def _update_data_path(self):
        while True:
            next_message = self._wait_for_valid_data_path()
            if self._runner.set_demo_path(mcap_path=next_message.file_path, load=True):
                break

    def _reorganize_current_message(self):
        config = self.config
        max_episodes = config.max_episodes
        output_dir = self._current_message.output_dir if self._current_message else None
        if output_dir:
            out_dir = Path(output_dir)
            reorg_dir = out_dir.parent
            episode_id = out_dir.name
        else:
            reorg_dir = config.reorganized_dir
            episode_id = ""
        if not reorg_dir:
            return
        if max_episodes != 1:
            raise NotImplementedError(
                "Reorganizing data by episode is only supported when max_episodes=1"
            )
        # NOTE: If a data replay fails, a retry should theoretically also fail, so the next one should proceed immediately. Therefore, different environments may have different output episodes corresponding to the same input episode_id. Currently, different environments theoretically correspond to the same physical process, only the rendering is different. Therefore, theoretically, there should not be a situation where some succeed and some fail.

        # Process each FSM separately to avoid mixing data from different tasks in multirun mode
        for fsm in self.fsms:
            cur_episode = fsm.sample_info.episode - 1
            episode_args = [str(cur_episode)]
            if episode_id:
                episode_args.append(episode_id)

            # Extract task name from the FSM's data directory
            # e.g., /data/home/haizhou/airdc/data/aao_data/door_0_0 -> door_0_0
            fsm_data_dir = fsm.dataset_config.absolute_directory
            task_name = (
                fsm_data_dir.name
                if isinstance(fsm_data_dir, Path)
                else Path(fsm_data_dir).name
            )

            reorganize_data_by_episode(
                ReorganizeDataByEpisodeConfig(
                    source_root=self._data_root,
                    output_root=reorg_dir,
                    overwrite=bool(episode_id),
                    file_type="symlink",
                    episode=episode_args,
                    task_filter=[task_name],
                )
            )

    def update(self):
        # if max_episodes and self._total_saved >= max_episodes:
        if self._cur_done_count > 0:
            if self._cur_done_count != len(self.fsms):
                self.get_logger().warning(
                    f"Expected all FSMs to be done at the same time, but found "
                    f"{self._cur_done_count} done FSMs out of {len(self.fsms)}."
                )
                # make all FSMs state to active to trigger reset in super
                for fsm in self.fsms:
                    if fsm.get_state() is State.sampling:
                        fsm.act(DAction.abandon)
            self._cur_done_count = 0
            self.get_logger().info(
                f"Total saved demonstrations: {self._total_saved}. Waiting for next data..."
            )
            self._reorganize_current_message()
            self._reorganized_message_id = id(self._current_message)
            # self._runner.reset()
            # Treat max_episodes as the completion boundary for the current Redis task.
            if not self._ack_current_message():
                return True
            self._total_saved = 0
            self._update_data_path()
        return super().update()

    def on_shutdown(self):
        # Catch-up reorganize when the main loop terminates before the next update()
        # tick (e.g., sample_limit.rounds caps the run right after a save).
        if (
            self._total_saved > 0
            and self._current_message is not None
            and id(self._current_message)
            != getattr(self, "_reorganized_message_id", None)
        ):
            self.get_logger().info(
                "Running pending reorganize on shutdown for current message."
            )
            try:
                self._reorganize_current_message()
            except Exception as exc:
                self.get_logger().error(f"Pending reorganize on shutdown failed: {exc}")
        if self._pubsub:
            self._pubsub.unsubscribe()
            self._pubsub.close()
        if self._client:
            self._client.close()
        return super().on_shutdown()
