"""Redis Stream producer: append file paths for stream-group consumers.

Usage:
    # Push one file path into the default stream:
    python tests/test_redis/redis_filepath_stream_producer.py /path/to/demo.mcap

    # Push multiple file paths with a delay between each message:
    python tests/test_redis/redis_filepath_stream_producer.py /path/a.mcap /path/b.mcap --interval 1.0

    # Push without local file existence checks:
    python tests/test_redis/redis_filepath_stream_producer.py /tmp/not-found.mcap --no-check

Options:
    --host          Redis host (default: localhost)
    --port          Redis port (default: 6379)
    --stream-key    Redis Stream key (default: stream:file_path)
    --field-name    Field name used in XADD payload (default: file_path)
    --no-check      Push even if the file path does not exist locally
    --interval      Delay in seconds between multiple messages (default: 0.0)
    --maxlen        Approximate MAXLEN trimming value for XADD (default: disabled)
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

import redis


def normalize_file_paths(file_paths: list[str], check_exists: bool) -> list[Path]:
    """Expand input paths and optionally verify that they exist locally."""
    normalized_paths: list[Path] = []
    for raw_path in file_paths:
        path = Path(raw_path).expanduser().resolve(strict=False)
        if check_exists and not path.exists():
            raise FileNotFoundError(f"File does not exist: {path}")
        normalized_paths.append(path)
    return normalized_paths


def produce(
    host: str,
    port: int,
    stream_key: str,
    field_name: str,
    output_dir: str | None,
    file_paths: list[str],
    check_exists: bool,
    interval: float,
    maxlen: int | None,
) -> None:
    normalized_paths = normalize_file_paths(file_paths, check_exists=check_exists)

    client = redis.Redis(host=host, port=port, decode_responses=True)
    client.ping()
    print(f"Connected to Redis at {host}:{port}")
    print(f"Appending to stream: {stream_key}\n")

    for idx, path in enumerate(normalized_paths):
        payload = {field_name: str(path), "output_dir": output_dir or ""}
        if maxlen is None:
            message_id = client.xadd(stream_key, payload)
        else:
            message_id = client.xadd(
                stream_key, payload, maxlen=maxlen, approximate=True
            )
        print(f"-> {message_id} | {payload}")
        if interval > 0 and idx < len(normalized_paths) - 1:
            time.sleep(interval)

    client.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file_paths", nargs="+", help="File path(s) to push")
    parser.add_argument("--host", default="localhost", help="Redis host")
    parser.add_argument("--port", type=int, default=6379, help="Redis port")
    parser.add_argument(
        "--stream-key",
        default="augment-tasks:7",
        help="Redis Stream key",
    )
    parser.add_argument(
        "--field-name",
        default="file_path",
        help="Payload field name in XADD",
    )
    parser.add_argument(
        "--output-dir",
        default="outputs/records/episode_0",
        help="Optional output directory to include in the message payload",
    )
    parser.add_argument(
        "--no-check",
        action="store_true",
        help="Push even if the file path does not exist locally",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=0.0,
        help="Delay in seconds between pushing multiple messages",
    )
    parser.add_argument(
        "--maxlen",
        type=int,
        default=None,
        help="Approximate MAXLEN trimming value for XADD",
    )
    parser.add_argument(
        "--range",
        type=int,
        nargs=2,
        metavar=("START", "END"),
        help="Optional range of output directories to include in the message payload (e.g. --range 0 10)",
    )
    args = parser.parse_args()

    if args.range:
        start, end = args.range
        output_dirs = [f"outputs/records/episode_{i}" for i in range(start, end)]
    else:
        output_dirs = [args.output_dir]
    for output_dir in output_dirs:
        produce(
            host=args.host,
            port=args.port,
            stream_key=args.stream_key,
            field_name=args.field_name,
            output_dir=output_dir,
            file_paths=args.file_paths,
            check_exists=not args.no_check,
            interval=args.interval,
            maxlen=args.maxlen,
        )
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
