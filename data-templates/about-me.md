# User Context Summary

<!-- ──────────────────────────────────────────────────────────────────────────
     TEMPLATE FILE — copy to data/about-me.md and fill in your details,
     OR start Claude Code and it will ask you questions and fill this for you.
     ────────────────────────────────────────────────────────────────────────── -->

## Contact Details
- **Full Name:** [YOUR_FULL_NAME]
- **Email:** [YOUR_EMAIL]
- **Phone:** [YOUR_PHONE]
- **LinkedIn:** [YOUR_LINKEDIN_URL]
- **GitHub:** [YOUR_GITHUB_URL]
- **Portfolio:** [YOUR_PORTFOLIO_URL]
- **Location:** [YOUR_CITY], [YOUR_STATE], [YOUR_COUNTRY]

## EU Contact Details (use only for EU/UK/European job applications)
<!-- Remove this section entirely if you are not applying to EU/UK roles -->
- **Phone (EU):** [YOUR_EU_PHONE]
- **Location (EU):** [YOUR_EU_CITY], [YOUR_EU_COUNTRY]
- **When to use:** Any role that is EU/UK remote, based in Europe, or posted on a European job board
- **generate_pdf.py flags:** `--location "[YOUR_EU_CITY], [YOUR_EU_COUNTRY]" --phone "[YOUR_EU_PHONE]"`

## Key Facts
- **Profession:** [YOUR_JOB_TITLE] (e.g. Senior Backend Software Engineer)
- **Core Skills:** [YOUR_PRIMARY_SKILLS] (e.g. Java, Spring Boot, AWS, Microservices)
- **Domain Experience:** [YOUR_DOMAINS] (e.g. Fintech, Payments, SaaS, Healthcare)
- **Visa Status:** [YOUR_VISA_STATUS] (e.g. US Citizen / Green Card / OPT EAD / J-2 EAD / Need sponsorship)
- **Open to:** [EMPLOYMENT_TYPE] (e.g. Full-time, Contract, Remote, Hybrid, Onsite in [CITY])
- **Career Focus:** [YOUR_TARGET_ROLES] (e.g. Senior/Lead Backend roles in fintech and cloud-native systems)

## Work History
- [JOB_TITLE] @ [COMPANY] ([START_YEAR] – [END_YEAR or Present])
- [JOB_TITLE] @ [COMPANY] ([START_YEAR] – [END_YEAR])
<!-- Add more rows as needed -->

## Certifications
- [CERTIFICATION_1] (e.g. AWS Certified Solutions Architect)
- [CERTIFICATION_2]
<!-- Remove section if none -->

## Languages
- [LANGUAGE_1] ([PROFICIENCY]) (e.g. English (Fluent))
- [LANGUAGE_2] ([PROFICIENCY])

## Phrases — Do NOT Use
<!-- List phrases that are inaccurate or you want excluded from all generated content -->
- **"[PHRASE]"** — [REASON]

## Skills — Do NOT Claim
<!-- List technologies NOT in your background — the agent will never mention these -->
- **[SKILL]:** [REASON] (e.g. Apache Kafka: No hands-on experience)

When a job description requires a skill you don't have as a hard requirement, flag it to the user before applying.

## Important Decisions / Conclusions
- [STANDING_INSTRUCTION_1] (e.g. Always clearly mention visa status and work authorization)
- [STANDING_INSTRUCTION_2]

## Keyword Optimisation — Standing Instruction

Every resume and cover letter generated for a job application MUST be keyword-optimised.

**Cover letter:**
- Identify the top 4–6 keywords/phrases from the job description (especially those repeated 2+ times)
- Weave them naturally into the body — do not force or fabricate
- Mirror the exact phrasing used in the JD where possible (ATS systems match exact strings)

**Resume (--summary flag):**
- Write a 2-sentence professional summary that opens with the exact job title from the JD
- Include the top matching technical keywords naturally
- Never use a generic summary — it must be specific to the role

**Rule:** If the ATS match score (Step 3a) is below 70%, pause and identify which keywords to add to the cover letter before generating PDFs.

## Application Workflow
- **Cover letter:** Use the template at `data/cover-letter-template.md`, customize with keywords from each job description.
- **Apply mode:** Present each application draft for review before submitting.
- **Resume path:** `data/Resume-[YOUR_LAST_NAME].pdf`

## Job Search Patterns

**Best-fit role titles to target:**
- [TARGET_TITLE_1] (e.g. Senior Software Engineer)
- [TARGET_TITLE_2] (e.g. Lead Backend Engineer)
- [TARGET_TITLE_3]

**Stack signals to look for in JDs (apply if 2+ match):**
- [STACK_SIGNAL_1] (e.g. Java, Spring Boot)
- [STACK_SIGNAL_2] (e.g. AWS, Kubernetes)
- [STACK_SIGNAL_3]

**Domains — in priority order:**
1. [DOMAIN_1] (e.g. Fintech / Payments)
2. [DOMAIN_2] (e.g. SaaS / Cloud-native)
3. [DOMAIN_3]

**Hard filters — skip these automatically:**
- [HARD_FILTER_1] (e.g. Requires US citizenship or security clearance)
- [HARD_FILTER_2] (e.g. Junior / Mid-level only roles)
- [HARD_FILTER_3]

**Deduplication — check before applying:**
- Check Google Sheet tracker before every application
- Skip any company+role combination already present

## Ongoing Focus Areas
- [FOCUS_1] (e.g. Actively applying to backend/cloud/fintech roles)
- [FOCUS_2]

## Strong Preferences
- Prefer short, clear, direct responses.
- Want human-sounding, natural answers (not overly robotic).
- Avoid unnecessary verbosity.
- Emphasize impact, scale, and ownership.
