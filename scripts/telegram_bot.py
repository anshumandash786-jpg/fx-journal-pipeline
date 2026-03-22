"""
telegram_bot.py — Telegram Bot for FX Journal Pipeline.

Receives videos (or Google Drive links) via Telegram, processes them
using the existing pipeline, and sends back a summary.

Features:
  - /trade caption → individual trade pipeline (Google Sheets + Notion Trades)
  - /day caption (or no caption) → daily markups pipeline (Notion Daily Markups)
  - Auto-downloads to /tmp, auto-deletes after processing
  - Sends "🟢 Online" on startup and processes queued messages
  - Sends rich summary feedback after processing

Usage:
    python scripts/telegram_bot.py
"""

import asyncio
import logging
import os
import re
import shutil
import sys
import tempfile
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

# ─────────────────────────────────────────────
# LOGGING
# ─────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("telegram_bot")

# Temp directory for downloaded videos (avoids cluttering the project)
TEMP_DIR = Path(tempfile.gettempdir()) / "fx_processing"
TEMP_DIR.mkdir(parents=True, exist_ok=True)


# ─────────────────────────────────────────────
# GOOGLE DRIVE LINK HANDLER
# ─────────────────────────────────────────────
def _extract_gdrive_id(text: str) -> str | None:
    """Extract Google Drive file ID from a shared link."""
    patterns = [
        r"drive\.google\.com/file/d/([a-zA-Z0-9_-]+)",
        r"drive\.google\.com/open\?id=([a-zA-Z0-9_-]+)",
        r"docs\.google\.com/.*?/d/([a-zA-Z0-9_-]+)",
    ]
    for p in patterns:
        m = re.search(p, text)
        if m:
            return m.group(1)
    return None


def _download_from_gdrive(file_id: str, output_path: Path) -> Path:
    """Download a file from Google Drive using gdown."""
    import gdown
    url = f"https://drive.google.com/uc?id={file_id}"
    logger.info(f"Downloading from Google Drive: {file_id}")
    gdown.download(url, str(output_path), quiet=False)
    if not output_path.exists():
        raise FileNotFoundError(f"Download failed: {output_path}")
    return output_path


# ─────────────────────────────────────────────
# PIPELINE RUNNERS
# ─────────────────────────────────────────────
def _run_trade_pipeline(video_path: Path) -> str:
    """Run the individual trade pipeline and return a summary message."""
    from scripts.process_video import process_video

    result = process_video(str(video_path))
    status = result.get("status", "failed")
    trades = result.get("trades_logged", 0)
    notion = result.get("notion_pages_created", 0)
    errors = result.get("errors", [])

    if status == "success":
        msg = f"✅ *Trade Pipeline Complete!*\n\n"
        msg += f"📊 *{trades} trade(s)* logged to Google Sheets\n"
        msg += f"📓 *{notion} page(s)* created in Notion\n"

        # Try to extract trade IDs from the result
        trade_ids = result.get("trade_ids", [])
        if trade_ids:
            msg += f"🏷️ Trade IDs: {', '.join(trade_ids)}\n"
    else:
        msg = f"⚠️ *Trade Pipeline Finished with Issues*\n\n"
        msg += f"📊 Trades logged: {trades}\n"
        msg += f"📓 Notion pages: {notion}\n"
        if errors:
            msg += f"\n❌ Errors:\n"
            for e in errors[:3]:  # Limit to 3 errors
                msg += f"  • {e[:100]}\n"

    return msg


def _run_day_pipeline(video_path: Path) -> str:
    """Run the daily markups pipeline and return a summary message."""
    from scripts.process_day import process_daily_video

    result = process_daily_video(str(video_path))
    status = result.get("status", "failed")
    errors = result.get("errors", [])

    if status == "success":
        msg = f"✅ *Daily Markups Complete!*\n\n"
        msg += f"📓 Notion daily card created\n"
        msg += f"📸 Screenshots extracted and uploaded\n"
    else:
        msg = f"⚠️ *Daily Markups Finished with Issues*\n\n"
        if errors:
            msg += f"❌ Errors:\n"
            for e in errors[:3]:
                msg += f"  • {e[:100]}\n"

    return msg


# ─────────────────────────────────────────────
# TELEGRAM HANDLERS
# ─────────────────────────────────────────────
async def _handle_start(update, context):
    """Handle /start command."""
    chat_id = update.message.chat_id
    logger.info(f"📱 /start from Chat ID: {chat_id} (user: {update.message.chat.first_name})")
    await update.message.reply_text(
        "👋 *FX Journal Bot is ready!*\n\n"
        "Send me a backtesting video and I'll process it.\n\n"
        "*Commands:*\n"
        "📹 Send video with caption `/trade` → Individual trade analysis\n"
        "📹 Send video with caption `/day` → Daily markups\n"
        "📹 Send video with no caption → Defaults to daily markups\n\n"
        "You can also send a Google Drive link!",
        parse_mode="Markdown",
    )


async def _handle_video(update, context):
    """Handle incoming video files."""
    message = update.message
    chat_id = str(message.chat_id)

    # Security: only accept from the authorized user
    if TELEGRAM_CHAT_ID and chat_id != TELEGRAM_CHAT_ID:
        await message.reply_text("⛔ Unauthorized. This bot is private.")
        return

    # Auto-save chat ID on first use if not set
    if not TELEGRAM_CHAT_ID:
        logger.info(f"First message! Your Chat ID is: {chat_id}")
        logger.info(f"Add this to .env: TELEGRAM_CHAT_ID={chat_id}")

    # Determine pipeline type from caption
    caption = (message.caption or "").strip().lower()
    is_trade = caption.startswith("/trade")
    pipeline_name = "Trade" if is_trade else "Daily Markups"

    # Send acknowledgment
    ack = await message.reply_text(
        f"⏳ *Processing {pipeline_name}...*\n\n"
        f"This may take 2-5 minutes. I'll send you a summary when done!",
        parse_mode="Markdown",
    )

    try:
        # Download video to /tmp
        video = message.video or message.document
        if not video:
            await message.reply_text("❌ No video found in message.")
            return

        file_ext = ".mp4"
        if video.file_name:
            file_ext = Path(video.file_name).suffix or ".mp4"

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        temp_path = TEMP_DIR / f"tg_{timestamp}{file_ext}"

        logger.info(f"Downloading video to {temp_path}...")
        tg_file = await context.bot.get_file(video.file_id)
        await tg_file.download_to_drive(str(temp_path))
        logger.info(f"Downloaded: {temp_path} ({temp_path.stat().st_size / 1024 / 1024:.1f} MB)")

        # Run the appropriate pipeline
        if is_trade:
            summary = _run_trade_pipeline(temp_path)
        else:
            summary = _run_day_pipeline(temp_path)

        # Send summary
        await message.reply_text(summary, parse_mode="Markdown")

    except Exception as e:
        logger.error(f"Processing failed: {e}")
        await message.reply_text(
            f"❌ *Processing Failed*\n\n{str(e)[:200]}",
            parse_mode="Markdown",
        )
    finally:
        # ALWAYS clean up temp files
        _cleanup_temp(temp_path if 'temp_path' in dir() else None)


async def _handle_text(update, context):
    """Handle text messages (Google Drive links)."""
    message = update.message
    chat_id = str(message.chat_id)
    text = message.text or ""

    # Security check
    if TELEGRAM_CHAT_ID and chat_id != TELEGRAM_CHAT_ID:
        await message.reply_text("⛔ Unauthorized.")
        return

    # Auto-save chat ID
    if not TELEGRAM_CHAT_ID:
        logger.info(f"First message! Your Chat ID is: {chat_id}")
        logger.info(f"Add this to .env: TELEGRAM_CHAT_ID={chat_id}")

    # Check for Google Drive link
    file_id = _extract_gdrive_id(text)
    if not file_id:
        await message.reply_text(
            "🤔 I didn't find a video or Drive link.\n\n"
            "Send me a video file or a Google Drive link!\n"
            "Use `/trade` or `/day` caption to choose the pipeline.",
            parse_mode="Markdown",
        )
        return

    # Determine pipeline from text
    is_trade = "/trade" in text.lower()
    pipeline_name = "Trade" if is_trade else "Daily Markups"

    ack = await message.reply_text(
        f"⏳ *Downloading from Google Drive & processing {pipeline_name}...*\n\n"
        f"This may take 3-8 minutes.",
        parse_mode="Markdown",
    )

    temp_path = None
    try:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        temp_path = TEMP_DIR / f"gdrive_{timestamp}.mp4"
        _download_from_gdrive(file_id, temp_path)

        if is_trade:
            summary = _run_trade_pipeline(temp_path)
        else:
            summary = _run_day_pipeline(temp_path)

        await message.reply_text(summary, parse_mode="Markdown")

    except Exception as e:
        logger.error(f"Processing failed: {e}")
        await message.reply_text(
            f"❌ *Processing Failed*\n\n{str(e)[:200]}",
            parse_mode="Markdown",
        )
    finally:
        _cleanup_temp(temp_path)


def _cleanup_temp(file_path: Path | None):
    """Delete the downloaded video and any generated screenshots."""
    if file_path and file_path.exists():
        try:
            file_path.unlink()
            logger.info(f"🗑️ Cleaned up: {file_path}")
        except Exception as e:
            logger.warning(f"Cleanup failed for {file_path}: {e}")

    # Also clean any screenshots generated during processing
    for f in TEMP_DIR.glob("*.png"):
        try:
            f.unlink()
        except Exception:
            pass


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────
def main():
    """Start the Telegram bot."""
    from telegram.ext import (
        ApplicationBuilder,
        CommandHandler,
        MessageHandler,
        filters,
    )

    if not TELEGRAM_BOT_TOKEN:
        print("❌ TELEGRAM_BOT_TOKEN not set in .env")
        print("   Get one from @BotFather on Telegram")
        sys.exit(1)

    logger.info("=" * 50)
    logger.info("FX Journal Telegram Bot Starting...")
    logger.info(f"Time: {datetime.now().isoformat()}")
    logger.info(f"Temp dir: {TEMP_DIR}")
    logger.info("=" * 50)

    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

    # Register handlers
    app.add_handler(CommandHandler("start", _handle_start))
    app.add_handler(CommandHandler("trade", _handle_start))  # /trade without video shows help
    app.add_handler(CommandHandler("day", _handle_start))     # /day without video shows help
    app.add_handler(MessageHandler(filters.VIDEO | filters.Document.VIDEO, _handle_video))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, _handle_text))

    # Send startup notification
    async def _send_startup(app):
        if TELEGRAM_CHAT_ID:
            try:
                await app.bot.send_message(
                    chat_id=int(TELEGRAM_CHAT_ID),
                    text="🟢 *FX Journal Bot is online!*\n\n"
                         f"Ready to process videos.\n"
                         f"_{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}_",
                    parse_mode="Markdown",
                )
            except Exception as e:
                logger.warning(f"Could not send startup message: {e}")

    app.post_init = _send_startup

    # Start polling (blocks forever)
    logger.info("Bot is polling for messages...")
    app.run_polling(drop_pending_updates=False)  # Process queued messages!


if __name__ == "__main__":
    main()
