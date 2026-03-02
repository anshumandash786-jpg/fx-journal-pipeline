#!/usr/bin/env python3
"""
run_pipeline.py — Desktop-friendly pipeline runner.

Processes all videos in ~/Desktop/Backtested video/ folder,
runs each through the full pipeline, and shows a results summary.

Usage:
    Double-click "Process Videos.command" on your Desktop
    — or —
    python run_pipeline.py
"""

import json
import sys
import time
from datetime import datetime
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from config.settings import SUPPORTED_VIDEO_EXTENSIONS
from scripts.process_video import process_video

# ─────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────
INBOX_DIR = Path.home() / "Desktop" / "Backtested video"
DONE_DIR = INBOX_DIR / "done"

# Ensure directories exist
INBOX_DIR.mkdir(parents=True, exist_ok=True)
DONE_DIR.mkdir(parents=True, exist_ok=True)


def print_banner():
    """Print a nice startup banner."""
    print()
    print("╔══════════════════════════════════════════════════════╗")
    print("║ 🏦 BACKTESTING VIDEO AUTOMATION TO GOOGLE SHEET 🏦  ║")
    print("╠══════════════════════════════════════════════════════╣")
    print(f"║  📂 Watching: ~/Desktop/Backtested video/            ║")
    print(f"║  🕐 Started:  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}                   ║")
    print("╚══════════════════════════════════════════════════════╝")
    print()


def find_videos() -> list[Path]:
    """Find all supported video files in the inbox."""
    videos = []
    for f in sorted(INBOX_DIR.iterdir()):
        if f.is_file() and f.suffix.lower() in SUPPORTED_VIDEO_EXTENSIONS:
            videos.append(f)
    return videos


def print_result(result: dict, elapsed: float):
    """Print a formatted result for a single video."""
    status = result["status"].upper()
    icon = "✅" if status == "SUCCESS" else "⚠️" if status == "PARTIAL" else "❌"

    print(f"\n  {icon} Status: {status}")
    print(f"  📊 Trades logged: {result['trades_logged']}")
    print(f"  📸 Screenshots uploaded: {result['screenshots_uploaded']}")
    print(f"  ⏱️  Processing time: {elapsed:.1f}s")

    if result["errors"]:
        print(f"  ⚠️  Errors:")
        for err in result["errors"]:
            print(f"      • {err}")


def main():
    print_banner()

    # Find videos
    videos = find_videos()

    if not videos:
        print("  📭 No videos found in ~/Desktop/Backtested video/")
        print()
        print("  ℹ️  Drop your backtesting recordings (.mp4, .mov, .mkv, .webm)")
        print("     into the folder and run this again.")
        print()
        input("  Press Enter to exit...")
        return

    print(f"  📹 Found {len(videos)} video(s) to process:")
    for i, v in enumerate(videos, 1):
        size_mb = v.stat().st_size / (1024 * 1024)
        print(f"      {i}. {v.name} ({size_mb:.1f} MB)")
    print()

    # Process each video
    all_results = []
    total_trades = 0

    for i, video in enumerate(videos, 1):
        print(f"  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        print(f"  🎬 [{i}/{len(videos)}] Processing: {video.name}")
        print(f"  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

        start_time = time.time()

        try:
            result = process_video(video)
        except Exception as e:
            result = {
                "status": "failed",
                "video": str(video),
                "trades_logged": 0,
                "screenshots_uploaded": 0,
                "errors": [str(e)],
            }

        elapsed = time.time() - start_time
        print_result(result, elapsed)
        all_results.append(result)
        total_trades += result["trades_logged"]

    # ── Final Summary ──────────────────────────
    print()
    print("╔══════════════════════════════════════════════════════╗")
    print("║                   📋 SUMMARY                        ║")
    print("╠══════════════════════════════════════════════════════╣")

    success = sum(1 for r in all_results if r["status"] == "success")
    partial = sum(1 for r in all_results if r["status"] == "partial")
    failed = sum(1 for r in all_results if r["status"] == "failed")

    print(f"║  Videos processed: {len(all_results):>3}                            ║")
    print(f"║  ✅ Success:       {success:>3}                            ║")
    if partial:
        print(f"║  ⚠️  Partial:       {partial:>3}                            ║")
    if failed:
        print(f"║  ❌ Failed:        {failed:>3}                            ║")
    print(f"║  📊 Total trades logged: {total_trades:>3}                       ║")
    print("╚══════════════════════════════════════════════════════╝")

    if total_trades > 0:
        print()
        print(f"  🔗 View your sheet:")
        print(f"     https://docs.google.com/spreadsheets/d/1mjLK-RlIiyghQbnqI9fTkgK86XtxsYzbj5WIkAK0JR4/edit")

    print()
    input("  Press Enter to exit...")


if __name__ == "__main__":
    main()
