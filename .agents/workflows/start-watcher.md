---
description: How to start the FX Journal watcher to automatically process new videos
---

### Purpose
This workflow starts the local folder watcher that monitors `~/FXBacktest/inbox` for new screen recordings.

### Steps
1. **Activate Environment**
   ```bash
   source venv/bin/activate
   ```

2. **Start the Watcher**
// turbo
   ```bash
   python scripts/watch_inbox.py
   ```

3. **Verification**
   - Check the console for "Starting to watch: /Users/ansumandash126/FXBacktest/inbox"
   - Drop a test `.mp4` into the folder to verify processing starts.
