"""
modules/shared/auth_google.py

Run once to authenticate with Google OAuth and generate token.json.
Token is reused automatically on all subsequent runs — you won't be prompted again
unless the token expires or is deleted.

Usage:
    python modules/shared/auth_google.py
"""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent  # modules/shared/ → modules/ → ClaudeAgent/
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow

from modules.shared.config import SCOPES_ALL, TOKEN_PATH, CREDENTIALS_PATH


def main():
    if not os.path.exists(CREDENTIALS_PATH):
        print("ERROR: credentials.json not found in project root.")
        print("\nTo fix:")
        print("  1. Go to https://console.cloud.google.com/")
        print("  2. Create a project and enable the Google Sheets API")
        print("  3. Create OAuth 2.0 credentials (type: Desktop app)")
        print("  4. Download and save as credentials.json in the project root")
        sys.exit(1)

    creds = None
    if os.path.exists(TOKEN_PATH):
        creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES_ALL)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            print("Token refreshed automatically.")
        else:
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_PATH, SCOPES_ALL)
            creds = flow.run_local_server(port=0)
            print("Authentication successful.")
        with open(TOKEN_PATH, "w") as f:
            f.write(creds.to_json())
        print(f"Token saved to {TOKEN_PATH}. You won't need to authenticate again.")
    else:
        print(f"Already authenticated. {TOKEN_PATH} is valid.")


if __name__ == "__main__":
    main()
