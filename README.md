# FX Journal Pipeline

**Automated backtesting journal for FX traders.** Record your FX Replay session, narrate your trades, and this pipeline automatically logs everything to Google Sheets — trade math, reasoning, and chart screenshots.

## How It Works

```
You record video → Whisper transcribes → Gemini extracts data → Google Sheets logs it
```

1. **Record** your FX Replay session with screen + mic (OBS, QuickTime, etc.)
2. **Narrate** using the verbal protocol (say prices, reasoning, "direction screenshot", etc.)
3. **Drop** the video file into `~/FXBacktest/inbox/`
4. **Pipeline auto-fires**: transcription → extraction → screenshots → Google Sheet

## Quick Start

```bash
# 1. Run setup (installs everything)
chmod +x setup.sh
./setup.sh

# 2. Configure your API keys
cp .env.example .env
nano .env  # Add your GEMINI_API_KEY and GOOGLE_DRIVE_FOLDER_ID

# 3. Set up Google credentials
# → Follow the instructions printed by setup.sh

# 4. Start the watcher
source venv/bin/activate
python scripts/watch_inbox.py

# 5. Drop a video into ~/FXBacktest/inbox/ and watch the magic happen
```

## Project Structure

```
fx-journal-pipeline/
├── config/
│   └── settings.py          # All configurable settings
├── scripts/
│   ├── transcribe.py        # Whisper audio transcription
│   ├── extract_frames.py    # Screenshot extraction at keyword timestamps
│   ├── parse_trade.py       # Gemini LLM trade data extraction
│   ├── upload.py            # Google Sheets + Drive integration
│   ├── process_video.py     # Master orchestration (chains all steps)
│   └── watch_inbox.py       # Folder watcher (standalone alternative to n8n)
├── n8n/
│   └── fx_journal_workflow.json  # Importable n8n workflow
├── tests/                   # Unit tests
├── setup.sh                 # One-shot Mac Mini M1 setup
├── .env.example             # Environment variable template
├── requirements.txt         # Python dependencies
├── com.fxjournal.watcher.plist  # macOS auto-start service
└── README.md
```

## Verbal Protocol (Follow This!)

For reliable data extraction, follow this pattern for each trade:

```
1. "Starting trade [N] on [PAIR], [DATE], [SESSION] session"
2. "Direction analysis" → pause on HTF chart
   → Explain your directional bias
   → "Direction screenshot" → hold still 1 second
3. "Location analysis" → pause on MTF chart
   → Explain your location reasoning
   → "Location screenshot" → hold still 1 second
4. "Execution" → explain the model/pattern
   → "Entry at [X], stop loss at [X], take profit at [X]"
   → "Execution screenshot" → hold still 1 second
5. After trade plays out:
   → "Trade closed at [X], outcome [WIN/LOSS/BE]"
   → "MAE was [X] pips, MFE was [X] pips"
6. "Ending trade [N]"
```

## Auto-Start on Boot (Optional)

To have the watcher start automatically when your Mac boots:

```bash
cp com.fxjournal.watcher.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.fxjournal.watcher.plist
```

## Cost

| Component | Monthly Cost |
|---|---|
| Whisper (local) | ₹0 |
| FFmpeg (local) | ₹0 |
| Gemini API | ₹0–200 |
| Google Sheets/Drive | ₹0 |
| **Total** | **₹0–200/month** |

## Troubleshooting

- **Whisper too slow**: Try the smaller model in `config/settings.py`: `WHISPER_MODEL = "mlx-community/whisper-small"`
- **Gemini errors**: Check your API key in `.env`. Free tier = 1,500 requests/day.
- **Sheet not updating**: Ensure you shared the Sheet with the service account email.
- **Logs**: Check `~/FXBacktest/logs/` for pipeline execution logs.

## 🤖 AI Bootstrap / Disaster Recovery

If you get a new computer, lose this project, or want to hand this over to another AI assistant (like a fresh Antigravity session), just copy and paste this exact prompt to the AI:

> *"Hi, I have a backtesting video automation project hosted on GitHub here: `https://github.com/anshumandash786-jpg/fx-journal-pipeline.git`. Please clone this repository to a new scratch folder. Read the `README.md`, `walkthrough.md`, and the python scripts to understand how the pipeline works. Please guide me through setting up the `.env` API keys and running the `setup.sh` file to get this working on my machine. If I face any issues, please help me debug and execute the pipeline."*
