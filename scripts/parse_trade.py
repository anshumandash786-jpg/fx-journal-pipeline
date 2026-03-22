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
EXTRACTION_PROMPT = """You are an expert FX trade journal analyst. Read the transcript of a backtesting session and extract structured trade data.

The trader uses ICT/SMC methodology and analyzes trades in 3 stages:
1. **Direction** — HTF bias (why price should move a certain way)
2. **Location** — The zone/area for entry (OB, FVG, breaker, demand/supply, etc.)
3. **Execution** — The entry model/pattern (CHoCH, BOS, MSS, CISD, etc.)

CRITICAL RULES:
- Extract ALL trades mentioned (there may be 1 or more).
- For prices, extract the EXACT numbers spoken. Do not guess.
- If a field is not mentioned, set it to null.
- For direction: ONLY "Long" or "Short".
- For outcome: ONLY "Win", "Loss", "Breakeven", or "Partial".
- For session: ONLY "Asian", "London", "NY AM", "NY PM", or "London-NY Overlap".
- Confluence/conviction: integers 1-5. If not mentioned, null.
- Trade duration: string like "45 min" or "2 hours". If not mentioned, null.
- Confluence lists: Extract any positive confluences (+ve) and negative confluences (-ve) mentioned into comma-separated strings.
- Times: Extract entry time and exit time if spoken (e.g. "10:30 AM", "14:15").

PAIR IDENTIFICATION:
- If the trader says the pair name, use it (e.g. "EURUSD", "cable" = GBPUSD, "fiber" = EURUSD).
- If NOT explicitly mentioned, INFER from the price levels:
  - 1.0xxx–1.1xxx range → likely EURUSD or GBPUSD (check 5-digit vs 4-digit precision)
  - 1.2xxx–1.3xxx range → likely GBPUSD
  - 0.6xxx–0.7xxx range → likely AUDUSD or NZDUSD
  - 1xx.xxx range → likely USDJPY
  - If unsure, set to null.

THESIS FIELDS — VERY IMPORTANT:
- Do NOT copy raw transcript text. The trader speaks casually and uses filler words.
- SUMMARIZE each thesis into 1-2 crisp, professional sentences using proper ICT/SMC terminology.
- Write as if you are filling a professional trade journal that the trader will review later.
- Examples of good thesis writing:
  - Direction: "Bearish HTF bias. D1 BOS to downside with H4 pullback into premium. Expecting continuation lower."
  - Location: "M15 supply zone / OB at the origin of the impulsive leg down. Last supply before BOS."
  - Execution: "M1 CHoCH confirmation after liquidity sweep of Asian high. Entered on the demand retest."

MISTAKES & REVIEW:
- If the trader mentions any mistakes, hesitations, or self-corrections, capture them concisely.
- If the trader gives a post-trade review (e.g. "this was a 3.84R trade"), summarize it.

Return a JSON array of trade objects with this structure:

[
  {
    "trade_number": 1,
    "date": "YYYY-MM-DD or null",
    "entry_time": "HH:MM AM/PM or null",
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
    "risk_percent": null,

    "outcome": "Win / Loss / Breakeven / Partial / null",
    "exit_price": null,
    "exit_time": "HH:MM AM/PM or null",
    "mae_pips": null,
    "mfe_pips": null,
    "max_r_available": null,
    "trade_duration": null,

    "direction_thesis": "1-2 crisp sentences summarizing HTF directional bias and reasoning",
    "location_zone_type": "OB / FVG / Breaker / Demand / Supply / BOS level / etc. or null",
    "location_thesis": "1-2 crisp sentences on why this zone was chosen",
    "execution_model_name": "CHoCH / BOS / MSS / CISD / FVG entry / OB mitigation / etc. or null",
    "execution_thesis": "1-2 crisp sentences on the entry trigger and confirmation",

    "positive_confluence_list": "Comma-separated list of positive confluences or null",
    "negative_confluence_list": "Comma-separated list of negative confluences or null",
    "pre_trade_conviction": null,
    "mistakes_noted": "Concise summary of mistakes or null",
    "post_trade_review": "Concise summary of post-trade observations or null",
    "early_exit_reason": null
  }
]

TRANSCRIPT:
\"\"\"
{transcript_text}
\"\"\"

Extract all trades. Summarize thesis fields — do NOT copy transcript verbatim. Return ONLY the JSON array."""


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
