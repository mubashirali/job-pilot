"""
Tool: update_sheet.py — CLI entry point for updating the job application tracker.

Delegates to modules/tracker/sheet.py.

Usage:
    # Append new row
    python tools/update_sheet.py \
        --company "Stripe" \
        --position "Senior Software Engineer" \
        --date "2026-03-04" \
        --url "https://stripe.com/jobs/123" \
        --status "Applied" \
        --notes "Focused on payments + distributed systems keywords"

    # Update existing row status
    python tools/update_sheet.py \
        --company "Stripe" \
        --position "Senior Software Engineer" \
        --update-status "Interview" \
        --notes "Recruiter reached out on LinkedIn"
"""

import argparse
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent  # modules/tracker/ → modules/ → ClaudeAgent/
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from modules.tracker.sheet import log_application, update_application, save_failed_log
from googleapiclient.errors import HttpError


def main():
    parser = argparse.ArgumentParser(description="Update the job application Google Sheet tracker.")
    parser.add_argument("--company",  required=True)
    parser.add_argument("--position", required=True)
    parser.add_argument("--date",     default=str(date.today()))
    parser.add_argument("--url",      default="")
    parser.add_argument("--status",   default="Applied")
    parser.add_argument("--notes",    default="")
    parser.add_argument("--update-status", dest="update_status", default=None)
    args = parser.parse_args()

    try:
        if args.update_status:
            success = update_application(args.company, args.position, args.update_status, args.notes)
            if not success:
                print(f"ERROR: No existing row found for '{args.company}' — '{args.position}'.")
                sys.exit(1)
            print(f"Updated: {args.company} — {args.position} | Status: {args.update_status}")
        else:
            success = log_application(
                args.company, args.position, args.date, args.url, args.status, args.notes
            )
            if not success:
                print(f"DUPLICATE: '{args.company}' — '{args.position}' already exists. Skipping.")
                sys.exit(0)
            print(f"Logged: {args.company} — {args.position} | Status: {args.status} | {args.date}")

    except HttpError as e:
        print(f"Google Sheets API error: {e}")
        save_failed_log(vars(args))
        sys.exit(1)
    except Exception as e:
        print(f"Unexpected error: {e}")
        save_failed_log(vars(args))
        sys.exit(1)


if __name__ == "__main__":
    main()
