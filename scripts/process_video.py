"""
process_video.py — Master orchestration script.

This is the main entry point that chains all pipeline steps together:
1. Transcribe video → transcript
2. Parse transcript → structured trade data (Gemini)
3. Extract screenshots → PNG files
4. Upload screenshots → Google Drive
5. Append trade data → Google Sheet

Designed to be called by n8n or run directly from the command line.

Usage:
    python process_video.py /path/to/video.mp4

Exit codes:
    0 = Success
    1 = Partial failure (some steps failed but trade data was logged)
    2 = Complete failure (no data was logged)
"""

import json
import logging
import shutil
import sys
import traceback
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import PROCESSING_DIR, DONE_DIR, LOG_DIR
from scripts.transcribe import transcribe_video
from scripts.extract_frames import extract_screenshots
from scripts.parse_trade import parse_trades_from_transcript
from scripts.upload import (
    upload_screenshots,
    append_trades_to_sheet,
)

# ─────────────────────────────────────────────
# LOGGING
# ─────────────────────────────────────────────
log_file = LOG_DIR / f"pipeline_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(str(log_file)),
    ],
)
logger = logging.getLogger("pipeline")


def process_video(video_path: str | Path) -> dict:
    """
    Process a single video file through the full pipeline.

    Args:
        video_path: Path to the video file.

    Returns:
        Dict with processing results:
        {
            "status": "success" | "partial" | "failed",
            "video": str,
            "trades_logged": int,
            "screenshots_uploaded": int,
            "errors": [str],
            "log_file": str,
        }
    """
    video_path = Path(video_path)
    result = {
        "status": "failed",
        "video": str(video_path),
        "trades_logged": 0,
        "screenshots_uploaded": 0,
        "errors": [],
        "log_file": str(log_file),
    }

    logger.info("=" * 60)
    logger.info(f"PIPELINE START: {video_path.name}")
    logger.info(f"Time: {datetime.now().isoformat()}")
    logger.info("=" * 60)

    # ── STEP 0: Validate input ──────────────────────────
    if not video_path.exists():
        error = f"Video file not found: {video_path}"
        logger.error(error)
        result["errors"].append(error)
        return result

    # Move video to processing dir to avoid re-trigger
    processing_path = PROCESSING_DIR / video_path.name
    try:
        shutil.move(str(video_path), str(processing_path))
        logger.info(f"Moved to processing: {processing_path}")
    except Exception as e:
        logger.warning(f"Could not move file (processing in place): {e}")
        processing_path = video_path

    # ── STEP 1: Transcribe ──────────────────────────────
    logger.info("─" * 40)
    logger.info("STEP 1/5: Transcribing audio...")
    try:
        transcript = transcribe_video(processing_path)
        logger.info(f"Transcript: {len(transcript.get('words', []))} words")
    except Exception as e:
        error = f"Transcription failed: {e}"
        logger.error(error)
        logger.error(traceback.format_exc())
        result["errors"].append(error)
        # Move back to inbox for retry
        _move_to_inbox(processing_path, video_path)
        return result

    # ── STEP 2: Parse trades via Gemini ─────────────────
    logger.info("─" * 40)
    logger.info("STEP 2/5: Extracting trade data via Gemini...")
    try:
        transcript_text = transcript.get("text", "")
        trades = parse_trades_from_transcript(transcript_text)
        logger.info(f"Extracted {len(trades)} trade(s)")
    except Exception as e:
        error = f"Trade parsing failed: {e}"
        logger.error(error)
        logger.error(traceback.format_exc())
        result["errors"].append(error)
        # Save transcript for manual review
        _save_transcript(transcript, processing_path)
        _move_to_inbox(processing_path, video_path)
        return result

    if not trades:
        error = "No trades found in transcript. Check your verbal protocol."
        logger.warning(error)
        result["errors"].append(error)
        _save_transcript(transcript, processing_path)
        _move_to_done(processing_path)
        return result

    # ── STEP 3: Extract screenshots ─────────────────────
    logger.info("─" * 40)
    logger.info("STEP 3/5: Extracting screenshots...")

    all_screenshots = []
    for i, trade in enumerate(trades):
        trade_num = trade.get("trade_number", i + 1)
        pair = (trade.get("pair") or "UNKNOWN").upper().replace("/", "")
        date_str = trade.get("date") or datetime.now().strftime("%Y-%m-%d")
        trade_label = f"{pair}_{date_str}_T{trade_num}"

        try:
            screenshots = extract_screenshots(processing_path, transcript, trade_label)
            all_screenshots.append(screenshots)
            logger.info(f"Trade {trade_num}: {len(screenshots)} screenshots extracted")
        except Exception as e:
            logger.warning(f"Screenshot extraction failed for trade {trade_num}: {e}")
            all_screenshots.append({})
            result["errors"].append(f"Screenshots failed for trade {trade_num}: {e}")

    # ── STEP 4: Upload screenshots to Drive ─────────────
    logger.info("─" * 40)
    logger.info("STEP 4/5: Uploading screenshots to Google Drive...")

    all_screenshot_links = []
    for i, screenshots in enumerate(all_screenshots):
        trade_num = trades[i].get("trade_number", i + 1)
        pair = (trades[i].get("pair") or "UNKNOWN").upper().replace("/", "")
        date_str = trades[i].get("date") or datetime.now().strftime("%Y-%m-%d")
        trade_label = f"{pair}_{date_str}_T{trade_num}"

        if screenshots:
            try:
                links = upload_screenshots(screenshots, trade_label)
                all_screenshot_links.append(links)
                result["screenshots_uploaded"] += len(links)
            except Exception as e:
                logger.warning(f"Drive upload failed for trade {trade_num}: {e}")
                all_screenshot_links.append({})
                result["errors"].append(f"Drive upload failed for trade {trade_num}: {e}")
        else:
            all_screenshot_links.append({})

    # ── STEP 5: Append to Google Sheet ──────────────────
    logger.info("─" * 40)
    logger.info("STEP 5/5: Writing to Google Sheet...")
    try:
        rows_added = append_trades_to_sheet(trades, all_screenshot_links)
        result["trades_logged"] = rows_added
        logger.info(f"Successfully logged {rows_added} trade(s) to Google Sheet")
    except Exception as e:
        error = f"Sheet write failed: {e}"
        logger.error(error)
        logger.error(traceback.format_exc())
        result["errors"].append(error)

        # Save trade data locally as backup
        backup_path = processing_path.parent / f"{processing_path.stem}_trades.json"
        with open(backup_path, "w") as f:
            json.dump(trades, f, indent=2)
        logger.info(f"Trade data backed up to: {backup_path}")

    # ── Determine final status ──────────────────────────
    if result["trades_logged"] > 0 and not result["errors"]:
        result["status"] = "success"
    elif result["trades_logged"] > 0:
        result["status"] = "partial"
    else:
        result["status"] = "failed"

    # ── Move completed video ────────────────────────────
    _move_to_done(processing_path)

    # Save processing result
    result_path = DONE_DIR / f"{processing_path.stem}_result.json"
    with open(result_path, "w") as f:
        json.dump(result, f, indent=2)

    # ── Summary ─────────────────────────────────────────
    logger.info("=" * 60)
    logger.info(f"PIPELINE COMPLETE: {result['status'].upper()}")
    logger.info(f"Trades logged: {result['trades_logged']}")
    logger.info(f"Screenshots uploaded: {result['screenshots_uploaded']}")
    if result["errors"]:
        logger.warning(f"Errors ({len(result['errors'])}):")
        for err in result["errors"]:
            logger.warning(f"  - {err}")
    logger.info(f"Log file: {log_file}")
    logger.info("=" * 60)

    return result


def _move_to_inbox(processing_path: Path, original_path: Path):
    """Move video back to inbox for retry on failure."""
    try:
        shutil.move(str(processing_path), str(original_path))
        logger.info(f"Moved back to inbox for retry: {original_path.name}")
    except Exception:
        pass


def _move_to_done(processing_path: Path):
    """Move video to done directory after processing."""
    done_path = DONE_DIR / processing_path.name
    try:
        if processing_path.exists():
            shutil.move(str(processing_path), str(done_path))
            logger.info(f"Moved to done: {done_path.name}")
    except Exception as e:
        logger.warning(f"Could not move to done: {e}")


def _save_transcript(transcript: dict, video_path: Path):
    """Save transcript as backup for manual review."""
    try:
        backup_path = video_path.parent / f"{video_path.stem}_transcript.json"
        with open(backup_path, "w") as f:
            json.dump(transcript, f, indent=2)
        logger.info(f"Transcript saved for review: {backup_path}")
    except Exception:
        pass


# ─────────────────────────────────────────────
# CLI entry point
# ─────────────────────────────────────────────
if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python process_video.py <video_path>")
        print("\nThis script processes a backtesting video through the full pipeline:")
        print("  1. Transcribes audio (local Whisper)")
        print("  2. Extracts trade data (Gemini API)")
        print("  3. Captures screenshots (FFmpeg)")
        print("  4. Uploads screenshots (Google Drive)")
        print("  5. Logs trade data (Google Sheets)")
        sys.exit(1)

    video_file = Path(sys.argv[1])
    result = process_video(video_file)

    # Exit with appropriate code
    if result["status"] == "success":
        sys.exit(0)
    elif result["status"] == "partial":
        sys.exit(1)
    else:
        sys.exit(2)
