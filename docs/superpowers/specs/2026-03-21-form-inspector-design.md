# Design Spec: form_inspector.py + Apply Workflow Improvements

Date: 2026-03-21

## Overview

Five-step improvement to the apply pipeline, starting with a pre-flight form field extractor
(`form_inspector.py`) that replaces the broken `WebFetch` approach in `apply_to_job.md` Step 1b.

---

## Step 1 — form_inspector.py

### Problem

`apply_to_job.md` Step 1b tells the agent to use `WebFetch` to map ATS form fields before automation.
`WebFetch` fetches raw HTML — it cannot render React SPAs. All major ATS platforms (Greenhouse, Workday,
Ashby, Lever) are React apps. The step is effectively a no-op today.

### Solution

A new CLI tool: `modules/apply/form_inspector.py`

Uses Playwright (already installed — no new dependency) to load the ATS page in a headless browser,
wait for React to hydrate, extract all visible form fields from the live DOM, resolve answers from
the user's data files, and output a structured JSON field map.

Placement in `modules/apply/` is intentional: the inspector is tightly coupled to the apply workflow
and uses Playwright, consistent with all other apply-layer tools.

### CLI

All flags are required unless noted.

```bash
python modules/apply/form_inspector.py \
  --url "https://boards.greenhouse.io/stripe/jobs/123456" \
  --company "Stripe" \
  --position "Senior Software Engineer" \
  [--ats-type greenhouse]   # optional override if auto-detection fails
  [--timeout 30]            # optional page load timeout in seconds (default: 30)
```

- `--company` and `--position` are required. Used for output filename and JSON metadata.
- `--ats-type` is optional. Forces ATS type when auto-detection fails (e.g., Greenhouse embed on
  custom domain). Valid values: `greenhouse`, `workday`, `ashby`, `lever`, `unknown`.
- `--timeout` is optional. Page load timeout in seconds. Default: 30.

### Output File

Path: `.tmp/form_fields_<slug-company>_<slug-position>_<YYYY-MM-DD>.json`

Company and position values are slugified: lowercased, spaces and special chars replaced with `_`.
Example: `Stripe` + `Senior Software Engineer` → `form_fields_stripe_senior_software_engineer_2026-03-21.json`

`.tmp/` is created with `mkdir(parents=True, exist_ok=True)` if it does not exist (consistent with
all other tools in this project).

### Exit Codes

| Code | Meaning |
|------|---------|
| 0 | All fields resolved — safe to proceed to Step 2 |
| 1 | One or more UNRESOLVED fields — agent must pause and ask user before Step 2 |
| 2 | Fatal error — page load failure, timeout, bot detection, no fields found |

### Output JSON Schema

```json
{
  "url": "https://boards.greenhouse.io/stripe/jobs/123456",
  "company": "Stripe",
  "position": "Senior Software Engineer",
  "ats_type": "greenhouse",
  "multi_step": true,
  "warning": "Greenhouse has ~3 pages. Fields on later pages will surface during preview mode (Step 2).",
  "scraped_at": "2026-03-21T10:30:00+00:00",
  "fields": [
    {
      "label": "First Name",
      "type": "text",
      "required": true,
      "planned_answer": "Mubashir",
      "source": "about-me.md"
    },
    {
      "label": "Resume/CV",
      "type": "file",
      "required": true,
      "planned_answer": ".tmp/resume_stripe_senior_software_engineer_2026-03-21.pdf",
      "source": "file"
    },
    {
      "label": "Are you authorized to work in the US?",
      "type": "radio",
      "required": true,
      "options": ["Yes", "No"],
      "planned_answer": "Yes",
      "source": "application-defaults.md"
    },
    {
      "label": "Desired salary",
      "type": "select",
      "required": false,
      "options": ["< $100k", "$100k-$150k", "$150k-$200k", "> $200k", "Prefer not to say"],
      "planned_answer": null,
      "source": "UNRESOLVED — dropdown options do not include 'Negotiable'; agent must pick closest match"
    },
    {
      "label": "Why do you want to work at Stripe?",
      "type": "textarea",
      "required": false,
      "planned_answer": null,
      "source": "UNRESOLVED"
    }
  ],
  "resolved_count": 8,
  "unresolved_count": 2,
  "unresolved_labels": ["Desired salary", "Why do you want to work at Stripe?"],
  "error": null
}
```

On fatal error, `fields` is `[]`, `error` contains the exception message, and exit code is 2:
```json
{
  "url": "...",
  "company": "Stripe",
  "position": "Senior Software Engineer",
  "ats_type": "unknown",
  "multi_step": null,
  "warning": null,
  "scraped_at": "2026-03-21T10:30:00+00:00",
  "fields": [],
  "resolved_count": 0,
  "unresolved_count": 0,
  "unresolved_labels": [],
  "error": "TimeoutError: Page did not reach networkidle within 30s"
}
```

### Valid `source` Values

| Value | Meaning |
|-------|---------|
| `about-me.md` | Parsed directly from `data/about-me.md` |
| `application-defaults.md` | Parsed directly from `data/application-defaults.md` |
| `derived` | Computed from data (e.g., years of experience = current year minus earliest start year) |
| `file` | File upload field; `planned_answer` is the resolved file path string (first glob match) |
| `UNRESOLVED` | No match found or dropdown options incompatible with resolved answer |

### `planned_answer` for File Upload Fields

`planned_answer` is the string path of the first file matching the glob:
- Resume: first match of `.tmp/resume_<slug-company>_*.pdf`, fallback to `data/Resume-Mubashir.pdf`
- Cover letter: first match of `.tmp/cover_letter_<slug-company>_*.pdf`
- If no match: `null` with `source: "UNRESOLVED"`

### Core Logic

1. Add project root to `sys.path` (consistent with all other tools in this project)
2. Load `python-dotenv` (consistent pattern across all tools)
3. Parse `data/about-me.md` and `data/application-defaults.md` using line-by-line text parsing
   (no external markdown library — use regex to extract `**Field:** Value` and `- Field: Value`
   patterns, consistent with how existing tools access these files)
4. Launch Playwright headless Chromium
5. Navigate to URL with `--timeout` seconds; catch `TimeoutError` and bot-detection redirects
   (detect bot detection by checking if final URL differs from target or contains "captcha"/"blocked")
6. Wait for `networkidle`; add 2s sleep buffer for React hydration
7. Take debug screenshot to `.tmp/screenshots/inspect_<slug-company>_<slug-position>.png`
   (include position in filename to avoid collision when same company has multiple roles)
8. Detect ATS type from URL (or use `--ats-type` override):
   - `greenhouse.io` or `boards.greenhouse.io` → greenhouse, multi_step=true
   - `myworkdayjobs.com` or `workday` in domain → workday, multi_step=true
   - `ashbyhq.com` → ashby, multi_step=false
   - `jobs.lever.co` → lever, multi_step=false
   - else → unknown, multi_step=null
9. DOM extraction — do NOT interact with the form (no uploads, no clicks that trigger state changes):
   - `input[type=text], input[type=email], input[type=tel], input[type=number], input[type=url]`
   - `input[type=file]`
   - `input[type=radio]` grouped by nearest `fieldset`, `[role=radiogroup]`, or shared `name` attr
   - `input[type=checkbox]`
   - `select` elements (extract all `<option>` text values)
   - `textarea`
   - For label: check `<label for=id>`, then `aria-label`, then closest ancestor `<label>`,
     then `placeholder`. If none found, use `aria-labelledby` text content.
   - `required`: HTML `required` attribute OR `aria-required="true"` OR label contains `*`
   - Workday: also query `[data-automation-id]` attributes for semantic field identification
10. Answer resolution — keyword matching (case-insensitive `in` check on label text):
    - "first name" → about-me.md first name
    - "last name" / "surname" → about-me.md last name
    - "email" → about-me.md email
    - "phone" → about-me.md phone
    - "linkedin" → about-me.md LinkedIn URL
    - "github" → about-me.md GitHub URL
    - "portfolio" / "website" / "personal site" → about-me.md portfolio URL
    - "resume" / "cv" → file glob (see above)
    - "cover letter" → file glob (see above)
    - "years of experience" / "how many years" → derived: current year minus earliest work
      history start year parsed from about-me.md Work History section
    - "authorized" / "work authorization" / "eligible to work" → application-defaults.md: Yes
    - "sponsorship" / "visa" / "require sponsorship" → application-defaults.md: No
    - "salary" / "compensation" / "pay" → check dropdown options first; if "Negotiable" is not
      an option, set source to "UNRESOLVED" with note about dropdown incompatibility
    - "relocate" / "relocation" → application-defaults.md value
    - "gender" / "race" / "ethnicity" / "veteran" / "disability" → Decline to answer
    - Overlapping keyword rule: if multiple keywords match, use the one with the longest match
      length in the label text (most specific wins)
    - Company-specific essay questions (no keyword match) → UNRESOLVED
11. Build and write JSON (UTC timestamp with timezone offset)
12. Print summary to stdout
13. Exit with appropriate exit code

### No New Dependencies

`form_inspector.py` uses only packages already in `requirements.txt`:
- `playwright` — browser automation
- `python-dotenv` — `.env` loading

---

## Step 2 — Fix Ashby Status in apply_to_job.md

Update the following locations in `workflows/apply_to_job.md`:

**Step 2 ATS support list** (currently says "Lever / Ashby / LinkedIn — screenshot only (stubs)"):
```
Before:
- Lever / Ashby / LinkedIn — screenshot only (stubs)

After:
- Ashby — full automation
- Lever / LinkedIn — screenshot only (stubs)
```

**Edge cases table** (currently says "ATS not supported (Lever, Ashby)"):
```
Before:
| ATS not supported (Lever, Ashby) | Provide cover letter + fields for manual paste; log as In Progress |

After:
| ATS not supported (Lever, LinkedIn) | Provide cover letter + fields for manual paste; log as In Progress |
```

**Step 1b** — replace WebFetch instructions with:
```
Run the form inspector tool to map all visible fields on page 1 of the application:

python modules/apply/form_inspector.py \
  --url "<job_url>" \
  --company "<Company>" \
  --position "<Position>"

Read the output JSON from .tmp/form_fields_<slug>.json.
- Exit code 0: all fields resolved — proceed to Step 2.
- Exit code 1: UNRESOLVED fields found — review unresolved_labels with user, get answers,
  add them to data/application-defaults.md, then proceed to Step 2.
- Exit code 2: fatal error — check error field in JSON, resolve issue before proceeding.
- Multi-step warning present: acknowledge that more fields will appear in preview mode.
```

---

## Step 3 — Crawl4AI Job Board Scrapers

Add `crawl4ai` to `requirements.txt`. Add scrapers to `modules/search/`:

- `scrape_greenhouse_jobs.py` — search Greenhouse boards for target companies
- `scrape_company_careers.py` — direct career page scraping for priority company list from find_jobs.md
- `scrape_linkedin_jobs.py` — LinkedIn job search (rate-limit aware, exponential backoff retry)

Each scraper CLI outputs JSON list of `{company, title, url, location, stack_keywords}`.
The agent deduplicates against Google Sheet tracker and builds `.tmp/job_shortlist_YYYY-MM-DD.md`.

Update tool references in `find_jobs.md` from `tools/scrape_*.py` → `modules/search/scrape_*.py`.

---

## Step 4 — Lever ATS Handler

Implement `modules/apply/ats/lever.py` replacing the empty stub.

Lever is common in fintech/startup. Standard form: contact info, resume upload, optional cover
letter, LinkedIn URL, work authorization Yes/No, open-ended essay questions.
Single-page or 2-page. Standard HTML — no React synthetic events needed.

Wire it into `browser_apply.py` ATS dispatch: `jobs.lever.co` → Lever handler.

---

## Step 5 — browser-use Fallback

Add `browser-use` to `requirements.txt`. In `browser_apply.py`, when ATS type is `unknown`,
invoke `browser-use` with a natural language prompt describing the form fill task using the
field map from `form_inspector.py` output. This handles novel ATS platforms without a bespoke handler.

---

## Complete File Change List

| File | Change |
|------|--------|
| `modules/apply/form_inspector.py` | NEW |
| `workflows/apply_to_job.md` | Update Step 1b command + ATS table in Step 2 + edge cases table |
| `modules/search/scrape_greenhouse_jobs.py` | NEW |
| `modules/search/scrape_company_careers.py` | NEW |
| `modules/search/scrape_linkedin_jobs.py` | NEW |
| `workflows/find_jobs.md` | Update tool paths from tools/ to modules/search/ |
| `modules/apply/ats/lever.py` | Replace empty stub with full implementation |
| `modules/apply/browser_apply.py` | Add Lever dispatch + browser-use fallback |
| `requirements.txt` | Add crawl4ai, browser-use |
