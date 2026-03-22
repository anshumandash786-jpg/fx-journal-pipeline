"""
get_video_date.py — Extracts the trading date from the FXReplay watermark.

This script extracts a single frame from the video and uses Gemini 1.5 Flash
to read the date in the bottom right corner.
It returns the precise date, ISO week number, and Day of the week.
"""

import json
import logging
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config.settings import GEMINI_API_KEY, GEMINI_MODEL

logger = logging.getLogger("get_video_date")


def extract_date_from_video(video_path: Path) -> dict:
    """
    Extract date from FXReplay watermark.
    
    Returns:
        dict: {"date": "YYYY-MM-DD", "week_num": int, "day": "M O N D A Y"}
    """
    if not GEMINI_API_KEY:
        raise ValueError("GEMINI_API_KEY not set.")

    frame_path = video_path.parent / f"{video_path.stem}_frame.jpg"
    
    try:
        # Extract a frame at 5 seconds (to avoid fade-ins)
        cmd = [
            "ffmpeg", "-y",
            "-ss", "00:00:05",
            "-i", str(video_path),
            "-frames:v", "1",
            "-q:v", "2",
            str(frame_path)
        ]
        
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        
        if not frame_path.exists():
            raise FileNotFoundError("FFmpeg failed to extract frame.")

        try:
            from google import genai
            from google.genai import types
        except ImportError:
            raise ImportError("google-genai not installed.")

        client = genai.Client(api_key=GEMINI_API_KEY)
        
        # Upload the frame
        prompt = (
            "Look at the bottom right corner of this trading screen. "
            "There is an FXReplay watermark indicating the current virtual date. "
            "Extract ONLY the date in YYYY-MM-DD format. "
            "If you cannot see it, return ONLY the word 'UNKNOWN'."
        )
        
        # Note: In standard python environments, we might upload via File API 
        # but for a single image, uploading bytes directly is often faster.
        # However, new google-genai SDK prefers client.files.upload or direct bytes.
        
        with open(frame_path, "rb") as f:
            image_bytes = f.read()
            
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=[
                types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg"),
                prompt
            ],
            config=types.GenerateContentConfig(
                temperature=0.0,
                max_output_tokens=20,
            ),
        )
        
        date_str = response.text.strip()
        
        if date_str == "UNKNOWN" or not date_str.startswith("20"):
            logger.warning(f"Could not read date from frame, got: '{date_str}'")
            return _fallback_date()
            
        try:
            dt = datetime.strptime(date_str, "%Y-%m-%d")
            week_num = dt.isocalendar()[1]
            day_name = dt.strftime("%A").upper()
            day_formatted = " ".join(day_name)  # e.g., "M O N D A Y"
            
            return {
                "date": date_str,
                "week_num": week_num,
                "day_of_week": day_formatted
            }
        except ValueError:
            logger.warning(f"Extracted date '{date_str}' was not YYYY-MM-DD format.")
            return _fallback_date()
            
    except Exception as e:
        logger.error(f"Error extracting video date: {e}")
        return _fallback_date()
        
    finally:
        # Cleanup frame
        if frame_path.exists():
            try:
                os.remove(frame_path)
            except Exception:
                pass

def _fallback_date() -> dict:
    today = datetime.now()
    week_num = today.isocalendar()[1]
    day_name = today.strftime("%A").upper()
    return {
        "date": today.strftime("%Y-%m-%d"),
        "week_num": week_num,
        "day_of_week": " ".join(day_name)
    }

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python get_video_date.py <video_path>")
        sys.exit(1)
        
    date_info = extract_date_from_video(Path(sys.argv[1]))
    print(json.dumps(date_info, indent=2))
