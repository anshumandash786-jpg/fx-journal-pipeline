"""
parse_day.py — LLM-based structured extraction for Daily Markups.

Sends the full transcript of a daily backtesting session to Gemini to extract:
1. Pre-Market analysis
2. Session Recording events (with timestamps for screenshots)
3. Post-Market review

Usage:
    python parse_day.py /path/to/transcript.json
"""

import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config.settings import GEMINI_API_KEY, GEMINI_MODEL

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("parse_day")

# ─────────────────────────────────────────────
# EXTRACTION PROMPT
# ─────────────────────────────────────────────
EXTRACTION_PROMPT = """You are an expert FX trade journal analyst. Read the transcript of a full-day backtesting session.
Your goal is to extract the trader's thought process throughout the day to populate their daily visual journal.

Divide the session into 3 phases:
1. **PRE MARKET**: What is the game plan for the day? What are they expecting before taking any trades?
2. **SESSION RECORDING**: What are the key moments during the active session? When does their thought process change? When do they take a trade? Identify up to 4 key events, and provide the exact timestamp (HH:MM:SS) where it happened so we can take a screenshot.
3. **POST MARKET**: EOD Review. What went right or wrong? Have they changed their bias for the next day?

CRITICAL RULES:
- Do NOT copy raw transcript text. The trader speaks casually.
- SUMMARIZE into crisp, professional bullet points using proper ICT/SMC terminology.
- Minimize token usage but maximize quality. Be ultra-concise but dense with logic.
- Timestamps MUST be in MM:SS or HH:MM:SS format corresponding to the transcript. If the transcript timing is strictly seconds, convert it accurately.

Return a JSON object exactly matching this structure:

{
  "pre_market": [
    "First crisp bullet point about game plan",
    "Second crisp bullet point about HTF zones to watch"
  ],
  "session_events": [
    {
      "timestamp": "HH:MM:SS",
      "description": "Crisp observation (e.g. 'M15 supply respected, shifting bias to short.')"
    }
  ],
  "post_market": [
    "First crisp bullet point reviewing the outcome",
    "Second crisp bullet point on mistakes or lessons"
  ]
}

TRANSCRIPT:
\"\"\"
{transcript_text}
\"\"\"

Extract the daily markup data. Return ONLY the JSON object."""

def parse_day_from_transcript(transcript_text: str) -> dict:
    """
    Send transcript to Gemini and extract structured daily journaling data.
    """
    if not GEMINI_API_KEY:
        raise ValueError("GEMINI_API_KEY not set.")

    logger.info("Sending transcript to Gemini for daily markup extraction...")

    try:
        from google import genai
        from google.genai import types
    except ImportError:
        raise ImportError("google-genai not installed.")

    client = genai.Client(api_key=GEMINI_API_KEY)
    prompt = EXTRACTION_PROMPT.replace("{transcript_text}", transcript_text)

    try:
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.2,
                top_p=0.95,
                max_output_tokens=2048,
                response_mime_type="application/json",
            ),
        )
        raw_text = response.text.strip()
    except Exception as e:
        logger.error(f"Gemini API call failed: {e}")
        raise

    # Parse JSON response
    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse Gemini response as JSON: {e}")
        logger.error(f"Raw response (first 500 chars): {raw_text[:500]}")
        # Try markdown fence extraction
        if "```json" in raw_text:
            json_str = raw_text.split("```json")[1].split("```")[0].strip()
            data = json.loads(json_str)
        elif "```" in raw_text:
            json_str = raw_text.split("```")[1].split("```")[0].strip()
            data = json.loads(json_str)
        else:
            raise

    logger.info(f"Extracted daily markups: {len(data.get('session_events', []))} session events.")
    return data

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python parse_day.py <transcript_json_path>")
        sys.exit(1)

    transcript_file = Path(sys.argv[1])
    with open(transcript_file) as f:
        transcript_data = json.load(f)

    # We need text with timestamps for Gemini to figure out the HH:MM:SS
    # So instead of just raw text, we provide segments if available.
    if "segments" in transcript_data:
        # Create a text representation including timestamps
        lines = []
        for seg in transcript_data["segments"]:
            start_m = int(seg['start'] // 60)
            start_s = int(seg['start'] % 60)
            lines.append(f"[{start_m:02d}:{start_s:02d}] {seg['text'].strip()}")
        transcript_text = "\\n".join(lines)
    else:
        transcript_text = transcript_data.get("text", "")

    data = parse_day_from_transcript(transcript_text)
    print(f"\\nExtracted Daily Markups:")
    print(json.dumps(data, indent=2))
