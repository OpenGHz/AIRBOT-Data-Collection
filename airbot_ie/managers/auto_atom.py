import os
import socket
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Optional, Union

import redis
from airdc.managers.auto_atom import (
    AutoAtomDataReplayConfig,
    AutoAtomDataReplayManager,
    DAction,
    State,
)
from pydantic import BaseModel, NonNegativeInt, ConfigDict
from redis.exceptions import (
    ConnectionError as RedisConnectionError,
    ResponseError,
    TimeoutError,
)
from setproctitle import getproctitle


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
    stream_key: str = "stream:file_path"
    """Redis Stream key when mode=stream_group (default: stream:file_path)"""
    group_name: Optional[str] = None
    """Redis Stream consumer group name when mode=stream_group. None means one group per process title (group:auto_atom:<process_name>)"""
    consumer_name: Optional[str] = None
    """Redis Stream consumer name when mode=stream_group. Defaults to hostname-pid"""
    group_start_id: Union[str, NonNegativeInt] = 0
    """Start ID used when creating a new consumer group (default: 0)"""
    read_count: NonNegativeInt = 1
    """Maximum number of messages read per XREADGROUP call (default: 1)"""
    block_ms: NonNegativeInt = 2000
    """Blocking timeout in milliseconds for XREADGROUP (default: 2000)"""


@dataclass(frozen=True)
class RedisFilePathMessage:
    """A normalized file-path message received from Redis."""

    file_path: str
    ack_id: Optional[str] = None


class DiscoverAutoAtomDataReplayConfig(AutoAtomDataReplayConfig):
    """Configuration for discovering the demonstration data"""

    redis_cfg: RedisConfig = RedisConfig()
    """Redis connection configuration"""
    max_episodes: NonNegativeInt = 0
    """Maximum number of episodes to save before waiting for new data (default: 0, meaning no limit)"""


class DiscoverAutoAtomDataReplayManager(AutoAtomDataReplayManager):
    """Manager for discovering demonstration data from Redis Pub/Sub or Stream groups."""

    def __init__(self, config: DiscoverAutoAtomDataReplayConfig):
        self.config = config
        self._client = None
        self._pubsub = None
        self._stream_group_name = None
        self._stream_consumer_name = None
        self._current_message = None

    def on_configure(self):
        redis_cfg = self.config.redis_cfg
        self._connect_and_subscribe(redis_cfg.host, redis_cfg.port, redis_cfg.channel)
        initial_message = self._wait_for_valid_data_path()
        self.config.replay.mcap_path = initial_message.file_path
        self._current_message = initial_message
        configured = super().on_configure()
        if configured and not self.config.max_episodes:
            self._ack_current_message()
        return configured

    @property
    def _use_stream_group(self) -> bool:
        return self.config.redis_cfg.mode == "stream_group"

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
            redis_cfg.consumer_name or f"auto-atom-{socket.gethostname()}-{os.getpid()}"
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

    def _read_pubsub_message(self, pubsub) -> RedisFilePathMessage:
        for message in pubsub.listen():
            if message["type"] != "message":
                continue
            file_path = str(message["data"]).strip()
            self.get_logger().info(f"<- Received file path: {file_path}")
            return RedisFilePathMessage(file_path=file_path)

    def _extract_stream_file_path(self, data: dict) -> str | None:
        if "file_path" in data:
            return str(data["file_path"]).strip()
        if len(data) == 1:
            return str(next(iter(data.values()))).strip()
        return None

    def _read_stream_group_message(self) -> RedisFilePathMessage:
        redis_cfg = self.config.redis_cfg
        while True:
            messages = self._client.xreadgroup(
                groupname=self._stream_group_name,
                consumername=self._stream_consumer_name,
                streams={redis_cfg.stream_key: ">"},
                count=max(1, redis_cfg.read_count),
                block=redis_cfg.block_ms,
            )
            if not messages:
                continue
            stream_name, msg_list = messages[0]
            for msg_id, data in msg_list:
                file_path = self._extract_stream_file_path(data)
                if not file_path:
                    self.get_logger().warning(
                        "Received Redis Stream message without a usable file path: "
                        f"id={msg_id}, data={data}. Leaving it pending."
                    )
                    continue
                self.get_logger().info(
                    f"<- Received file path from [{stream_name}] {msg_id}: {file_path}"
                )
                return RedisFilePathMessage(file_path=file_path, ack_id=msg_id)

    def _waiting_for_data_path_once(self) -> RedisFilePathMessage:
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
            path = Path(message.file_path).expanduser()
            if path.exists():
                return RedisFilePathMessage(
                    file_path=str(path.resolve()),
                    ack_id=message.ack_id,
                )
            self.get_logger().warning(
                f"Received file path does not exist: {path.resolve(strict=False)}. "
                "Waiting for next data..."
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

    def update(self):
        max_episodes = self.config.max_episodes
        if max_episodes and self._total_saved >= max_episodes:
            self.get_logger().info(
                f"Total saved demonstrations: {self._total_saved}. Waiting for next data..."
            )
            # make all FSMs state to active to trigger reset in super
            for fsm in self.fsms:
                if fsm.get_state() is State.sampling:
                    fsm.act(DAction.abandon)
            # self._runner.reset()
            # Treat max_episodes as the completion boundary for the current Redis task.
            if not self._ack_current_message():
                return True
            self._total_saved = 0
            next_message = self._wait_for_valid_data_path()
            self.config.replay.mcap_path = next_message.file_path
            self._runner.set_demo_path(mcap_path=next_message.file_path)
            self._current_message = next_message
        return super().update()

    def on_shutdown(self):
        if self._pubsub:
            self._pubsub.unsubscribe()
            self._pubsub.close()
        if self._client:
            self._client.close()
        return super().on_shutdown()
