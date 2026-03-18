# Workflow: Tailor Application

## Objective

For a given job posting, research the company, score the ATS keyword match, write a
tailored cover letter, and generate PDFs. Produces a ready-to-review application package.

Hands off to `workflows/apply_to_job.md` when the user approves.

## Required Inputs

- Job posting URL
- Job title
- Company name
- Job description (full text)

---

## Step 1 — Load User Profile

Read `data/about-me.md` to get:
- Contact details (name, email, phone, LinkedIn, GitHub, portfolio)
- EU contact details if the role is EU/UK/European — use `--location` and `--phone` overrides
- Visa status and work authorization statement
- Key differentiators and experience summary
- Skills not to claim (e.g. Kafka, RabbitMQ — check the "Do NOT Claim" section)

Read `data/application-defaults.md` to get:
- Standard answers for US job application fields (disability, veteran, sponsorship, EEO, etc.)
- If a question appears on the application NOT in this file, stop and ask the user

---

## Step 2 — Research the Company

Gather context to personalise the cover letter:

- What does the company do? What is their core product?
- Stage (startup, scale-up, public)?
- Recent news, funding rounds, or product launches worth mentioning?
- Tech stack (if public)?
- Hiring manager or engineering lead (LinkedIn, company blog)?

Save output to `.tmp/research_<company>_<date>.md`

---

## Step 3 — Extract Keywords from Job Description

Parse the job description and extract into these categories:

| Category | What to look for |
|----------|-----------------|
| **Hard skills** | Languages, frameworks, tools (e.g., Java, Spring Boot, Kafka, AWS, Kubernetes) |
| **Soft/domain skills** | Payments, distributed systems, fintech, microservices, event-driven |
| **Seniority signals** | "lead", "own", "drive", "mentor", "architect", "staff", "principal" |
| **Culture signals** | "fast-paced", "ownership", "cross-functional", "high scale", "reliability" |
| **ATS trigger phrases** | Exact phrases repeated 2+ times in the JD — these weight heavily in ATS |

Save to `.tmp/keywords_<company>_<role>_<date>.md`

---

## Step 3a — ATS Keyword Match Score

Before writing the cover letter, score how well Mubashir's profile matches the JD.

**Process:**

1. Take the full keyword list from Step 3
2. Check each keyword against `data/resume.md` and `data/about-me.md`
3. Classify each keyword:
   - `MATCH` — keyword clearly present in resume/profile
   - `PARTIAL` — related concept present but exact phrasing differs
   - `MISSING` — not present at all

4. Compute ATS score:
   - Score = (MATCH + 0.5 × PARTIAL) / total keywords × 100
   - Target: **70%+ before applying**

5. For every `PARTIAL` keyword, suggest a phrase that bridges the gap naturally

**ATS Score Report format:**

```
## ATS Match Report — [Company] | [Role]

Overall Score: XX%  (Target: ≥70%)

| Keyword            | Category     | Status  | Resume Evidence / Suggestion         |
|--------------------|--------------|---------|--------------------------------------|
| Java               | Hard skill   | MATCH   | "Java, Spring Boot" — current role   |
| Kafka              | Hard skill   | MISSING | Not in resume — skip or note exposure |
| Payments platform  | Domain       | MATCH   | "wallet & accounting microservices"  |
| Mentoring          | Seniority    | PARTIAL | Add "mentored junior engineers"      |

Recommendation: [PROCEED / PROCEED WITH NOTES / FLAG TO USER]
```

Save to `.tmp/ats_report_<company>_<role>_<date>.md`

**Rules:**
- Score ≥ 70%: proceed automatically
- Score 60–69%: proceed but note gaps in the package
- Score < 60%: flag to user with report — let them decide
- Never fabricate keywords. Only use skills in resume or about-me.md.

---

## Step 4 — Write Tailored Cover Letter

Load template from `data/cover-letter-template.md` and fill all placeholders:

| Placeholder | Replace with |
|-------------|-------------|
| `[Hiring Manager Name / Hiring Manager]` | Hiring manager name if found, else "Hiring Manager" |
| `[Job Title]` | Exact job title from posting |
| `[Company Name]` | Company name |
| `[insert company-specific reason]` | 1–2 sentences from company research |
| `[insert keywords from job description]` | Top 3–5 matching keywords from Step 3 |

Rules:
- One page maximum.
- Human and direct — not robotic.
- Emphasise impact, scale, and ownership.
- **EU roles:** use Berlin location and EU phone number. Replace J-2 EAD statement with "I am based in Berlin, Germany and available to work remotely within EU timezones."
- **US roles:** always include J-2 + EAD statement.
- **Keyword optimise:** weave MATCH and PARTIAL keywords naturally into the body. Prioritise phrases that appear 2+ times in the JD. Never fabricate experience.

Save to `.tmp/cover_letter_<company>_<role>_<date>.md`

---

## Step 4a — Generate PDFs

After the cover letter is written, generate PDF documents.

**Write the `--summary` first:**
- Take top 4–6 MATCH keywords from the ATS report
- Write a 2-sentence hook: opens with the job title from the JD, naturally includes those keywords
- Example: "Senior Backend Engineer with 11+ years building distributed payment systems on Java, Spring Boot, and AWS. Proven track record delivering high-throughput microservices with 99.9%+ uptime in fintech environments."

**US role:**
```bash
python modules/tailor/generate_pdf.py \
  --cover-letter ".tmp/cover_letter_<Company>_<Role>_<date>.md" \
  --company "<Company>" \
  --position "<Position>" \
  --summary "<2-sentence keyword hook>"
```

**EU role** (adds Berlin location + EU phone to resume header):
```bash
python modules/tailor/generate_pdf.py \
  --cover-letter ".tmp/cover_letter_<Company>_<Role>_<date>.md" \
  --company "<Company>" \
  --position "<Position>" \
  --summary "<2-sentence keyword hook>" \
  --location "Berlin, Germany" \
  --phone "+4917669032445"
```

Outputs:
- `.tmp/cover_letter_<Company>_<Position>_<date>.pdf`
- `.tmp/resume_<Company>_<Position>_<date>.pdf`

---

## Step 5 — Prepare Application Package

Compile the full application for review:

```
## Application Draft — [Company] | [Position] | [Date]

**Job URL:** [url]
**Hiring Manager:** [name or "Not found"]
**ATS Match Score:** XX% | Top matched keywords: Java, Spring Boot, [...]
**Gaps flagged:** [any MISSING keywords worth noting]

---

### Cover Letter
[full cover letter text]

---

### Resume
data/resume.md (PDF: .tmp/resume_<Company>_<Position>_<date>.pdf)

---

### Additional Fields (if any)
- Years of experience: 11
- Visa / work authorization: J-2 EAD, no sponsorship required
- LinkedIn: https://linkedin.com/in/mubashir-ali992
- GitHub: https://github.com/mubashirali/
- Portfolio: https://mubashir-ali.netlify.app/
- Salary expectation: [skip if optional]

---

**Ready to submit?** Review above and confirm.
```

Present to the user and wait for approval before handing off to `workflows/apply_to_job.md`.

---

## Output

| File | Description |
|------|-------------|
| `.tmp/keywords_<company>_<role>_<date>.md` | Extracted JD keywords |
| `.tmp/ats_report_<company>_<role>_<date>.md` | ATS match score + gap analysis |
| `.tmp/research_<company>_<date>.md` | Company research notes |
| `.tmp/cover_letter_<company>_<role>_<date>.md` | Tailored cover letter (markdown) |
| `.tmp/cover_letter_<company>_<role>_<date>.pdf` | Cover letter PDF |
| `.tmp/resume_<company>_<role>_<date>.pdf` | Resume PDF with tailored summary |

## Next Step

On user approval → `workflows/apply_to_job.md`
On rejection → ask for reason; if company excluded, update `data/about-me.md`
