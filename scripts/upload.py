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
    Matches the actual 41-column Google Sheet schema.

    Columns that are formulas in the Sheet are left empty (the Sheet formulas will compute them).
    """
    pair = trade.get("pair") or ""
    entry = trade.get("entry_price")
    sl = trade.get("stop_loss")
    tp = trade.get("take_profit")
    exit_price = trade.get("exit_price")
    direction = trade.get("direction") or ""
    pos_size = trade.get("position_size_lots") or DEFAULT_POSITION_SIZE

    # Calculate pip values where we have the data
    pip_mult = get_pip_multiplier(pair)
    sl_pips = round(abs(entry - sl) * pip_mult, 1) if entry and sl else None
    tp_pips = round(abs(tp - entry) * pip_mult, 1) if tp and entry else None
    rr_ratio = round(tp_pips / sl_pips, 2) if tp_pips and sl_pips else None

    result_pips = None
    r_multiple = None
    if exit_price and entry and sl:
        sign = 1 if direction.lower() == "long" else -1
        result_pips = round((exit_price - entry) * sign * pip_mult, 1)
        if sl_pips:
            r_multiple = round(result_pips / sl_pips, 2)

    # P&L in dollars (simplified: result_pips * 10 * lots for standard pairs)
    pnl_dollars = round(result_pips * 10 * pos_size, 2) if result_pips else None

    mae = trade.get("mae_pips")
    mfe = trade.get("mfe_pips")
    mae_pct_sl = round(mae / sl_pips * 100, 1) if mae and sl_pips else None
    mfe_pct_tp = round(mfe / tp_pips * 100, 1) if mfe and tp_pips else None

    # Build the row (41 columns, matching actual Google Sheet schema)
    row = [
        # Col 1-5: Trade Identification
        trade_id,                                    # 1. Trade ID
        trade.get("date") or "",                     # 2. Date
        pair,                                        # 3. Pair
        trade.get("session") or "",                  # 4. Session
        direction,                                   # 5. Direction

        # Col 6-10: Core Trade Mechanics
        entry or "",                                 # 6. Entry Price
        sl or "",                                    # 7. Stop Loss
        tp or "",                                    # 8. Take Profit
        exit_price or "",                            # 9. Exit Price
        trade.get("outcome") or "",                  # 10. Outcome

        # Col 11-17: Trade Metrics
        sl_pips or "",                               # 11. SL Pips
        tp_pips or "",                               # 12. TP Pips
        result_pips or "",                           # 13. Result Pips
        rr_ratio or "",                              # 14. RR Ratio
        r_multiple or "",                            # 15. R-Multiple
        pnl_dollars or "",                           # 16. P&L ($)
        pos_size,                                    # 17. Position Size

        # Col 18-22: Risk Analytics
        mae or "",                                   # 18. MAE Pips
        mfe or "",                                   # 19. MFE Pips
        mae_pct_sl or "",                            # 20. MAE % of SL
        mfe_pct_tp or "",                            # 21. MFE % of TP
        trade.get("trade_duration") or "",           # 22. Trade Duration

        # Col 23-34: Trade Reasoning
        trade.get("htf_reference") or "",            # 23. HTF Reference
        trade.get("direction_thesis") or "",         # 24. Direction Thesis
        trade.get("location_zone_type") or "",       # 25. Location Zone
        trade.get("location_timeframe") or "",       # 26. Location TF
        trade.get("location_thesis") or "",          # 27. Location Thesis
        trade.get("execution_model_name") or "",     # 28. Execution Model
        trade.get("execution_timeframe") or "",      # 29. Execution TF
        trade.get("execution_thesis") or "",         # 30. Execution Thesis
        trade.get("confluence_score") or "",         # 31. Confluence
        trade.get("pre_trade_conviction") or "",     # 32. Conviction
        trade.get("mistakes_noted") or "",           # 33. Mistakes
        trade.get("post_trade_review") or "",        # 34. Post-Trade Review

        # Col 35-37: Visual Evidence
        screenshot_links.get("direction", ""),       # 35. Dir Screenshot
        screenshot_links.get("location", ""),        # 36. Loc Screenshot
        screenshot_links.get("execution", ""),       # 37. Exec Screenshot

        # Col 38-41: Performance Analytics — ALL FORMULAS in Sheet
        "",  # 38. Cumulative R (formula)
        "",  # 39. Cumulative P&L (formula)
        "",  # 40. Equity Peak (formula)
        "",  # 41. Drawdown ($) (formula)
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
    """Return the 41-column header row for the Google Sheet."""
    return [
        # Trade Identification
        "Trade ID", "Date", "Pair", "Session", "Direction",
        # Core Trade Mechanics
        "Entry Price", "Stop Loss", "Take Profit", "Exit Price", "Outcome",
        # Trade Metrics
        "SL Pips", "TP Pips", "Result Pips", "RR Ratio", "R-Multiple",
        "P&L ($)", "Position Size",
        # Risk Analytics
        "MAE Pips", "MFE Pips", "MAE % of SL", "MFE % of TP",
        "Trade Duration",
        # Trade Reasoning
        "HTF Reference", "Direction Thesis",
        "Location Zone", "Location TF", "Location Thesis",
        "Execution Model", "Execution TF", "Execution Thesis",
        "Confluence", "Conviction",
        "Mistakes", "Post-Trade Review",
        # Visual Evidence
        "Dir Screenshot", "Loc Screenshot", "Exec Screenshot",
        # Performance Analytics (formulas)
        "Cumulative R", "Cumulative P&L", "Equity Peak", "Drawdown ($)",
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
