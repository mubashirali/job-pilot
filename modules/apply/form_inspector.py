"""
form_inspector.py — Pre-flight ATS form field extractor.

Before running browser_apply.py, call this tool to map every visible field on page 1
of the job application form and resolve answers from the user's data files.

Usage:
    python modules/apply/form_inspector.py \\
        --url "https://boards.greenhouse.io/stripe/jobs/123456" \\
        --company "Stripe" \\
        --position "Senior Software Engineer" \\
        [--ats-type greenhouse] \\
        [--timeout 30]

Exit codes:
    0 — all fields resolved
    1 — one or more UNRESOLVED fields (agent must ask user before Step 2)
    2 — fatal error (page load failure, bot detection, no fields found)

Output:
    .tmp/form_fields_<slug-company>_<slug-position>_<YYYY-MM-DD>.json
    .tmp/screenshots/inspect_<slug-company>_<slug-position>.png
"""

import argparse
import json
import logging
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(dotenv_path=ROOT / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger("form_inspector")

# Reuse load_applicant from browser_apply — single source of truth for profile data
from modules.apply.browser_apply import load_applicant


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def slug(text: str) -> str:
    """Lowercase, replace non-alphanumeric with underscore, collapse runs."""
    return re.sub(r"_+", "_", re.sub(r"[^a-z0-9]", "_", text.lower())).strip("_")


MULTI_STEP_WARNINGS = {
    "greenhouse": "Greenhouse has ~3 pages. Fields on later pages will surface during preview mode (Step 2).",
    "workday": (
        "Workday has ~5 pages. Fields on later pages will surface during preview mode (Step 2). "
        "A new Workday account will be created using WORKDAY_EMAIL / WORKDAY_PASSWORD from .env."
    ),
}


def detect_ats(url: str, override: str | None = None) -> tuple[str, bool | None]:
    """Return (ats_type, multi_step). Override takes precedence."""
    if override:
        return override, override in ("greenhouse", "workday")
    patterns = [
        (r"greenhouse\.io|grnh\.se",           "greenhouse", True),
        (r"workday\.com|myworkdayjobs\.com",   "workday",    True),
        (r"ashbyhq\.com",                       "ashby",      False),
        (r"lever\.co",                          "lever",      False),
    ]
    for pattern, ats, multi_step in patterns:
        if re.search(pattern, url, re.IGNORECASE):
            return ats, multi_step
    return "unknown", None


def find_file(pattern: str) -> str | None:
    """Return first file matching glob under .tmp/, or None."""
    matches = sorted((ROOT / ".tmp").glob(pattern))
    return str(matches[0]) if matches else None


FIRST_JOB_YEAR = 2015  # Update if earliest job in data/about-me.md Work History changes

def _derive_years_experience(applicant: dict) -> str:
    """Compute years of experience from current year minus first job start year."""
    years = datetime.now(timezone.utc).year - FIRST_JOB_YEAR
    return str(years)


def _resolve_salary(options: list[str]) -> str | None:
    """Return 'Negotiable' if the field is free-text, or the closest option."""
    if not options:
        return "Negotiable"
    for opt in options:
        if any(k in opt.lower() for k in ["negotiable", "prefer not", "decline"]):
            return opt
    return None  # Caller will mark UNRESOLVED with a note about dropdown mismatch


def resolve_answer(
    label: str,
    field_type: str,
    options: list[str],
    applicant: dict,
    slug_company: str,
    slug_position: str,
) -> tuple[str | None, str]:
    """
    Keyword-match label to a known answer.
    Returns (planned_answer, source).
    source is one of: about-me.md, application-defaults.md, derived, file, UNRESOLVED[...].
    """
    lbl = label.lower()

    # --- File uploads ---
    if field_type == "file":
        if any(k in lbl for k in ["resume", "cv"]):
            path = (
                find_file(f"resume_{slug_company}*.pdf")
                or find_file("resume_*.pdf")
                or applicant.get("resume_path")
            )
            return (path, "file") if path else (None, "UNRESOLVED")
        if "cover" in lbl:
            path = find_file(f"cover_letter_{slug_company}*.pdf")
            return (path, "file") if path else (None, "UNRESOLVED")
        return None, "UNRESOLVED"

    # --- Keyword rules (most-specific match wins by keyword length) ---
    # Format: ([keyword_list], answer_or_None, source)
    RULES: list[tuple[list[str], str | None, str]] = [
        (["first name"],                                          applicant.get("first_name"),     "about-me.md"),
        (["last name", "surname", "family name"],                 applicant.get("last_name"),      "about-me.md"),
        (["full name", "your name"],                              applicant.get("full_name"),      "about-me.md"),
        (["email"],                                               applicant.get("email"),          "about-me.md"),
        (["phone", "telephone", "mobile"],                        applicant.get("phone"),          "about-me.md"),
        (["linkedin"],                                            applicant.get("linkedin"),       "about-me.md"),
        (["github"],                                              applicant.get("github"),         "about-me.md"),
        (["portfolio", "personal site", "personal website"],      applicant.get("website"),        "about-me.md"),
        (["website"],                                             applicant.get("website"),        "about-me.md"),
        (["city", "location", "where are you located"],           applicant.get("city"),           "about-me.md"),
        (["current company", "current employer", "employer"],     applicant.get("current_company"),"about-me.md"),
        (["current title", "job title", "current role"],          applicant.get("current_title"),  "about-me.md"),
        (["pronouns"],                                            applicant.get("pronouns"),       "about-me.md"),
        (["years of experience", "how many years", "years experience"],
                                                                  _derive_years_experience(applicant), "derived"),
        (["authorized to work", "work authorization", "eligible to work", "legally authorized"],
                                                                  "Yes",                          "application-defaults.md"),
        (["require sponsorship", "sponsorship", "visa sponsor", "need sponsorship"],
                                                                  "No",                           "application-defaults.md"),
        (["salary", "compensation", "pay expectation", "desired pay", "expected salary"],
                                                                  _resolve_salary(options),       "application-defaults.md"),
        (["willing to relocate", "relocation", "relocat"],        "Open to discussion",           "application-defaults.md"),
        (["gender"],                                              "Decline to answer",            "application-defaults.md"),
        (["race", "ethnicity"],                                   "Decline to answer",            "application-defaults.md"),
        (["veteran"],                                             "I am not a protected veteran", "application-defaults.md"),
        (["disability"],                                          "I do not have a disability",   "application-defaults.md"),
        (["how did you hear", "referral", "source"],              "LinkedIn",                     "application-defaults.md"),
    ]

    best_answer: str | None = None
    best_source: str = "UNRESOLVED"
    best_len: int = 0

    for keywords, answer, source in RULES:
        for kw in keywords:
            if kw in lbl and len(kw) > best_len:
                best_len = len(kw)
                best_answer = answer
                best_source = source

    if best_answer is None:
        return None, "UNRESOLVED"

    # Validate against dropdown options
    if options:
        if best_answer in options:
            return best_answer, best_source
        # Case-insensitive fallback
        for opt in options:
            if opt.lower() == best_answer.lower():
                return opt, best_source
        # No match in dropdown — flag as unresolved with context
        return None, f"UNRESOLVED — '{best_answer}' not in dropdown options: {options}"

    return best_answer, best_source


# ---------------------------------------------------------------------------
# DOM extraction
# ---------------------------------------------------------------------------

def extract_fields(
    page,
    ats_type: str,
    applicant: dict,
    slug_company: str,
    slug_position: str,
) -> list[dict]:
    """Extract all visible form fields from the rendered page DOM."""
    fields: list[dict] = []
    seen_labels: set[str] = set()

    def get_label(el) -> str:
        """Resolve a human-readable label for a form element.

        Priority (per spec): <label for=id> → aria-labelledby → aria-label → placeholder → ancestor label/legend
        """
        # 1. <label for=id>  — most reliable for standard HTML forms
        el_id = el.get_attribute("id") or ""
        if el_id:
            try:
                lbl = page.locator(f"label[for='{el_id}']").first.inner_text()
                if lbl.strip():
                    return lbl.strip()
            except Exception:
                pass
        # 2. aria-labelledby — React/ARIA patterns
        labelledby = el.get_attribute("aria-labelledby") or ""
        if labelledby:
            try:
                return page.locator(f"#{labelledby}").first.inner_text().strip()
            except Exception:
                pass
        # 3. aria-label — direct attribute label
        aria = el.get_attribute("aria-label") or ""
        if aria.strip():
            return aria.strip()
        # 4. placeholder — last text resort
        placeholder = el.get_attribute("placeholder") or ""
        if placeholder.strip():
            return placeholder.strip()
        # 5. Closest ancestor label/fieldset legend via JS
        try:
            result = el.evaluate(
                """el => {
                    const lbl = el.closest('label');
                    if (lbl) return lbl.innerText.trim();
                    const fs = el.closest('fieldset');
                    if (fs) {
                        const leg = fs.querySelector('legend');
                        if (leg) return leg.innerText.trim();
                    }
                    return '';
                }"""
            )
            if result and result.strip():
                return result.strip()
        except Exception:
            pass
        return ""

    def get_required(el) -> bool:
        return (
            el.get_attribute("required") is not None
            or el.get_attribute("aria-required") == "true"
        )

    def add_field(label: str, ftype: str, required: bool, options: list[str] | None = None) -> None:
        label = label.strip()
        if not label or label in seen_labels:
            return
        seen_labels.add(label)
        answer, source = resolve_answer(
            label, ftype, options or [], applicant, slug_company, slug_position
        )
        entry: dict = {
            "label":          label,
            "type":           ftype,
            "required":       required,
            "planned_answer": answer,
            "source":         source,
        }
        if options:
            entry["options"] = options
        fields.append(entry)

    # Text-like inputs
    for sel, ftype in [
        ("input[type=text]",   "text"),
        ("input[type=email]",  "email"),
        ("input[type=tel]",    "tel"),
        ("input[type=number]", "number"),
        ("input[type=url]",    "url"),
        ("input:not([type])",  "text"),
    ]:
        for el in page.locator(sel).all():
            try:
                add_field(get_label(el), ftype, get_required(el))
            except Exception as e:
                logger.debug(f"Skipped {ftype} input: {e}")

    # File uploads
    for el in page.locator("input[type=file]").all():
        try:
            add_field(get_label(el), "file", get_required(el))
        except Exception as e:
            logger.debug(f"Skipped file input: {e}")

    # Textareas
    for el in page.locator("textarea").all():
        try:
            add_field(get_label(el), "textarea", get_required(el))
        except Exception as e:
            logger.debug(f"Skipped textarea: {e}")

    # Selects
    for el in page.locator("select").all():
        try:
            opts = []
            for opt in el.locator("option").all():
                val = opt.get_attribute("value") or ""
                txt = opt.inner_text().strip()
                if val and txt:
                    opts.append(txt)
            add_field(get_label(el), "select", get_required(el), options=opts or None)
        except Exception as e:
            logger.debug(f"Skipped select: {e}")

    # Radio groups (grouped by name attribute)
    seen_radio_names: set[str] = set()
    for el in page.locator("input[type=radio]").all():
        try:
            name = el.get_attribute("name") or ""
            if not name or name in seen_radio_names:
                continue
            seen_radio_names.add(name)

            radios = page.locator(f"input[type=radio][name='{name}']")
            options: list[str] = []
            for r in radios.all():
                r_id = r.get_attribute("id") or ""
                if r_id:
                    try:
                        lbl_txt = page.locator(f"label[for='{r_id}']").first.inner_text().strip()
                        if lbl_txt:
                            options.append(lbl_txt)
                            continue
                    except Exception:
                        pass
                val = r.get_attribute("value") or ""
                if val:
                    options.append(val)

            group_label = get_label(radios.first)
            if not group_label:
                try:
                    group_label = radios.first.evaluate(
                        """el => {
                            const fs = el.closest('fieldset');
                            if (fs) {
                                const leg = fs.querySelector('legend');
                                if (leg) return leg.innerText.trim();
                            }
                            return '';
                        }"""
                    )
                except Exception:
                    pass
            add_field(group_label or name, "radio", get_required(radios.first), options=options or None)
        except Exception as e:
            logger.debug(f"Skipped radio group: {e}")

    # Standalone checkboxes
    for el in page.locator("input[type=checkbox]").all():
        try:
            add_field(get_label(el), "checkbox", get_required(el))
        except Exception as e:
            logger.debug(f"Skipped checkbox: {e}")

    # Workday-specific: data-automation-id attributes carry semantic field names
    if ats_type == "workday":
        for el in page.locator("[data-automation-id]").all():
            try:
                auto_id = el.get_attribute("data-automation-id") or ""
                tag = el.evaluate("el => el.tagName.toLowerCase()")
                if auto_id and tag in ("input", "select", "textarea") and auto_id not in seen_labels:
                    label = get_label(el) or auto_id
                    ftype = el.get_attribute("type") or tag
                    add_field(label, ftype, get_required(el))
            except Exception as e:
                logger.debug(f"Skipped workday automation-id element: {e}")

    return fields


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Pre-flight ATS form field inspector")
    parser.add_argument("--url",      required=True,  help="Direct ATS application URL")
    parser.add_argument("--company",  required=True,  help="Company name")
    parser.add_argument("--position", required=True,  help="Job position title")
    parser.add_argument(
        "--ats-type",
        default=None,
        choices=["greenhouse", "workday", "ashby", "lever", "unknown"],
        help="Force ATS type (overrides URL auto-detection)",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=30,
        help="Page load timeout in seconds (default: 30)",
    )
    args = parser.parse_args()

    slug_co  = slug(args.company)
    slug_pos = slug(args.position)
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    tmp_dir        = ROOT / ".tmp"
    screenshot_dir = tmp_dir / "screenshots"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    screenshot_dir.mkdir(parents=True, exist_ok=True)

    out_path        = tmp_dir / f"form_fields_{slug_co}_{slug_pos}_{date_str}.json"
    screenshot_path = str(screenshot_dir / f"inspect_{slug_co}_{slug_pos}.png")

    ats_type, multi_step = detect_ats(args.url, args.ats_type)
    warning   = MULTI_STEP_WARNINGS.get(ats_type)
    applicant = load_applicant()

    result: dict = {
        "url":               args.url,
        "company":           args.company,
        "position":          args.position,
        "ats_type":          ats_type,
        "multi_step":        multi_step,
        "warning":           warning,
        "scraped_at":        datetime.now(timezone.utc).isoformat(),
        "fields":            [],
        "resolved_count":    0,
        "unresolved_count":  0,
        "unresolved_labels": [],
        "error":             None,
    }

    from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

    try:
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
            print(f"[form_inspector] Navigating to {args.url} ...")

            try:
                page.goto(args.url, wait_until="domcontentloaded", timeout=args.timeout * 1000)
                page.wait_for_load_state("networkidle", timeout=args.timeout * 1000)
            except PlaywrightTimeoutError:
                raise RuntimeError(f"Page did not load within {args.timeout}s")

            # Extra buffer for React hydration
            page.wait_for_timeout(2000)

            # Bot-detection check
            final_url = page.url
            if any(k in final_url.lower() for k in ["captcha", "blocked", "robot", "denied"]):
                raise RuntimeError(f"Bot detection triggered — redirected to: {final_url}")

            page.screenshot(path=screenshot_path, full_page=True)
            print(f"[form_inspector] Screenshot: {screenshot_path}")

            print(f"[form_inspector] Extracting fields (ATS: {ats_type}) ...")
            fields = extract_fields(page, ats_type, applicant, slug_co, slug_pos)
            browser.close()

    except Exception as exc:
        result["error"] = str(exc)
        logger.error(f"Fatal: {exc}")
        out_path.write_text(json.dumps(result, indent=2))
        print(f"\n[form_inspector] FATAL ERROR: {exc}")
        print(f"[form_inspector] Output: {out_path}")
        sys.exit(2)

    unresolved = [f for f in fields if f["planned_answer"] is None]
    result["fields"]            = fields
    result["resolved_count"]    = len(fields) - len(unresolved)
    result["unresolved_count"]  = len(unresolved)
    result["unresolved_labels"] = [f["label"] for f in unresolved]

    out_path.write_text(json.dumps(result, indent=2))

    print(f"\n[form_inspector] Fields found:  {len(fields)}")
    print(f"[form_inspector] Resolved:      {result['resolved_count']}")
    print(f"[form_inspector] Unresolved:    {result['unresolved_count']}")
    if result["unresolved_labels"]:
        print("[form_inspector] Unresolved fields:")
        for lbl in result["unresolved_labels"]:
            print(f"  - {lbl}")
    if warning:
        print(f"\n[form_inspector] NOTE: {warning}")
    print(f"\n[form_inspector] Output: {out_path}")

    sys.exit(1 if unresolved else 0)


if __name__ == "__main__":
    main()
