"""Redis Pub/Sub client: publish file paths to a channel.

Usage:
    # Publish one file path:
    python tests/redis_filepath_publisher.py /path/to/some/file.npz

    # Publish multiple file paths with a delay between each message:
    python tests/redis_filepath_publisher.py /path/a.mcap /path/b.mcap --interval 1.0

Options:
    --host          Redis host (default: localhost)
    --port          Redis port (default: 6379)
    --channel       Channel name to publish to (default: file_paths)
    --no-check      Publish even if the file path does not exist locally
    --interval      Delay in seconds between messages (default: 0.0)
"""

from __future__ import annotations
import argparse
import time
import redis
from pathlib import Path


def normalize_file_paths(file_paths: list[str], check_exists: bool) -> list[Path]:
    """Expand input paths and optionally verify they exist locally."""
    normalized_paths: list[Path] = []
    for raw_path in file_paths:
        path = Path(raw_path).expanduser().resolve(strict=False)
        if check_exists and not path.exists():
            raise FileNotFoundError(f"File does not exist: {path}")
        normalized_paths.append(path)
    return normalized_paths


def publish(
    host: str,
    port: int,
    channel: str,
    file_paths: list[str],
    check_exists: bool,
    interval: float,
) -> None:
    normalized_paths = normalize_file_paths(file_paths, check_exists=check_exists)

    r = redis.Redis(host=host, port=port, decode_responses=True)
    r.ping()
    print(f"Connected to Redis at {host}:{port}")
    print(f"Publishing to channel: {channel}\n")

    for idx, path in enumerate(normalized_paths):
        subscriber_count = r.publish(channel, str(path))
        print(f"-> {path} (delivered to {subscriber_count} subscriber(s))")
        if interval > 0 and idx < len(normalized_paths) - 1:
            time.sleep(interval)

    r.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file_paths", nargs="+", help="File path(s) to publish")
    parser.add_argument("--host", default="localhost", help="Redis host")
    parser.add_argument("--port", type=int, default=6379, help="Redis port")
    parser.add_argument("--channel", default="file_path", help="Pub/Sub channel name")
    parser.add_argument(
        "--no-check",
        action="store_true",
        help="Publish even if the file path does not exist locally",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=0.0,
        help="Delay in seconds between publishing multiple file paths",
    )
    args = parser.parse_args()

    publish(
        host=args.host,
        port=args.port,
        channel=args.channel,
        file_paths=args.file_paths,
        check_exists=not args.no_check,
        interval=args.interval,
    )


if __name__ == "__main__":
    main()
