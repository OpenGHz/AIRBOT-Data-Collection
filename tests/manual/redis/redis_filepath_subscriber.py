"""Redis Pub/Sub client: subscribe to a channel and receive file paths.

Usage:
    # Start the subscriber (blocking):
    python examples/redis_filepath_subscriber.py

    # Publish a file path from another terminal:
    redis-cli PUBLISH file_paths "/path/to/some/file.npz"

Options:
    --host          Redis host (default: localhost)
    --port          Redis port (default: 6379)
    --channel       Channel name to subscribe (default: file_paths)
    --callback      What to do with received paths: "print" or "load" (default: print)
"""

from __future__ import annotations

import argparse
import signal
import sys
import redis
from pathlib import Path


def on_file_path_received(path: Path) -> None:
    """Process a received file path. Customize this for your use case."""
    if not path.exists():
        print(f"[WARN] File does not exist: {path}")
        return
    print(f"[OK] Received valid file: {path} ({path.stat().st_size} bytes)")


def subscribe(host: str, port: int, channel: str) -> None:
    r = redis.Redis(host=host, port=port, decode_responses=True)
    r.ping()
    print(f"Connected to Redis at {host}:{port}")

    pubsub = r.pubsub()
    pubsub.subscribe(channel)
    print(f"Subscribed to channel: {channel}")
    print("Waiting for file paths... (Ctrl+C to quit)\n")

    # Graceful shutdown on SIGINT/SIGTERM
    def _shutdown(sig, frame):
        print("\nShutting down...")
        pubsub.unsubscribe()
        pubsub.close()
        r.close()
        sys.exit(0)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    for message in pubsub.listen():
        if message["type"] != "message":
            continue
        file_path = message["data"].strip()
        print(f"<- {file_path}")
        on_file_path_received(Path(file_path))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="localhost", help="Redis host")
    parser.add_argument("--port", type=int, default=6379, help="Redis port")
    parser.add_argument("--channel", default="file_paths", help="Pub/Sub channel name")
    args = parser.parse_args()

    subscribe(args.host, args.port, args.channel)


if __name__ == "__main__":
    main()
