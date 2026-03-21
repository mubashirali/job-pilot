"""
scrape_linkedin_jobs.py — Search LinkedIn Jobs for matching roles.

Uses Crawl4AI with headless browser. LinkedIn rate-limits heavily — use sparingly.

Usage:
    python modules/search/scrape_linkedin_jobs.py [--query "Senior Java Engineer Remote"]

Output:
    JSON list of {company, title, url, location, stack_keywords} to stdout.
    Also saves to .tmp/linkedin_jobs_<date>.json.
"""

import asyncio
import json
import logging
import re
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import quote_plus

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(dotenv_path=ROOT / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger("scrape_linkedin")

DEFAULT_QUERIES = [
    "Senior Software Engineer Java Remote",
    "Lead Backend Engineer Spring Boot Remote",
    "Staff Software Engineer Microservices Remote",
]

SENIOR_KEYWORDS  = ["senior", "lead", "staff", "principal"]
EXCLUDE_KEYWORDS = ["junior", "intern", "qa", "data scientist", "product manager"]
ROLE_KEYWORDS    = ["engineer", "developer", "architect"]
STACK_KEYWORDS   = ["java", "kotlin", "spring", "microservice", "distributed", "aws", "backend"]


def is_relevant_title(title: str) -> bool:
    t = title.lower()
    if not any(k in t for k in SENIOR_KEYWORDS):
        return False
    if any(k in t for k in EXCLUDE_KEYWORDS):
        return False
    return any(k in t for k in ROLE_KEYWORDS)


def build_search_url(query: str) -> str:
    return (
        f"https://www.linkedin.com/jobs/search/?keywords={quote_plus(query)}"
        "&location=United%20States&f_WT=2&f_E=4&f_TPR=r604800"
    )


async def scrape_query(query: str) -> list[dict]:
    from crawl4ai import AsyncWebCrawler
    url = build_search_url(query)
    jobs = []
    try:
        async with AsyncWebCrawler(headless=True) as crawler:
            result = await crawler.arun(url=url, timeout=45, delay_before_return_html=3.0)
            if not result.success:
                logger.warning(f"LinkedIn scrape failed for '{query}': {result.error_message}")
                return []
            for match in re.finditer(
                r"\[([^\]]+)\]\((https://www\.linkedin\.com/jobs/view/[^\)]+)\)",
                result.markdown,
            ):
                title, job_url = match.group(1).strip(), match.group(2)
                if is_relevant_title(title):
                    stack = [k for k in STACK_KEYWORDS if k in title.lower()]
                    jobs.append({
                        "company":        "",
                        "title":          title,
                        "url":            job_url,
                        "location":       "Remote",
                        "stack_keywords": stack,
                    })
    except Exception as e:
        logger.warning(f"Error scraping LinkedIn for '{query}': {e}")
    return jobs


async def main_async(queries: list[str]) -> None:
    all_jobs: list[dict] = []
    seen_urls: set[str] = set()

    for query in queries:
        logger.info(f"Searching LinkedIn: '{query}' ...")
        jobs = await scrape_query(query)
        for job in jobs:
            if job["url"] not in seen_urls:
                seen_urls.add(job["url"])
                all_jobs.append(job)
        logger.info(f"  {len(jobs)} results (running total: {len(all_jobs)})")
        await asyncio.sleep(5)

    date_str = datetime.now().strftime("%Y-%m-%d")
    out_path = ROOT / ".tmp" / f"linkedin_jobs_{date_str}.json"
    (ROOT / ".tmp").mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(all_jobs, indent=2))

    print(json.dumps(all_jobs, indent=2))
    logger.info(f"Total unique: {len(all_jobs)} | Saved: {out_path}")


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--query", default=None)
    args = parser.parse_args()
    queries = [args.query] if args.query else DEFAULT_QUERIES
    asyncio.run(main_async(queries))


if __name__ == "__main__":
    main()
