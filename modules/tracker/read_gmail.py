"""
Tool: read_gmail.py — CLI entry point for fetching security codes from Gmail.

Delegates to modules/tracker/gmail.py.

Usage:
    python tools/read_gmail.py [--after-epoch N] [--wait N] [--sender-filter STR]

Options:
    --after-epoch N     Only look at emails received after this Unix timestamp.
    --wait N            Poll for up to N seconds (default: 90).
    --sender-filter STR Search emails from senders containing this string (default: greenhouse).

Exits 0 and prints the code on success; exits 1 on failure.
"""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent  # modules/tracker/ → modules/ → ClaudeAgent/
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from modules.tracker.gmail import fetch_security_code


def main():
    parser = argparse.ArgumentParser(description="Fetch a security/verification code from Gmail")
    parser.add_argument("--after-epoch", type=int, default=None)
    parser.add_argument("--wait",        type=int, default=90)
    parser.add_argument("--sender-filter", default="greenhouse")
    args = parser.parse_args()

    code = fetch_security_code(
        sender_filter=args.sender_filter,
        after_epoch=args.after_epoch,
        wait_seconds=args.wait,
    )

    if code:
        print(code)
        sys.exit(0)
    else:
        print("[gmail] ERROR: Security code not found in Gmail within the timeout", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
