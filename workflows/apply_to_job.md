# Workflow: Apply to Job

## Objective

Given a ready application package (cover letter + resume PDFs), submit the job application
via browser automation, confirm submission, and log to the tracker.

Requires `workflows/tailor_application.md` to have run first and the user to have approved
the application package.

## Required Inputs

- Job posting URL
- Company name
- Position title
- `.tmp/cover_letter_<Company>_<Role>_<date>.md` — cover letter markdown
- `.tmp/cover_letter_<Company>_<Role>_<date>.pdf` — cover letter PDF
- `.tmp/resume_<Company>_<Role>_<date>.pdf` — tailored resume PDF

---

## Step 1 — Duplicate Check

Before submitting, verify this company + position hasn't already been applied to:

```bash
python modules/tracker/read_sheet.py --check-dup "<Company>" "<Position>"
```

- `DUPLICATE` found → stop, notify user, do not apply again.
- `NOT_FOUND` → proceed to Step 2.

---

## Step 2 — Preview (Fill Form, No Submit)

Run browser automation in **preview** mode — fills the form and takes screenshots
without submitting:

```bash
python modules/apply/browser_apply.py \
  --url "<job_url>" \
  --cover-letter ".tmp/cover_letter_<Company>_<Role>_<date>.md" \
  --company "<Company>" \
  --position "<Position>" \
  --mode preview
```

ATS detection is automatic from the URL. Supported ATS:
- **Greenhouse** — full automation
- **Workday** — full automation (requires WORKDAY_EMAIL + WORKDAY_PASSWORD in .env for account-creation gates)
- **Stripe** — full automation (Greenhouse-based)
- **Lever / Ashby / LinkedIn** — screenshot only (stubs)

Read all screenshots from `.tmp/screenshots/` using the Read tool and show them to the user.

---

## Step 3 — User Confirmation

Present the screenshots and ask the user:
- Does the filled form look correct?
- Any fields to fix before submitting?

If corrections needed: stop, fix the data in `data/about-me.md` or `data/application-defaults.md`,
then re-run Step 2.

---

## Step 4 — Submit

On user approval, run in **submit** mode:

```bash
python modules/apply/browser_apply.py \
  --url "<job_url>" \
  --cover-letter ".tmp/cover_letter_<Company>_<Role>_<date>.md" \
  --company "<Company>" \
  --position "<Position>" \
  --mode submit
```

Read the confirmation screenshot and show it to the user.

---

## Step 5 — Log to Tracker

After successful submission, immediately log via `workflows/update_tracker.md`:

```bash
python modules/tracker/update_sheet.py \
  --company   "<Company>" \
  --position  "<Position>" \
  --date      "<YYYY-MM-DD>" \
  --url       "<job_url>" \
  --status    "Applied" \
  --notes     "<optional: ATS used, keywords, contract flag, etc.>"
```

---

## Step 6 — On Rejection / Skip

If the user decides not to apply after seeing the preview:
- Ask for the reason.
- If company should be excluded going forward, update `data/about-me.md`.
- Log with status `Skipped` if the application was started but abandoned.
- Do not log if the application was never attempted.

---

## Edge Cases

| Situation | Action |
|-----------|--------|
| ATS not supported (Lever, Ashby) | Provide cover letter + fields for manual paste; log as `In Progress` |
| Workday account-creation gate | Set WORKDAY_EMAIL + WORKDAY_PASSWORD in .env and retry |
| CAPTCHA encountered | Stop, screenshot, ask user to complete manually |
| Salary field required | Use "Negotiable / Market rate" unless user specifies |
| Work authorization asked | Always: authorized = Yes, sponsorship = No |
| Contract role | Note "Contract" in tracker Notes column |

---

## Output

- Confirmation screenshot in `.tmp/screenshots/`
- New row in Google Sheet tracker (via `workflows/update_tracker.md`)
