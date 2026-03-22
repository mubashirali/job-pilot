"""
Tool: read_sheet.py — CLI entry point for reading the job application tracker.

Delegates to modules/tracker/sheet.py.

Usage:
    python tools/read_sheet.py
    python tools/read_sheet.py --company "Stripe"
    python tools/read_sheet.py --check-dup "Stripe" "Senior Software Engineer"
"""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent  # modules/tracker/ → modules/ → ClaudeAgent/
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from modules.tracker.sheet import get_all_rows, check_duplicate
from modules.shared.config import SHEET_TAB
from googleapiclient.errors import HttpError


def main():
    parser = argparse.ArgumentParser(description="Read job application tracker.")
    parser.add_argument("--company", default=None, help="Filter by company name")
    parser.add_argument("--tab", default=SHEET_TAB, help="Sheet tab name (default: from .env)")
    parser.add_argument(
        "--check-dup", nargs=2, metavar=("COMPANY", "POSITION"),
        help="Check if company+position already exists across AI and 2025-2026 tabs",
    )
    args = parser.parse_args()

    try:
        if args.check_dup:
            company, position = args.check_dup
            found = check_duplicate(company, position)
            if found:
                print(f"DUPLICATE: '{company}' — '{position}' already in tracker.")
            else:
                print(f"NOT_FOUND: '{company}' — '{position}' is not in tracker. Safe to apply.")
            return

        rows = get_all_rows()
        if not rows:
            print("Tracker is empty.")
            return

        if args.company:
            rows = [r for r in rows if r.get("Company", "").strip().lower() == args.company.strip().lower()]

        from modules.shared.config import SHEET_COLUMNS
        headers = SHEET_COLUMNS
        print("\t".join(headers))
        print("-" * 80)
        for row in rows:
            print("\t".join(str(row.get(h, "")) for h in headers))

        print(f"\n{len(data)} row(s) found.")

    except HttpError as e:
        print(f"Google Sheets API error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
