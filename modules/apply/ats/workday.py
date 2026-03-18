"""
Workday ATS handler.

Supports two authentication paths:
  1. Account login — uses WORKDAY_EMAIL + WORKDAY_PASSWORD from .env
  2. Guest apply   — clicks "Apply Manually" / "Continue as Guest" if available

Multi-step wizard flow:
  Step 1 — My Information  (name, phone, address, resume)
  Step 2 — My Experience   (work history entries skipped; resume already uploaded)
  Step 3 — Application Questions (work auth, sponsorship, custom questions)
  Step 4 — Self Identify   (EEO — skipped / decline-all)
  Step 5 — Review          (scroll + submit)

All selectors use Workday's data-automation-id attributes, which are consistent
across tenants.
"""

import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path

_ROOT = Path(__file__).parent.parent.parent.parent  # modules/apply/ats → project root
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Workday data-automation-id selectors
# ---------------------------------------------------------------------------

# Job page
_APPLY_BTN        = '[data-automation-id="apply-button"]'

# Auth gate
_SIGN_IN_EMAIL    = 'input[data-automation-id="email"]'
_SIGN_IN_PASSWORD = 'input[data-automation-id="password"]'
_SIGN_IN_SUBMIT   = '[data-automation-id="signInSubmitButton"]'
_CREATE_ACCT_LINK = '[data-automation-id="createAccountLink"]'

# Guest / manual apply options (varies by Workday version)
_GUEST_SELECTORS  = [
    '[data-automation-id="guest-apply"]',
    '[data-automation-id="applyManually"]',
    'button:has-text("Apply Manually")',
    'button:has-text("Continue as Guest")',
    'button:has-text("Continue without signing in")',
    'a:has-text("Apply Manually")',
    'a:has-text("Continue as Guest")',
    'a:has-text("Continue without")',
    '[data-automation-id="authn-options"] a',
    'text=Apply Manually',
    'text=Continue as Guest',
]

# Step navigation
_NEXT_BTN         = '[data-automation-id="bottom-navigation-next-button"]'
_SAVE_NEXT_BTN    = '[data-automation-id="bottom-navigation-next-button"]'
_SUBMIT_BTN       = '[data-automation-id="bottom-navigation-submit-button"]'

# Step 1 — My Information
_FIRST_NAME       = 'input[data-automation-id="legalNameSection_firstName"]'
_LAST_NAME        = 'input[data-automation-id="legalNameSection_lastName"]'
_PREFERRED_NAME   = 'input[data-automation-id="preferredNameSection_firstName"]'
_PHONE_NUMBER     = 'input[data-automation-id="phone-number"]'
_PHONE_DEVICE     = '[data-automation-id="phoneDeviceType"]'
_ADDRESS_LINE1    = 'input[data-automation-id="addressSection_addressLine1"]'
_CITY             = 'input[data-automation-id="addressSection_city"]'
_STATE_REGION     = '[data-automation-id="addressSection_regionAbbreviation"]'
_POSTAL_CODE      = 'input[data-automation-id="addressSection_postalCode"]'
_HOW_DID_YOU_HEAR = '[data-automation-id="howDidYouHearAboutUs"]'

# Step 2 — My Experience (resume)
_RESUME_SECTION   = '[data-automation-id="resumeSection"]'
_UPLOAD_RESUME    = '[data-automation-id="file-upload-input-ref"]'
_DROP_RESUME_BTN  = '[data-automation-id="dropResumeLink"]'

# Step 3 — Application Questions (work auth / sponsorship dropdowns)
# These are Workday radio or dropdown answers — identified by text
_YES_RADIO        = '[data-automation-id="Yes"]'
_NO_RADIO         = '[data-automation-id="No"]'


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ss(page, path: str) -> str:
    """Take full-page screenshot and return path."""
    page.screenshot(path=path, full_page=True)
    logger.info(f"Screenshot: {path}")
    print(f"[workday] Screenshot: {path}")
    return path


def _fill(page, selector: str, value: str, label: str = "") -> bool:
    """Clear + fill a text input by CSS selector."""
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
        logger.warning(f"Could not fill '{label or selector}': {e}")
    return False


def _fill_by_label(page, label_texts: list, value: str, label: str = "") -> bool:
    """Fill an input by its associated label text."""
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


def _click_text(page, texts: list, label: str = "") -> bool:
    """Click a button or link by its visible text."""
    for text in texts:
        for role in ("button", "link", "option"):
            try:
                el = page.get_by_role(role, name=text, exact=False)
                if el.count() > 0:
                    el.first.scroll_into_view_if_needed()
                    el.first.click()
                    logger.debug(f"Clicked '{label}' via role={role} text='{text}'")
                    return True
            except Exception:
                pass
        # Generic text locator
        try:
            el = page.locator(f"text={text}")
            if el.count() > 0:
                el.first.scroll_into_view_if_needed()
                el.first.click()
                logger.debug(f"Clicked '{label}' via text='{text}'")
                return True
        except Exception:
            pass
    logger.warning(f"Could not click '{label}'")
    return False


def _select_dropdown(page, selector: str, value: str, label: str = "") -> bool:
    """
    Open a Workday custom dropdown (data-automation-id based) and pick an option.
    Workday dropdowns are typically <button> triggers that open a listbox.
    """
    if not value:
        return False
    try:
        el = page.locator(selector)
        if el.count() == 0:
            return False
        el.first.scroll_into_view_if_needed()
        el.first.click()
        page.wait_for_timeout(700)

        # Try ARIA listbox options
        opt = page.get_by_role("option", name=value, exact=False)
        if opt.count() > 0:
            opt.first.click()
            logger.debug(f"Dropdown '{label}' = '{value}'")
            return True

        # Fallback: listitem
        opt = page.locator("li").filter(has_text=value)
        if opt.count() > 0:
            opt.first.click()
            logger.debug(f"Dropdown '{label}' = '{value}' (listitem)")
            return True

        page.keyboard.press("Escape")
        logger.warning(f"Dropdown '{label}': option '{value}' not found")
    except Exception as e:
        logger.warning(f"Dropdown '{label}' error: {e}")
    return False


def _answer_yes_no_question(page, question_texts: list, answer: str) -> bool:
    """
    Answer a Yes/No radio question in Workday application questions.
    Finds the question container by label text, then clicks Yes or No radio/button.
    """
    for q_text in question_texts:
        try:
            # Find a container that holds the question text
            container = page.locator("div, section, fieldset").filter(has_text=q_text).last
            if container.count() == 0:
                continue

            # Try radio inputs within the container
            radio = container.locator(f'[data-automation-id="{answer}"]')
            if radio.count() > 0:
                radio.first.click()
                logger.debug(f"Answered '{q_text[:40]}' → {answer}")
                return True

            # Try by label text within container
            radio = container.get_by_label(answer, exact=False)
            if radio.count() > 0:
                radio.first.click()
                logger.debug(f"Answered '{q_text[:40]}' → {answer} (by label)")
                return True

            # Try button/radio with text Yes/No
            btn = container.get_by_role("radio", name=answer, exact=False)
            if btn.count() > 0:
                btn.first.click()
                logger.debug(f"Answered '{q_text[:40]}' → {answer} (radio role)")
                return True

        except Exception as e:
            logger.warning(f"Yes/No answer error for '{q_text[:40]}': {e}")
    return False


def _wait_for_step(page, timeout: int = 15000):
    """Wait for Workday step content to settle."""
    try:
        page.wait_for_load_state("networkidle", timeout=timeout)
    except Exception:
        pass
    page.wait_for_timeout(1000)


def _click_next(page) -> bool:
    """Click the Next / Save & Continue button and wait for the next step to load."""
    for sel in (_NEXT_BTN, _SAVE_NEXT_BTN):
        try:
            btn = page.locator(sel)
            if btn.count() > 0 and btn.first.is_visible():
                btn.first.scroll_into_view_if_needed()
                btn.first.click()
                _wait_for_step(page)
                logger.debug("Clicked Next")
                return True
        except Exception:
            pass

    # Fallback: button with text "Next" or "Save and Continue"
    for text in ("Next", "Save and Continue", "Continue"):
        try:
            btn = page.get_by_role("button", name=text, exact=False)
            if btn.count() > 0 and btn.first.is_visible():
                btn.first.click()
                _wait_for_step(page)
                logger.debug(f"Clicked '{text}'")
                return True
        except Exception:
            pass

    logger.warning("Next button not found")
    return False


def _on_form(page) -> bool:
    """Return True if we're inside the Workday application wizard (past auth gate).

    Deliberately excludes the progress bar because it is also visible on the
    'Create Account / Sign In' auth step — which is NOT the application form.
    """
    indicators = [
        '[data-automation-id="bottom-navigation-next-button"]',
        '[data-automation-id="bottom-navigation-submit-button"]',
        '[data-automation-id="legalNameSection_firstName"]',
        '[data-automation-id="resumeSection"]',
    ]
    for sel in indicators:
        try:
            if page.locator(sel).count() > 0:
                return True
        except Exception:
            pass
    return False


# ---------------------------------------------------------------------------
# Auth gate helpers
# ---------------------------------------------------------------------------

def _attempt_login(page, email: str, password: str) -> bool:
    """Try to sign in with stored Workday credentials."""
    if not email or not password:
        return False
    try:
        if page.locator(_SIGN_IN_EMAIL).count() > 0:
            page.locator(_SIGN_IN_EMAIL).first.fill(email)
            page.wait_for_timeout(300)
        if page.locator(_SIGN_IN_PASSWORD).count() > 0:
            page.locator(_SIGN_IN_PASSWORD).first.fill(password)
            page.wait_for_timeout(300)
        if page.locator(_SIGN_IN_SUBMIT).count() > 0:
            page.locator(_SIGN_IN_SUBMIT).first.click()
            _wait_for_step(page)
            logger.info("Signed in to Workday account")
            return True
    except Exception as e:
        logger.warning(f"Login attempt failed: {e}")
    return False


def _attempt_guest_apply(page) -> bool:
    """Try clicking a 'guest apply' / 'apply manually' option."""
    for sel in _GUEST_SELECTORS:
        try:
            el = page.locator(sel)
            if el.count() > 0 and el.first.is_visible():
                el.first.click()
                _wait_for_step(page)
                logger.info(f"Clicked guest apply: {sel}")
                return True
        except Exception:
            pass
    return False


def _navigate_past_auth(page, applicant: dict, screenshot_dir: str, ts: str) -> bool:
    """
    Detect and pass the Workday auth gate.
    Returns True if we successfully entered the application form.
    """
    # Check if we're on a login / auth-gate page
    on_login = (
        page.locator('input[data-automation-id="email"]').count() > 0
        or page.locator('input[type="email"]').count() > 0
        or page.locator('[data-automation-id="authn-modal"]').count() > 0
        or page.locator(_SIGN_IN_SUBMIT).count() > 0
        or "login" in page.url.lower()
        or "signin" in page.url.lower()
    )

    if not on_login:
        # Already on the form — no auth gate
        return True

    _ss(page, f"{screenshot_dir}/workday_{ts}_auth_gate.png")
    print("[workday] Auth gate detected.")

    # 1. Try guest apply first (no credentials needed)
    if _attempt_guest_apply(page):
        print("[workday] Continuing as guest.")
        _ss(page, f"{screenshot_dir}/workday_{ts}_after_guest.png")
        return True

    # 2. Try account login with stored credentials
    wd_email = os.getenv("WORKDAY_EMAIL", "")
    wd_pass  = os.getenv("WORKDAY_PASSWORD", "")
    if wd_email and wd_pass:
        print(f"[workday] Signing in as {wd_email}...")
        if _attempt_login(page, wd_email, wd_pass):
            _ss(page, f"{screenshot_dir}/workday_{ts}_after_login.png")
            return True

    # 3. Neither worked — blocked
    print("[workday] Could not bypass auth gate.")
    print("[workday] Add WORKDAY_EMAIL + WORKDAY_PASSWORD to .env, or apply manually.")
    return False


# ---------------------------------------------------------------------------
# Step fillers
# ---------------------------------------------------------------------------

def _fill_step1_my_information(page, applicant: dict):
    """Fill Step 1: My Information."""
    print("[workday] Filling Step 1: My Information...")

    _fill(page, _FIRST_NAME, applicant.get("first_name", ""), "first_name")
    _fill(page, _LAST_NAME,  applicant.get("last_name",  ""), "last_name")
    _fill(page, _PREFERRED_NAME, applicant.get("first_name", ""), "preferred_name")

    # Phone
    _fill(page, _PHONE_NUMBER, applicant.get("phone", ""), "phone")
    # Phone type — try to set "Mobile"
    _select_dropdown(page, _PHONE_DEVICE, "Mobile", "phone_device_type")

    # Address
    _fill(page, _ADDRESS_LINE1, "Columbia, MO", "address_line1")
    _fill(page, _CITY, "Columbia", "city")
    _fill(page, _POSTAL_CODE, "65201", "postal_code")
    # State — Workday uses a searchable dropdown for state
    _select_dropdown(page, _STATE_REGION, "Missouri", "state")

    # "How did you hear about us" — common Workday field
    _select_dropdown(page, _HOW_DID_YOU_HEAR, "LinkedIn", "how_did_you_hear")

    # Email (sometimes editable on guest apply)
    _fill_by_label(
        page,
        ["Email", "Email Address", "Work Email"],
        applicant.get("email", ""),
        "email",
    )


def _fill_step2_my_experience(page, applicant: dict):
    """
    Fill Step 2: My Experience.
    Primary action: upload resume. Work history entries are skipped
    since the resume covers them.
    """
    print("[workday] Filling Step 2: My Experience (resume upload)...")

    resume_path = applicant.get("resume_path", "")
    if not resume_path or not Path(resume_path).exists():
        logger.warning(f"Resume not found: {resume_path}")
        return

    # Workday resume upload — click "Upload" then set file input
    # Try clicking the drop/upload link first to reveal the file input
    for upload_trigger in (
        '[data-automation-id="dropResumeLink"]',
        '[data-automation-id="uploadResumeButton"]',
        'button:has-text("Upload")',
        'a:has-text("Upload")',
        'button:has-text("Select files")',
    ):
        try:
            el = page.locator(upload_trigger)
            if el.count() > 0 and el.first.is_visible():
                el.first.click()
                page.wait_for_timeout(1000)
                break
        except Exception:
            pass

    # Now set the file on the (possibly hidden) file input
    uploaded = False
    for file_sel in (
        'input[type="file"]',
        '[data-automation-id="file-upload-input-ref"]',
        'input[name="resume"]',
    ):
        try:
            el = page.locator(file_sel)
            if el.count() > 0:
                el.first.set_input_files(resume_path)
                page.wait_for_timeout(2000)
                print(f"[workday] Resume uploaded: {resume_path}")
                uploaded = True
                break
        except Exception as e:
            logger.warning(f"Resume upload via '{file_sel}' failed: {e}")

    if not uploaded:
        logger.warning("Could not upload resume — no file input found")


def _fill_step3_application_questions(page, applicant: dict):
    """
    Fill Step 3: Application Questions.
    Answers work authorization, sponsorship, and common Yes/No questions.
    """
    print("[workday] Filling Step 3: Application Questions...")

    # Work authorization — Yes
    _answer_yes_no_question(
        page,
        [
            "authorized to work",
            "legally authorized",
            "work authorization",
            "eligible to work",
        ],
        "Yes",
    )

    # Sponsorship — No
    _answer_yes_no_question(
        page,
        [
            "require sponsorship",
            "visa sponsorship",
            "sponsorship",
            "require an employer",
        ],
        "No",
    )

    # "Have you previously worked here?" — No
    _answer_yes_no_question(
        page,
        [
            "previously worked",
            "previously employed",
            "former employee",
            "worked for this company",
        ],
        "No",
    )

    # LinkedIn URL — plain text field (some Workday forms ask for it)
    _fill_by_label(
        page,
        ["LinkedIn", "LinkedIn URL", "LinkedIn Profile"],
        applicant.get("linkedin", ""),
        "linkedin",
    )

    # Website / Portfolio
    _fill_by_label(
        page,
        ["Website", "Portfolio", "Personal Website"],
        applicant.get("website", ""),
        "website",
    )

    # "How did you hear" text fallback
    _fill_by_label(
        page,
        ["How did you hear", "How did you find out", "Source"],
        "LinkedIn",
        "how_did_you_hear_text",
    )

    # Consent / privacy checkboxes — tick all unchecked
    _sweep_checkboxes(page)


def _fill_step4_self_identify(page):
    """
    Fill Step 4: Self Identify (EEO).
    Selects 'decline to self-identify' for all voluntary fields where possible.
    """
    print("[workday] Filling Step 4: Self Identify (EEO)...")

    # Gender
    for sel_text in ("Male", "Man", "Decline"):
        try:
            btn = page.get_by_role("radio", name=sel_text, exact=False)
            if btn.count() > 0:
                btn.first.click()
                break
        except Exception:
            pass

    # Race/Ethnicity
    _answer_yes_no_question(
        page,
        ["Hispanic or Latino", "Hispanic or Latino origin"],
        "No",
    )

    # Veteran
    for sel_text in ("not a protected veteran", "I am not", "Not a veteran", "Decline"):
        try:
            btn = page.get_by_role("radio", name=sel_text, exact=False)
            if btn.count() > 0:
                btn.first.click()
                break
        except Exception:
            pass

    # Disability
    for sel_text in ("I do not want to answer", "I don't wish to answer", "Decline", "No disability"):
        try:
            btn = page.get_by_role("radio", name=sel_text, exact=False)
            if btn.count() > 0:
                btn.first.click()
                break
        except Exception:
            pass


def _sweep_checkboxes(page):
    """Tick all unchecked native and ARIA checkboxes (consent, privacy, etc.)."""
    try:
        unchecked = page.locator("input[type='checkbox']:not(:checked)")
        for i in range(unchecked.count()):
            try:
                unchecked.nth(i).scroll_into_view_if_needed()
                unchecked.nth(i).click()
                page.wait_for_timeout(120)
            except Exception:
                pass
    except Exception:
        pass

    try:
        aria_unchecked = page.locator("[role='checkbox'][aria-checked='false']")
        for i in range(aria_unchecked.count()):
            try:
                aria_unchecked.nth(i).scroll_into_view_if_needed()
                aria_unchecked.nth(i).click()
                page.wait_for_timeout(120)
            except Exception:
                pass
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Step detection
# ---------------------------------------------------------------------------

def _current_step_name(page) -> str:
    """Guess the current wizard step using a cascading strategy."""
    # 1. Workday step wizard breadcrumbs (most reliable when present)
    for sel in [
        '[data-automation-id="progressBar"] [aria-current="step"]',
        '[aria-current="step"]',
        '[data-automation-id="currentStep"]',
    ]:
        try:
            el = page.locator(sel)
            if el.count() > 0:
                text = el.first.inner_text().strip().lower()
                if text:
                    return text
        except Exception:
            pass

    # 2. Heading scoped to form/dialog container (not background page heading)
    for sel in [
        '[role="dialog"] h2',
        'form h2',
        '[data-automation-id="formContainer"] h2',
        'main form h2',
    ]:
        try:
            el = page.locator(sel)
            if el.count() > 0:
                text = el.first.inner_text().strip().lower()
                if text:
                    return text
        except Exception:
            pass

    # 3. Detect step by presence of distinctive form fields
    if page.locator('[data-automation-id="legalNameSection_firstName"]').count() > 0:
        return "my information"
    if page.locator('[data-automation-id="resumeSection"]').count() > 0:
        return "my experience"
    if page.locator('[data-automation-id="bottom-navigation-submit-button"]').count() > 0:
        return "review"
    # Create Account / Sign In step (some Workday tenants require account creation)
    if page.locator('input[type="password"]').count() > 0:
        return "create account"

    return page.url.lower()


# ---------------------------------------------------------------------------
# Main handler
# ---------------------------------------------------------------------------

def apply(page, applicant: dict, cover_letter: str, mode: str, screenshot_dir: str) -> list[str]:
    """
    Workday application handler.

    Args:
        page: Playwright page, already navigated to the Workday job URL
        applicant: dict with applicant data (from browser_apply.load_applicant())
        cover_letter: plain-text cover letter (not used directly; resume PDF is uploaded)
        mode: "preview" or "submit"
        screenshot_dir: directory to save screenshots

    Returns:
        list of screenshot file paths
    """
    screenshots = []
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    def shot(name: str) -> str:
        path = f"{screenshot_dir}/workday_{ts}_{name}.png"
        screenshots.append(_ss(page, path))
        return path

    print("[workday] Waiting for job page to load...")
    try:
        page.wait_for_load_state("networkidle", timeout=30000)
    except Exception:
        pass
    page.wait_for_timeout(2000)

    shot("01_job_page")

    # -----------------------------------------------------------------------
    # 1. Click the Apply button on the job page
    # -----------------------------------------------------------------------
    apply_clicked = False
    for sel in (_APPLY_BTN, 'button:has-text("Apply")', 'a:has-text("Apply")'):
        try:
            btn = page.locator(sel)
            if btn.count() > 0 and btn.first.is_visible():
                btn.first.click()
                page.wait_for_timeout(2000)
                try:
                    page.wait_for_load_state("networkidle", timeout=10000)
                except Exception:
                    pass
                print("[workday] Clicked Apply button.")
                apply_clicked = True
                break
        except Exception:
            pass

    if not apply_clicked:
        print("[workday] Apply button not found — may already be on the form.")

    # Wait 3 s for any modal to fully render before checking auth state
    page.wait_for_timeout(3000)
    shot("02_after_apply_click")

    # -----------------------------------------------------------------------
    # 2. Pass auth gate (guest apply or account login)
    # -----------------------------------------------------------------------
    if _on_form(page):
        print("[workday] Already on application form.")
    else:
        print("[workday] Auth gate present — trying guest apply...")
        auth_gate_path = f"{screenshot_dir}/workday_{ts}_auth_gate.png"
        screenshots.append(_ss(page, auth_gate_path))

        # Always attempt guest apply first; some Workday sites call the "Apply
        # Manually" option a guest apply but then land on a Create Account page.
        _attempt_guest_apply(page)
        _wait_for_step(page)

        if not _on_form(page):
            # Guest apply either wasn't found or it led to a Create Account / Sign In
            # page — try stored credentials next.
            wd_email = os.getenv("WORKDAY_EMAIL", "")
            wd_pass  = os.getenv("WORKDAY_PASSWORD", "")
            if wd_email and wd_pass:
                print(f"[workday] Guest apply did not reach form — signing in as {wd_email}...")
                # Some Workday tenants show a Sign In link on the Create Account page
                try:
                    sign_in_link = page.locator('a:has-text("Sign In"), button:has-text("Sign In")')
                    if sign_in_link.count() > 0:
                        sign_in_link.first.click()
                        _wait_for_step(page)
                except Exception:
                    pass
                _attempt_login(page, wd_email, wd_pass)
                _wait_for_step(page)
            else:
                print("[workday] Guest apply requires account creation — no credentials set.")
                print("[workday] Add WORKDAY_EMAIL + WORKDAY_PASSWORD to .env")
                shot("03_auth_blocked")
                print("[workday] ACTION REQUIRED: Apply manually at the URL above.")
                cl_path = Path(screenshot_dir).parent / "cover_letter_tmp.txt"
                cl_path.write_text(cover_letter, encoding="utf-8")
                print(f"[workday] Cover letter text saved to: {cl_path}")
                return screenshots

        if not _on_form(page):
            shot("03_auth_blocked")
            print("[workday] Could not get past auth gate. Apply manually.")
            cl_path = Path(screenshot_dir).parent / "cover_letter_tmp.txt"
            cl_path.write_text(cover_letter, encoding="utf-8")
            print(f"[workday] Cover letter text saved to: {cl_path}")
            return screenshots

    shot("03_on_form")

    # -----------------------------------------------------------------------
    # 3. Navigate the multi-step form
    #    We iterate up to 10 steps. At each step: detect, fill, screenshot, Next.
    # -----------------------------------------------------------------------
    max_steps = 10
    for step_num in range(1, max_steps + 1):
        print(f"[workday] Step {step_num}: detecting content...")
        step_name = _current_step_name(page)
        print(f"[workday] Step heading: '{step_name}'")

        # Fill based on detected step
        if any(kw in step_name for kw in ("information", "contact", "personal")):
            _fill_step1_my_information(page, applicant)

        elif any(kw in step_name for kw in ("experience", "background", "resume", "history")):
            _fill_step2_my_experience(page, applicant)

        elif any(kw in step_name for kw in ("question", "application", "additional", "screening")):
            _fill_step3_application_questions(page, applicant)

        elif any(kw in step_name for kw in ("identify", "eeo", "diversity", "voluntary")):
            _fill_step4_self_identify(page)

        elif any(kw in step_name for kw in ("review", "summary", "confirm")):
            # Final review step
            page.wait_for_timeout(1000)
            shot(f"0{3 + step_num}_review")
            print("[workday] On review page.")

            if mode == "submit":
                print("[workday] Submitting application...")
                submitted = False
                # Try submit button
                for sel in (_SUBMIT_BTN, 'button:has-text("Submit")', 'button:has-text("Apply")'):
                    try:
                        btn = page.locator(sel)
                        if btn.count() > 0 and btn.first.is_visible():
                            btn.first.click()
                            _wait_for_step(page)
                            shot(f"0{3 + step_num}_submitted")
                            print("[workday] Application submitted!")
                            submitted = True
                            break
                    except Exception:
                        pass

                if not submitted:
                    print("[workday] Submit button not found — screenshot taken for review.")
                    shot(f"0{3 + step_num}_submit_failed")
            else:
                print("[workday] Preview mode — not submitting.")
            break

        elif any(kw in step_name for kw in ("create account", "sign in", "signin", "account")):
            # Workday tenant requires account creation before the form
            print("[workday] Create Account / Sign In step reached in step loop — auth should have handled this.")
            print("[workday] Stopping. Add WORKDAY_EMAIL + WORKDAY_PASSWORD to .env and retry.")
            shot(f"0{3 + step_num}_create_account_blocked")
            break

        else:
            # Unknown step — fill what we can and move on
            _fill_step3_application_questions(page, applicant)
            _sweep_checkboxes(page)

        # Screenshot after filling this step
        page.wait_for_timeout(800)
        shot(f"0{3 + step_num}_step{step_num}_filled")

        # Check if submit button is visible (we may be on the last step)
        try:
            sub_btn = page.locator(_SUBMIT_BTN)
            if sub_btn.count() > 0 and sub_btn.first.is_visible():
                print("[workday] Submit button visible — treating as final step.")
                if mode == "submit":
                    print("[workday] Submitting...")
                    sub_btn.first.click()
                    _wait_for_step(page)
                    shot(f"0{3 + step_num}_submitted")
                    print("[workday] Application submitted!")
                else:
                    print("[workday] Preview mode — not submitting.")
                break
        except Exception:
            pass

        # Click Next to advance
        advanced = _click_next(page)
        if not advanced:
            print(f"[workday] Could not advance from step {step_num} — stopping.")
            shot(f"0{3 + step_num}_stuck")
            break

    shot("final_state")
    return screenshots