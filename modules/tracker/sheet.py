"""
modules/tracker/sheet.py

Core Google Sheets API for the job application tracker.

Functions:
    get_all_rows()                          → list[dict]
    check_duplicate(company, position)      → bool
    log_application(...)                    → bool  (False = duplicate, skip)
    update_application(...)                 → bool  (False = row not found)
    save_failed_log(args_dict)              → None  (writes to .tmp/failed_logs/)
"""

import json
import logging
import os
import sys
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from modules.shared.config import (
    CREDENTIALS_PATH, TOKEN_PATH, SCOPES_SHEETS, SHEET_ID, SHEET_TAB, SHEET_COLUMNS
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Auth helper
# ---------------------------------------------------------------------------

def _get_sheets_service():
    """Build and return an authenticated Google Sheets service object."""
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    creds = None
    if os.path.exists(TOKEN_PATH):
        creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES_SHEETS)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            with open(TOKEN_PATH, "w") as f:
                f.write(creds.to_json())
        else:
            if not os.path.exists(CREDENTIALS_PATH):
                raise FileNotFoundError(
                    f"credentials.json not found at {CREDENTIALS_PATH}. "
                    "Run modules/shared/auth_google.py to set up OAuth."
                )
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_PATH, SCOPES_SHEETS)
            creds = flow.run_local_server(port=0)
            with open(TOKEN_PATH, "w") as f:
                f.write(creds.to_json())

    return build("sheets", "v4", credentials=creds)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_all_rows() -> list[dict]:
    """
    Return all data rows from the tracker sheet as a list of dicts.
    Keys come from SHEET_COLUMNS (row 1 headers).
    """
    service = _get_sheets_service()
    result = (
        service.spreadsheets()
        .values()
        .get(spreadsheetId=SHEET_ID, range=f"{SHEET_TAB}!A1:Z")
        .execute()
    )
    values = result.get("values", [])
    if not values:
        return []
    headers = values[0]
    rows = []
    for row in values[1:]:
        # Pad short rows
        padded = row + [""] * (len(headers) - len(row))
        rows.append(dict(zip(headers, padded)))
    return rows


def check_duplicate(company: str, position: str) -> bool:
    """Return True if a row already exists for this company + position."""
    rows = get_all_rows()
    c = company.strip().lower()
    p = position.strip().lower()
    for row in rows:
        if row.get("Company", "").strip().lower() == c and \
           row.get("Position", "").strip().lower() == p:
            return True
    return False


def log_application(
    company: str,
    position: str,
    date_applied: str = "",
    url: str = "",
    status: str = "Applied",
    notes: str = "",
) -> bool:
    """
    Append a new application row to the tracker sheet.

    Returns:
        True  — row added
        False — duplicate found, nothing written
    """
    if check_duplicate(company, position):
        logger.info(f"Duplicate: '{company}' — '{position}' already in sheet.")
        return False

    if not date_applied:
        date_applied = str(date.today())

    row = [company, position, date_applied, url, status, notes]
    service = _get_sheets_service()
    service.spreadsheets().values().append(
        spreadsheetId=SHEET_ID,
        range=f"{SHEET_TAB}!A:F",
        valueInputOption="USER_ENTERED",
        insertDataOption="INSERT_ROWS",
        body={"values": [row]},
    ).execute()

    logger.info(f"Logged: '{company}' — '{position}' | {status}")
    return True


def update_application(
    company: str,
    position: str,
    new_status: str,
    notes: str = "",
) -> bool:
    """
    Update the Status (and optionally Notes) of an existing row.

    Returns:
        True  — row found and updated
        False — no matching row found
    """
    service = _get_sheets_service()
    result = (
        service.spreadsheets()
        .values()
        .get(spreadsheetId=SHEET_ID, range=f"{SHEET_TAB}!A1:Z")
        .execute()
    )
    values = result.get("values", [])
    if not values:
        return False

    headers = values[0]
    company_col  = headers.index("Company")  if "Company"  in headers else 0
    position_col = headers.index("Position") if "Position" in headers else 1
    status_col   = headers.index("Status")   if "Status"   in headers else 4
    notes_col    = headers.index("Notes")    if "Notes"    in headers else 5

    c = company.strip().lower()
    p = position.strip().lower()

    for i, row in enumerate(values[1:], start=2):  # 1-indexed, skip header
        padded = row + [""] * (max(status_col, notes_col) + 1 - len(row))
        if padded[company_col].strip().lower() == c and \
           padded[position_col].strip().lower() == p:
            # Update status cell
            status_range = f"{SHEET_TAB}!{chr(65 + status_col)}{i}"
            service.spreadsheets().values().update(
                spreadsheetId=SHEET_ID,
                range=status_range,
                valueInputOption="USER_ENTERED",
                body={"values": [[new_status]]},
            ).execute()
            # Update notes cell if provided
            if notes:
                notes_range = f"{SHEET_TAB}!{chr(65 + notes_col)}{i}"
                service.spreadsheets().values().update(
                    spreadsheetId=SHEET_ID,
                    range=notes_range,
                    valueInputOption="USER_ENTERED",
                    body={"values": [[notes]]},
                ).execute()
            logger.info(f"Updated: '{company}' — '{position}' → {new_status}")
            return True

    return False


def save_failed_log(args_dict: dict) -> None:
    """
    Save a failed log attempt to .tmp/failed_logs/ so it can be retried later.
    """
    log_dir = ROOT / ".tmp" / "failed_logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = log_dir / f"failed_{ts}.json"
    with open(log_file, "w", encoding="utf-8") as f:
        json.dump(args_dict, f, indent=2, default=str)
    print(f"[sheet] Saved failed log to {log_file}")
