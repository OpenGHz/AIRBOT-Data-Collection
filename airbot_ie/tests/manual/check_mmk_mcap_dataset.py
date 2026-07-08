import os
import tempfile
import logging
import cv2
import numpy as np
import random
import re
import subprocess
import json
import time
from pathlib import Path
from typing import List, Dict, Tuple
from mcap.reader import make_reader
from tqdm import tqdm

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Define video problem types to detect
VIDEO_PROBLEMS = [
    "co located POCs unavailable",
    "reference picture missing during reorder",
    "Missing reference picture, default is",
]

# Topic configurations
MCAP_STATE_TOPICS = [
    "/mmk/observation/left_arm/joint_state/position",
    "/mmk/observation/left_arm_eef/joint_state/position",
    "/mmk/observation/right_arm/joint_state/position",
    "/mmk/observation/right_arm_eef/joint_state/position",
    "/mmk/observation/head/joint_state/position",
    "/mmk/observation/spine/joint_state/position",
]
MCAP_ACTION_TOPICS = [
    "/mmk/action/left_arm/joint_state/position",
    "/mmk/action/left_arm_eef/joint_state/position",
    "/mmk/action/right_arm/joint_state/position",
    "/mmk/action/right_arm_eef/joint_state/position",
    "/mmk/action/head/joint_state/position",
    "/mmk/action/spine/joint_state/position",
]
MCAP_CAMERA_NAMES = [
    "/mmk/head_camera/color/image_raw",
    "/mmk/left_camera/color/image_raw",
    "/mmk/right_camera/color/image_raw",
]

# Frame rate thresholds
FPS_TARGET = 20
FPS_MIN = 18
FPS_MAX = 22

# Freeze detection thresholds
MSE_THRESHOLD = 5.0
LOW_VARIANCE_THRESHOLD = 10
STUCK_DURATION_THRESHOLD = 2.0


def calculate_frame_difference(prev: np.ndarray, curr: np.ndarray) -> float:
    """Optimization: Use faster grayscale conversion and difference calculation"""
    if prev is None or curr is None:
        return 0.0

    if prev.shape != curr.shape:
        # Use faster interpolation method
        prev = cv2.resize(
            prev, (curr.shape[1], curr.shape[0]), interpolation=cv2.INTER_LINEAR
        )

    # Calculate difference directly to avoid extra conversions
    diff = cv2.absdiff(prev, curr)
    diff_gray = cv2.cvtColor(diff, cv2.COLOR_BGR2GRAY)
    mse = np.mean(diff_gray.astype(np.float32))
    return mse


def check_video_stuck(
    cap: cv2.VideoCapture, min_frames: int
) -> Tuple[List[float], int]:
    """
    Check if video has freezes (frames not moving for extended periods)
    Returns: MSE for each detected segment and freeze frame count
    """
    stuck_frames = []  # Record MSE of frozen frames
    stuck_frames_count = 0  # Count of frozen frames
    consecutive_static_frames = 0  # Count of consecutive static frames
    prev_frame = None
    frame_idx = 0

    # Reset video stream to start
    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)

    # Number of frames to check (avoid very short videos)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    frames_to_check = min(min_frames, total_frames)

    # Frame sampling step (adjust sample interval based on frame rate)
    fps = cap.get(cv2.CAP_PROP_FPS)
    step = max(1, int(fps * 0.1))  # Sample once every 0.1 seconds

    for frame_idx in range(0, total_frames, step):
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
        ret, frame = cap.read()
        if not ret:
            continue

        if prev_frame is not None:
            mse = calculate_frame_difference(prev_frame, frame)

            # If frame difference is small, might be static or frozen
            if mse < MSE_THRESHOLD:
                consecutive_static_frames += step
                stuck_frames_count += step
                stuck_frames.append(mse)
            else:
                consecutive_static_frames = 0

            # Detect continuous static frames exceeding threshold
            if consecutive_static_frames / fps >= STUCK_DURATION_THRESHOLD:
                return stuck_frames, stuck_frames_count

        prev_frame = frame

    return stuck_frames, stuck_frames_count


def run_ffmpeg_check(video_path: str) -> Dict[str, any]:
    """
    Check video file using FFmpeg, capture all output and analyze issues
    Returns: All detected issues
    """
    result = {
        "warnings": [],  # List of raw warning messages
        "problem_details": {},  # Detailed information for each problem
        "problem_count": 0,  # Total number of problems
        "has_errors": False,  # Whether there are critical errors
    }

    # Initialize problem counters
    for problem in VIDEO_PROBLEMS:
        result["problem_details"][problem] = {"count": 0, "examples": []}

    try:
        # Run FFmpeg command to check video
        cmd = [
            "ffmpeg",
            "-v",
            "error",  # Only output error messages
            "-i",
            video_path,
            "-f",
            "null",  # Output to null device
            "-",
        ]

        # Use timeout mechanism (60 seconds)
        process = subprocess.run(
            cmd,
            stderr=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
            timeout=60,  # 60-second timeout
        )

        # Process warning output
        if process.stderr:
            # Collect all warning lines
            warnings = process.stderr.strip().split("\n")
            result["warnings"] = warnings

            # Parse specific problem types
            for warning in warnings:
                # Check for critical errors
                if "error while decoding MB" in warning:
                    result["has_errors"] = True

                # Match specific problem types
                for problem in VIDEO_PROBLEMS:
                    if problem in warning:
                        # Update problem count
                        result["problem_details"][problem]["count"] += 1
                        result["problem_details"][problem]["examples"].append(warning)
                        result["problem_count"] += 1

    except subprocess.TimeoutExpired:
        logger.warning(f"FFmpeg check timed out: {video_path}")
        result["has_errors"] = True
        result["warnings"].append("FFmpeg check timed out (exceeded 60 seconds)")
    except Exception as e:
        logger.error(f"FFmpeg check failed: {str(e)}")
        result["has_errors"] = True

    return result


def check_mcap_file(mcap_path: Path, skip_cache: bool = False) -> Dict[str, any]:
    """
    Check single MCAP file for topic consistency and video corruption issues.
    Returns a dictionary containing check results.
    """
    result = {"file": str(mcap_path), "errors": [], "warnings": [], "details": {}}

    if not mcap_path.exists():
        result["errors"].append(f"File not found: {mcap_path}")
        return result

    # Check cache file
    cache_file = mcap_path.with_suffix(".status")
    if not skip_cache and cache_file.exists():
        try:
            # Check file modification time, use cache if source file unchanged
            if cache_file.stat().st_mtime > mcap_path.stat().st_mtime:
                with open(cache_file, "r") as f:
                    return json.load(f)
        except Exception as e:
            logger.warning(f"Failed to read cache: {str(e)}")

    try:
        with mcap_path.open("rb") as f:
            reader = make_reader(f)
            summary = reader.get_summary()
            if summary is None:
                result["errors"].append("Failed to get MCAP summary")
                return result

            # Check topic consistency (for message topics only)
            available_topics = {ch.topic for ch in summary.channels.values()}
            result["details"]["available_topics"] = available_topics

            missing_state = set(MCAP_STATE_TOPICS) - available_topics
            missing_action = set(MCAP_ACTION_TOPICS) - available_topics

            if missing_state:
                result["errors"].append(f"Missing state topics: {missing_state}")
            if missing_action:
                result["errors"].append(f"Missing action topics: {missing_action}")

            # Calculate episode_len (based on state/action message counts)
            episode_len = 0
            for channel in summary.channels:
                topic = summary.channels[channel].topic
                if topic in MCAP_STATE_TOPICS or topic in MCAP_ACTION_TOPICS:
                    msg_count = summary.statistics.channel_message_counts[channel]
                    if episode_len == 0:
                        episode_len = msg_count
                    elif episode_len != msg_count:
                        result["warnings"].append(
                            f"Message count mismatch for {topic}: {msg_count} (expected {episode_len})"
                        )
            result["details"]["episode_len_from_messages"] = episode_len

            # Check if attachment names match expectations
            available_attachments = []
            min_video_frames = float("inf")
            video_problems = {}  # Store video issues

            for attach in reader.iter_attachments():
                available_attachments.append(attach.name)
                if attach.name not in MCAP_CAMERA_NAMES:
                    continue

                with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
                    tmp.write(attach.data)
                    tmp.flush()
                    tmp_path = tmp.name

                # Check video issues using FFmpeg
                ffmpeg_result = run_ffmpeg_check(tmp_path)
                result["details"][f"ffmpeg_warnings_{attach.name}"] = ffmpeg_result

                # Add video issues to results
                video_problems[attach.name] = []

                # Handle critical errors
                if ffmpeg_result["has_errors"]:
                    result["warnings"].append(
                        f"Video {attach.name} has critical decoding errors"
                    )
                    video_problems[attach.name].append("Critical decoding error")

                # Handle specific problems
                for problem in VIDEO_PROBLEMS:
                    count = ffmpeg_result["problem_details"][problem]["count"]
                    if count > 0:
                        # Add to warnings
                        warning_msg = f"Video {attach.name} found {count} instances of '{problem}'"
                        result["warnings"].append(warning_msg)

                        # Add to problem records
                        video_problems[attach.name].append(warning_msg)

                        # Add examples to details
                        examples = ffmpeg_result["problem_details"][problem][
                            "examples"
                        ][:3]  # Record max 3 examples
                        for i, example in enumerate(examples):
                            result["warnings"].append(f"  Example {i + 1}: {example}")

                # Basic video information
                cap = cv2.VideoCapture(tmp_path)
                total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
                fps = cap.get(cv2.CAP_PROP_FPS)
                result["details"][f"frames_{attach.name}"] = total_frames
                result["details"][f"fps_{attach.name}"] = fps
                min_video_frames = min(min_video_frames, total_frames)

                # Check if frame rate is close to 20fps
                if not (FPS_MIN <= fps <= FPS_MAX):
                    result["warnings"].append(
                        f"FPS inconsistency: {attach.name} has FPS {fps} (expected around {FPS_TARGET})"
                    )
                    video_problems[attach.name].append(f"FPS inconsistency: {fps}")

                # Try to read last frame to check for corruption
                cap.set(cv2.CAP_PROP_POS_FRAMES, total_frames - 1)
                ret, _ = cap.read()
                if not ret:
                    result["warnings"].append(
                        f"Cannot read last frame of {attach.name} (may be corrupted)"
                    )
                    video_problems[attach.name].append("Last frame corrupted")

                # New: Check for video freezes
                if total_frames > 10:  # Ensure video has enough frames
                    stuck_info = []
                    # Perform 3 random position freeze checks
                    for _ in range(3):
                        # Randomly select a starting point
                        start_frame = random.randint(0, max(0, total_frames - 50))
                        cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
                        stuck_mse, stuck_count = check_video_stuck(cap, 100)
                        if stuck_count > 0:
                            stuck_info.append(
                                {
                                    "start_frame": start_frame,
                                    "stuck_count": stuck_count,
                                    "avg_mse": float(np.mean(stuck_mse))
                                    if stuck_mse
                                    else 0,
                                }
                            )

                    # If there are freeze records
                    if stuck_info:
                        stuck_warning = (
                            f"Video {attach.name} may have freeze segments: "
                        )
                        for info in stuck_info:
                            stuck_warning += f"[Start:{info['start_frame']}, Duration:{info['stuck_count'] / fps:.2f}s, Avg MSE:{info['avg_mse']:.2f}] "
                        result["warnings"].append(stuck_warning)
                        result["details"][f"stuck_segments_{attach.name}"] = stuck_info
                        video_problems[attach.name].append("Freeze risk exists")

                cap.release()
                os.remove(tmp_path)

            result["details"]["available_attachments"] = available_attachments
            result["details"]["min_video_frames"] = min_video_frames
            result["details"]["video_problems"] = video_problems

            missing_camera = set(MCAP_CAMERA_NAMES) - set(available_attachments)
            if missing_camera:
                result["errors"].append(f"Missing camera attachments: {missing_camera}")

            # Check if message length matches video frame count
            if episode_len > min_video_frames:
                result["errors"].append(
                    f"Mismatch: message length={episode_len} > minimum video frames={min_video_frames}"
                )
            elif episode_len < min_video_frames:
                result["warnings"].append(
                    f"Mismatch: message length={episode_len} < minimum video frames={min_video_frames} (video has extra frames)"
                )

            # If there are any video issues
            if any(video_problems.values()):
                result["warnings"].append("Video quality issues detected")

    except Exception as e:
        result["errors"].append(f"Unexpected error: {str(e)}")
        logger.exception("Error processing MCAP file")

    # Save results to cache
    if not skip_cache:
        try:
            with open(cache_file, "w") as f:
                json.dump(result, f)
        except Exception as e:
            logger.warning(f"Failed to save cache: {str(e)}")

    return result


def main(dataset_dir: str, print_details: bool = False, skip_cache: bool = False):
    """
    Traverse dataset folder, check all .mcap files, and print reports.
    Add progress visualization and output summary statistics report.
    """
    path = Path(dataset_dir)
    if not path.exists() or not path.is_dir():
        logger.error(f"Dataset directory not found: {dataset_dir}")
        return

    mcap_files = list(path.glob("*.mcap"))
    total_files = len(mcap_files)
    if total_files == 0:
        logger.warning(f"No .mcap files found in {dataset_dir}")
        return

    logger.info(f"Found {total_files} MCAP files. Starting verification...")

    # Sort by file size (process smaller files first)
    file_sizes = [(f, os.path.getsize(f)) for f in mcap_files]
    sorted_files = sorted(file_sizes, key=lambda x: x[1])
    files_to_process = [f[0] for f in sorted_files]

    # Batch processing parameters
    batch_size = 10
    results = []
    normal_count = 0
    error_count = 0
    video_problem_files = []  # Store files with video issues
    error_details = {}  # file -> list of errors
    problem_details = {}  # file -> list of problems

    # Create progress bar
    progress_bar = tqdm(total=total_files, desc="Checking MCAP files", unit="file")

    # Process files in batches
    for i in range(0, len(files_to_process), batch_size):
        batch_files = files_to_process[i : i + batch_size]
        batch_results = []

        # Process current batch
        for file_path in batch_files:
            try:
                result = check_mcap_file(file_path, skip_cache)
                batch_results.append(result)
                progress_bar.update(1)
            except Exception as e:
                logger.error(f"Error processing file {file_path}: {str(e)}")
                result = {"file": str(file_path), "errors": [str(e)], "warnings": []}
                batch_results.append(result)

        # Process batch results
        for result in batch_results:
            results.append(result)

            # Record files with video issues
            if "video_problems" in result.get("details", {}):
                if any(result["details"]["video_problems"].values()):
                    problems = []
                    for cam, cam_problems in result["details"][
                        "video_problems"
                    ].items():
                        problems.extend(cam_problems)
                    video_problem_files.append(
                        {
                            "name": Path(result["file"]).name,
                            "problems": list(set(problems)),  # Deduplicate
                        }
                    )
                    problem_details[Path(result["file"]).name] = problems

            # Categorize and count
            if result.get("errors"):
                error_count += 1
                error_details[result["file"]] = result["errors"]
            else:
                normal_count += 1

            # Print detailed results
            if print_details:
                logger.info(f"\n=== Report for {result['file']} ===")
                if result["errors"]:
                    logger.error("Errors:")
                    for err in result["errors"]:
                        logger.error(f"  - {err}")
                if result["warnings"]:
                    logger.warning("Warnings:")
                    for warn in result["warnings"]:
                        logger.warning(f"  - {warn}")
                logger.info("Details:")
                for key, value in result["details"].items():
                    if key.startswith("ffmpeg_warnings_"):
                        logger.info(
                            f"  {key}: Total {value['problem_count']} video issues found"
                        )
                        for problem in VIDEO_PROBLEMS:
                            count = value["problem_details"][problem]["count"]
                            if count > 0:
                                logger.info(f"    '{problem}': {count} instances")
                    else:
                        logger.info(f"  {key}: {value}")
                if not result["errors"] and not result["warnings"]:
                    logger.info("All checks passed!")

        # Release resources (prevent memory accumulation)
        del batch_results
        time.sleep(0.1)  # Brief pause to allow system resource recovery

    # Close progress bar
    progress_bar.close()

    # Output summary statistics report
    logger.info("\n=== Summary Report ===")
    logger.info(f"Total files: {total_files}")
    logger.info(f"Normal files: {normal_count}")
    logger.info(f"Abnormal files: {error_count}")

    # Output files with video quality issues
    if video_problem_files:
        logger.warning(
            f"\nFound {len(video_problem_files)} files with video quality issues:"
        )
        for file_info in video_problem_files:
            logger.warning(f"  File: {file_info['name']}")
            for problem in file_info["problems"]:
                logger.warning(f"    - {problem}")

    # Output specific problem distribution
    logger.info("\nVideo problem distribution:")
    problem_counts = {problem: 0 for problem in VIDEO_PROBLEMS}
    for problems in problem_details.values():
        for problem in problems:
            for p_type in VIDEO_PROBLEMS:
                if p_type in problem:
                    problem_counts[p_type] += 1

    for problem, count in problem_counts.items():
        if count > 0:
            logger.info(f"  {problem}: {count} files affected")

    if error_count > 0:
        logger.info("\nAbnormal files and their issues:")
        for file, errors in error_details.items():
            logger.info(f"  {file}:")
            for err in errors:
                logger.info(f"    - {err}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Check MCAP dataset file consistency and video integrity"
    )
    parser.add_argument(
        "--dir",
        type=str,
        default="data/mcap/mmk2_pick_and_place_wooden_blocks_0731",
        help="Path to MCAP dataset folder",
    )
    parser.add_argument(
        "--print_details",
        action="store_true",
        help="Whether to print detailed check results for each file",
    )
    parser.add_argument(
        "--skip_cache",
        action="store_true",
        help="Skip cache and force recheck all files",
    )
    args = parser.parse_args()

    main(args.dir, print_details=args.print_details, skip_cache=args.skip_cache)
