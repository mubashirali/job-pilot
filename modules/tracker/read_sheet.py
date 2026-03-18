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
            found, tabs = check_duplicate(company, position)
            if found:
                print(f"DUPLICATE: '{company}' — '{position}' found in tab(s): {', '.join(tabs)}")
            else:
                print(f"NOT_FOUND: '{company}' — '{position}' is not in any tab. Safe to apply.")
            return

        rows = get_all_rows(tab=args.tab)
        if not rows:
            print("Tracker is empty.")
            return

        header, *data = rows

        if args.company:
            data = [r for r in data if r and r[0].strip().lower() == args.company.strip().lower()]

        print("\t".join(header))
        print("-" * 80)
        for row in data:
            padded = row + [""] * (6 - len(row))
            print("\t".join(padded[:6]))

        print(f"\n{len(data)} row(s) found.")

    except HttpError as e:
        print(f"Google Sheets API error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
