import time
import redis
from airdc.managers.auto_atom import (
    AutoAtomDataReplayConfig,
    AutoAtomDataReplayManager,
    DAction,
)
from pydantic import BaseModel, NonNegativeInt
from redis.exceptions import ConnectionError as RedisConnectionError, TimeoutError
from pathlib import Path


class RedisConfig(BaseModel, frozen=True):
    """Configuration for Redis connection."""

    host: str = "localhost"
    """Redis host address (default: localhost)"""
    port: int = 6379
    """Redis port number (default: 6379)"""
    channel: str = "file_path"
    """Redis Pub/Sub channel name (default: file_path)"""
    message_buffer: bool = True
    """Whether to buffer messages in Redis Pub/Sub (default: True)"""


class DiscoverAutoAtomDataReplayConfig(AutoAtomDataReplayConfig):
    """Configuration for discovering the demonstration data"""

    redis_cfg: RedisConfig = RedisConfig()
    """Redis connection configuration"""
    max_episodes: NonNegativeInt = 2
    """Maximum number of episodes to save before waiting for new data (default: 2)"""


class DiscoverAutoAtomDataReplayManager(AutoAtomDataReplayManager):
    """Manager for discovering the demonstration data from Redis Pub/Sub"""

    def __init__(self, config: DiscoverAutoAtomDataReplayConfig):
        self.config = config
        self._client = None
        self._pubsub = None

    def on_configure(self):
        redis_cfg = self.config.redis_cfg
        self._connect_and_subscribe(redis_cfg.host, redis_cfg.port, redis_cfg.channel)
        self._waiting_for_data_path_once()  # Block until we get the first data path
        return super().on_configure()

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
                if self.config.redis_cfg.message_buffer:
                    self._pubsub = self._client.pubsub()
                    self._pubsub.subscribe(channel)
                return
            except (RedisConnectionError, TimeoutError) as exc:
                self.get_logger().warning(
                    f"Redis unavailable at {host}:{port}: {exc}. "
                    f"Retrying in {retry_interval_s:.1f}s..."
                )
                if self._client:
                    self._client.close()
                    del self._client
                time.sleep(retry_interval_s)

    def _get_message(self, pubsub):
        for message in pubsub.listen():
            if message["type"] != "message":
                continue
            file_path = message["data"].strip()
            self.get_logger().info(f"<- Received file path: {file_path}")
            self.config.replay.mcap_path = file_path
            return file_path

    def _waiting_for_data_path_once(self):
        self.get_logger().info("Waiting for demonstration data file path...")
        channel = self.config.redis_cfg.channel
        pubsub = self._client.pubsub()
        pubsub.subscribe(channel)
        file_path = self._get_message(pubsub)
        pubsub.unsubscribe()
        pubsub.close()
        return file_path

    def update(self):
        if self._total_saved >= self.config.max_episodes:
            self.get_logger().info(
                f"Total saved demonstrations: {self._total_saved}. Waiting for next data..."
            )
            # make all FSMs state to active to trigger reset in super
            for fsm in self.fsms:
                fsm.act(DAction.abandon)
            # self._runner.reset()
            self._total_saved = 0
            # Block until we get the next data path
            while True:
                if self._pubsub:
                    file_path = self._pubsub.get_message(
                        ignore_subscribe_messages=True, timeout=None
                    )
                else:
                    file_path = self._waiting_for_data_path_once()
                path = Path(file_path)
                if path.exists():
                    break
                else:
                    self.get_logger().warning(
                        f"Received file path does not exist: {path.absolute()}. Waiting for next data..."
                    )
            self._runner.set_demo_path(mcap_path=file_path)
        return super().update()

    def on_shutdown(self):
        if self._client:
            self._client.close()
        if self._pubsub:
            self._pubsub.close()
        return super().on_shutdown()
