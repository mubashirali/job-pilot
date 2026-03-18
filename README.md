# JobPilot

Put your job search on autopilot. **JobPilot** is an autonomous job application agent built on the **WAT framework** (Workflows, Agents, Tools). It uses Claude Code as the AI decision-maker to find relevant job postings, tailor applications, submit them via browser automation, and track everything in a Google Sheet — with minimal human intervention.

---

## What It Does

| Capability | Description |
|---|---|
| **Find jobs** | Searches LinkedIn, Indeed, Greenhouse boards, and direct company career pages for matching roles |
| **Deduplicate** | Checks your Google Sheet tracker before applying — never applies to the same role twice |
| **Tailor applications** | Scores ATS keyword match (target ≥ 70%), writes a tailored cover letter, generates resume + cover letter PDFs |
| **Auto-apply** | Fills and submits job application forms via headless browser automation (Playwright) |
| **Track everything** | Logs every application to a Google Sheet with company, role, date, URL, and status |
| **Continuous mode** | "Apply until stopped" — loops: find → tailor → apply → log, one job at a time |

---

## Architecture

```
workflows/          # Markdown SOPs (what to do and in what order)
data/               # Your profile, resume, cover letter template, application defaults
modules/
  shared/           # Config loader, Google OAuth helper
  tracker/          # Read/write Google Sheet, read Gmail
  tailor/           # PDF generation (cover letter + resume)
  apply/            # Browser automation + ATS handlers
    ats/            # Greenhouse, Workday, Lever, Ashby, LinkedIn
  search/           # Job scrapers (placeholder — add your scrapers here)
.tmp/               # Generated files: PDFs, screenshots, shortlists (disposable)
```

The AI (Claude Code) reads the workflows, makes decisions, and calls the Python scripts. Python scripts do all deterministic execution — API calls, form filling, PDF generation, Sheet writes.

---

## Workflow Chain

```
find_jobs → tailor_application → apply_to_job → update_tracker
```

Each workflow is also independently runnable (e.g., tailor without applying, or log a manual application).

---

## Prerequisites

- Python 3.11+
- [Claude Code](https://github.com/anthropics/claude-code) installed and authenticated
- A Google account (for Sheets + Gmail tracking)
- A Google Cloud project with Sheets API + Gmail API enabled

---

## Setup

### 1. Clone and install dependencies

```bash
git clone <repo-url>
cd JobPilot
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
```

### 2. Configure your profile

**Everything the agent needs to know about you lives in the `data/` folder.**

| File | What to edit |
|---|---|
| `data/about-me.md` | Your name, contact info, skills, work history, job preferences, hard filters |
| `data/resume.md` | Your full resume in markdown (source for PDF generation) |
| `data/Resume-YourName.pdf` | Your existing resume PDF (used as upload fallback) |
| `data/cover-letter-template.md` | Your cover letter template with placeholders |
| `data/application-defaults.md` | Standard answers for US job application fields (EEO, visa, salary, etc.) |

See [Adapting for Yourself](#adapting-for-yourself) below for exactly what to change.

### 3. Set up environment variables

Create a `.env` file in the project root:

```env
GOOGLE_SHEET_ID=your_google_sheet_id_here
GOOGLE_SHEET_TAB=Sheet1

# Optional: only needed for Workday ATS
WORKDAY_EMAIL=your-email@example.com
WORKDAY_PASSWORD=your-workday-password
```

To find your Sheet ID: open your Google Sheet and copy the ID from the URL:
`https://docs.google.com/spreadsheets/d/THIS_IS_THE_ID/edit`

### 4. Set up Google OAuth

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a project (or use an existing one)
3. Enable **Google Sheets API** and **Gmail API**
4. Go to **APIs & Services → Credentials → Create Credentials → OAuth 2.0 Client ID**
5. Application type: **Desktop app**
6. Download the JSON file and save it as `credentials.json` in the project root
7. Run the one-time auth setup:

```bash
python modules/shared/auth_google.py
```

A browser window will open. Authenticate with your Google account. A `token.json` file is saved — you won't need to do this again unless the token expires.

### 5. Set up your Google Sheet

Create a Google Sheet with these columns in this exact order:

| A — Company | B — Position | C — Date Applied | D — Job URL | E — Status | F — Notes |
|---|---|---|---|---|---|

The agent will append a new row for each application submitted.

---

## Usage

Start Claude Code in the project directory:

```bash
claude
```

Then give natural language instructions:

```
Find me 5 Senior Backend Engineer jobs and create a shortlist
```

```
Tailor and apply to this job: https://boards.greenhouse.io/company/jobs/12345
```

```
Apply until stopped
```

```
Log a manual application: Company=Acme, Position=Senior SWE, URL=..., Status=Applied
```

```
Check my tracker for duplicates, then apply to the top 3 jobs from today's shortlist
```

### Two-phase application (always)

The agent always runs in **preview mode first** — it fills the form and takes screenshots without submitting. You review the screenshots, then confirm to submit. This prevents accidental submissions.

### Status values in the tracker

| Status | Meaning |
|---|---|
| `Applied` | Submitted successfully |
| `In Progress` | Started but not yet submitted |
| `Skipped` | Decided not to apply |
| `Interview` | Recruiter/hiring manager reached out |
| `Rejected` | Rejection received |
| `Offer` | Offer received |

---

## Supported ATS Platforms

| ATS | Support level |
|---|---|
| Greenhouse | Full automation |
| Workday | Full automation (requires account credentials in `.env`) |
| Stripe (Greenhouse-based) | Full automation |
| Lever | Screenshot only (manual paste) |
| Ashby | Screenshot only (manual paste) |
| LinkedIn | Blocked — use direct ATS URL instead |

---

## Adapting for Yourself

This project was built for a specific user. To use it for yourself, update these files:

### `data/about-me.md`

Replace all personal details with your own:

```markdown
## Contact Details
- Full Name: Your Name
- Email: you@example.com
- Phone: +1...
- LinkedIn: https://linkedin.com/in/yourhandle
- GitHub: https://github.com/yourusername
- Portfolio: https://your-site.com
- Location: Your City, State, USA

## Key Facts
- Profession: [Your role title]
- Core Skills: [Your primary skills]
- Visa Status: [e.g., US Citizen / Green Card / OPT / etc.]
- Open to: [Full-time / Contract / Remote / etc.]
- Career Focus: [Your target roles and domains]

## Work History
- [Title] @ [Company] ([years])
- ...

## Job Search Patterns
### Best-fit role titles to target:
- [Your target titles]

### Stack signals to look for:
- [Your tech stack]

### Domains — in priority order:
1. [Your preferred domains]

### Hard filters — skip these automatically:
- [Your dealbreakers — visa requirements, role types, etc.]
```

Key sections to update:
- **Contact Details** — your name, email, phone, LinkedIn, GitHub
- **Key Facts** — your profession, skills, and visa/work authorization status
- **Work History** — your employment history
- **Skills — Do NOT Claim** — list technologies you don't have real experience with
- **Job Search Patterns** — your target titles, stack, and domains
- **Hard filters** — roles you want automatically skipped

### `data/resume.md`

Replace with your actual resume content. This is the source file for PDF generation. Keep the same markdown structure (Contact, Professional Summary, Technical Skills, Experience, etc.) — the PDF generator reads it.

### `data/Resume-YourName.pdf`

Replace `data/Resume-Mubashir.pdf` with your own PDF resume. Update the filename reference in `data/about-me.md`:

```markdown
## Application Workflow
- Resume path: data/Resume-YourName.pdf
```

### `data/cover-letter-template.md`

Replace the template body with your own. Keep these placeholders — the agent fills them in per job:

```
[Hiring Manager Name / Hiring Manager]
[Job Title]
[Company Name]
[insert company-specific reason]
[insert keywords from job description]
```

Update your name, LinkedIn URL, and portfolio link at the bottom.

### `data/application-defaults.md`

Update the standard answers for your situation:

```markdown
## Work Authorization
| Are you authorized to work in the US? | Yes / No |
| Do you require visa sponsorship?       | Yes / No |
| Visa type                              | [Your visa status] |

## EEO (Equal Employment Opportunity)
| Gender   | [Your gender] |
| Race     | [Your ethnicity] |

## Role & Availability
| Years of relevant experience | [Your years] |
| LinkedIn                     | [Your LinkedIn URL] |
| GitHub                       | [Your GitHub URL] |
```

### `CLAUDE.md`

The `## Primary Mission` and `## User Profile` sections reference your profile. Once you've updated `data/about-me.md`, you may also want to update the role descriptions and domain focus in CLAUDE.md to match your background.

---

## File Reference

```
.env                         # API keys and Sheet ID (gitignored — never commit this)
credentials.json             # Google OAuth credentials (gitignored)
token.json                   # Google OAuth token (gitignored — auto-generated)
requirements.txt             # Python dependencies
CLAUDE.md                    # Agent instructions (read by Claude Code automatically)

data/
  about-me.md                # YOUR profile — the single source of truth
  resume.md                  # YOUR resume in markdown
  Resume-YourName.pdf        # YOUR resume PDF
  cover-letter-template.md   # YOUR cover letter template
  application-defaults.md    # YOUR standard job application answers

workflows/
  find_jobs.md               # How to search and filter job postings
  tailor_application.md      # How to write cover letters and generate PDFs
  apply_to_job.md            # How to fill and submit applications
  update_tracker.md          # How to log applications to Google Sheets

modules/
  shared/config.py           # Reads .env — single source for all config
  shared/auth_google.py      # One-time Google OAuth setup
  tracker/read_sheet.py      # CLI: read tracker / check duplicates
  tracker/update_sheet.py    # CLI: log or update an application row
  tracker/read_gmail.py      # CLI: check Gmail for application confirmation emails
  tailor/generate_pdf.py     # CLI: generate cover letter + resume PDFs
  apply/browser_apply.py     # CLI: fill and submit job application forms

.tmp/                        # Auto-generated — disposable
  job_shortlist_YYYY-MM-DD.md
  cover_letter_Company_Role_date.{md,pdf}
  resume_Company_Role_date.pdf
  screenshots/               # Form preview screenshots
```

---

## Gitignore Recommendations

Add these to your `.gitignore`:

```
.env
credentials.json
token.json
.tmp/
.venv/
__pycache__/
.DS_Store
```

---

## Troubleshooting

**Google auth errors:** Delete `token.json` and re-run `python modules/shared/auth_google.py`

**Sheet not updating:** Verify `GOOGLE_SHEET_ID` and `GOOGLE_SHEET_TAB` in `.env` match your actual sheet

**Playwright/browser errors:** Run `playwright install chromium` to reinstall the browser

**CAPTCHA on application form:** The agent will stop and show a screenshot — complete it manually, then tell the agent to continue

**ATS not supported:** For Lever/Ashby, the agent screenshots the form and gives you the field values to paste manually