#!/bin/bash
# ═══════════════════════════════════════════════════════
# Backtesting Video Automation To google sheet — Process Backtesting Videos
# Double-click this file to process all videos in
# ~/Desktop/Backtested video/
# ═══════════════════════════════════════════════════════

# Get the project directory (where the pipeline code lives)
PROJECT_DIR="$HOME/.gemini/antigravity/scratch/fx-journal-pipeline"

# Activate virtual environment and run
cd "$PROJECT_DIR"
source venv/bin/activate
python scripts/run_pipeline.py
