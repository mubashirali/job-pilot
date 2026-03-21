"""
scrape_greenhouse_jobs.py — Search Greenhouse job boards for matching roles.

Uses the Greenhouse public JSON API (no scraping, no auth needed).

Usage:
    python modules/search/scrape_greenhouse_jobs.py [--companies Stripe,Brex,Plaid]

Output:
    JSON list of {company, title, url, location, department, stack_keywords} to stdout.
    Also saves to .tmp/greenhouse_jobs_<date>.json.
"""

import argparse
import json
import logging
import sys
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(dotenv_path=ROOT / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger("scrape_greenhouse")

# Companies from find_jobs.md priority list — map display name → board slug
GREENHOUSE_COMPANIES = {
    "Stripe":    "stripe",
    "Brex":      "brex",
    "Plaid":     "plaid",
    "Chime":     "chime",
    "Robinhood": "robinhoodmarkets",
    "Rippling":  "rippling",
    "Coinbase":  "coinbase",
    "Gusto":     "gusto",
    "Affirm":    "affirm",
    "Marqeta":   "marqeta",
    "Mercury":   "mercury",
}

SENIOR_KEYWORDS   = ["senior", "lead", "staff", "principal"]
EXCLUDE_KEYWORDS  = ["junior", "intern", "qa ", "data scientist", "product manager", "devops"]
ROLE_KEYWORDS     = ["engineer", "developer", "architect"]
STACK_KEYWORDS    = ["java", "kotlin", "spring", "microservice", "distributed", "aws", "backend"]


def fetch_jobs(company_name: str, board_slug: str) -> list[dict]:
    url = f"https://boards-api.greenhouse.io/v1/boards/{board_slug}/jobs?content=true"
    try:
        with urllib.request.urlopen(url, timeout=15) as resp:
            data = json.loads(resp.read())
    except Exception as e:
        logger.warning(f"Failed to fetch {company_name}: {e}")
        return []

    jobs = []
    for job in data.get("jobs", []):
        title = job.get("title", "")
        title_lower = title.lower()

        if not any(k in title_lower for k in SENIOR_KEYWORDS):
            continue
        if any(k in title_lower for k in EXCLUDE_KEYWORDS):
            continue
        if not any(k in title_lower for k in ROLE_KEYWORDS):
            continue

        location = job.get("location", {}).get("name", "")
        loc_lower = location.lower()
        if not any(k in loc_lower for k in ["remote", "missouri", "kansas", "mo,", "ks,"]):
            continue

        content = job.get("content", "") or ""
        matched_stack = [k for k in STACK_KEYWORDS if k in content.lower() or k in title_lower]

        jobs.append({
            "company":        company_name,
            "title":          title,
            "url":            job.get("absolute_url", ""),
            "location":       location,
            "department":     (job.get("departments") or [{}])[0].get("name", ""),
            "stack_keywords": matched_stack,
        })

    return jobs


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--companies",
        default=None,
        help="Comma-separated company names to search (default: all)",
    )
    args = parser.parse_args()

    target = GREENHOUSE_COMPANIES
    if args.companies:
        names = [n.strip() for n in args.companies.split(",")]
        target = {k: v for k, v in GREENHOUSE_COMPANIES.items() if k in names}

    all_jobs: list[dict] = []
    for company_name, board_slug in target.items():
        logger.info(f"Fetching {company_name} ({board_slug}) ...")
        jobs = fetch_jobs(company_name, board_slug)
        logger.info(f"  {len(jobs)} matching roles")
        all_jobs.extend(jobs)

    date_str = datetime.now().strftime("%Y-%m-%d")
    out_path = ROOT / ".tmp" / f"greenhouse_jobs_{date_str}.json"
    (ROOT / ".tmp").mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(all_jobs, indent=2))

    print(json.dumps(all_jobs, indent=2))
    logger.info(f"Total: {len(all_jobs)} jobs | Saved: {out_path}")


if __name__ == "__main__":
    main()
