"""
watch_inbox.py — Simple folder watcher that triggers the pipeline.

Alternative to n8n: a standalone Python script that watches the inbox
folder for new video files and processes them automatically.

This is useful if you don't want to set up Docker/n8n, or as a quick
way to test the pipeline.

Usage:
    python watch_inbox.py

Runs continuously. Press Ctrl+C to stop.
"""

import logging
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import INBOX_DIR, SUPPORTED_VIDEO_EXTENSIONS
from scripts.process_video import process_video

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("watcher")

# Load .env file if present
try:
    from dotenv import load_dotenv
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if env_path.exists():
        load_dotenv(env_path)
        logger.info(f"Loaded environment from {env_path}")
except ImportError:
    pass


def scan_inbox() -> list[Path]:
    """Scan the inbox directory for new video files."""
    videos = []
    for ext in SUPPORTED_VIDEO_EXTENSIONS:
        videos.extend(INBOX_DIR.glob(f"*{ext}"))
    return sorted(videos, key=lambda p: p.stat().st_mtime)


def watch_forever(poll_interval: int = 30):
    """
    Continuously watch the inbox folder and process new videos.

    Args:
        poll_interval: Seconds between scans (default: 30)
    """
    logger.info("=" * 60)
    logger.info("FX Journal Pipeline — Inbox Watcher")
    logger.info(f"Watching: {INBOX_DIR}")
    logger.info(f"Poll interval: {poll_interval}s")
    logger.info("Press Ctrl+C to stop")
    logger.info("=" * 60)

    processed_files = set()

    while True:
        try:
            videos = scan_inbox()

            for video_path in videos:
                # Skip files we've already processed
                if str(video_path) in processed_files:
                    continue

                # Skip files that are still being written (size changing)
                size1 = video_path.stat().st_size
                time.sleep(2)
                if not video_path.exists():
                    continue
                size2 = video_path.stat().st_size
                if size1 != size2:
                    logger.info(f"File still being written: {video_path.name}")
                    continue

                # Process the video
                logger.info(f"\n{'='*60}")
                logger.info(f"New video detected: {video_path.name}")
                logger.info(f"{'='*60}\n")

                result = process_video(video_path)
                processed_files.add(str(video_path))

                # Log result
                status = result["status"]
                trades = result["trades_logged"]
                screenshots = result["screenshots_uploaded"]
                errors = result["errors"]

                if status == "success":
                    logger.info(f"✓ SUCCESS: {trades} trade(s), {screenshots} screenshots")
                elif status == "partial":
                    logger.warning(f"⚠ PARTIAL: {trades} trade(s) logged, but {len(errors)} error(s)")
                else:
                    logger.error(f"✗ FAILED: {', '.join(errors)}")

            time.sleep(poll_interval)

        except KeyboardInterrupt:
            logger.info("\nWatcher stopped by user.")
            break
        except Exception as e:
            logger.error(f"Unexpected error in watcher: {e}")
            time.sleep(poll_interval)


if __name__ == "__main__":
    poll = int(sys.argv[1]) if len(sys.argv) > 1 else 30
    watch_forever(poll_interval=poll)
