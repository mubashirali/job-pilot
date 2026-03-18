"""
browser_apply.py — Browser automation entry point for job applications.

Usage:
    python tools/browser_apply.py \\
        --url "https://job-boards.greenhouse.io/affirm/jobs/7471141003" \\
        --cover-letter ".tmp/cover_letter_Affirm_MerchantInterfaces_2026-03-04.md" \\
        --company "Affirm" \\
        --position "Senior Software Engineer, Backend (Merchant Interfaces)" \\
        --mode preview

Modes:
    preview  — fills the form and takes screenshots (no submit)
    submit   — fills the form and clicks the submit button

ATS detection is automatic based on the URL.
Screenshots are saved to .tmp/screenshots/ and paths are printed on exit.
"""

import argparse
import logging
import os
import re
import sys
from datetime import datetime
from pathlib import Path

# Ensure project root is on path: modules/apply/ → modules/ → ClaudeAgent/
ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(dotenv_path=ROOT / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger("browser_apply")


# ---------------------------------------------------------------------------
# ATS detection
# ---------------------------------------------------------------------------

ATS_PATTERNS = {
    # More-specific patterns must come BEFORE broader ones (dict order matters)
    "stripe":     [r"stripe\.com/jobs", r"greenhouse\.io/stripe/"],
    "greenhouse": [r"greenhouse\.io", r"grnh\.se"],
    "lever":      [r"lever\.co", r"jobs\.lever\.co"],
    "ashby":      [r"ashbyhq\.com", r"jobs\.ashbyhq\.com"],
    "workday":    [r"workday\.com", r"myworkdayjobs\.com"],
}

# These platforms use "Easy Apply" flows that are intentionally NOT automated.
# Always apply via the company's direct application URL instead.
MANUAL_ONLY_PATTERNS = {
    "linkedin": [r"linkedin\.com"],
    "indeed": [r"indeed\.com"],
}


def detect_ats(url: str) -> str:
    for platform, patterns in MANUAL_ONLY_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, url, re.IGNORECASE):
                return f"manual:{platform}"

    for ats, patterns in ATS_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, url, re.IGNORECASE):
                return ats
    return "generic"


# ---------------------------------------------------------------------------
# Profile / cover letter loaders
# ---------------------------------------------------------------------------

def load_applicant() -> dict:
    """Load applicant data from data/about-me.md and data/application-defaults.md."""
    # Core contact data (hardcoded from data/about-me.md — canonical source)
    applicant = {
        "first_name": "Mubashir",
        "last_name": "Ali",
        "email": "mubashir.ali.memon@gmail.com",
        "phone": "+15734352970",
        "linkedin": "https://linkedin.com/in/mubashir-ali992",
        "github": "https://github.com/mubashirali/",
        "website": "https://mubashir-ali.netlify.app/",
        "resume_path": str(ROOT / "data" / "Resume-Mubashir.pdf"),
        "current_company": "Delivery Hero",
        "current_title": "Senior Software Engineer",
        "full_name": "Mubashir Ali",
        "city": "Columbia, MO",             # for plain-text city fields
        "city_plain": "Columbia",           # for plain-text "What City do you live in?"
        "city_typeahead_type": "Columbia",  # typed into Greenhouse location typeahead
        "city_typeahead_pick": "Columbia, Missouri",  # picked from suggestion list
        "pronouns": "He/Him",
        # Work authorization (from data/application-defaults.md)
        "work_authorized": True,
        "requires_sponsorship": False,
        # EEO (from data/application-defaults.md)
        "gender": "Male",
        "race": "Asian",
    }
    return applicant


def load_cover_letter(path: str) -> str:
    """
    Load cover letter text from a .md file.
    Strips YAML-style metadata header (lines starting with --- ... ---) if present.
    """
    content = Path(path).read_text(encoding="utf-8")

    # Strip optional YAML front-matter block (--- ... ---)
    front_matter_pattern = re.compile(r"^---\s*\n.*?\n---\s*\n", re.DOTALL)
    content = front_matter_pattern.sub("", content).strip()

    return content


# ---------------------------------------------------------------------------
# Generic ATS handler (screenshot only)
# ---------------------------------------------------------------------------

def apply_generic(page, applicant: dict, cover_letter: str, mode: str, screenshot_dir: str) -> list[str]:
    """Fallback for unknown ATS — take screenshot and alert user."""
    logger.warning("Unknown ATS — screenshot only. Manual application required.")
    print("[generic] Unknown ATS detected. Taking screenshot for manual review.")

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    page.wait_for_load_state("networkidle", timeout=30000)
    shot = f"{screenshot_dir}/generic_{ts}_manual_required.png"
    page.screenshot(path=shot, full_page=True)
    print(f"[generic] Screenshot saved: {shot}")
    print("[generic] This ATS is not yet supported. Please apply manually.")
    return [shot]


# ---------------------------------------------------------------------------
# ATS router
# ---------------------------------------------------------------------------

ATS_HANDLERS = {
    "greenhouse": None,   # loaded dynamically
    "lever": None,
    "ashby": None,
    "workday": None,
    "linkedin": None,
    "generic": None,
}


def get_handler(ats: str):
    """Dynamically import the ATS handler module."""
    if ats == "generic":
        return apply_generic

    try:
        module_path = f"modules.apply.ats.{ats}"
        import importlib
        module = importlib.import_module(module_path)
        return module.apply
    except ImportError:
        logger.warning(f"No handler module found for ATS '{ats}' — using generic")
        return apply_generic


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Automated job application via browser")
    parser.add_argument("--url", required=True, help="Job application URL")
    parser.add_argument("--cover-letter", required=True, help="Path to cover letter .md file")
    parser.add_argument("--company", required=True, help="Company name (used in screenshot filenames)")
    parser.add_argument("--position", required=True, help="Job position title")
    parser.add_argument(
        "--mode",
        choices=["preview", "submit"],
        default="preview",
        help="preview: fill form + screenshot (no submit). submit: fill + submit.",
    )
    parser.add_argument(
        "--cover-letter-pdf",
        default=None,
        help="Path to cover letter PDF for file upload (optional; defaults to same path as --cover-letter with .pdf extension)",
    )
    parser.add_argument(
        "--security-code",
        default=None,
        help="Security/anti-spam code if the form requires it (filled into #security-input-N fields)",
    )
    args = parser.parse_args()

    # Detect ATS
    ats = detect_ats(args.url)
    print(f"[browser_apply] URL: {args.url}")
    print(f"[browser_apply] ATS detected: {ats}")
    print(f"[browser_apply] Mode: {args.mode}")

    # Block Easy Apply platforms — always apply via the company's direct URL
    if ats.startswith("manual:"):
        platform = ats.split(":")[1].capitalize()
        print(f"\n[browser_apply] {platform} Easy Apply is disabled.")
        print(f"[browser_apply] Do not use {platform} Easy Apply.")
        print(f"[browser_apply] Find the company's direct application URL (Greenhouse, Lever, Ashby, etc.) and use that instead.")
        sys.exit(1)

    # Prepare screenshot directory
    screenshot_dir = str(ROOT / ".tmp" / "screenshots")
    Path(screenshot_dir).mkdir(parents=True, exist_ok=True)

    # Load data
    applicant = load_applicant()
    cover_letter = load_cover_letter(args.cover_letter)

    # Resolve cover letter PDF path for file upload (Greenhouse and others use file inputs)
    cl_pdf = args.cover_letter_pdf
    if not cl_pdf:
        # Default: same filename as the .md file but with .pdf extension
        cl_pdf = str(Path(args.cover_letter).with_suffix(".pdf"))
    applicant["cover_letter_pdf_path"] = cl_pdf if Path(cl_pdf).exists() else None
    if applicant["cover_letter_pdf_path"]:
        print(f"[browser_apply] Cover letter PDF: {applicant['cover_letter_pdf_path']}")
    else:
        print("[browser_apply] Cover letter PDF not found — will upload as text file")

    if args.security_code:
        applicant["security_code"] = args.security_code

    # Launch browser
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
        )
        page = context.new_page()

        print(f"[browser_apply] Navigating to {args.url}...")
        page.goto(args.url, wait_until="domcontentloaded", timeout=60000)

        handler = get_handler(ats)
        screenshots = handler(
            page=page,
            applicant=applicant,
            cover_letter=cover_letter,
            mode=args.mode,
            screenshot_dir=screenshot_dir,
        )

        browser.close()

    print("\n[browser_apply] Done.")
    print("[browser_apply] Screenshots:")
    for s in screenshots:
        print(f"  {s}")

    if args.mode == "preview":
        print("\n[browser_apply] PREVIEW complete — form filled but NOT submitted.")
        print("[browser_apply] Review screenshots above, then run with --mode submit to submit.")
    else:
        print("\n[browser_apply] SUBMIT complete — application submitted.")


if __name__ == "__main__":
    main()
