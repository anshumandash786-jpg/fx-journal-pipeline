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

    # Build the row (45 columns, matching actual Google Sheet schema)
    row = [
        # Col 1-5: Trade Identification
        trade_id,                                    # 1. Trade ID
        trade.get("date") or "",                     # 2. Date
        trade.get("entry_time") or "",               # 3. Entry Time
        pair,                                        # 4. Pair
        trade.get("session") or "",                  # 5. Session
        
        # Col 6-12: Core Trade Mechanics
        direction,                                   # 6. Direction
        entry or "",                                 # 7. Entry Price
        sl or "",                                    # 8. Stop Loss
        tp or "",                                    # 9. Take Profit
        exit_price or "",                            # 10. Exit Price
        trade.get("exit_time") or "",                # 11. Exit Time
        trade.get("outcome") or "",                  # 12. Outcome
        
        # Col 13-19: Core Metrics & Hidden Calcs
        sl_pips or "",                               # 13. SL Pips (M)
        tp_pips or "",                               # 14. TP Pips (N)
        result_pips or "",                           # 15. Result Pips (O)
        rr_ratio or "",                              # 16. RR Ratio (P)
        r_multiple or "",                            # 17. R-Multiple (Q)
        pnl_dollars or "",                           # 18. P&L ($) (R)
        pos_size or "",                              # 19. Position Size (S)
        
        # Col 20-24: Risk Analytics
        mae or "",                                   # 20. MAE Pips (T)
        mfe or "",                                   # 21. MFE Pips (U)
        mae_pct_sl or "",                            # 22. MAE % of SL (V)
        mfe_pct_tp or "",                            # 23. MFE % of TP (W)
        trade.get("trade_duration") or "",           # 24. Trade Duration (X)

        # Col 25-32: Trade Reasoning
        trade.get("htf_reference") or "",            # 25. HTF Reference (Y)
        trade.get("direction_thesis") or "",         # 26. Direction Thesis (Z)
        trade.get("location_zone_type") or "",       # 27. Location Zone (AA)
        trade.get("location_timeframe") or "",       # 28. Location TF (AB)
        trade.get("location_thesis") or "",          # 29. Location Thesis (AC)
        trade.get("execution_model_name") or "",     # 30. Execution Model (AD)
        trade.get("execution_timeframe") or "",      # 31. Execution TF (AE)
        trade.get("execution_thesis") or "",         # 32. Execution Thesis (AF)
        
        # Col 33-38: Confluence & Review
        trade.get("positive_confluence_list") or "", # 33. +ve Confluence List (AG)
        trade.get("negative_confluence_list") or "", # 34. -ve Confluence List (AH)
        trade.get("confluence_score") or "",         # 35. Confluence (OLD) (AI)
        trade.get("pre_trade_conviction") or "",     # 36. Conviction (AJ)
        trade.get("mistakes_noted") or "",           # 37. Mistakes (AK)
        trade.get("post_trade_review") or "",        # 38. Post-Trade Review (AL)

        # Col 39-41: Visual Evidence
        screenshot_links.get("direction", ""),       # 39. Dir Screenshot (AM)
        screenshot_links.get("location", ""),        # 40. Loc Screenshot (AN)
        screenshot_links.get("execution", ""),       # 41. Exec Screenshot (AO)

        # Col 42-45: Performance Analytics — ALL FORMULAS in Sheet
        "",  # 42. Cumulative R (formula) (AP)
        "",  # 43. Cumulative P&L (formula) (AQ)
        "",  # 44. Equity Peak (formula) (AR)
        "",  # 45. Drawdown ($) (formula) (AS)
    ]

    return row


def get_next_week_trade_id(week_num: int) -> str:
    """
    Generate the next trade ID by checking the Sheet for existing entries.
    Format: W{week_num}-T{trade_num} (e.g., W3-T4)
    """
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
            return f"W{week_num}-T1"

        # Get all values in column A (Trade ID)
        trade_ids = worksheet.col_values(1)

        prefix = f"W{week_num}-T"
        matching = [tid for tid in trade_ids if tid.startswith(prefix)]

        if matching:
            last_num = max(int(tid.split("-T")[-1]) for tid in matching)
            return f"{prefix}{last_num + 1}"
        else:
            return f"{prefix}1"

    except Exception as e:
        logger.warning(f"Could not fetch existing trade IDs: {e}")
        return f"W{week_num}-T1"


def append_trades_to_sheet(trades: list[dict], all_screenshot_links: list[dict], trade_ids: list[str] = None) -> tuple[int, list[str]]:
    """
    Append one or more trade rows to the Google Sheet.

    Args:
        trades: List of trade dicts from parse_trade.py
        all_screenshot_links: List of screenshot link dicts (one per trade)
        trade_ids: Optional list of trade IDs. If not provided, basic ones are generated.

    Returns:
        Tuple of (number of rows appended, list of trade IDs generated/used).
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
    used_trade_ids = []
    
    for i, trade in enumerate(trades):
        if trade_ids and i < len(trade_ids):
            trade_id = trade_ids[i]
        else:
            # Fallback if no trade_ids provided
            pair = (trade.get("pair") or "UNKNOWN").upper().replace("/", "")
            trade_id = f"{pair}-T{i+1}"
            
        used_trade_ids.append(trade_id)
        screenshot_links = all_screenshot_links[i] if i < len(all_screenshot_links) else {}

        row = build_sheet_row(trade, screenshot_links, trade_id)

        # Convert all values to strings for Sheets API compatibility
        row = [str(v) if v is not None else "" for v in row]

        worksheet.append_row(row, value_input_option="USER_ENTERED")
        logger.info(f"Appended trade {trade_id} to Sheet.")
        rows_added += 1

    logger.info(f"Total rows appended: {rows_added}")
    return rows_added, used_trade_ids


def get_sheet_headers() -> list[str]:
    """Return the 45-column header row for the Google Sheet."""
    return [
        "Trade ID", "Date", "Entry Time", "Pair", "Session", 
        "Direction", "Entry Price", "Stop Loss", "Take Profit", "Exit Price", 
        "Exit Time", "Outcome", "SL Pips", "TP Pips", "Result Pips", 
        "RR Ratio", "R-Multiple", "P&L ($)", "Position Size", "MAE Pips", 
        "MFE Pips", "MAE % of SL", "MFE % of TP", "Trade Duration", "HTF Reference", 
        "Direction Thesis", "Location Zone", "Location TF", "Location Thesis", "Execution Model", 
        "Execution TF", "Execution Thesis", "+ve Confluence List", "-ve Confluence List", "Confluence", 
        "Conviction", "Mistakes", "Post-Trade Review", "Dir Screenshot", "Loc Screenshot", 
        "Exec Screenshot", "Cumulative R", "Cumulative P&L", "Equity Peak", "Drawdown ($)"
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
