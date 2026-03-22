"""
modules/shared/config.py

Single source of truth for environment variables, paths, and API scopes.
All other modules import from here — do not duplicate these values elsewhere.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).parent.parent.parent  # project root
load_dotenv(ROOT / ".env")

# ---------------------------------------------------------------------------
# Google OAuth
# ---------------------------------------------------------------------------
SCOPES_SHEETS = ["https://www.googleapis.com/auth/spreadsheets"]
SCOPES_GMAIL  = ["https://www.googleapis.com/auth/gmail.readonly"]
SCOPES_ALL    = SCOPES_SHEETS + SCOPES_GMAIL

TOKEN_PATH       = str(ROOT / os.getenv("GOOGLE_TOKEN_PATH", "token.json"))
CREDENTIALS_PATH = str(ROOT / os.getenv("GOOGLE_CREDENTIALS_PATH", "credentials.json"))

# ---------------------------------------------------------------------------
# Google Sheets tracker
# ---------------------------------------------------------------------------
SHEET_ID  = os.getenv("GOOGLE_SHEET_ID", "")
SHEET_TAB = os.getenv("GOOGLE_SHEET_TAB", "AI")

# Column order in the tracker sheet
SHEET_COLUMNS = ["Company", "Position", "Date Applied", "Job URL", "Status", "Notes"]

# ---------------------------------------------------------------------------
# Credentials (job board logins)
# ---------------------------------------------------------------------------
WORKDAY_EMAIL    = os.getenv("WORKDAY_EMAIL", "")
WORKDAY_PASSWORD = os.getenv("WORKDAY_PASSWORD", "")

LINKEDIN_EMAIL    = os.getenv("LINKEDIN_EMAIL", "")
LINKEDIN_PASSWORD = os.getenv("LINKEDIN_PASSWORD", "")
