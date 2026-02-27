"""
parse_trade.py — LLM-based structured extraction from transcript text.

Sends the full transcript to Gemini 2.0 Flash with a carefully crafted
prompt that extracts trade parameters (Block 1: math) and trade reasoning
(Block 2: narrative) into a structured JSON format.

Supports multi-trade videos by returning a list of trade objects.

Usage:
    python parse_trade.py /path/to/transcript.json

Output:
    Returns list of trade dicts matching the Google Sheet schema.
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
logger = logging.getLogger("parse_trade")

# ─────────────────────────────────────────────
# EXTRACTION PROMPT
# ─────────────────────────────────────────────
EXTRACTION_PROMPT = """You are an expert trade journal parser for a professional FX trader. Your job is to read a transcript of a backtesting session narration and extract structured trade data.

The trader analyzes price in 3 stages:
1. **Direction** — Higher timeframe (HTF) bias, why price is expected to move a certain way
2. **Location** — The specific zone/area chosen for the trade (OB, FVG, breaker, liquidity, etc.)
3. **Execution** — The specific model/pattern used to enter (BOS, MSS, CISD, FVG entry, etc.)

IMPORTANT RULES:
- Extract ALL trades mentioned in the transcript (there may be 1 or more).
- For prices, extract the EXACT numbers spoken. Do not guess or calculate prices.
- If a field is not mentioned, set it to null.
- For direction, ONLY use "Long" or "Short".
- For outcome, ONLY use "Win", "Loss", "Breakeven", or "Partial".
- For session, ONLY use "Asian", "London", "NY AM", "NY PM", or "London-NY Overlap".
- Confluence score and conviction should be integers 1-5. If not mentioned, set to null.
- Trade duration should be a string like "45 min" or "2 hours". If not mentioned, set to null.
- Return ONLY valid JSON. No markdown, no code fences, no explanatory text.

Return a JSON array of trade objects. Each trade should have this exact structure:

[
  {
    "trade_number": 1,
    "date": "YYYY-MM-DD or null",
    "session": "London / NY AM / NY PM / Asian / London-NY Overlap / null",
    "pair": "EURUSD / GBPUSD / etc. or null",
    "trade_type": "Scalp / Intraday / null",
    "direction": "Long / Short / null",

    "entry_price": 0.00000,
    "stop_loss": 0.00000,
    "take_profit": 0.00000,
    "scale_in_1": null,
    "scale_in_2": null,
    "scale_out_1": null,
    "scale_out_2": null,
    "position_size_lots": null,
    "risk_percent": null,

    "outcome": "Win / Loss / Breakeven / Partial / null",
    "exit_price": null,
    "mae_pips": null,
    "mfe_pips": null,
    "max_r_available": null,
    "trade_duration": null,

    "htf_reference": "H4 / D1 / W1 / etc. or null",
    "direction_thesis": "Full narrative of why they believe price is going this direction",
    "location_zone_type": "OB / FVG / Breaker / Liquidity / BOS level / etc. or null",
    "location_timeframe": "M15 / H1 / etc. or null",
    "location_thesis": "Full narrative of why this specific location was chosen",
    "execution_model_name": "BOS / MSS / CISD / FVG entry / OB mitigation / etc. or null",
    "execution_timeframe": "M1 / M5 / etc. or null",
    "execution_thesis": "Full narrative of what made them enter at that exact moment",

    "confluence_score": null,
    "pre_trade_conviction": null,
    "mistakes_noted": null,
    "post_trade_review": null,
    "early_exit_reason": null
  }
]

TRANSCRIPT:
\"\"\"
{transcript_text}
\"\"\"

Extract all trades from the above transcript. Return ONLY the JSON array."""


def parse_trades_from_transcript(transcript_text: str) -> list[dict]:
    """
    Send transcript to Gemini Flash and extract structured trade data.

    Args:
        transcript_text: Full text of the Whisper transcript.

    Returns:
        List of trade dicts matching the Sheet schema.
    """
    if not GEMINI_API_KEY:
        raise ValueError(
            "GEMINI_API_KEY not set. Set it as an environment variable:\n"
            "  export GEMINI_API_KEY='your-key-here'\n"
            "Get a free key at: https://aistudio.google.com/apikey"
        )

    logger.info("Sending transcript to Gemini for structured extraction...")

    try:
        from google import genai
        from google.genai import types
    except ImportError:
        raise ImportError(
            "google-genai not installed. Install with:\n"
            "  pip install google-genai"
        )

    client = genai.Client(api_key=GEMINI_API_KEY)

    prompt = EXTRACTION_PROMPT.replace("{transcript_text}", transcript_text)

    try:
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.1,  # Low temp for deterministic extraction
                top_p=0.95,
                max_output_tokens=8192,
                response_mime_type="application/json",  # Force JSON output
            ),
        )
        raw_text = response.text.strip()
    except Exception as e:
        logger.error(f"Gemini API call failed: {e}")
        raise

    # Parse JSON response
    try:
        trades = json.loads(raw_text)
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse Gemini response as JSON: {e}")
        logger.error(f"Raw response (first 500 chars): {raw_text[:500]}")
        # Try to extract JSON from markdown fences if present
        if "```json" in raw_text:
            json_str = raw_text.split("```json")[1].split("```")[0].strip()
            trades = json.loads(json_str)
        elif "```" in raw_text:
            json_str = raw_text.split("```")[1].split("```")[0].strip()
            trades = json.loads(json_str)
        else:
            raise

    # Ensure we have a list
    if isinstance(trades, dict):
        trades = [trades]

    logger.info(f"Extracted {len(trades)} trade(s) from transcript.")

    # Validate and clean each trade
    for i, trade in enumerate(trades):
        trade["trade_number"] = trade.get("trade_number", i + 1)
        # Ensure direction is normalized
        if trade.get("direction"):
            trade["direction"] = trade["direction"].capitalize()
            if trade["direction"] not in ("Long", "Short"):
                logger.warning(f"Trade {i+1}: unexpected direction '{trade['direction']}'")

    return trades


# ─────────────────────────────────────────────
# CLI entry point
# ─────────────────────────────────────────────
if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python parse_trade.py <transcript_json_path>")
        sys.exit(1)

    transcript_file = Path(sys.argv[1])
    with open(transcript_file) as f:
        transcript_data = json.load(f)

    transcript_text = transcript_data.get("text", "")
    trades = parse_trades_from_transcript(transcript_text)

    print(f"\nExtracted {len(trades)} trade(s):")
    print(json.dumps(trades, indent=2))
