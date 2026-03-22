"""
Ashby ATS handler.

Fills standard Ashby application form fields and optional company-specific
essay questions loaded from .tmp/custom_answers_<Company>.json.

Supported form fields:
  - Full Name, Email, Phone, Location
  - Resume file upload
  - Work Authorization (boolean radio)
  - Visa Sponsorship (boolean radio)
  - Essay/textarea questions (matched by keyword)

Usage:
    Invoked by browser_apply.py when the URL matches ashbyhq.com.
    Optional company-specific answers: .tmp/custom_answers_<Company>.json
      Keys: ai_generated_code_issue, end_to_end_feature, system_improvement
            (any key matching a substring of the question label)
"""

import json
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
    print(f"[ashby] Screenshot: {path}")
    return path


def _fill(page, selector: str, value: str, label: str = "") -> bool:
    if not value:
        return False
    try:
        el = page.locator(selector)
        if el.count() > 0:
            el.first.scroll_into_view_if_needed()
            el.first.click(click_count=3)  # triple-click to select all
            el.first.fill(value)
            logger.debug(f"Filled '{label or selector}'")
            return True
    except Exception as e:
        logger.warning(f"Could not fill '{label}': {e}")
    return False


def _fill_by_label(page, label_texts: list, value: str, label: str = "") -> bool:
    if not value:
        return False
    for lbl in label_texts:
        try:
            el = page.get_by_label(lbl, exact=False)
            if el.count() > 0:
                el.first.scroll_into_view_if_needed()
                el.first.click(click_count=3)  # triple-click to select all
                el.first.fill(value)
                logger.debug(f"Filled '{label}' via label '{lbl}'")
                return True
        except Exception:
            pass
    return False


def _click_radio_or_checkbox(page, question_keyword: str, answer: str) -> bool:
    """
    Find a question by keyword substring and click the matching Yes/No radio or checkbox.
    answer: "Yes" or "No"

    Iterates containers from INNERMOST (most specific) to outermost to avoid accidentally
    clicking a button in the wrong question when multiple questions share common words.
    """
    try:
        containers = page.locator("div, section, fieldset, label").filter(has_text=question_keyword)
        count = containers.count()
        if count == 0:
            return False

        # Iterate in reverse so we try the smallest/deepest container first
        start = max(0, count - 8)
        for i in range(count - 1, start - 1, -1):
            container = containers.nth(i)
            # Try radio by role
            radio = container.get_by_role("radio", name=answer, exact=True)
            if radio.count() == 0:
                radio = container.get_by_role("radio", name=answer, exact=False)
            if radio.count() > 0:
                radio.first.click()
                logger.debug(f"Clicked radio '{answer}' for '{question_keyword[:40]}'")
                return True
            # Try button with exact text
            btn = container.get_by_role("button", name=answer, exact=True)
            if btn.count() == 0:
                btn = container.get_by_role("button", name=answer, exact=False)
            if btn.count() > 0:
                btn.first.click()
                logger.debug(f"Clicked button '{answer}' for '{question_keyword[:40]}'")
                return True
            # Fallback: any element with exact text matching the answer
            txt_el = container.locator(f"text={answer}").first
            try:
                if txt_el.is_visible():
                    txt_el.click()
                    logger.debug(f"Clicked text '{answer}' for '{question_keyword[:40]}'")
                    return True
            except Exception:
                pass
    except Exception as e:
        logger.warning(f"Radio click error for '{question_keyword[:40]}': {e}")
    return False


def _upload_file(page, file_path: str, label_hints: list = None) -> bool:
    """Upload a file by triggering the file input."""
    if not file_path or not Path(file_path).exists():
        logger.warning(f"File not found for upload: {file_path}")
        return False

    label_hints = label_hints or []

    # Try clicking an upload button/link first to reveal hidden file input
    for trigger_text in ("Upload", "Attach", "Choose file", "Select file", "Add resume", "Browse"):
        try:
            btn = page.get_by_role("button", name=trigger_text, exact=False)
            if btn.count() > 0 and btn.first.is_visible():
                btn.first.click()
                page.wait_for_timeout(800)
                break
        except Exception:
            pass

    # Set the file on any file input
    for sel in ('input[type="file"]', 'input[name="resume"]', 'input[accept*="pdf"]'):
        try:
            el = page.locator(sel)
            if el.count() > 0:
                el.first.set_input_files(file_path)
                page.wait_for_timeout(1500)
                print(f"[ashby] Uploaded file: {file_path}")
                return True
        except Exception as e:
            logger.warning(f"File upload via '{sel}' failed: {e}")
    return False


def _fill_textarea_by_keyword(page, keyword: str, value: str) -> bool:
    """
    Find an EMPTY textarea near a label/question containing keyword and fill it.

    Strategy: Prefer the innermost container with exactly one textarea (most
    specific match). Skip textareas that are already filled to avoid overwriting
    an answer placed by an earlier keyword pass.
    """
    if not value:
        return False
    try:
        containers = page.locator("div, label, p, section").filter(has_text=keyword)
        count = containers.count()
        if count == 0:
            return False

        # Pass 1: prefer containers with exactly 1 textarea (most specific)
        for i in range(min(count, 12)):
            c = containers.nth(i)
            tas = c.locator("textarea")
            if tas.count() != 1:
                continue
            ta = tas.first
            # Skip already-filled textareas
            try:
                current = ta.input_value() or ""
                if current.strip():
                    continue
            except Exception:
                pass
            try:
                ta.scroll_into_view_if_needed()
                ta.fill(value)
                logger.debug(f"Filled textarea (1-ta container) near '{keyword[:40]}'")
                return True
            except Exception as e:
                logger.warning(f"Fill error near '{keyword[:40]}': {e}")

        # Pass 2: containers with multiple textareas — pick first empty one
        for i in range(min(count, 12)):
            c = containers.nth(i)
            tas = c.locator("textarea")
            if tas.count() == 0:
                continue
            for j in range(tas.count()):
                ta = tas.nth(j)
                try:
                    current = ta.input_value() or ""
                    if current.strip():
                        continue
                except Exception:
                    pass
                try:
                    ta.scroll_into_view_if_needed()
                    ta.fill(value)
                    logger.debug(f"Filled textarea (multi-ta container) near '{keyword[:40]}'")
                    return True
                except Exception:
                    pass

        # Fallback: get_by_label
        try:
            el = page.get_by_label(keyword, exact=False)
            if el.count() > 0:
                try:
                    current = el.first.input_value() or ""
                    if not current.strip():
                        el.first.scroll_into_view_if_needed()
                        el.first.fill(value)
                        return True
                except Exception:
                    pass
        except Exception:
            pass

    except Exception as e:
        logger.warning(f"Textarea fill error for '{keyword[:40]}': {e}")
    return False


def _js_click_answer(page, question_phrase: str, answer: str) -> bool:
    """
    Use JavaScript to find the smallest DOM container containing question_phrase,
    then click the button/radio inside it whose text matches answer exactly.
    Works for Ashby's custom styled Yes/No toggle buttons that have no ARIA roles.
    """
    try:
        result = page.evaluate(
            """([phrase, answer]) => {
                const els = [...document.querySelectorAll('div, section, fieldset, label, p')];
                let smallest = null, minLen = Infinity;
                for (const el of els) {
                    const t = el.textContent;
                    if (t.includes(phrase) && t.length < minLen) {
                        smallest = el;
                        minLen = t.length;
                    }
                }
                if (!smallest) return false;
                const candidates = smallest.querySelectorAll(
                    'button, [role="radio"], [role="button"], input[type="radio"], label, span, div'
                );
                for (const el of candidates) {
                    if (el.textContent.trim() === answer) {
                        el.click();
                        return true;
                    }
                }
                return false;
            }""",
            [question_phrase, answer],
        )
        if result:
            logger.debug(f"JS clicked '{answer}' for '{question_phrase[:40]}'")
        return bool(result)
    except Exception as e:
        logger.warning(f"JS click error for '{question_phrase[:40]}': {e}")
        return False


def _load_custom_answers(company: str) -> dict:
    """Load company-specific essay answers from .tmp/custom_answers_<Company>.json.
    Tries exact match, capitalized, and case-insensitive fallback."""
    tmp_dir = _ROOT / ".tmp"
    candidates = [
        tmp_dir / f"custom_answers_{company}.json",
        tmp_dir / f"custom_answers_{company.capitalize()}.json",
        tmp_dir / f"custom_answers_{company.title()}.json",
    ]
    # Also scan for case-insensitive match
    try:
        for f in tmp_dir.glob("custom_answers_*.json"):
            if f.stem.lower() == f"custom_answers_{company.lower()}":
                candidates.insert(0, f)
    except Exception:
        pass

    for path in candidates:
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                print(f"[ashby] Loaded custom answers from {path.name}")
                return data
            except Exception as e:
                logger.warning(f"Could not load custom answers from {path}: {e}")
    return {}


# ---------------------------------------------------------------------------
# Main handler
# ---------------------------------------------------------------------------

def apply(page, applicant: dict, cover_letter: str, mode: str, screenshot_dir: str) -> list[str]:
    """
    Ashby ATS application handler.

    Args:
        page: Playwright page, already navigated to the Ashby job URL
        applicant: applicant data dict
        cover_letter: cover letter plain text (used as fallback for essay fields)
        mode: "preview" or "submit"
        screenshot_dir: directory for screenshots

    Returns:
        list of screenshot paths
    """
    screenshots = []
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    company = applicant.get("current_company_apply", applicant.get("first_name", "unknown"))

    # Derive company name from URL: https://jobs.ashbyhq.com/<company>/<job-id>
    # URL parts: ["https:", "", "jobs.ashbyhq.com", "<company>", "<job-id>"]
    url_parts = page.url.split("/")
    company_from_url = url_parts[3] if len(url_parts) > 3 else "company"

    custom_answers = _load_custom_answers(
        applicant.get("apply_company", company_from_url)
    )

    def shot(name: str) -> str:
        path = f"{screenshot_dir}/ashby_{ts}_{name}.png"
        screenshots.append(_ss(page, path))
        return path

    print("[ashby] Waiting for page to load...")
    try:
        page.wait_for_load_state("networkidle", timeout=30000)
    except Exception:
        pass
    page.wait_for_timeout(2000)

    # Wait for Ashby's "Parsing your resume / Autofilling..." banner to disappear
    # If we fill fields while it's running, the auto-fill will overwrite our values
    try:
        banner = page.locator("text=Autofilling")
        if banner.count() > 0:
            print("[ashby] Waiting for auto-fill to complete...")
            banner.wait_for(state="hidden", timeout=15000)
            page.wait_for_timeout(1000)
    except Exception:
        pass

    shot("01_job_page")

    # -----------------------------------------------------------------------
    # Click Apply button if present (some Ashby pages show job description first)
    # -----------------------------------------------------------------------
    for apply_sel in (
        'a:has-text("Apply")',
        'button:has-text("Apply")',
        '[data-testid="apply-button"]',
        'a:has-text("Apply for this job")',
        'button:has-text("Apply for this job")',
    ):
        try:
            btn = page.locator(apply_sel)
            if btn.count() > 0 and btn.first.is_visible():
                btn.first.click()
                page.wait_for_timeout(2000)
                try:
                    page.wait_for_load_state("networkidle", timeout=10000)
                except Exception:
                    pass
                print("[ashby] Clicked Apply button.")
                break
        except Exception:
            pass

    shot("02_after_apply_click")

    # -----------------------------------------------------------------------
    # Fill standard contact fields
    # -----------------------------------------------------------------------
    print("[ashby] Filling contact fields...")

    full_name = f"{applicant.get('first_name', '')} {applicant.get('last_name', '')}".strip()

    # Full Name — try label, then common selectors, then first visible text input
    name_filled = _fill_by_label(
        page,
        ["Full name", "Name", "Full Name", "Your name", "Applicant Name"],
        full_name, "full_name",
    )
    if not name_filled:
        for sel in (
            'input[name="name"]', 'input[id*="name"]',
            'input[placeholder*="name" i]', 'input[placeholder*="Name"]',
            'input[autocomplete="name"]',
        ):
            if _fill(page, sel, full_name, "full_name_sel"):
                name_filled = True
                break
    if not name_filled:
        # Last resort: first visible text input in the Candidate Information section
        try:
            section = page.locator("text=Candidate Information").locator("..")
            inp = section.locator('input[type="text"]')
            if inp.count() > 0:
                inp.first.click(click_count=3)
                inp.first.fill(full_name)
                name_filled = True
        except Exception:
            pass

    # Email
    email_filled = _fill_by_label(
        page,
        ["Email", "Email address", "Your email", "Email Address"],
        applicant.get("email", ""), "email",
    )
    if not email_filled:
        for sel in (
            'input[type="email"]', 'input[name="email"]',
            'input[id*="email"]', 'input[placeholder*="email" i]',
            'input[autocomplete="email"]',
        ):
            if _fill(page, sel, applicant.get("email", ""), "email_sel"):
                break

    # Phone
    phone_filled = _fill_by_label(
        page,
        ["Phone", "Phone number", "Mobile", "Phone Number"],
        applicant.get("phone", ""), "phone",
    )
    if not phone_filled:
        for sel in (
            'input[type="tel"]', 'input[name="phone"]',
            'input[id*="phone"]', 'input[placeholder*="phone" i]',
            'input[autocomplete="tel"]',
        ):
            if _fill(page, sel, applicant.get("phone", ""), "phone_sel"):
                break

    # Location — Ashby often uses a dropdown/combobox for city
    loc_filled = _fill_by_label(
        page,
        ["Location", "City", "Your location", "Where are you located", "Location*"],
        applicant.get("city", "Columbia, MO"), "location",
    )
    if not loc_filled:
        for sel in (
            'input[name="location"]', 'input[id*="location"]',
            'input[placeholder*="location" i]', 'input[placeholder*="city" i]',
        ):
            if _fill(page, sel, applicant.get("city", "Columbia, MO"), "location_sel"):
                break

    shot("03_contact_filled")

    # -----------------------------------------------------------------------
    # Upload resume
    # -----------------------------------------------------------------------
    resume_path = applicant.get("resume_path", "")
    if resume_path and Path(resume_path).exists():
        print(f"[ashby] Uploading resume: {resume_path}")
        _upload_file(page, resume_path)
        shot("04_resume_uploaded")
    else:
        # Try tailored resume from .tmp/ if available
        print("[ashby] Resume not found at default path.")

    # Wait for any post-upload auto-fill to settle
    try:
        banner = page.locator("text=Autofilling")
        if banner.count() > 0:
            print("[ashby] Waiting for post-upload auto-fill to complete...")
            banner.wait_for(state="hidden", timeout=15000)
            page.wait_for_timeout(1000)
    except Exception:
        page.wait_for_timeout(2000)

    # Re-fill contact fields if auto-fill overwrote them with wrong values
    name_el = page.get_by_label("Full Name", exact=False)
    if name_el.count() > 0:
        try:
            current = name_el.first.input_value() or ""
            if current.strip() != full_name:
                name_el.first.triple_click()
                name_el.first.fill(full_name)
        except Exception:
            pass

    # -----------------------------------------------------------------------
    # Cover letter field (if present)
    # -----------------------------------------------------------------------
    _fill_textarea_by_keyword(page, "cover letter", cover_letter)

    # -----------------------------------------------------------------------
    # Work authorization and sponsorship
    #
    # Dave has two questions:
    #   Q1: "Are you permanently authorized to work in the US without visa sponsorship?" → Yes
    #   Q2: "Will you require sponsorship... at any point in the future?" → No
    #
    # IMPORTANT: "sponsorship" alone matches both questions (ambiguous).
    # Use specific phrases: "permanently authorized" for Q1, "require sponsorship" for Q2.
    # Click Q1 LAST so that if a broad keyword accidentally sets Q1→No, we re-set it to Yes.
    # -----------------------------------------------------------------------
    print("[ashby] Filling work authorization...")

    # Strategy: The Dave Ashby form has two consecutive Yes/No questions:
    #   Q1: "permanently authorized to work without visa sponsorship?" → Yes
    #   Q2: "require sponsorship at any point in the future?" → No
    #
    # Standard Playwright role-based clicking often fails because these are styled divs,
    # not native <button> or <input type="radio"> elements.
    # Use index-based JS: find all leaf "Yes"/"No" elements and click by position.

    # Click the 1st "Yes" (Q1's Yes) and 2nd "No" (Q2's No) using leaf-node index.
    # Wrap in IIFE to avoid strict-mode function-declaration restrictions in eval().
    try:
        page.evaluate("""
            (() => {
                const clickLeaf = (text, idx) => {
                    const els = Array.from(document.querySelectorAll('*')).filter(
                        el => el.children.length === 0
                           && el.textContent.trim() === text
                           && el.offsetParent !== null
                    );
                    if (els[idx]) els[idx].click();
                };
                clickLeaf('Yes', 0);
                clickLeaf('No', 1);
            })()
        """)
        page.wait_for_timeout(300)
        print("[ashby] Clicked work auth buttons via leaf-node index.")
    except Exception as e:
        logger.warning(f"Leaf-node work auth click failed: {e}")

    # Verification fallback: if Q1 Yes or Q2 No still not selected, try JS smallest-container
    q2_answered = _js_click_answer(page, "require sponsorship", "No")
    if not q2_answered:
        _click_radio_or_checkbox(page, "require sponsorship", "No")

    # Q1 last — ensure Yes is set regardless of what happened above
    q1_answered = _js_click_answer(page, "permanently authorized", "Yes")
    if not q1_answered:
        _click_radio_or_checkbox(page, "permanently authorized", "Yes")

    page.wait_for_timeout(200)

    shot("05_auth_filled")

    # -----------------------------------------------------------------------
    # Essay / custom questions
    # Attempt to fill each known essay question type using keywords
    # -----------------------------------------------------------------------
    print("[ashby] Filling essay questions...")

    essay_map = {
        "ai-generated": custom_answers.get("ai_generated_code_issue", ""),
        "copilot":       custom_answers.get("ai_generated_code_issue", ""),
        "chatgpt":       custom_answers.get("ai_generated_code_issue", ""),
        "ai generated":  custom_answers.get("ai_generated_code_issue", ""),
        "end-to-end":    custom_answers.get("end_to_end_feature", ""),
        "end to end":    custom_answers.get("end_to_end_feature", ""),
        "built end":     custom_answers.get("end_to_end_feature", ""),
        "feature you":   custom_answers.get("end_to_end_feature", ""),
        "improved":      custom_answers.get("system_improvement", ""),
        "improvement":   custom_answers.get("system_improvement", ""),
        "existing system": custom_answers.get("system_improvement", ""),
        "not just built": custom_answers.get("system_improvement", ""),
    }

    for keyword, answer in essay_map.items():
        if answer:
            filled = _fill_textarea_by_keyword(page, keyword, answer)
            if filled:
                logger.debug(f"Filled essay question matching '{keyword}'")

    shot("06_essays_filled")

    # -----------------------------------------------------------------------
    # Tick any unchecked consent/privacy checkboxes
    # -----------------------------------------------------------------------
    try:
        unchecked = page.locator("input[type='checkbox']:not(:checked)")
        for i in range(unchecked.count()):
            try:
                unchecked.nth(i).scroll_into_view_if_needed()
                unchecked.nth(i).click()
                page.wait_for_timeout(100)
            except Exception:
                pass
    except Exception:
        pass

    shot("07_pre_submit")

    # -----------------------------------------------------------------------
    # Submit (only in submit mode)
    # -----------------------------------------------------------------------
    if mode == "submit":
        print("[ashby] Submitting application...")
        submitted = False
        for sel in (
            'button:has-text("Submit application")',
            'button:has-text("Submit")',
            'button:has-text("Apply")',
            '[type="submit"]',
        ):
            try:
                btn = page.locator(sel)
                if btn.count() > 0 and btn.first.is_visible():
                    btn.first.click()
                    try:
                        page.wait_for_load_state("networkidle", timeout=15000)
                    except Exception:
                        pass
                    page.wait_for_timeout(2000)
                    shot("08_submitted")
                    print("[ashby] Application submitted.")
                    submitted = True
                    break
            except Exception as e:
                logger.warning(f"Submit button error: {e}")

        if not submitted:
            shot("08_submit_failed")
            print("[ashby] Submit button not found — check screenshot.")
    else:
        print("[ashby] Preview mode — not submitting.")

    shot("final_state")
    return screenshots
