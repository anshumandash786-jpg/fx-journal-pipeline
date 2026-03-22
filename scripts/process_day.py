"""
process_day.py — Master orchestration script for Daily Markups.

This script processes a full-day recording:
1. Transcribes audio (local Whisper)
2. Extracts Date/Week/Day from video frame (FXReplay watermark)
3. Extracts Pre-Market, Session Events (w/ timestamps), and Post-Market (Gemini)
4. Captures screenshots at the identified timestamps (FFmpeg)
5. Uploads screenshots (Google Drive)
6. Appends all data to the specific Day page in the Notion Markups Database.

Usage:
    python process_day.py /path/to/fullday_video.mp4
"""

import json
import logging
import shutil
import sys
import traceback
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import PROCESSING_DIR, DONE_DIR, LOG_DIR, NOTION_ENABLED
from scripts.transcribe import transcribe_video
from scripts.get_video_date import extract_date_from_video
from scripts.parse_day import parse_day_from_transcript
from scripts.extract_frames import extract_frame_at_time
from scripts.upload import upload_screenshot_to_drive
from scripts.notion_upload import create_daily_markup_page

# ─────────────────────────────────────────────
# LOGGING
# ─────────────────────────────────────────────
log_file = LOG_DIR / f"daily_pipeline_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(str(log_file)),
    ],
)
logger = logging.getLogger("process_day")


def process_daily_video(video_path: str | Path) -> dict:
    video_path = Path(video_path)
    result = {
        "status": "failed",
        "video": str(video_path),
        "errors": [],
        "log_file": str(log_file),
    }

    logger.info("=" * 60)
    logger.info(f"DAILY PIPELINE START: {video_path.name}")
    logger.info(f"Time: {datetime.now().isoformat()}")
    logger.info("=" * 60)

    # ── STEP 0: Validate input ──────────────────────────
    if not video_path.exists():
        error = f"Video file not found: {video_path}"
        logger.error(error)
        result["errors"].append(error)
        return result

    processing_path = PROCESSING_DIR / video_path.name
    try:
        shutil.move(str(video_path), str(processing_path))
        logger.info(f"Moved to processing: {processing_path}")
    except Exception as e:
        logger.warning(f"Could not move file (processing in place): {e}")
        processing_path = video_path

    # ── STEP 1: Transcribe ──────────────────────────────
    logger.info("─" * 40)
    logger.info("STEP 1/6: Transcribing audio...")
    try:
        transcript = transcribe_video(processing_path)
        logger.info(f"Transcript: {len(transcript.get('words', []))} words")
    except Exception as e:
        error = f"Transcription failed: {e}"
        logger.error(error)
        result["errors"].append(error)
        _move_to_inbox(processing_path, video_path)
        return result

    # ── STEP 2: Extract Date & Day ──────────────────────
    logger.info("─" * 40)
    logger.info("STEP 2/6: Extracting exact trading date from video...")
    try:
        date_info = extract_date_from_video(processing_path)
        video_date = date_info["date"]
        week_num = date_info["week_num"]
        day_of_week = date_info["day_of_week"]
        logger.info(f"Extracted Date: {video_date} (Week: {week_num}, Day: {day_of_week})")
    except Exception as e:
        error = f"Could not extract date from video: {e}"
        logger.error(error)
        result["errors"].append(error)
        _move_to_inbox(processing_path, video_path)
        return result

    # ── STEP 3: Parse Daily Narrative via Gemini ────────
    logger.info("─" * 40)
    logger.info("STEP 3/6: Extracting daily markups via Gemini...")
    try:
        # Include timestamps for Gemini to identify events accurately
        if "segments" in transcript:
            lines = []
            for seg in transcript["segments"]:
                start_m = int(seg['start'] // 60)
                start_s = int(seg['start'] % 60)
                lines.append(f"[{start_m:02d}:{start_s:02d}] {seg['text'].strip()}")
            transcript_text = "\\n".join(lines)
        else:
            transcript_text = transcript.get("text", "")
            
        daily_markups = parse_day_from_transcript(transcript_text)
        logger.info(f"Extracted {len(daily_markups.get('session_events', []))} session events.")
    except Exception as e:
        error = f"Narrative extraction failed: {e}"
        logger.error(error)
        result["errors"].append(error)
        _move_to_inbox(processing_path, video_path)
        return result

    # ── STEP 4 & 5: Extract and Upload Screenshots ──────
    logger.info("─" * 40)
    logger.info("STEP 4&5/6: Extracting and Uploading Event Screenshots...")
    
    screenshot_links = []
    events = daily_markups.get("session_events", [])
    for i, event in enumerate(events):
        ts = event.get("timestamp")
        if ts:
            try:
                # Need HH:MM:SS format
                if len(ts.split(":")) == 2:
                    ts = f"00:{ts}"
                
                # Extract
                stype = f"Event_{i+1}"
                frame_path = processing_path.parent / f"{processing_path.stem}_{stype}.png"
                frame_path = extract_frame_at_time(processing_path, ts, frame_path)
                
                if frame_path and frame_path.exists():
                    drive_filename = f"Day_{video_date}_{stype}.png"
                    link = upload_screenshot_to_drive(frame_path, drive_filename)
                    screenshot_links.append(link)
                else:
                    logger.warning(f"Failed to extract frame at {ts}")
                    screenshot_links.append("")
                    
            except Exception as e:
                logger.warning(f"Screenshot process failed for event at {ts}: {e}")
                screenshot_links.append("")
        else:
            screenshot_links.append("")

    # ── STEP 6: Write to Notion ────────────────────────
    if NOTION_ENABLED:
        logger.info("─" * 40)
        logger.info(f"STEP 6/6: Creating Daily Markups Page in Notion for {video_date}...")
        try:
            success = create_daily_markup_page(video_date, week_num, day_of_week, daily_markups, screenshot_links)
            if success:
                result["status"] = "success"
                logger.info(f"Successfully recorded daily markups for W{week_num} {day_of_week} ({video_date})")
            else:
                result["errors"].append("Failed to create Notion page.")
        except Exception as e:
            error = f"Notion write failed: {e}"
            logger.error(error)
            logger.error(traceback.format_exc())
            result["errors"].append(error)
    else:
        logger.info("Notion integration disabled. Cannot append daily markups.")
        result["errors"].append("Notion disabled, cannot complete daily markups.")

    # ── Wrap Up ─────────────────────────────────────────
    if result["status"] == "success":
        _move_to_done(processing_path)
    else:
        # Keep processing and dump data
        dump_path = processing_path.parent / f"{processing_path.stem}_markups_dump.json"
        with open(dump_path, "w") as f:
            json.dump(daily_markups, f, indent=2)

    result_path = DONE_DIR / f"{processing_path.stem}_daily_result.json"
    if result["status"] == "success":
        with open(result_path, "w") as f:
            json.dump(result, f, indent=2)

    logger.info("=" * 60)
    logger.info(f"DAILY PIPELINE COMPLETE: {result['status'].upper()}")
    if result["errors"]:
        logger.warning(f"Errors: {result['errors']}")
    logger.info(f"Log file: {log_file}")
    logger.info("=" * 60)

    return result


def _move_to_inbox(processing_path: Path, original_path: Path):
    try:
        shutil.move(str(processing_path), str(original_path))
    except Exception:
        pass


def _move_to_done(processing_path: Path):
    done_path = DONE_DIR / processing_path.name
    try:
        if processing_path.exists():
            shutil.move(str(processing_path), str(done_path))
    except Exception:
        pass


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python process_day.py <fullday_video_path>")
        sys.exit(1)

    result = process_daily_video(Path(sys.argv[1]))
    if result["status"] == "success":
        sys.exit(0)
    else:
        sys.exit(1)
