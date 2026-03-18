cl2# Workflow: Update Application Tracker

## Objective

After every job application is submitted or attempted, log it to the Google Sheet tracker
using `modules/tracker/update_sheet.py`. This is the system of record for all applications.

## Required Inputs

- Company name
- Position / job title
- Date applied (YYYY-MM-DD)
- Job posting URL
- Status (`Applied` / `In Progress` / `Skipped` / `Interview` / `Rejected` / `Offer`)
- Notes (optional — e.g., contract role, referred by, cover letter customization note)

## Google Sheet Schema

The tracker sheet must have these columns in this exact order:

| Column | Description |
|--------|-------------|
| A — Company | Company name |
| B — Position | Job title as listed in the posting |
| C — Date Applied | YYYY-MM-DD format |
| D — Job URL | Full URL of the job posting |
| E — Status | Applied / In Progress / Skipped / Interview / Rejected / Offer |
| F — Notes | Free text — contract, referral, keywords used, follow-up needed, etc. |

## Step-by-Step

### Step 1 — Check for Duplicate

Before writing, call `modules/tracker/read_sheet.py` to fetch existing rows.

Check if a row already exists with the same Company + Position combination.

- If duplicate found: skip writing, notify the user, do not create a duplicate row.
- If not found: proceed to Step 2.

### Step 2 — Write the Row

Call `modules/tracker/update_sheet.py` with the following arguments:

```bash
python modules/tracker/update_sheet.py \
  --company   "<company name>" \
  --position  "<job title>" \
  --date      "<YYYY-MM-DD>" \
  --url       "<job posting URL>" \
  --status    "<status>" \
  --notes     "<optional notes>"
```

The script appends a new row to the next empty row in the sheet.

### Step 3 — Confirm

After the script runs successfully, confirm to the user:

```
Logged: [Company] — [Position] | Status: Applied | [Date]
```

If the script fails, log the error and retry once. If it fails again, save the row data to
`.tmp/failed_log_<date>.json` so it can be manually added or retried later.

## Status Values

| Status | When to use |
|--------|-------------|
| `Applied` | Application submitted successfully |
| `In Progress` | Started application but not yet submitted (e.g., waiting for user to create account) |
| `Skipped` | Decided not to apply (not a fit, excluded company, etc.) |
| `Interview` | Recruiter / hiring manager reached out |
| `Rejected` | Received rejection |
| `Offer` | Received offer |

## Updating Existing Rows

To update an existing row (e.g., status changes from Applied to Interview):

```bash
python modules/tracker/update_sheet.py \
  --company   "<company name>" \
  --position  "<job title>" \
  --update-status "<new status>" \
  --notes     "<optional update note>"
```

The script will find the existing row by Company + Position and update only the Status and Notes columns.

## Edge Cases

- **Sheet not found / auth error:** Check that `credentials.json` and `token.json` exist and are valid.
  Re-run `modules/shared/auth_google.py` to refresh the token.
- **Row not appending:** Verify the sheet ID in `modules/shared/config.py` is correct.
- **Duplicate found but user insists on logging:** Add a suffix to position (e.g., "Senior SWE (2nd attempt)") and log.
