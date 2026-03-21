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
- `NOT_FOUND` → proceed to Step 1b.

Also check `data/about-me.md` → "Already Applied" and "Do Not Apply" sections for in-memory overrides.

---

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
- **Ashby** — full automation
- **Lever / LinkedIn** — screenshot only (stubs)

Read all screenshots from `.tmp/screenshots/` using the Read tool and show them to the user.

---

## Step 3 — Review Screenshots

Review screenshots from `.tmp/screenshots/` — check that every field is filled correctly.
If any field is wrong or missing:
- Fix the answer in `data/application-defaults.md` or `data/about-me.md`
- Re-run Step 2 before submitting

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
| ATS not supported (Lever, LinkedIn) | Provide cover letter + fields for manual paste; log as `In Progress` |
| Workday account-creation gate | Set WORKDAY_EMAIL + WORKDAY_PASSWORD in .env and retry |
| CAPTCHA encountered | Stop, screenshot, ask user to complete manually |
| Salary field required | Use "Negotiable / Market rate" unless user specifies |
| Work authorization asked | Always: authorized = Yes, sponsorship = No |
| Contract role | Note "Contract" in tracker Notes column |

---

## Output

- Confirmation screenshot in `.tmp/screenshots/`
- New row in Google Sheet tracker (via `workflows/update_tracker.md`)
