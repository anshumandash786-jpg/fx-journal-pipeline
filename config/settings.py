"""
FX Journal Pipeline — Configuration
All user-configurable settings in one place.
"""
import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env from the project root (Backtesting-Video-Automation-To-google-sheet/.env)
_project_root = Path(__file__).resolve().parent.parent
load_dotenv(_project_root / ".env")

# ─────────────────────────────────────────────
# PATHS
# ─────────────────────────────────────────────
BASE_DIR = Path.home() / "FXBacktest"
INBOX_DIR = BASE_DIR / "inbox"          # Drop videos here
PROCESSING_DIR = BASE_DIR / "processing"  # Videos being processed
DONE_DIR = BASE_DIR / "done"            # Completed videos
SCREENSHOTS_DIR = BASE_DIR / "screenshots"  # Extracted frames (temp)

# Create dirs on import
for d in [INBOX_DIR, PROCESSING_DIR, DONE_DIR, SCREENSHOTS_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# ─────────────────────────────────────────────
# WHISPER (Local Transcription)
# ─────────────────────────────────────────────
WHISPER_MODEL = "mlx-community/whisper-large-v3-turbo"
# Best publicly available MLX Whisper model (no HF auth needed)
# Note: whisper-large-v3 (non-turbo) is gated and requires HuggingFace login
#       whisper-large-v3-turbo is ~1-2% less accurate but publicly accessible
#       whisper-small is fastest but least accurate

# ─────────────────────────────────────────────
# GEMINI API
# ─────────────────────────────────────────────
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = "gemini-2.5-flash"
# Latest Flash model — fast and cost-effective

# ─────────────────────────────────────────────
# GOOGLE SHEETS
# ─────────────────────────────────────────────
GOOGLE_SHEET_ID = os.environ.get(
    "GOOGLE_SHEET_ID",
    "1mjLK-RlIiyghQbnqI9fTkgK86XtxsYzbj5WIkAK0JR4"
)
SHEET_TAB_NAME = "TradeLog"  # Tab name in the spreadsheet

# Path to the Google Service Account credentials JSON file
GOOGLE_CREDENTIALS_FILE = os.environ.get(
    "GOOGLE_CREDENTIALS_FILE",
    str(Path.home() / ".config" / "fx-journal" / "service-account.json")
)

# ─────────────────────────────────────────────
# GOOGLE DRIVE
# ─────────────────────────────────────────────
# Folder ID in Google Drive where screenshots will be uploaded
# (Create a folder in Drive → get the ID from URL)
GOOGLE_DRIVE_FOLDER_ID = os.environ.get("GOOGLE_DRIVE_FOLDER_ID", "")

# ─────────────────────────────────────────────
# NOTION
# ─────────────────────────────────────────────
NOTION_API_KEY = os.environ.get("NOTION_API_KEY", "")
NOTION_DATABASE_ID = os.environ.get("NOTION_DATABASE_ID", "")
NOTION_DAILY_MARKUPS_DATABASE_ID = os.environ.get("NOTION_DAILY_MARKUPS_DATABASE_ID", "")
NOTION_JOURNAL_PAGE_ID = os.environ.get("NOTION_JOURNAL_PAGE_ID", "")
# Auto-enable Notion if both values are set
NOTION_ENABLED = bool(NOTION_API_KEY and NOTION_DATABASE_ID)

# ─────────────────────────────────────────────
# Telegram Bot
# ─────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

# ─────────────────────────────────────────────
# TRADE DEFAULTS
# ─────────────────────────────────────────────
DEFAULT_POSITION_SIZE = 0.01  # lots
DEFAULT_RISK_PERCENT = 1.0    # percent of account
ACCOUNT_CURRENCY = "USD"

# Pip multiplier for different pair types
# JPY pairs: 1 pip = 0.01 → multiply by 100
# All others: 1 pip = 0.0001 → multiply by 10000
PIP_MULTIPLIERS = {
    "default": 10000,
    "JPY": 100,  # For pairs like USDJPY, EURJPY, GBPJPY etc.
}

# ─────────────────────────────────────────────
# SCREENSHOT KEYWORD TRIGGERS
# ─────────────────────────────────────────────
# Words/phrases in the transcript that trigger a screenshot extraction
SCREENSHOT_KEYWORDS = {
    "direction": [
        "direction screenshot",
        "direction analysis screenshot",
        "screenshot direction",
        "capture direction",
    ],
    "location": [
        "location screenshot",
        "location analysis screenshot",
        "screenshot location",
        "capture location",
    ],
    "execution": [
        "execution screenshot",
        "execution analysis screenshot",
        "screenshot execution",
        "capture execution",
    ],
}

# ─────────────────────────────────────────────
# VIDEO FORMATS
# ─────────────────────────────────────────────
SUPPORTED_VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm", ".avi"}

# ─────────────────────────────────────────────
# LOGGING
# ─────────────────────────────────────────────
LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_LEVEL = "INFO"
