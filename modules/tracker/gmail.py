"""
modules/tracker/gmail.py

Gmail API helpers for the job application tracker.

Functions:
    fetch_security_code(sender_filter, after_epoch, wait_seconds) -> str | None
"""

import base64
import logging
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from modules.shared.config import CREDENTIALS_PATH, TOKEN_PATH, SCOPES_GMAIL

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Auth helper
# ---------------------------------------------------------------------------

def _get_gmail_service():
    """Build and return an authenticated Gmail service object."""
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    # Try to load existing token; it may already include Gmail scope
    creds = None
    if os.path.exists(TOKEN_PATH):
        creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES_GMAIL)

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
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_PATH, SCOPES_GMAIL)
            creds = flow.run_local_server(port=0)
            with open(TOKEN_PATH, "w") as f:
                f.write(creds.to_json())

    return build("gmail", "v1", credentials=creds)


# ---------------------------------------------------------------------------
# Security code extraction
# ---------------------------------------------------------------------------

# Greenhouse verification codes are always exactly 6 digits
_CODE_RE = re.compile(r"\b(\d{6})\b")

# Email subjects that indicate a verification/code email
_VERIFY_SUBJECT_RE = re.compile(
    r"(code|verif|confirm|secur|authentica|one.time|otp)",
    re.IGNORECASE,
)


def _extract_code_from_text(text: str) -> str | None:
    """Return the first 6-digit code found in text, or None.

    Only matches exactly 6 consecutive digits to avoid false positives from
    years (2026), phone numbers, or other numeric content in email footers.
    """
    for match in _CODE_RE.finditer(text):
        return match.group(1)
    return None


def _decode_message_body(payload: dict) -> str:
    """Recursively decode a Gmail message payload to plain text."""
    mime_type = payload.get("mimeType", "")
    body = payload.get("body", {})
    data = body.get("data", "")

    if data and mime_type in ("text/plain", "text/html"):
        return base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="replace")

    # Recurse into parts
    for part in payload.get("parts", []):
        result = _decode_message_body(part)
        if result:
            return result

    return ""


def fetch_security_code(
    sender_filter: str = "greenhouse",
    after_epoch: int | None = None,
    wait_seconds: int = 90,
) -> str | None:
    """
    Poll Gmail for a security/verification code email.

    Args:
        sender_filter: Substring to match against the From header (e.g. "greenhouse").
        after_epoch:   Only consider emails received after this Unix timestamp.
                       Defaults to (now - 5 minutes).
        wait_seconds:  How long to keep polling before giving up.

    Returns:
        The code as a string, or None if not found within the timeout.
    """
    if after_epoch is None:
        after_epoch = int(time.time()) - 300  # 5-minute lookback default

    service = _get_gmail_service()
    deadline = time.time() + wait_seconds
    poll_interval = 5  # seconds between Gmail API polls

    logger.info(f"Polling Gmail for security code (sender: {sender_filter!r}, timeout: {wait_seconds}s)")

    while time.time() < deadline:
        try:
            # Search for recent emails from the target sender
            query = f"from:{sender_filter} newer_than:10m"
            result = service.users().messages().list(
                userId="me", q=query, maxResults=10
            ).execute()

            messages = result.get("messages", [])
            for msg_stub in messages:
                msg = service.users().messages().get(
                    userId="me",
                    id=msg_stub["id"],
                    format="full",
                ).execute()

                # Skip emails older than after_epoch
                internal_date_ms = int(msg.get("internalDate", 0))
                if internal_date_ms // 1000 < after_epoch:
                    continue

                # Check subject line — only extract codes from verification emails
                headers = {h["name"]: h["value"] for h in msg.get("payload", {}).get("headers", [])}
                subject = headers.get("Subject", "")
                if not _VERIFY_SUBJECT_RE.search(subject):
                    logger.debug(f"Skipping email (subject not verification-related): {subject!r}")
                    continue

                body_text = _decode_message_body(msg.get("payload", {}))
                code = _extract_code_from_text(body_text)
                if code:
                    logger.info(f"Security code found in '{subject}': {code}")
                    return code

        except Exception as e:
            logger.warning(f"Gmail poll error: {e}")

        remaining = deadline - time.time()
        if remaining <= 0:
            break
        time.sleep(min(poll_interval, remaining))

    logger.warning(f"No security code found from {sender_filter!r} within {wait_seconds}s")
    return None
