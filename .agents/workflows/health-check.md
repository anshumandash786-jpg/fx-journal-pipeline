---
description: How to run a manual verification of the Google Sheets connection
---

### Purpose
Ensures the Gemini API and Google Sheets credentials are still valid.

### Steps
1. **Run Connection Test**
// turbo
   ```bash
   venv/bin/python -c "from scripts.upload import get_google_credentials; print('Auth Check:', 'SUCCESS' if get_google_credentials() else 'FAILED')"
   ```
