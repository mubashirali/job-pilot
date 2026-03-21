"""
scrape_company_careers.py — Scrape direct company career pages for matching roles.

Uses Crawl4AI for JS-rendered pages. A single browser session is reused across all
companies to avoid per-URL browser launch overhead.

Usage:
    python modules/search/scrape_company_careers.py

Output:
    JSON list of {company, title, url, location, stack_keywords} to stdout.
    Also saves to .tmp/company_careers_<date>.json.
"""

import asyncio
import json
import logging
import re
import sys
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
logger = logging.getLogger("scrape_careers")

# Priority companies from find_jobs.md (those not on Greenhouse covered by scrape_greenhouse_jobs.py)
CAREER_PAGES = [
    {"company": "Square/Block", "url": "https://careers.squareup.com/us/en/jobs?role=Software+Engineering"},
]

SENIOR_KEYWORDS  = ["senior", "lead", "staff", "principal"]
EXCLUDE_KEYWORDS = ["junior", "intern", "qa", "data scientist", "product manager", "devops"]
ROLE_KEYWORDS    = ["engineer", "developer", "architect"]
STACK_KEYWORDS   = ["java", "kotlin", "spring", "microservice", "distributed", "aws", "backend"]


def is_relevant_title(title: str) -> bool:
    t = title.lower()
    if not any(k in t for k in SENIOR_KEYWORDS):
        return False
    if any(k in t for k in EXCLUDE_KEYWORDS):
        return False
    return any(k in t for k in ROLE_KEYWORDS)


async def scrape_page(crawler, company: str, url: str) -> list[dict]:
    """Scrape one career page using an existing crawler session."""
    jobs = []
    try:
        result = await crawler.arun(url=url, timeout=30)
        if not result.success:
            logger.warning(f"Failed to scrape {company}: {result.error_message}")
            return []
        markdown = result.markdown or ""
        for match in re.finditer(r"\[([^\]]+)\]\((https?://[^\)]+)\)", markdown):
            title, job_url = match.group(1), match.group(2)
            if is_relevant_title(title):
                # Check stack keywords against surrounding markdown context (200 chars), not just title
                start = max(0, match.start() - 100)
                end = min(len(markdown), match.end() + 100)
                context = markdown[start:end].lower()
                stack = [k for k in STACK_KEYWORDS if k in context]
                jobs.append({
                    "company":        company,
                    "title":          title,
                    "url":            job_url,
                    "location":       "",
                    "stack_keywords": stack,
                })
    except Exception as e:
        logger.warning(f"Error scraping {company}: {e}")
    return jobs


async def main_async() -> None:
    from crawl4ai import AsyncWebCrawler

    all_jobs: list[dict] = []
    # Single browser session shared across all career pages
    async with AsyncWebCrawler(headless=True) as crawler:
        for page_info in CAREER_PAGES:
            logger.info(f"Scraping {page_info['company']} ...")
            jobs = await scrape_page(crawler, page_info["company"], page_info["url"])
            logger.info(f"  {len(jobs)} matching roles")
            all_jobs.extend(jobs)

    date_str = datetime.now().strftime("%Y-%m-%d")
    out_path = ROOT / ".tmp" / f"company_careers_{date_str}.json"
    (ROOT / ".tmp").mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(all_jobs, indent=2))

    print(json.dumps(all_jobs, indent=2))
    logger.info(f"Total: {len(all_jobs)} jobs | Saved: {out_path}")


def main() -> None:
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
