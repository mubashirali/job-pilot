# Workflow: Find Jobs

## Objective

Search across multiple job portals for Senior / Lead Backend Software Engineer roles that match Mubashir's profile,
deduplicate against already-applied jobs in the Google Sheet tracker, and return a shortlist ready for application.

## Required Inputs

- Current list of applied jobs from the Google Sheet (to avoid duplicates)
- Optional: override search keywords or filters for this run

## Target Profile (from CLAUDE.md)

- **Role keywords:** Senior Software Engineer, Lead Software Engineer, Staff Software Engineer, Backend Engineer,
  Java Engineer, Distributed Systems Engineer, Platform Engineer
- **Stack keywords:** Java, Spring Boot, Kotlin, Microservices, AWS, Kubernetes, Distributed Systems, Fintech, Payments
- **Location:** Remote (USA); or hybrid/onsite in Missouri / Kansas area
- **Visa:** No sponsorship required — filter out roles that require H-1B sponsorship

## Search Sources

Run searches across all of the following in each session:

### 1. LinkedIn Jobs
- URL: https://www.linkedin.com/jobs/
- Filters: Remote | United States | Posted in last 7 days | Experience: Senior level
- Use tool: `modules/search/scrape_linkedin_jobs.py`
- Search queries to run:
  - "Senior Software Engineer Java Remote"
  - "Lead Backend Engineer Spring Boot Remote"
  - "Staff Software Engineer Microservices Remote"
  - "Senior Java Engineer Fintech Remote"
  - "Backend Engineer Distributed Systems Remote"

### 2. Indeed
- URL: https://www.indeed.com/
- Filters: Remote | Full-time | Posted in last 7 days
- Use tool: `modules/search/scrape_linkedin_jobs.py`
- Search queries to run:
  - "Senior Software Engineer Java Remote"
  - "Lead Backend Engineer Remote"
  - "Senior Java Developer Fintech"
  - "Distributed Systems Engineer Remote"

### 3. Greenhouse Job Boards
- Greenhouse is used by many tech companies. Search via:
  - https://boards.greenhouse.io/ (company-specific boards)
  - Aggregate via: https://www.greenhouse.io/job-board
- Use tool: `modules/search/scrape_greenhouse_jobs.py`
- Target companies known to use Greenhouse: Stripe, Brex, Plaid, Rippling, Chime, Robinhood, etc.

### 4. Company Career Pages (Direct)
Check these high-priority companies directly each run:

| Company       | Career Page URL                                      | Why |
|---------------|------------------------------------------------------|-----|
| Stripe        | https://stripe.com/jobs                              | Fintech, Java/distributed systems |
| Plaid         | https://plaid.com/careers/                           | Fintech, payments |
| Brex          | https://www.brex.com/careers                         | Fintech, backend-heavy |
| Chime         | https://www.chime.com/careers/                       | Fintech, payments |
| Robinhood     | https://careers.robinhood.com/                       | Fintech, high scale |
| Rippling      | https://www.rippling.com/careers                     | SaaS, backend infra |
| Coinbase      | https://www.coinbase.com/careers/                    | Crypto/fintech |
| Square/Block  | https://careers.squareup.com/                        | Fintech, payments |
| Gusto         | https://gusto.com/company/jobs                       | Fintech, payroll |
| Affirm        | https://www.affirm.com/careers                       | Fintech, payments |
| Marqeta       | https://www.marqeta.com/company/careers              | Payments, card issuing |
| Mercury       | https://mercury.com/jobs                             | Fintech banking |

- Use tool: `modules/search/scrape_company_careers.py`

### 5. Other Portals
- **Wellfound (AngelList):** https://wellfound.com/jobs — strong for startups
- **Lever:** Search via company boards (similar to Greenhouse)
- **Glassdoor:** https://www.glassdoor.com/Job/
- **Dice:** https://www.dice.com/ — strong for tech/engineering roles in the US
- **Remotive:** https://remotive.com/ — remote-only roles
- **We Work Remotely:** https://weworkremotely.com/

## Filtering Criteria

After scraping, filter results to only include jobs that meet ALL of the following:

- [ ] Role title contains: Engineer, Developer, or Architect (exclude QA, DevOps-only, PM, Data Science)
- [ ] Seniority: Senior, Lead, Staff, or Principal (exclude Junior, Mid, Intern)
- [ ] Stack overlap: at least one of Java, Spring Boot, Kotlin, Microservices, AWS, Distributed Systems
- [ ] Location: Remote (USA) OR onsite/hybrid in Missouri or Kansas
- [ ] NOT already in the Google Sheet tracker (check by company + role title)
- [ ] Does NOT explicitly require H-1B sponsorship or US citizenship (e.g., DoD clearance)

## Deduplication

Before returning results:

1. Pull current applications from Google Sheet using `modules/tracker/read_sheet.py`
2. Compare each result against existing rows by (Company + Position)
3. Drop any matches — do not re-apply

## Output Format

Return a list of job opportunities in this format:

```
## Job Shortlist — [Date]

1. **[Company]** — [Position Title]
   - URL: [Job posting URL]
   - Location: [Remote / Hybrid / Onsite + city]
   - Stack match: [e.g., Java, Spring Boot, AWS]
   - Notes: [Any relevant detail — visa, sponsorship policy, stage, etc.]

2. ...
```

Save the raw shortlist to `.tmp/job_shortlist_YYYY-MM-DD.md` for reference.

## Edge Cases

- **Rate limiting / blocked scraper:** Wait 60s and retry once. If still blocked, skip that source and log it.
- **Job posting with no stack info:** Include it only if the company is on the priority list above.
- **Ambiguous seniority (e.g., "Software Engineer III"):** Include it — apply judgment from the job description.
- **Contract roles:** Include them. Mubashir is open to contract.

## Continuous Apply Mode

Activated when the user says "apply until stopped", "keep applying", "search and apply loop", or similar.

In this mode the agent does **not** build a full shortlist. Instead it works one job at a time:

### Loop

1. **Find one job** — identify the single highest-fit qualifying job not yet applied to:
   - Search sources in order: job-search skill (hiring.cafe) → Greenhouse boards → direct career pages
   - Apply all Filtering Criteria and Deduplication checks from this workflow
   - Pick the top-scoring job per `shared/references/fit-scoring.md` (High before Medium)
2. **Apply immediately** — hand off to `workflows/apply_to_job.md` for that one job
   - Present the application draft to the user for review before submitting
   - Wait for approval, edits, or skip instruction
3. **After apply completes** (submitted, skipped, or rejected) — loop back to step 1
4. **Stop when:**
   - User explicitly says "stop", "that's enough", "pause", or similar
   - No qualifying jobs remain in current search results (report this and ask to re-search)
   - An error requires user input that blocks the loop

### In-Memory State (maintain across iterations)

Keep a running list in context of jobs already seen this session (company + role) to avoid
re-fetching the same postings. Do not re-present a job the user has already rejected this session.

### User Controls During Loop

At any point the user can say:
- **"skip"** → skip current job, move to next
- **"stop"** → exit the loop, summarise what was applied
- **"pause"** → finish current application, then stop
- **"show shortlist"** → display remaining qualifying jobs found so far before continuing

### Session Summary on Stop

When the loop ends, output:

```
## Apply Session Summary — [Date]

Applied: [N] jobs
Skipped: [N] jobs
---
[List of applied: Company | Role | Status]
[List of skipped: Company | Role | Reason]
```

## Next Step

- **Batch mode (default):** After producing the shortlist, proceed to `workflows/apply_to_job.md` for each job.
- **Continuous mode:** Activate when user requests "apply until stopped" — follow the Continuous Apply Mode section above.
