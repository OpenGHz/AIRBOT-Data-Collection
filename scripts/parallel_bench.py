#!/usr/bin/env python3
"""Run multiple airdc processes in parallel and report Average update freq.

Usage:
    python parallel_bench.py -n 4 --gpus 0,1
    python parallel_bench.py -n 8 --gpus 0,1,2,3
    python parallel_bench.py -n 6 --gpus 2,3  # 3 workers on GPU 2, 3 workers on GPU 3

Press Ctrl+C to stop all workers. Each worker will print its summary
(including Average update freq) before exiting. The script then extracts
and aggregates the frequencies.
"""

from __future__ import annotations

import argparse
import os
import re
import signal
import shlex
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from statistics import mean, stdev


DEFAULT_COMMAND = (
    "airdc --name aao_config"
    " dataset.directory=aao_data/door"
    " managers/auto_atom/task=cup_on_coaster_gs"
    " batch_size=1"
    " samplers=mock"
)

FREQ_PATTERN = re.compile(r"Average update freq.*?(\d+(?:\.\d+)?)\s*Hz")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run N airdc processes in parallel and report average update frequency."
    )
    parser.add_argument(
        "-n",
        "--num-workers",
        type=int,
        required=True,
        help="Number of parallel airdc processes to launch.",
    )
    parser.add_argument(
        "--gpus",
        type=str,
        default=None,
        help="Comma-separated GPU IDs to distribute workers across, e.g. '0,1,2'. "
        "Workers are assigned round-robin. If not set, inherits the current "
        "CUDA_VISIBLE_DEVICES environment variable.",
    )
    parser.add_argument(
        "--command",
        type=str,
        default=DEFAULT_COMMAND,
        help=f"The airdc command to run (default: {DEFAULT_COMMAND!r}).",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="outputs/parallel_bench",
        help="Directory for log files (default: outputs/parallel_bench).",
    )
    parser.add_argument(
        "--shutdown-timeout",
        type=float,
        default=30.0,
        help="Seconds to wait for each worker to exit after SIGINT (default: 30).",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    n = args.num_workers
    cmd_tokens = shlex.split(args.command)

    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_dir = Path(args.output_dir) / f"n{n}_{run_id}"
    log_dir.mkdir(parents=True, exist_ok=True)

    # Parse GPU list
    gpu_ids: list[str] | None = None
    if args.gpus is not None:
        gpu_ids = [g.strip() for g in args.gpus.split(",") if g.strip()]
        if not gpu_ids:
            print("Error: --gpus requires at least one GPU ID.", file=sys.stderr)
            return 1

    print(f"Launching {n} workers...")
    print(f"Command: {args.command}")
    if gpu_ids:
        print(f"GPUs:    {','.join(gpu_ids)} ({len(gpu_ids)} devices, round-robin)")
    print(f"Logs:    {log_dir.resolve()}")
    print("Press Ctrl+C to stop all workers.\n")

    # Spawn workers
    workers: list[dict] = []
    for i in range(n):
        log_path = log_dir / f"worker_{i}.log"
        log_file = log_path.open("w", encoding="utf-8")

        env = os.environ.copy()
        if gpu_ids:
            assigned_gpu = gpu_ids[i % len(gpu_ids)]
            env["CUDA_VISIBLE_DEVICES"] = assigned_gpu
        else:
            assigned_gpu = env.get("CUDA_VISIBLE_DEVICES", "all")

        proc = subprocess.Popen(
            cmd_tokens,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            text=True,
            env=env,
            # Isolate children from terminal SIGINT; we send it explicitly.
            preexec_fn=os.setpgrp,
        )
        workers.append(
            {
                "proc": proc,
                "log_file": log_file,
                "log_path": log_path,
                "id": i,
                "gpu": assigned_gpu,
            }
        )
        print(f"  Worker {i}: PID {proc.pid}, GPU {assigned_gpu}")

    print()

    # Wait for Ctrl+C
    interrupted = False
    original_sigint = signal.getsignal(signal.SIGINT)

    def on_sigint(signum, frame):
        nonlocal interrupted
        if interrupted:
            # Second Ctrl+C: force kill
            print("\nForce killing all workers...")
            for w in workers:
                try:
                    w["proc"].kill()
                except OSError:
                    pass
            sys.exit(1)
        interrupted = True
        print("\nSIGINT received. Stopping workers gracefully...")

    signal.signal(signal.SIGINT, on_sigint)

    # Poll until interrupted or all workers exit on their own
    try:
        while not interrupted:
            if all(w["proc"].poll() is not None for w in workers):
                print("All workers exited on their own.")
                break
            time.sleep(0.5)
    except Exception:
        interrupted = True

    # Send SIGINT to each worker and wait
    for w in workers:
        if w["proc"].poll() is None:
            try:
                w["proc"].send_signal(signal.SIGINT)
            except OSError:
                pass

    timeout = args.shutdown_timeout
    deadline = time.monotonic() + timeout
    for w in workers:
        remaining = max(0, deadline - time.monotonic())
        try:
            w["proc"].wait(timeout=remaining)
        except subprocess.TimeoutExpired:
            print(f"  Worker {w['id']}: timed out, killing...")
            w["proc"].kill()
            w["proc"].wait()

    # Close log file handles
    for w in workers:
        w["log_file"].close()

    # Restore signal handler
    signal.signal(signal.SIGINT, original_sigint)

    # Extract frequencies
    print("\n" + "=" * 60)
    print("Results")
    print("=" * 60)

    freqs: list[float] = []
    for w in workers:
        text = w["log_path"].read_text(encoding="utf-8", errors="replace")
        match = FREQ_PATTERN.search(text)
        if match:
            freq = float(match.group(1))
            freqs.append(freq)
            print(f"  Worker {w['id']} (GPU {w['gpu']}): {freq:.4f} Hz")
        else:
            print(f"  Worker {w['id']} (GPU {w['gpu']}): <no frequency found>")

    print()
    if not freqs:
        print("No frequencies extracted. Check the log files for errors:")
        for w in workers:
            print(f"  {w['log_path'].resolve()}")
        return 1

    n_ok = len(freqs)
    avg = mean(freqs)
    sd = stdev(freqs) if n_ok > 1 else 0.0
    total = sum(freqs)

    print(f"Workers with data: {n_ok}/{n}")
    print(
        f"Per-worker freq:   mean={avg:.4f} Hz, min={min(freqs):.4f} Hz, max={max(freqs):.4f} Hz, std={sd:.4f} Hz"
    )
    print(f"Aggregate throughput (sum): {total:.4f} Hz")
    print(f"\nLog directory: {log_dir.resolve()}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
