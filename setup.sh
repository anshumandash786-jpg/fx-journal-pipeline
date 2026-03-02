#!/bin/bash
# ═══════════════════════════════════════════════════════════════
# Backtesting Video Automation To google sheet — Mac Mini M1 Setup Script
# ═══════════════════════════════════════════════════════════════
#
# This script installs ALL dependencies on your Mac Mini M1.
# Run it once, then never again.
#
# Usage:
#   chmod +x setup.sh
#   ./setup.sh
#
# ═══════════════════════════════════════════════════════════════

set -e  # Exit on any error

echo "═══════════════════════════════════════════════════════════"
echo "  Backtesting Video Automation To google sheet — Setup (Mac Mini M1)"
echo "═══════════════════════════════════════════════════════════"
echo ""

# ── 1. Check for Homebrew ────────────────────────────────────
echo "▸ Step 1/6: Checking Homebrew..."
if ! command -v brew &> /dev/null; then
    echo "  Installing Homebrew..."
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    # Add to PATH for M1 Macs
    echo 'eval "$(/opt/homebrew/bin/brew shellenv)"' >> ~/.zprofile
    eval "$(/opt/homebrew/bin/brew shellenv)"
else
    echo "  ✓ Homebrew already installed"
fi

# ── 2. Install system dependencies ──────────────────────────
echo ""
echo "▸ Step 2/6: Installing system tools..."
brew install ffmpeg python@3.11 2>/dev/null || echo "  (some already installed)"
echo "  ✓ ffmpeg and Python 3.11 installed"

# ── 3. Create Python virtual environment ─────────────────────
echo ""
echo "▸ Step 3/6: Setting up Python environment..."

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$SCRIPT_DIR/venv"

if [ ! -d "$VENV_DIR" ]; then
    python3.11 -m venv "$VENV_DIR"
    echo "  ✓ Virtual environment created at $VENV_DIR"
else
    echo "  ✓ Virtual environment already exists"
fi

# Activate venv
source "$VENV_DIR/bin/activate"

# ── 4. Install Python dependencies ──────────────────────────
echo ""
echo "▸ Step 4/6: Installing Python packages (this may take a few minutes)..."
pip install --upgrade pip setuptools wheel -q
pip install -r "$SCRIPT_DIR/requirements.txt" -q
echo "  ✓ All Python packages installed"

# ── 5. Create folder structure ────────────────────────────────
echo ""
echo "▸ Step 5/6: Creating folder structure..."
mkdir -p ~/FXBacktest/inbox
mkdir -p ~/FXBacktest/processing
mkdir -p ~/FXBacktest/done
mkdir -p ~/FXBacktest/screenshots
mkdir -p ~/FXBacktest/logs
mkdir -p ~/.config/fx-journal
echo "  ✓ ~/FXBacktest/ directory structure created"
echo "    inbox/       → Drop your videos here"
echo "    processing/  → Videos being processed (auto)"
echo "    done/        → Completed videos (auto)"
echo "    screenshots/ → Extracted frames (auto)"
echo "    logs/        → Pipeline logs (auto)"

# ── 6. Check for Docker ──────────────────────────────────────
echo ""
echo "▸ Step 6/6: Checking Docker (for n8n)..."
if command -v docker &> /dev/null; then
    echo "  ✓ Docker is installed"
    
    # Check if n8n is already running
    if docker ps --format '{{.Names}}' | grep -q 'n8n'; then
        echo "  ✓ n8n is already running"
    else
        echo ""
        echo "  To start n8n, run:"
        echo "    docker run -d --name n8n -p 5678:5678 \\"
        echo "      -v n8n_data:/home/node/.n8n \\"
        echo "      -e GENERIC_TIMEZONE=Asia/Kolkata \\"
        echo "      --restart unless-stopped \\"
        echo "      n8nio/n8n"
        echo ""
        echo "  Then open: http://localhost:5678"
    fi
else
    echo "  ✗ Docker NOT installed."
    echo ""
    echo "  Install Docker Desktop for Mac (Apple Silicon):"
    echo "    https://docs.docker.com/desktop/install/mac-install/"
    echo ""
    echo "  After installing Docker, start n8n with:"
    echo "    docker run -d --name n8n -p 5678:5678 \\"
    echo "      -v n8n_data:/home/node/.n8n \\"
    echo "      -e GENERIC_TIMEZONE=Asia/Kolkata \\"
    echo "      --restart unless-stopped \\"
    echo "      n8nio/n8n"
fi

# ── Summary ──────────────────────────────────────────────────
echo ""
echo "═══════════════════════════════════════════════════════════"
echo "  SETUP COMPLETE"
echo "═══════════════════════════════════════════════════════════"
echo ""
echo "  Next steps:"
echo ""
echo "  1. Set up your .env file:"
echo "     cp .env.example .env"
echo "     nano .env"
echo "     → Add your GEMINI_API_KEY"
echo "     → Add your GOOGLE_DRIVE_FOLDER_ID"
echo ""
echo "  2. Set up Google credentials:"
echo "     → Go to https://console.cloud.google.com/"
echo "     → Create/select a project"
echo "     → Enable 'Google Sheets API' and 'Google Drive API'"
echo "     → Create Service Account → JSON key"
echo "     → Save to: ~/.config/fx-journal/service-account.json"
echo "     → Share your Google Sheet with the service account email"
echo ""
echo "  3. Get a Gemini API key (free):"
echo "     → Go to https://aistudio.google.com/apikey"
echo "     → Create API key"
echo "     → Add to .env file"
echo ""
echo "  4. Test the pipeline:"
echo "     source venv/bin/activate"
echo "     python scripts/process_video.py ~/FXBacktest/inbox/test.mp4"
echo ""
echo "═══════════════════════════════════════════════════════════"
