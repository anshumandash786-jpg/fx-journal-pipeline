"""
upload.py — Google Sheets & Google Drive integration.

Uploads screenshots to a Google Drive folder and appends structured
trade data as rows to a Google Sheet.

Requires:
    - A Google Cloud Service Account with Sheets API + Drive API enabled
    - The service account's email added as an editor on the Google Sheet
    - The service account's email added as a contributor on the Drive folder

Usage:
    python upload.py  (called programmatically by process_video.py)
"""

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config.settings import (
    GOOGLE_CREDENTIALS_FILE,
    GOOGLE_DRIVE_FOLDER_ID,
    GOOGLE_SHEET_ID,
    SHEET_TAB_NAME,
    DEFAULT_POSITION_SIZE,
    DEFAULT_RISK_PERCENT,
    ACCOUNT_CURRENCY,
    PIP_MULTIPLIERS,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("upload")


def get_google_credentials():
    """Load Google Service Account credentials."""
    creds_path = Path(GOOGLE_CREDENTIALS_FILE)
    if not creds_path.exists():
        raise FileNotFoundError(
            f"Google credentials not found at: {creds_path}\n\n"
            "Setup instructions:\n"
            "1. Go to https://console.cloud.google.com/\n"
            "2. Create a project (or use existing)\n"
            "3. Enable 'Google Sheets API' and 'Google Drive API'\n"
            "4. Create a Service Account → Keys → JSON\n"
            "5. Download the JSON file and save it to:\n"
            f"   {creds_path}\n"
            "6. Share your Google Sheet with the service account email\n"
            "   (the email ending in @*.iam.gserviceaccount.com)"
        )

    from google.oauth2.service_account import Credentials

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive.file",
    ]
    return Credentials.from_service_account_file(str(creds_path), scopes=scopes)


def upload_screenshot_to_drive(file_path: Path, filename: str = None) -> str:
    """
    Upload a screenshot to Google Drive and return the shareable link.

    Args:
        file_path: Path to the screenshot PNG file.
        filename: Optional custom filename for Drive.

    Returns:
        Shareable URL string.
    """
    if not GOOGLE_DRIVE_FOLDER_ID:
        logger.warning("GOOGLE_DRIVE_FOLDER_ID not set. Skipping Drive upload.")
        return f"[LOCAL] {file_path}"

    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload

    creds = get_google_credentials()
    service = build("drive", "v3", credentials=creds)

    file_metadata = {
        "name": filename or file_path.name,
        "parents": [GOOGLE_DRIVE_FOLDER_ID],
    }

    media = MediaFileUpload(str(file_path), mimetype="image/png")

    uploaded = (
        service.files()
        .create(body=file_metadata, media_body=media, fields="id,webViewLink")
        .execute()
    )

    # Make the file viewable by anyone with the link
    service.permissions().create(
        fileId=uploaded["id"],
        body={"type": "anyone", "role": "reader"},
    ).execute()

    link = uploaded.get("webViewLink", f"https://drive.google.com/file/d/{uploaded['id']}/view")
    logger.info(f"Uploaded {file_path.name} → {link}")
    return link


def upload_screenshots(screenshots: dict, trade_label: str) -> dict:
    """
    Upload all screenshots for a trade to Google Drive.

    Args:
        screenshots: Dict of {type: Path} from extract_frames.py
        trade_label: Label for naming (e.g., 'EURUSD_2025-06-15_T1')

    Returns:
        Dict of {type: URL} with Drive links.
    """
    links = {}
    for stype, filepath in screenshots.items():
        filepath = Path(filepath)
        if filepath.exists():
            drive_filename = f"{trade_label}_{stype}.png"
            try:
                link = upload_screenshot_to_drive(filepath, drive_filename)
                links[stype] = link
            except Exception as e:
                logger.error(f"Failed to upload {stype} screenshot: {e}")
                links[stype] = f"[UPLOAD FAILED] {filepath}"
        else:
            logger.warning(f"Screenshot file not found: {filepath}")
            links[stype] = ""

    return links


def get_pip_multiplier(pair: str) -> int:
    """Get the pip multiplier for a currency pair."""
    if pair and "JPY" in pair.upper():
        return PIP_MULTIPLIERS["JPY"]
    return PIP_MULTIPLIERS["default"]


def build_sheet_row(trade: dict, screenshot_links: dict, trade_id: str) -> list:
    """
    Build a single row for the Google Sheet from trade data and screenshot links.
    Matches the 52-column schema from the implementation plan.

    Columns that are formulas in the Sheet are left empty (the Sheet formulas will compute them).
    """
    pair = trade.get("pair") or ""
    entry = trade.get("entry_price")
    sl = trade.get("stop_loss")
    tp = trade.get("take_profit")
    exit_price = trade.get("exit_price")
    direction = trade.get("direction") or ""
    pos_size = trade.get("position_size_lots") or DEFAULT_POSITION_SIZE
    risk_pct = trade.get("risk_percent") or DEFAULT_RISK_PERCENT

    # Calculate pip values where we have the data
    pip_mult = get_pip_multiplier(pair)
    risk_pips = abs(entry - sl) * pip_mult if entry and sl else None
    reward_pips = abs(tp - entry) * pip_mult if tp and entry else None
    rr_ratio = round(reward_pips / risk_pips, 2) if reward_pips and risk_pips else None

    pnl_pips = None
    realized_r = None
    if exit_price and entry and sl:
        sign = 1 if direction.lower() == "long" else -1
        pnl_pips = round((exit_price - entry) * sign * pip_mult, 1)
        if risk_pips:
            realized_r = round(pnl_pips / risk_pips, 2)

    mae = trade.get("mae_pips")
    mfe = trade.get("mfe_pips")
    mae_pct_sl = round(mae / risk_pips, 2) if mae and risk_pips else None
    mfe_pct_tp = round(mfe / reward_pips, 2) if mfe and reward_pips else None

    max_r = trade.get("max_r_available")
    r_capture = round(realized_r / max_r, 2) if realized_r and max_r else None

    # Build the row (52 columns, matching schema order)
    row = [
        # Block 1: Trade Identification (cols 1-8)
        trade_id,                                    # Trade ID
        trade.get("date") or "",                     # Date
        "",                                          # Day (formula in Sheet)
        "",                                          # Week Num (formula in Sheet)
        trade.get("session") or "",                  # Session
        pair,                                        # Pair
        trade.get("trade_type") or "Intraday",       # Trade Type
        direction,                                   # Direction

        # Block 2: Trade Mechanics (cols 9-31)
        entry or "",                                 # Entry Price
        sl or "",                                    # Stop Loss
        tp or "",                                    # Take Profit
        trade.get("scale_in_1") or "",               # Scale-In Price 1
        trade.get("scale_in_2") or "",               # Scale-In Price 2
        trade.get("scale_out_1") or "",              # Scale-Out Price 1
        trade.get("scale_out_2") or "",              # Scale-Out Price 2
        pos_size,                                    # Position Size (lots)
        risk_pct,                                    # Risk %
        risk_pips or "",                             # Risk (pips)
        reward_pips or "",                           # Reward (pips)
        rr_ratio or "",                              # Planned RR
        trade.get("outcome") or "",                  # Outcome
        exit_price or "",                            # Exit Price
        pnl_pips or "",                              # P&L (pips)
        realized_r or "",                            # Realized R-Multiple
        max_r or "",                                 # Maximum R Available
        r_capture or "",                             # R Capture Efficiency
        mae or "",                                   # MAE (pips)
        mfe or "",                                   # MFE (pips)
        mae_pct_sl or "",                            # MAE as % of SL
        mfe_pct_tp or "",                            # MFE as % of TP
        trade.get("trade_duration") or "",           # Trade Duration

        # Block 3: Trade Reasoning (cols 32-44)
        trade.get("htf_reference") or "",            # HTF Reference
        trade.get("direction_thesis") or "",         # Direction Thesis
        trade.get("location_zone_type") or "",       # Location Zone Type
        trade.get("location_timeframe") or "",       # Location Timeframe
        trade.get("location_thesis") or "",          # Location Thesis
        trade.get("execution_model_name") or "",     # Execution Model Name
        trade.get("execution_timeframe") or "",      # Execution Timeframe
        trade.get("execution_thesis") or "",         # Execution Thesis
        trade.get("confluence_score") or "",         # Confluence Score (1-5)
        trade.get("pre_trade_conviction") or "",     # Pre-Trade Conviction (1-5)
        trade.get("mistakes_noted") or "",           # Mistakes Noted
        trade.get("post_trade_review") or "",        # Post-Trade Review
        trade.get("early_exit_reason") or "",        # Early Exit Reason

        # Block 4: Visual Evidence (cols 45-47)
        screenshot_links.get("direction", ""),       # Direction Screenshot
        screenshot_links.get("location", ""),        # Location Screenshot
        screenshot_links.get("execution", ""),       # Execution Screenshot

        # Block 5: Performance Analytics (cols 48-52) — ALL FORMULAS in Sheet
        "",  # Equity Curve (formula)
        "",  # Running Peak (formula)
        "",  # Drawdown (formula)
        "",  # Cumulative R (formula)
        "",  # Win Rate rolling 20 (formula)
    ]

    return row


def get_next_trade_id(pair: str) -> str:
    """
    Generate the next trade ID by checking the Sheet for existing entries.
    Format: PAIR-YYYY-NNN (e.g., EURUSD-2025-014)
    """
    import datetime

    try:
        import gspread

        creds = get_google_credentials()
        gc = gspread.authorize(creds)
        sheet = gc.open_by_key(GOOGLE_SHEET_ID)

        try:
            worksheet = sheet.worksheet(SHEET_TAB_NAME)
        except gspread.WorksheetNotFound:
            # Create the tab if it doesn't exist
            worksheet = sheet.add_worksheet(title=SHEET_TAB_NAME, rows=1000, cols=52)
            return f"{pair}-{datetime.datetime.now().year}-001"

        # Get all values in column A (Trade ID)
        trade_ids = worksheet.col_values(1)

        # Filter for this pair and year
        year = datetime.datetime.now().year
        prefix = f"{pair}-{year}-"
        matching = [tid for tid in trade_ids if tid.startswith(prefix)]

        if matching:
            last_num = max(int(tid.split("-")[-1]) for tid in matching)
            return f"{prefix}{last_num + 1:03d}"
        else:
            return f"{prefix}001"

    except Exception as e:
        logger.warning(f"Could not fetch existing trade IDs: {e}")
        return f"{pair}-{datetime.datetime.now().year}-001"


def append_trades_to_sheet(trades: list[dict], all_screenshot_links: list[dict]) -> int:
    """
    Append one or more trade rows to the Google Sheet.

    Args:
        trades: List of trade dicts from parse_trade.py
        all_screenshot_links: List of screenshot link dicts (one per trade)

    Returns:
        Number of rows appended.
    """
    try:
        import gspread
    except ImportError:
        raise ImportError("gspread not installed. Install with: pip install gspread")

    creds = get_google_credentials()
    gc = gspread.authorize(creds)
    sheet = gc.open_by_key(GOOGLE_SHEET_ID)

    try:
        worksheet = sheet.worksheet(SHEET_TAB_NAME)
    except Exception:
        # Create the worksheet with headers if it doesn't exist
        worksheet = sheet.add_worksheet(title=SHEET_TAB_NAME, rows=1000, cols=52)
        headers = get_sheet_headers()
        worksheet.append_row(headers, value_input_option="USER_ENTERED")
        logger.info(f"Created '{SHEET_TAB_NAME}' tab with headers.")

    # Check if headers exist
    first_row = worksheet.row_values(1)
    if not first_row or first_row[0] != "Trade ID":
        headers = get_sheet_headers()
        worksheet.insert_row(headers, index=1, value_input_option="USER_ENTERED")
        logger.info("Inserted header row.")

    rows_added = 0
    for i, trade in enumerate(trades):
        pair = (trade.get("pair") or "UNKNOWN").upper().replace("/", "")
        trade_id = get_next_trade_id(pair)
        screenshot_links = all_screenshot_links[i] if i < len(all_screenshot_links) else {}

        row = build_sheet_row(trade, screenshot_links, trade_id)

        # Convert all values to strings for Sheets API compatibility
        row = [str(v) if v is not None else "" for v in row]

        worksheet.append_row(row, value_input_option="USER_ENTERED")
        logger.info(f"Appended trade {trade_id} to Sheet.")
        rows_added += 1

    logger.info(f"Total rows appended: {rows_added}")
    return rows_added


def get_sheet_headers() -> list[str]:
    """Return the 52-column header row for the Google Sheet."""
    return [
        # Block 1: Trade Identification
        "Trade ID", "Date", "Day", "Week Num", "Session", "Pair", "Trade Type", "Direction",
        # Block 2: Trade Mechanics
        "Entry Price", "Stop Loss", "Take Profit",
        "Scale-In 1", "Scale-In 2", "Scale-Out 1", "Scale-Out 2",
        "Position Size (lots)", "Risk %",
        "Risk (pips)", "Reward (pips)", "Planned RR",
        "Outcome", "Exit Price", "P&L (pips)", "Realized R",
        "Max R Available", "R Capture %",
        "MAE (pips)", "MFE (pips)", "MAE % of SL", "MFE % of TP",
        "Trade Duration",
        # Block 3: Trade Reasoning
        "HTF Reference", "Direction Thesis",
        "Location Zone Type", "Location TF", "Location Thesis",
        "Execution Model", "Execution TF", "Execution Thesis",
        "Confluence (1-5)", "Conviction (1-5)",
        "Mistakes", "Post-Trade Review", "Early Exit Reason",
        # Block 4: Visual Evidence
        "Direction Screenshot", "Location Screenshot", "Execution Screenshot",
        # Block 5: Performance Analytics
        "Equity Curve", "Running Peak", "Drawdown (pips)", "Cumulative R", "Win Rate (R20)",
    ]


# ─────────────────────────────────────────────
# CLI entry point
# ─────────────────────────────────────────────
if __name__ == "__main__":
    # Quick test: print headers
    headers = get_sheet_headers()
    print(f"Sheet schema: {len(headers)} columns")
    for i, h in enumerate(headers, 1):
        print(f"  [{i:2d}] {h}")
