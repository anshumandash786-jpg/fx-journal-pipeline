"""
extract_frames.py — Screenshot extraction at keyword-triggered timestamps.

Reads the transcript (with word-level timestamps) and finds moments where
you say "direction screenshot", "location screenshot", or "execution screenshot".
Then uses ffmpeg to extract the exact video frame at that timestamp.

Usage:
    python extract_frames.py /path/to/video.mp4 /path/to/transcript.json

Output:
    Saves PNG files to the screenshots directory:
    - PAIR_DATE_T1_direction.png
    - PAIR_DATE_T1_location.png
    - PAIR_DATE_T1_execution.png
"""

import json
import logging
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config.settings import SCREENSHOT_KEYWORDS, SCREENSHOTS_DIR

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("extract_frames")


def find_keyword_timestamps(transcript: dict) -> dict:
    """
    Scan the transcript for screenshot trigger keywords.
    Returns a dict of {screenshot_type: timestamp_seconds}.

    Strategy:
    1. First, try to find exact keyword phrases in the full text using
       word-level timestamps for precise timing.
    2. If word-level timestamps aren't available, fall back to segment-level.
    """
    found_timestamps = {}
    words = transcript.get("words", [])
    segments = transcript.get("segments", [])

    if words:
        # Build a running text window to match multi-word phrases
        for screenshot_type, keywords in SCREENSHOT_KEYWORDS.items():
            for keyword in keywords:
                keyword_lower = keyword.lower()
                keyword_words = keyword_lower.split()
                keyword_len = len(keyword_words)

                # Slide through word list looking for the phrase
                for i in range(len(words) - keyword_len + 1):
                    window = " ".join(
                        w["word"].lower().strip(".,!?;:") for w in words[i : i + keyword_len]
                    )
                    if window == keyword_lower:
                        # Use the timestamp of the FIRST word in the phrase
                        # Then add 1 second to capture the moment AFTER they say it
                        # (they should be holding still on the chart)
                        timestamp = words[i]["start"] + 1.0
                        found_timestamps[screenshot_type] = round(timestamp, 2)
                        logger.info(
                            f"Found '{keyword}' at {timestamp:.1f}s → "
                            f"extracting {screenshot_type} screenshot"
                        )
                        break  # Found this type, move to next

                if screenshot_type in found_timestamps:
                    break  # Already found, skip other keyword variants

    elif segments:
        # Fallback: search in segment text
        logger.warning("No word-level timestamps. Using segment-level (less precise).")
        for screenshot_type, keywords in SCREENSHOT_KEYWORDS.items():
            for seg in segments:
                seg_text = seg.get("text", "").lower()
                for keyword in keywords:
                    if keyword.lower() in seg_text:
                        # Use the start of the segment + 2 seconds
                        timestamp = seg["start"] + 2.0
                        found_timestamps[screenshot_type] = round(timestamp, 2)
                        logger.info(
                            f"Found '{keyword}' in segment at {timestamp:.1f}s → "
                            f"{screenshot_type} screenshot"
                        )
                        break
                if screenshot_type in found_timestamps:
                    break

    # Log what we didn't find
    for stype in SCREENSHOT_KEYWORDS:
        if stype not in found_timestamps:
            logger.warning(f"No keyword found for '{stype}' screenshot. Skipping.")

    return found_timestamps


def extract_frame(video_path: Path, timestamp: float, output_path: Path) -> Path:
    """
    Extract a single frame from video at the given timestamp using ffmpeg.
    """
    cmd = [
        "ffmpeg",
        "-ss", str(timestamp),
        "-i", str(video_path),
        "-frames:v", "1",
        "-q:v", "2",  # High quality JPEG/PNG
        "-y",
        str(output_path),
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        logger.error(f"Frame extraction failed at {timestamp}s: {result.stderr[-300:]}")
        raise RuntimeError(f"FFmpeg frame extraction failed at {timestamp}s")

    logger.info(f"Extracted frame at {timestamp:.1f}s → {output_path.name}")
    return output_path


def extract_screenshots(
    video_path: str | Path,
    transcript: dict,
    trade_label: str = "trade",
) -> dict:
    """
    Main entry point: find keyword timestamps in transcript and extract frames.

    Args:
        video_path: Path to the video file.
        transcript: Parsed transcript dict with 'words' or 'segments'.
        trade_label: Label for file naming (e.g., 'EURUSD_2025-06-15_T1').

    Returns:
        Dict of {screenshot_type: Path_to_saved_png}
    """
    video_path = Path(video_path)

    if not video_path.exists():
        raise FileNotFoundError(f"Video not found: {video_path}")

    # Find timestamps
    timestamps = find_keyword_timestamps(transcript)

    if not timestamps:
        logger.warning("No screenshot keywords found in transcript. No frames extracted.")
        return {}

    # Extract frames
    screenshots = {}
    for screenshot_type, timestamp in timestamps.items():
        filename = f"{trade_label}_{screenshot_type}.png"
        output_path = SCREENSHOTS_DIR / filename
        try:
            extract_frame(video_path, timestamp, output_path)
            screenshots[screenshot_type] = output_path
        except RuntimeError as e:
            logger.error(f"Failed to extract {screenshot_type} screenshot: {e}")

    logger.info(f"Extracted {len(screenshots)}/{len(timestamps)} screenshots.")
    return screenshots


# ─────────────────────────────────────────────
# CLI entry point
# ─────────────────────────────────────────────
if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python extract_frames.py <video_path> <transcript_json_path>")
        sys.exit(1)

    video_file = Path(sys.argv[1])
    transcript_file = Path(sys.argv[2])

    with open(transcript_file) as f:
        transcript_data = json.load(f)

    result = extract_screenshots(video_file, transcript_data, trade_label="test_trade")
    print(f"\nExtracted screenshots: {list(result.keys())}")
    for stype, path in result.items():
        print(f"  {stype}: {path}")
