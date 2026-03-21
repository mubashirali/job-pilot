# Apply Pipeline Improvements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a pre-flight ATS form inspector, fix stale workflow docs, add Crawl4AI job scrapers, implement Lever ATS handler, and add browser-use as a fallback for unknown ATS platforms.

**Architecture:** Each improvement is self-contained. form_inspector.py uses Playwright (already installed) to extract live DOM fields and resolve answers from existing data files, outputting a JSON field map the agent reviews before running browser_apply.py. Lever follows the same handler pattern as ashby.py. Scrapers in modules/search/ each produce a JSON list the agent aggregates into a shortlist.

**Tech Stack:** Python 3.11+, Playwright (already installed), Crawl4AI (new), browser-use (new), python-dotenv (already installed)

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `modules/apply/form_inspector.py` | CREATE | Pre-flight form field extractor — Playwright DOM scrape + answer resolution |
| `workflows/apply_to_job.md` | MODIFY | Step 1b command, ATS support table, edge cases table |
| `modules/apply/ats/lever.py` | REPLACE stub | Lever ATS form handler |
| `modules/apply/browser_apply.py` | MODIFY | Add Lever to ATS dispatch + browser-use fallback for unknown |
| `modules/search/scrape_greenhouse_jobs.py` | CREATE | Crawl4AI scraper for Greenhouse job boards |
| `modules/search/scrape_company_careers.py` | CREATE | Crawl4AI scraper for direct company career pages |
| `modules/search/scrape_linkedin_jobs.py` | CREATE | Crawl4AI scraper for LinkedIn job search |
| `workflows/find_jobs.md` | MODIFY | Update tool paths from tools/ to modules/search/ |
| `requirements.txt` | MODIFY | Add crawl4ai, browser-use |

---

## Task 1: form_inspector.py

**Files:**
- Create: `modules/apply/form_inspector.py`

### What it does

Navigates to an ATS application URL with a headless browser, waits for React to render, extracts every
visible form field (inputs, selects, textareas, radios, checkboxes, file uploads), resolves answers
from `load_applicant()` using keyword matching, and writes `.tmp/form_fields_<company>_<position>_<date>.json`.

Exit 0 = all resolved. Exit 1 = unresolved fields. Exit 2 = fatal error.

- [ ] **Step 1: Create the file**

`modules/apply/form_inspector.py`:

```python
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
        (["require.*sponsor", "sponsorship", "visa sponsor", "need.*sponsor"],
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
    # These are often hidden inputs or custom-styled elements not caught by the selectors above
    if ats_type == "workday":
        for el in page.locator("[data-automation-id]").all():
            try:
                auto_id = el.get_attribute("data-automation-id") or ""
                tag = el.evaluate("el => el.tagName.toLowerCase()")
                if auto_id and tag in ("input", "select", "textarea") and auto_id not in seen_labels:
                    # Use data-automation-id as the label if no other label was found
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

    out_path       = tmp_dir / f"form_fields_{slug_co}_{slug_pos}_{date_str}.json"
    screenshot_path = str(screenshot_dir / f"inspect_{slug_co}_{slug_pos}.png")

    ats_type, multi_step = detect_ats(args.url, args.ats_type)
    warning  = MULTI_STEP_WARNINGS.get(ats_type)
    applicant = load_applicant()

    result: dict = {
        "url":              args.url,
        "company":          args.company,
        "position":         args.position,
        "ats_type":         ats_type,
        "multi_step":       multi_step,
        "warning":          warning,
        "scraped_at":       datetime.now(timezone.utc).isoformat(),
        "fields":           [],
        "resolved_count":   0,
        "unresolved_count": 0,
        "unresolved_labels":[],
        "error":            None,
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
    result["fields"]           = fields
    result["resolved_count"]   = len(fields) - len(unresolved)
    result["unresolved_count"] = len(unresolved)
    result["unresolved_labels"]= [f["label"] for f in unresolved]

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
```

- [ ] **Step 2: Smoke-test the module can be imported without errors**

```bash
cd /path/to/job-pilot
python -c "import modules.apply.form_inspector; print('Import OK')"
```

Expected output: `Import OK`

- [ ] **Step 3: Run against a real public Greenhouse URL (preview only — no submit)**

Pick any public Greenhouse job posting URL. Example (replace with any live posting):

```bash
python modules/apply/form_inspector.py \
  --url "https://boards.greenhouse.io/affirm/jobs/7471141003" \
  --company "Affirm" \
  --position "Senior Software Engineer" \
  --timeout 45
```

Expected:
- Prints `[form_inspector] Fields found: N` (N > 0)
- Writes `.tmp/form_fields_affirm_senior_software_engineer_<date>.json`
- Writes `.tmp/screenshots/inspect_affirm_senior_software_engineer.png`
- Exit code 0 or 1 (not 2)

If exit code 2, check the `error` field in the JSON and fix the page load / bot-detection issue.

- [ ] **Step 4: Verify the JSON output structure**

```bash
python -c "
import json
from pathlib import Path
data = json.loads(next(Path('.tmp').glob('form_fields_affirm_*.json')).read_text())
print('ATS type:', data['ats_type'])
print('Fields:', len(data['fields']))
print('Unresolved:', data['unresolved_labels'])
assert data['ats_type'] == 'greenhouse'
assert len(data['fields']) > 0
print('JSON structure OK')
"
```

- [ ] **Step 5: Commit**

```bash
git add modules/apply/form_inspector.py
git commit -m "feat(apply): add form_inspector.py — pre-flight ATS form field extractor"
```

---

## Task 2: Update apply_to_job.md

**Files:**
- Modify: `workflows/apply_to_job.md`

Three locations need updating.

- [ ] **Step 1: Replace Step 1b (WebFetch → form_inspector CLI)**

Find the Step 1b section (currently starts with "Use WebFetch on the direct ATS application URL").
Replace the entire body of Step 1b with:

```markdown
## Step 1b — Scrape & Understand the Form

**Before running any browser automation**, run the form inspector to map every visible field on page 1:

```bash
python modules/apply/form_inspector.py \
  --url "<job_url>" \
  --company "<Company>" \
  --position "<Position>"
```

Read the output from `.tmp/form_fields_<slug>.json`.

- **Exit code 0** — all fields resolved. Proceed to Step 2.
- **Exit code 1** — unresolved fields found. Review `unresolved_labels` with the user, get their
  answers, save new Q&A pairs to `data/application-defaults.md`, then proceed to Step 2.
- **Exit code 2** — fatal error. Check the `error` field in the JSON and resolve before continuing.
- **`multi_step: true` / `warning` present** — acknowledge that additional fields will appear during
  preview mode (Step 2). They will be handled by the ATS handler at that time.

**Rules (unchanged):**
- Never guess or fabricate answers
- Never leave a required field blank without flagging it first
- If a new Q&A pair is resolved with the user, add it to `data/application-defaults.md`
```

- [ ] **Step 2: Update the ATS support table in Step 2**

Find the line:
```
- **Lever / Ashby / LinkedIn** — screenshot only (stubs)
```

Replace with:
```
- **Ashby** — full automation
- **Lever / LinkedIn** — screenshot only (stubs)
```

- [ ] **Step 3: Update the Edge Cases table**

Find the row:
```
| ATS not supported (Lever, Ashby) | Provide cover letter + fields for manual paste; log as `In Progress` |
```

Replace with:
```
| ATS not supported (Lever, LinkedIn) | Provide cover letter + fields for manual paste; log as `In Progress` |
```

- [ ] **Step 4: Verify the file reads correctly**

```bash
grep -n "form_inspector" workflows/apply_to_job.md
grep -n "Ashby" workflows/apply_to_job.md
```

Expected: `form_inspector` appears in Step 1b, `Ashby — full automation` appears in Step 2.

- [ ] **Step 5: Commit**

```bash
git add workflows/apply_to_job.md
git commit -m "docs(workflow): update apply_to_job — use form_inspector, fix Ashby status"
```

---

## Task 3: Crawl4AI Job Board Scrapers

**Files:**
- Modify: `requirements.txt`
- Create: `modules/search/scrape_greenhouse_jobs.py`
- Create: `modules/search/scrape_company_careers.py`
- Create: `modules/search/scrape_linkedin_jobs.py`
- Modify: `workflows/find_jobs.md`

### 3a — Install Crawl4AI

- [ ] **Step 1: Add to requirements.txt**

Add to `requirements.txt`:
```
crawl4ai==0.4.247
```

(Pin to latest stable. Check `pip index versions crawl4ai` for current version if unsure.)

- [ ] **Step 2: Install and run post-install setup**

```bash
pip install crawl4ai
crawl4ai-setup  # runs post-install browser and model setup
```

Expected: No errors. Crawl4AI uses its own Playwright installation separate from the project's.

### 3b — Greenhouse scraper

Greenhouse job boards are public JSON APIs: `https://boards-api.greenhouse.io/v1/boards/{company}/jobs`

- [ ] **Step 3: Create modules/search/scrape_greenhouse_jobs.py**

```python
"""
scrape_greenhouse_jobs.py — Search Greenhouse job boards for matching roles.

Usage:
    python modules/search/scrape_greenhouse_jobs.py [--companies stripe,brex,plaid]

Output:
    JSON list of {company, title, url, location, department} to stdout.
    Also saves to .tmp/greenhouse_jobs_<date>.json.
"""

import json
import logging
import re
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

TITLE_KEYWORDS = [
    "senior", "lead", "staff", "principal",
    "engineer", "developer", "architect",
]
TITLE_EXCLUDE = ["junior", "intern", "qa ", "data scientist", "product manager", "devops"]
STACK_KEYWORDS = ["java", "kotlin", "spring", "microservice", "distributed", "aws", "backend"]


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

        # Seniority filter
        if not any(k in title_lower for k in ["senior", "lead", "staff", "principal"]):
            continue
        if any(k in title_lower for k in TITLE_EXCLUDE):
            continue
        if not any(k in title_lower for k in ["engineer", "developer", "architect"]):
            continue

        # Location filter (remote or Missouri/Kansas)
        location = job.get("location", {}).get("name", "")
        loc_lower = location.lower()
        if not any(k in loc_lower for k in ["remote", "missouri", "kansas", "mo,", "ks,"]):
            continue

        # Extract stack keywords from content field if available
        content = job.get("content", "") or ""
        matched_stack = [k for k in STACK_KEYWORDS if k in content.lower() or k in title.lower()]

        jobs.append({
            "company":       company_name,
            "title":         title,
            "url":           job.get("absolute_url", ""),
            "location":      location,
            "department":    (job.get("departments") or [{}])[0].get("name", ""),
            "stack_keywords": matched_stack,
        })

    return jobs


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--companies",
        default=None,
        help="Comma-separated company names to search (default: all in list)",
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
```

- [ ] **Step 4: Smoke-test the Greenhouse scraper**

```bash
python modules/search/scrape_greenhouse_jobs.py --companies Stripe,Affirm
```

Expected: JSON output to stdout. Check for `"company": "Stripe"` entries.

### 3c — Company career pages scraper

- [ ] **Step 5: Create modules/search/scrape_company_careers.py**

```python
"""
scrape_company_careers.py — Scrape direct company career pages for matching roles.

Uses Crawl4AI for JS-rendered pages. Each company in the target list is fetched,
job titles and URLs extracted, and filtered by seniority + stack keywords.

Usage:
    python modules/search/scrape_company_careers.py

Output:
    JSON list of {company, title, url, location} to stdout.
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

# Priority companies from find_jobs.md (non-Greenhouse — those are covered by scrape_greenhouse_jobs.py)
CAREER_PAGES = [
    {"company": "Square/Block", "url": "https://careers.squareup.com/us/en/jobs?role=Software+Engineering"},
]

SENIOR_KEYWORDS = ["senior", "lead", "staff", "principal"]
EXCLUDE_KEYWORDS = ["junior", "intern", "qa", "data scientist", "product manager"]
ROLE_KEYWORDS = ["engineer", "developer", "architect"]


def is_relevant_title(title: str) -> bool:
    t = title.lower()
    if not any(k in t for k in SENIOR_KEYWORDS):
        return False
    if any(k in t for k in EXCLUDE_KEYWORDS):
        return False
    return any(k in t for k in ROLE_KEYWORDS)


async def scrape_page(company: str, url: str) -> list[dict]:
    from crawl4ai import AsyncWebCrawler
    jobs = []
    try:
        async with AsyncWebCrawler(headless=True) as crawler:
            result = await crawler.arun(url=url, timeout=30)
            if not result.success:
                logger.warning(f"Failed to scrape {company}: {result.error_message}")
                return []
            # Extract job links from markdown (Crawl4AI converts HTML → markdown)
            # Pattern: [Job Title](URL)
            for match in re.finditer(r"\[([^\]]+)\]\((https?://[^\)]+)\)", result.markdown):
                title, job_url = match.group(1), match.group(2)
                if is_relevant_title(title):
                    stack = [k for k in STACK_KEYWORDS if k in title.lower()]
                    jobs.append({
                        "company":        company,
                        "title":          title,
                        "url":            job_url,
                        "location":       "",  # Requires visiting each job page; left for agent to verify
                        "stack_keywords": stack,
                    })
    except Exception as e:
        logger.warning(f"Error scraping {company}: {e}")
    return jobs


async def main_async() -> None:
    all_jobs: list[dict] = []
    for page_info in CAREER_PAGES:
        logger.info(f"Scraping {page_info['company']} ...")
        jobs = await scrape_page(page_info["company"], page_info["url"])
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
```

- [ ] **Step 6: Smoke-test the company careers scraper**

```bash
python modules/search/scrape_company_careers.py
```

Expected: JSON output (may be empty if no matching roles). No Python errors. File saved to `.tmp/`.

### 3d — LinkedIn scraper

Note: LinkedIn aggressively rate-limits and blocks scrapers. This scraper uses Crawl4AI's browser
mode with delays. For production use, prefer the Greenhouse API scraper for known companies.

- [ ] **Step 7: Create modules/search/scrape_linkedin_jobs.py**

```python
"""
scrape_linkedin_jobs.py — Search LinkedIn Jobs for matching roles.

Uses Crawl4AI with headless browser to bypass JS rendering.
Note: LinkedIn rate-limits heavily. Use sparingly (once per session).

Usage:
    python modules/search/scrape_linkedin_jobs.py [--query "Senior Java Engineer Remote"]

Output:
    JSON list of {company, title, url, location} to stdout.
    Also saves to .tmp/linkedin_jobs_<date>.json.
"""

import asyncio
import json
import logging
import re
import sys
import time
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

SENIOR_KEYWORDS = ["senior", "lead", "staff", "principal"]
EXCLUDE_KEYWORDS = ["junior", "intern", "qa", "data scientist", "product manager"]
ROLE_KEYWORDS = ["engineer", "developer", "architect"]


def is_relevant_title(title: str) -> bool:
    t = title.lower()
    if not any(k in t for k in SENIOR_KEYWORDS):
        return False
    if any(k in t for k in EXCLUDE_KEYWORDS):
        return False
    return any(k in t for k in ROLE_KEYWORDS)


def build_search_url(query: str) -> str:
    # f_TPR=r604800 = posted in last 7 days; f_WT=2 = remote; f_E=4 = senior level
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
            # Extract job card links from markdown
            for match in re.finditer(r"\[([^\]]+)\]\((https://www\.linkedin\.com/jobs/view/[^\)]+)\)", result.markdown):
                title, job_url = match.group(1).strip(), match.group(2)
                if is_relevant_title(title):
                    stack = [k for k in ["java", "kotlin", "spring", "microservice", "distributed", "aws", "backend"] if k in title.lower()]
                    jobs.append({
                        "company":        "",   # Company name requires clicking into job card
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
        # Polite delay between queries to avoid rate limiting
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
    parser.add_argument("--query", default=None, help="Search query (default: runs all default queries)")
    args = parser.parse_args()
    queries = [args.query] if args.query else DEFAULT_QUERIES
    asyncio.run(main_async(queries))


if __name__ == "__main__":
    main()
```

- [ ] **Step 8: Smoke-test LinkedIn scraper with one query**

```bash
python modules/search/scrape_linkedin_jobs.py --query "Senior Java Engineer Remote"
```

Expected: JSON output. If LinkedIn blocks (empty results / 429), that is expected and noted — LinkedIn scraping is best-effort. No Python errors.

### 3e — Update find_jobs.md tool paths

- [ ] **Step 9: Fix tool paths in find_jobs.md**

In `workflows/find_jobs.md`, find and update tool references:

| Find | Replace |
|------|---------|
| `tools/scrape_linkedin_jobs.py` | `modules/search/scrape_linkedin_jobs.py` |
| `tools/scrape_indeed_jobs.py` | `modules/search/scrape_linkedin_jobs.py` (no Indeed scraper yet — reuse LinkedIn) |
| `tools/scrape_greenhouse_jobs.py` | `modules/search/scrape_greenhouse_jobs.py` |
| `tools/scrape_company_careers.py` | `modules/search/scrape_company_careers.py` |
| `tools/scrape_other_portals.py` | *(remove line — no other-portals scraper yet)* |

- [ ] **Step 10: Commit all search-related work**

```bash
git add requirements.txt modules/search/ workflows/find_jobs.md
git commit -m "feat(search): add Crawl4AI job board scrapers — Greenhouse, company careers, LinkedIn"
```

---

## Task 4: Lever ATS Handler

**Files:**
- Replace: `modules/apply/ats/lever.py`
- Verify (no change needed): `modules/apply/browser_apply.py`

> **Note on dispatch wiring:** `browser_apply.py` line 50 already contains
> `"lever": [r"lever\.co", r"jobs\.lever\.co"]` in `ATS_PATTERNS`. The dynamic import
> via `get_handler()` will automatically pick up the new `lever.py` module — no changes
> to `browser_apply.py` are required for the Lever dispatch.

Lever apply pages live at `https://jobs.lever.co/{company}/{job-id}/apply`.
They are standard HTML forms (no complex React synthetic events like Workday).
Fields: Name, Email, Phone, Current Company, Resume upload, Cover Letter, LinkedIn/GitHub/Portfolio URLs,
and company-specific custom questions (textareas).

- [ ] **Step 1: Replace the empty stub with a full implementation**

`modules/apply/ats/lever.py`:

```python
"""
Lever ATS handler.

Fills standard Lever application form fields.

Supported fields:
  - Full Name, Email, Phone, Current Company
  - Resume file upload
  - Cover letter textarea (if present)
  - LinkedIn, GitHub, Portfolio URL fields
  - Custom textarea questions (matched by keyword)

Usage:
    Invoked by browser_apply.py when the URL matches lever.co.
"""

import logging
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

_ROOT = Path(__file__).parent.parent.parent.parent  # project root


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ss(page, path: str) -> str:
    page.screenshot(path=path, full_page=True)
    logger.info(f"Screenshot: {path}")
    print(f"[lever] Screenshot: {path}")
    return path


def _fill(page, selector: str, value: str, label: str = "") -> bool:
    """Fill a field by CSS selector. Returns True on success."""
    if not value:
        return False
    try:
        el = page.locator(selector)
        if el.count() > 0:
            el.first.scroll_into_view_if_needed()
            el.first.triple_click()
            el.first.fill(value)
            logger.debug(f"Filled '{label or selector}'")
            return True
    except Exception as e:
        logger.warning(f"Could not fill '{label}': {e}")
    return False


def _fill_by_label(page, label_texts: list[str], value: str, label: str = "") -> bool:
    """Fill a field by matching one of several label strings."""
    if not value:
        return False
    for lbl in label_texts:
        try:
            el = page.get_by_label(lbl, exact=False)
            if el.count() > 0:
                el.first.scroll_into_view_if_needed()
                el.first.triple_click()
                el.first.fill(value)
                logger.debug(f"Filled '{label}' via label '{lbl}'")
                return True
        except Exception:
            pass
    return False


def _fill_textarea(page, label_keyword: str, value: str) -> bool:
    """Find a textarea whose associated label contains label_keyword and fill it."""
    if not value:
        return False
    try:
        # Lever labels textareas with <label> elements above them
        labels = page.locator("label").all()
        for lbl_el in labels:
            if label_keyword.lower() in (lbl_el.inner_text() or "").lower():
                lbl_for = lbl_el.get_attribute("for") or ""
                if lbl_for:
                    ta = page.locator(f"textarea#{lbl_for}, #{lbl_for}")
                    if ta.count() > 0:
                        ta.first.scroll_into_view_if_needed()
                        ta.first.triple_click()
                        ta.first.fill(value)
                        logger.debug(f"Filled textarea for '{label_keyword}'")
                        return True
    except Exception as e:
        logger.warning(f"Could not fill textarea '{label_keyword}': {e}")
    return False


# ---------------------------------------------------------------------------
# Main apply function
# ---------------------------------------------------------------------------

def apply(page, applicant: dict, cover_letter: str, mode: str, screenshot_dir: str) -> list[str]:
    """
    Fill and optionally submit a Lever application form.

    Args:
        page:           Playwright page, already navigated to the apply URL.
        applicant:      Dict from load_applicant() in browser_apply.py.
        cover_letter:   Full text of the cover letter.
        mode:           "preview" or "submit".
        screenshot_dir: Path to screenshots directory.

    Returns:
        List of screenshot file paths taken.
    """
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    screenshots: list[str] = []

    print("[lever] Waiting for form to load ...")
    page.wait_for_load_state("networkidle", timeout=30000)
    page.wait_for_timeout(1500)

    # --- Screenshot: initial state ---
    screenshots.append(_ss(page, f"{screenshot_dir}/lever_{ts}_01_loaded.png"))

    # --- Full Name ---
    _fill_by_label(page, ["Full name", "Name"], applicant.get("full_name", ""), "Full Name")

    # --- Email ---
    _fill_by_label(page, ["Email", "Email address"], applicant.get("email", ""), "Email")

    # --- Phone ---
    _fill_by_label(page, ["Phone", "Phone number"], applicant.get("phone", ""), "Phone")

    # --- Current Company (optional field, not always present) ---
    _fill_by_label(page, ["Current company", "Company", "Organization"], applicant.get("current_company", ""), "Current Company")

    # --- Social / portfolio links ---
    _fill_by_label(page, ["LinkedIn", "LinkedIn URL", "LinkedIn profile"], applicant.get("linkedin", ""), "LinkedIn")
    _fill_by_label(page, ["GitHub", "GitHub URL"], applicant.get("github", ""), "GitHub")
    _fill_by_label(page, ["Portfolio", "Website", "Personal website"], applicant.get("website", ""), "Portfolio")

    # --- Resume upload ---
    resume_path = applicant.get("resume_path", "")
    if resume_path and Path(resume_path).exists():
        try:
            file_input = page.locator("input[type=file]").first
            if file_input.count() > 0:
                file_input.set_input_files(resume_path)
                page.wait_for_timeout(1500)
                print(f"[lever] Uploaded resume: {resume_path}")
            else:
                logger.warning("No file input found for resume")
        except Exception as e:
            logger.warning(f"Resume upload failed: {e}")
    else:
        logger.warning(f"Resume not found at: {resume_path}")

    # --- Cover letter (textarea, if present) ---
    _fill_textarea(page, "cover letter", cover_letter)

    # --- Additional info / "Why us?" textarea (common in Lever forms) ---
    for keyword in ["additional information", "anything else", "why"]:
        if _fill_textarea(page, keyword, cover_letter):
            break  # Only fill the first matching textarea

    # --- Screenshot: after filling ---
    screenshots.append(_ss(page, f"{screenshot_dir}/lever_{ts}_02_filled.png"))

    if mode == "preview":
        print("[lever] PREVIEW mode — form filled. Not submitting.")
        return screenshots

    # --- Submit ---
    print("[lever] Submitting application ...")
    try:
        submit_btn = page.locator("button[type=submit], input[type=submit]").last
        submit_btn.scroll_into_view_if_needed()
        submit_btn.click()
        page.wait_for_load_state("networkidle", timeout=30000)
        page.wait_for_timeout(2000)
        print("[lever] Submit clicked.")
    except Exception as e:
        logger.error(f"Submit failed: {e}")
        screenshots.append(_ss(page, f"{screenshot_dir}/lever_{ts}_ERROR_submit.png"))
        return screenshots

    # --- Screenshot: confirmation ---
    screenshots.append(_ss(page, f"{screenshot_dir}/lever_{ts}_03_submitted.png"))
    print("[lever] Application submitted.")
    return screenshots
```

- [ ] **Step 2: Verify Lever handler is importable**

```bash
python -c "from modules.apply.ats.lever import apply; print('Lever handler OK')"
```

Expected: `Lever handler OK`

- [ ] **Step 3: Test against a live Lever preview (if a URL is available)**

Find a Lever job URL (pattern: `https://jobs.lever.co/<company>/<job-id>`). Run preview:

```bash
python modules/apply/browser_apply.py \
  --url "https://jobs.lever.co/<company>/<job-id>/apply" \
  --cover-letter ".tmp/cover_letter_tmp.txt" \
  --company "<Company>" \
  --position "<Position>" \
  --mode preview
```

Expected: Screenshots saved, form partially filled, ATS detected as `lever`.

Note: If no Lever URL is available, skip the live test and proceed — the import test is sufficient.

- [ ] **Step 4: Commit**

```bash
git add modules/apply/ats/lever.py
git commit -m "feat(apply): implement Lever ATS handler — replaces empty stub"
```

---

## Task 5: browser-use Fallback for Unknown ATS

**Files:**
- Modify: `requirements.txt`
- Modify: `modules/apply/browser_apply.py`

When ATS detection returns `"generic"` (unknown platform), the current fallback just takes a screenshot
and prints "apply manually". With `browser-use`, we can attempt an AI-driven form fill before giving up.

- [ ] **Step 1: Add browser-use to requirements.txt**

```
browser-use==0.1.40
```

(Check `pip index versions browser-use` for current version.)

```bash
pip install browser-use
```

- [ ] **Step 2: Add browser-use fallback to browser_apply.py**

In `modules/apply/browser_apply.py`, replace the `apply_generic` function:

```python
def apply_generic(page, applicant: dict, cover_letter: str, mode: str, screenshot_dir: str) -> list[str]:
    """
    Fallback for unknown ATS platforms.

    Attempts browser-use AI-driven form fill. Falls back to screenshot-only if
    browser-use is not installed or the attempt fails.
    """
    logger.warning("Unknown ATS — attempting browser-use AI fallback.")
    print("[generic] Unknown ATS detected. Trying browser-use AI fallback ...")

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    screenshots: list[str] = []

    try:
        from browser_use import Agent
        from langchain_anthropic import ChatAnthropic
        import asyncio

        task_prompt = f"""
You are filling out a job application form. The page is already open.

Fill in the following fields wherever they appear on the page:
- Full name: {applicant.get('full_name')}
- Email: {applicant.get('email')}
- Phone: {applicant.get('phone')}
- LinkedIn: {applicant.get('linkedin')}
- Current company: {applicant.get('current_company')}
- Work authorized in US: Yes
- Requires visa sponsorship: No

Upload the resume from: {applicant.get('resume_path')}

If there is a cover letter field, paste this text:
{cover_letter[:500]}...

{"Do NOT click the final submit button." if mode == "preview" else "After filling all fields, click the submit button."}

Take a screenshot when done.
"""
        llm = ChatAnthropic(model="claude-sonnet-4-6")
        # Note: browser-use Agent manages its own browser session.
        # It does NOT accept a `page` parameter — it opens a fresh browser internally.
        agent = Agent(task=task_prompt, llm=llm)

        asyncio.run(agent.run())
        print("[generic] browser-use AI fill complete.")

    except ImportError:
        logger.warning("browser-use not installed — falling back to screenshot only.")
        print("[generic] browser-use not installed. Taking screenshot for manual review.")
    except Exception as e:
        logger.warning(f"browser-use failed: {e} — falling back to screenshot.")
        print(f"[generic] browser-use error: {e}. Taking screenshot for manual review.")

    shot = f"{screenshot_dir}/generic_{ts}_unknown_ats.png"
    page.screenshot(path=shot, full_page=True)
    screenshots.append(shot)
    print(f"[generic] Screenshot: {shot}")

    if mode == "preview":
        print("[generic] PREVIEW complete. Review screenshot above.")
    else:
        print("[generic] If browser-use filled the form, check the screenshot to confirm submission.")

    return screenshots
```

- [ ] **Step 3: Verify the import still works after modification**

```bash
python -c "import modules.apply.browser_apply; print('browser_apply import OK')"
```

Expected: `browser_apply import OK`

Note: `browser-use` and `langchain_anthropic` will only be invoked at runtime if an unknown ATS is
encountered. The import is inside the function so it degrades gracefully if not installed.

- [ ] **Step 4: Add langchain-anthropic to requirements.txt (dependency of browser-use)**

```
langchain-anthropic==0.3.12
```

(Check `pip index versions langchain-anthropic` for current version.)

```bash
pip install langchain-anthropic
```

- [ ] **Step 5: Commit**

```bash
git add requirements.txt modules/apply/browser_apply.py
git commit -m "feat(apply): add browser-use AI fallback for unknown ATS platforms"
```

---

## Final Verification

- [ ] **Run all imports to confirm no broken dependencies**

```bash
python -c "
import modules.apply.form_inspector
import modules.apply.browser_apply
import modules.apply.ats.lever
import modules.apply.ats.ashby
import modules.apply.ats.greenhouse
import modules.search.scrape_greenhouse_jobs
import modules.search.scrape_company_careers
import modules.search.scrape_linkedin_jobs
print('All modules import OK')
"
```

- [ ] **Run form_inspector against one real URL as end-to-end check**

```bash
python modules/apply/form_inspector.py \
  --url "https://boards.greenhouse.io/affirm/jobs/7471141003" \
  --company "Affirm" \
  --position "Senior Software Engineer" \
  --timeout 45
echo "Exit code: $?"
```

- [ ] **Run Greenhouse scraper to confirm live job data returns**

```bash
python modules/search/scrape_greenhouse_jobs.py --companies Stripe
```

- [ ] **Final commit — update requirements.txt with pinned versions**

```bash
git add requirements.txt
git commit -m "chore: pin crawl4ai, browser-use, langchain-anthropic versions"
```
