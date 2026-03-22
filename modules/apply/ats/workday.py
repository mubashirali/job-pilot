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


def _react_fill(page, el, value: str) -> bool:
    """
    Fill a React-managed input by simulating real keyboard input.
    Workday uses React synthetic events — .fill() may not trigger them.
    This method clicks the element, selects all existing text, and types character by character.

    NOTE: On macOS, Control+a moves the cursor to line start (does NOT select all).
          We use select_text() or Meta+a (Cmd+A) to select all before replacing.
    """
    try:
        el.scroll_into_view_if_needed()
        el.click(force=True)
        page.wait_for_timeout(200)
        # Ensure the element is focused before keyboard operations
        # (force=True click may not focus the element on all platforms)
        try:
            el.focus()
        except Exception:
            pass
        page.wait_for_timeout(100)
        # Select all existing text — use select_text() first, fall back to Meta+a (Cmd+A)
        try:
            el.select_text()
        except Exception:
            try:
                el.press("Meta+a")  # Cmd+A on macOS = select all
            except Exception:
                pass
        page.wait_for_timeout(100)
        # Delete the selection — only if the element is still focused
        try:
            el.press("Backspace")  # Delete the selection
        except Exception:
            pass
        page.wait_for_timeout(100)
        # Type the value (triggers React onChange events)
        el.type(value, delay=30)
        page.wait_for_timeout(200)
        return True
    except Exception as e:
        logger.warning(f"react_fill error: {e}")
        return False


def _fill(page, selector: str, value: str, label: str = "") -> bool:
    """Clear + fill a text input by CSS selector. Uses React-compatible typing."""
    if not value:
        return False
    try:
        el = page.locator(selector)
        if el.count() > 0:
            if _react_fill(page, el.first, value):
                logger.debug(f"Filled '{label or selector}'")
                return True
    except Exception as e:
        logger.warning(f"Could not fill '{label or selector}': {e}")
    return False


def _fill_by_label(page, label_texts: list, value: str, label: str = "") -> bool:
    """Fill an input by its associated label text. Uses React-compatible typing."""
    if not value:
        return False
    for lbl in label_texts:
        try:
            el = page.get_by_label(lbl, exact=False)
            if el.count() > 0:
                if _react_fill(page, el.first, value):
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
        el.first.click(force=True)
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


def _select_workday_prompt(page, selector: str, search_text: str, label: str = "") -> bool:
    """
    Select a value from a Workday prompt/search-select widget (the ones with the list icon).
    These widgets open a search overlay when clicked. You type to filter, then click an option.
    Also handles native HTML <select> elements as a fallback.
    """
    if not search_text:
        return False
    try:
        el = page.locator(selector)
        if el.count() == 0:
            logger.warning(f"Workday prompt '{label}': field not found ({selector})")
            return False

        el.first.scroll_into_view_if_needed()

        # If it's a native <select>, use select_option directly
        tag = el.first.evaluate("el => el.tagName.toLowerCase()")
        if tag == "select":
            for lbl_variant in (search_text, search_text.replace(" of America", ""), "US", "USA"):
                try:
                    el.first.select_option(label=lbl_variant)
                    page.wait_for_timeout(300)
                    logger.debug(f"Native select '{label}' = '{lbl_variant}'")
                    return True
                except Exception:
                    pass

        # Workday custom prompt: click to open search overlay
        el.first.click(force=True)
        page.wait_for_timeout(600)

        # Look for a search input that appeared in the overlay
        search_input = page.locator(
            '[data-automation-id="searchBox"] input, '
            '[placeholder*="Search"], '
            '[role="combobox"] input'
        )
        if search_input.count() > 0 and search_input.first.is_visible():
            search_input.first.fill("")
            search_input.first.type(search_text, delay=40)
            page.wait_for_timeout(600)
        else:
            # The element itself may accept typing (inline combobox)
            page.keyboard.type(search_text, delay=40)
            page.wait_for_timeout(600)

        # Click matching option
        for locator in (
            page.get_by_role("option", name=search_text, exact=False),
            page.locator("[role='listbox'] li").filter(has_text=search_text),
            page.locator("li[role='option']").filter(has_text=search_text),
            page.locator("li").filter(has_text=search_text),
        ):
            try:
                if locator.count() > 0:
                    locator.first.click()
                    page.wait_for_timeout(300)
                    logger.debug(f"Workday prompt '{label}' = '{search_text}'")
                    return True
            except Exception:
                pass

        # Close any open overlay — do NOT press Enter (could trigger form submit/Next)
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        logger.warning(f"Workday prompt '{label}': no option matched for '{search_text}' — overlay closed")
        return False

    except Exception as e:
        logger.warning(f"Workday prompt '{label}' error: {e}")
    return False


def _clear_workday_tag(page, field_selector: str) -> bool:
    """
    Remove a selected tag from a Workday multi-select prompt field
    (e.g. Country Phone Code showing 'X Germany (+49)').
    """
    try:
        container = page.locator(field_selector)
        if container.count() == 0:
            return False
        # Workday tag remove buttons: data-automation-id or aria-label
        for remove_sel in (
            '[data-automation-id="removeButton"]',
            'button[aria-label*="Remove"]',
            '[data-automation-id="delete"]',
        ):
            btns = container.locator(remove_sel)
            if btns.count() > 0:
                btns.first.click(force=True)
                page.wait_for_timeout(400)
                return True
        # Generic: any button containing '×' or '✕'
        all_btns = container.locator("button")
        for i in range(all_btns.count()):
            try:
                txt = all_btns.nth(i).inner_text().strip()
                if txt in ("×", "✕", "x", "X", ""):
                    all_btns.nth(i).click(force=True)
                    page.wait_for_timeout(400)
                    return True
            except Exception:
                pass
    except Exception as e:
        logger.warning(f"Could not clear tag from '{field_selector}': {e}")
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


def _wait_for_step(page, timeout: int = 8000):
    """Wait for Workday step content to settle."""
    try:
        page.wait_for_load_state("networkidle", timeout=timeout)
    except Exception:
        pass
    page.wait_for_timeout(1500)


def _wait_for_form_ready(page, timeout: int = 20000):
    """Wait until the Workday application form has rendered actual form fields.

    We require actual INPUT or TEXTAREA elements to be present, not just headings
    or navigation buttons, to avoid false positives while the form is still loading.
    """
    # Strong indicators that the form is ready (inputs/textareas present)
    strong_indicators = [
        '[data-automation-id="legalNameSection_firstName"]',
        '[data-automation-id="bottom-navigation-next-button"]',
        '[data-automation-id="resumeSection"]',
        'input[type="radio"]',
        'textarea',
    ]
    # Weak indicators — only use as fallback after strong wait
    weak_indicators = [
        'button:has-text("Save and Continue")',
        'button:has-text("Save & Continue")',
    ]
    deadline = timeout
    step = 1000
    while deadline > 0:
        for sel in strong_indicators:
            try:
                if page.locator(sel).count() > 0:
                    page.wait_for_timeout(1000)  # Extra settle time after form appears
                    return
            except Exception:
                pass
        page.wait_for_timeout(step)
        deadline -= step
    # Final wait even if indicators not found
    page.wait_for_timeout(1000)


def _click_next(page) -> bool:
    """Click the Next / Save & Continue button and wait for the next step to load.
    Uses force=True to bypass Workday's click_filter overlay div."""
    for sel in (_NEXT_BTN, _SAVE_NEXT_BTN):
        try:
            btn = page.locator(sel)
            if btn.count() > 0 and btn.first.is_visible():
                btn.first.scroll_into_view_if_needed()
                btn.first.click(force=True)
                _wait_for_step(page)
                logger.debug("Clicked Next (by selector)")
                return True
        except Exception:
            pass

    # Fallback: button with text "Next", "Save and Continue", "Save & Continue"
    for text in ("Save and Continue", "Save & Continue", "Next", "Continue"):
        try:
            btn = page.get_by_role("button", name=text, exact=False)
            if btn.count() > 0 and btn.first.is_visible():
                btn.first.scroll_into_view_if_needed()
                btn.first.click(force=True)
                _wait_for_step(page)
                logger.debug(f"Clicked '{text}' (by text)")
                return True
        except Exception:
            pass

    logger.warning("Next button not found")
    return False


def _on_form(page) -> bool:
    """Return True if we're inside the Workday application wizard (past auth gate).

    Checks for navigation buttons and form-specific fields.
    Deliberately excludes the progress bar because it is also visible on the
    'Create Account / Sign In' auth step.
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

    # Workday tenants may use "Save and Continue" instead of standard nav buttons
    for text in ("Save and Continue", "Save & Continue", "Next"):
        try:
            btn = page.get_by_role("button", name=text, exact=False)
            if btn.count() > 0 and btn.first.is_visible():
                # Confirm we're past the auth gate (email/password no longer shown)
                has_password = page.locator('input[type="password"]').count() > 0
                if not has_password:
                    return True
        except Exception:
            pass

    # Detect "My Information" heading on the application form
    for sel in ('h1:has-text("My Information")', 'h2:has-text("My Information")'):
        try:
            if page.locator(sel).count() > 0:
                return True
        except Exception:
            pass

    return False


# ---------------------------------------------------------------------------
# Auth gate helpers
# ---------------------------------------------------------------------------

def _wd_fill(page, selectors: list, labels: list, value: str, label: str = "") -> bool:
    """
    Fill a Workday input field. Tries CSS selectors first, then label-based.
    Uses force=True to bypass Workday's click_filter overlay.
    """
    if not value:
        return False
    # Try label-based (most robust for Workday)
    for lbl in labels:
        try:
            el = page.get_by_label(lbl, exact=False)
            if el.count() > 0:
                el.first.scroll_into_view_if_needed()
                el.first.click(force=True)
                el.first.fill(value)
                logger.debug(f"Filled '{label}' via label '{lbl}'")
                return True
        except Exception:
            pass
    # CSS selector fallback
    for sel in selectors:
        try:
            el = page.locator(sel)
            if el.count() > 0:
                el.first.scroll_into_view_if_needed()
                el.first.click(force=True)
                el.first.fill(value)
                logger.debug(f"Filled '{label}' via selector '{sel}'")
                return True
        except Exception:
            pass
    return False


def _wd_click(page, selectors: list, texts: list, label: str = "") -> bool:
    """Click a Workday button/link using force=True to bypass click_filter overlay."""
    for sel in selectors:
        try:
            el = page.locator(sel)
            if el.count() > 0:
                el.first.scroll_into_view_if_needed()
                el.first.click(force=True)
                logger.debug(f"Clicked '{label}' via selector '{sel}'")
                return True
        except Exception:
            pass
    for text in texts:
        for role in ("button", "link"):
            try:
                el = page.get_by_role(role, name=text, exact=False)
                if el.count() > 0:
                    el.first.scroll_into_view_if_needed()
                    el.first.click(force=True)
                    logger.debug(f"Clicked '{label}' via role={role} text='{text}'")
                    return True
            except Exception:
                pass
        try:
            el = page.locator(f"text={text}")
            if el.count() > 0:
                el.first.scroll_into_view_if_needed()
                el.first.click(force=True)
                logger.debug(f"Clicked '{label}' via text='{text}'")
                return True
        except Exception:
            pass
    logger.warning(f"Could not click '{label}'")
    return False


def _attempt_login(page, email: str, password: str) -> bool:
    """Try to sign in with stored Workday credentials."""
    if not email or not password:
        return False
    try:
        _wd_fill(
            page,
            [_SIGN_IN_EMAIL, 'input[type="email"]'],
            ["Email", "Email Address", "Username"],
            email, "sign-in email",
        )
        page.wait_for_timeout(300)

        _wd_fill(
            page,
            [_SIGN_IN_PASSWORD, 'input[type="password"]'],
            ["Password"],
            password, "sign-in password",
        )
        page.wait_for_timeout(300)

        clicked = _wd_click(
            page,
            [_SIGN_IN_SUBMIT, '[data-automation-id="click_filter"]'],
            ["Sign In", "Log In", "Login"],
            "sign-in submit",
        )
        if clicked:
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


def _on_create_account_page(page) -> bool:
    """Return True if the current page is a Workday 'Create Account' form."""
    indicators = [
        'input[data-automation-id="password"]',
        'input[type="password"]',
        '[data-automation-id="createAccountLink"]',
    ]
    # Must also have an email input to distinguish from a sign-in-only page
    has_email = (
        page.locator('input[data-automation-id="email"]').count() > 0
        or page.locator('input[type="email"]').count() > 0
    )
    if not has_email:
        return False
    for sel in indicators:
        if page.locator(sel).count() > 0:
            return True
    # Detect by heading text
    for text in ("Create Account", "Create your account", "New Account"):
        if page.locator(f"text={text}").count() > 0:
            return True
    return False


def _create_workday_account(page, email: str, password: str) -> bool:
    """
    Fill the Workday 'Create Account' form and submit it.

    Strategy:
      - Every Workday tenant is a separate account database, so we create a
        fresh account per company using the same email + stored password.
      - If an account already exists for this email, sign-in instead.

    Returns True if we successfully passed the auth gate (either by creating
    a new account or by detecting we already had one).
    """
    if not email or not password:
        return False

    print(f"[workday] Creating new account for {email}...")

    # Wait for form to fully render
    page.wait_for_timeout(1500)

    # Fill email
    _wd_fill(
        page,
        ['input[data-automation-id="email"]', 'input[type="email"]'],
        ["Email Address", "Email", "Username"],
        email, "create-account email",
    )
    page.wait_for_timeout(300)

    # Fill password (label-based is most reliable on Workday create-account page)
    pw_filled = _wd_fill(
        page,
        ['input[data-automation-id="password"]', 'input[name="password"]'],
        ["Password"],
        password, "create-account password",
    )

    # Fill verify/confirm password
    _wd_fill(
        page,
        ['input[data-automation-id="verifyPassword"]', 'input[name="verifyPassword"]'],
        ["Verify New Password", "Confirm Password", "Verify Password"],
        password, "create-account verify-password",
    )

    if not pw_filled:
        # Last resort: fill all password-type inputs in order
        try:
            pw_inputs = page.locator('input[type="password"]')
            count = pw_inputs.count()
            if count == 0:
                # Workday sometimes renders password fields as type=text with autocomplete=new-password
                pw_inputs = page.locator('input[autocomplete="new-password"], input[autocomplete="current-password"]')
                count = pw_inputs.count()
            if count > 0:
                pw_inputs.first.click(force=True)
                pw_inputs.first.fill(password)
                if count >= 2:
                    pw_inputs.nth(1).click(force=True)
                    pw_inputs.nth(1).fill(password)
                pw_filled = True
                print("[workday] Filled password fields via type/autocomplete selector")
        except Exception as e:
            logger.warning(f"[workday] Password field fallback failed: {e}")

    if not pw_filled:
        logger.warning("[workday] Could not find password field for account creation")
        return False

    page.wait_for_timeout(300)

    # Check the terms/consent checkbox
    for chk_sel in (
        'input[type="checkbox"]',
        '[data-automation-id="termsAndConditions"]',
        '[data-automation-id="agreedToTerms"]',
    ):
        try:
            chk = page.locator(chk_sel)
            if chk.count() > 0 and not chk.first.is_checked():
                chk.first.click(force=True)
                page.wait_for_timeout(200)
                break
        except Exception:
            pass

    # Click "Create Account" — use force=True to bypass click_filter overlay
    created = _wd_click(
        page,
        [
            '[data-automation-id="createAccountSubmitButton"]',
            'button[type="submit"]',
            'button:has-text("Create Account")',
            'input[type="submit"]',
        ],
        ["Create Account", "Register", "Sign Up"],
        "create-account submit",
    )

    if not created:
        logger.warning("[workday] 'Create Account' button not found")
        return False

    print("[workday] Clicked 'Create Account'.")
    _wait_for_step(page)
    page.wait_for_timeout(2000)

    page.wait_for_timeout(3000)

    # After creation, Workday may:
    # (a) Land directly on the application form — check _on_form()
    # (b) Show an email verification page — handle by waiting or skipping
    # (c) Show an error (e.g. email already in use) — try sign-in instead
    if _on_form(page):
        print("[workday] Account created — now on application form.")
        return True

    # Check for "email already exists" error → try sign-in
    already_exists_signals = [
        "already exists",
        "already registered",
        "already have an account",
        "email address is already",
    ]
    page_text = ""
    try:
        page_text = page.locator("body").inner_text().lower()
    except Exception:
        pass

    if any(s in page_text for s in already_exists_signals):
        print("[workday] Email already registered — attempting sign-in instead.")
        # Navigate to sign-in
        for link_text in ("Sign In", "Log In", "Already have an account"):
            try:
                link = page.get_by_role("link", name=link_text, exact=False)
                if link.count() == 0:
                    link = page.get_by_role("button", name=link_text, exact=False)
                if link.count() > 0:
                    link.first.click()
                    _wait_for_step(page)
                    break
            except Exception:
                pass
        return _attempt_login(page, email, password)

    # Check for email verification page
    verify_signals = ["verify your email", "check your email", "verification email", "confirm your email"]
    if any(s in page_text for s in verify_signals):
        print("[workday] Email verification required — check Gmail and verify, then re-run.")
        logger.warning("Workday account created but email verification required before proceeding.")
        return False

    # Unknown post-creation state — check if we can proceed
    if _on_form(page):
        return True

    print("[workday] Account created but unknown state after creation — taking screenshot.")
    return False


def _navigate_past_auth(page, applicant: dict, screenshot_dir: str, ts: str) -> bool:
    """
    Detect and pass the Workday auth gate.

    Strategy (in order):
      1. Already on form — nothing to do
      2. Guest apply / Apply Manually — no account needed
      3. Sign in with stored credentials — existing account for this tenant
      4. Create new account — first time on this tenant
    """
    # "Start Your Application" modal (some tenants show this instead of a login form)
    _start_modal = (
        page.locator('button:has-text("Sign In to Workday")').count() > 0
        or page.locator('a:has-text("Sign In to Workday")').count() > 0
        or page.locator('text=Start Your Application').count() > 0
    )

    on_login = (
        _start_modal
        or page.locator('input[data-automation-id="email"]').count() > 0
        or page.locator('input[type="email"]').count() > 0
        or page.locator('[data-automation-id="authn-modal"]').count() > 0
        or page.locator(_SIGN_IN_SUBMIT).count() > 0
        or "login" in page.url.lower()
        or "signin" in page.url.lower()
    )

    if not on_login:
        return True  # Already on the form

    _ss(page, f"{screenshot_dir}/workday_{ts}_auth_gate.png")
    print("[workday] Auth gate detected.")

    wd_email = os.getenv("WORKDAY_EMAIL", "")
    wd_pass  = os.getenv("WORKDAY_PASSWORD", "")

    # 0. Handle "Start Your Application" modal — navigate to /apply URL to bypass modal
    if _start_modal:
        # The modal is CSS-styled as all-caps so text matching fails; navigate past it
        # by going directly to the /apply variant of the current URL.
        current_url = page.url
        if "/apply" not in current_url.lower().split("?")[0].split("#")[0].rstrip("/")[-6:]:
            apply_url = current_url.rstrip("/") + "/apply"
        else:
            apply_url = current_url

        if wd_email and wd_pass:
            print(f"[workday] 'Start Your Application' modal — navigating to {apply_url} ...")
            page.goto(apply_url)
            _wait_for_step(page)

            # The /apply page shows "Start Your Application" with two options.
            # Button text is CSS all-caps; use JS case-insensitive match to click "Sign In".
            clicked_signin = page.evaluate("""
                () => {
                    const btns = Array.from(document.querySelectorAll('button, a'));
                    const btn = btns.find(el => el.textContent.toLowerCase().includes('sign in'));
                    if (btn) { btn.click(); return true; }
                    return false;
                }
            """)
            if clicked_signin:
                print("[workday] Clicked 'Sign In to Workday' via JS — waiting for dialog...")
                page.wait_for_timeout(2000)

            # Now the Sign In dialog should be open — fill email + password inside it
            # Scope the fill to the dialog to avoid hitting hidden fields
            dialog = page.locator('[role="dialog"]')
            if dialog.count() > 0 and dialog.first.is_visible():
                print("[workday] Sign In dialog detected — filling credentials...")
                try:
                    inputs = dialog.first.locator('input')
                    if inputs.count() >= 2:
                        inputs.nth(0).fill(wd_email)
                        page.wait_for_timeout(200)
                        inputs.nth(1).fill(wd_pass)
                        page.wait_for_timeout(200)
                    elif inputs.count() == 1:
                        inputs.nth(0).fill(wd_email)
                    # Click Sign In button inside dialog
                    sign_btn = dialog.first.locator('button').filter(has_text="Sign In")
                    if sign_btn.count() == 0:
                        sign_btn = dialog.first.get_by_role("button", name="Sign In", exact=False)
                    if sign_btn.count() > 0:
                        sign_btn.first.click(force=True)
                        _wait_for_step(page)
                        logger.info("Signed in to Workday account via dialog")
                        _ss(page, f"{screenshot_dir}/workday_{ts}_after_login.png")
                        return True
                except Exception as e:
                    logger.warning(f"Dialog sign-in failed: {e}")

            # Fallback: standard login attempt (page-level form)
            if _attempt_login(page, wd_email, wd_pass):
                _ss(page, f"{screenshot_dir}/workday_{ts}_after_login.png")
                return True
            # Couldn't sign in — fall through to remaining auth logic
        else:
            # No credentials — try clicking Apply Manually in the modal
            apply_manually_btn = page.locator(
                'button:has-text("Apply Manually"), a:has-text("Apply Manually")'
            )
            if apply_manually_btn.count() > 0 and apply_manually_btn.first.is_visible():
                print("[workday] 'Start Your Application' modal — clicking 'Apply Manually'...")
                apply_manually_btn.first.click()
                _wait_for_step(page)
                if _on_form(page):
                    _ss(page, f"{screenshot_dir}/workday_{ts}_after_guest.png")
                    return True

    # 1. Try guest apply first (no credentials needed) — skip if credentials available
    if not (wd_email and wd_pass) and _attempt_guest_apply(page):
        print("[workday] Continuing as guest.")
        _ss(page, f"{screenshot_dir}/workday_{ts}_after_guest.png")
        return True

    if not wd_email or not wd_pass:
        print("[workday] No credentials in .env — cannot proceed past auth gate.")
        return False

    # 2. If we're on a Create Account page → create account directly
    if _on_create_account_page(page):
        print("[workday] Create Account page detected — creating new account.")
        if _create_workday_account(page, wd_email, wd_pass):
            _ss(page, f"{screenshot_dir}/workday_{ts}_after_create_account.png")
            return True
        # Creation failed — try sign-in as fallback (may already have account)
        print("[workday] Account creation failed — trying sign-in as fallback.")

    # 3. Try sign in (existing account for this Workday tenant)
    print(f"[workday] Attempting sign-in as {wd_email}...")
    # Navigate to Sign In if we're still on Create Account page
    for link_text in ("Sign In", "Already have an account", "Log in"):
        try:
            link = page.get_by_role("link", name=link_text, exact=False)
            if link.count() == 0:
                link = page.get_by_role("button", name=link_text, exact=False)
            if link.count() > 0 and link.first.is_visible():
                link.first.click()
                _wait_for_step(page)
                break
        except Exception:
            pass

    if _attempt_login(page, wd_email, wd_pass):
        _ss(page, f"{screenshot_dir}/workday_{ts}_after_login.png")
        return True

    # 4. Sign-in failed — account likely doesn't exist yet; try creating
    print("[workday] Sign-in failed — attempting to create new account.")
    # Navigate back to Create Account if needed
    for link_text in ("Create Account", "New User", "Register"):
        try:
            link = page.get_by_role("link", name=link_text, exact=False)
            if link.count() == 0:
                link = page.get_by_role("button", name=link_text, exact=False)
            if link.count() > 0 and link.first.is_visible():
                link.first.click()
                _wait_for_step(page)
                break
        except Exception:
            pass

    if _create_workday_account(page, wd_email, wd_pass):
        _ss(page, f"{screenshot_dir}/workday_{ts}_after_create_account.png")
        return True

    print("[workday] Could not bypass auth gate.")
    return False


# ---------------------------------------------------------------------------
# Step fillers
# ---------------------------------------------------------------------------

def _on_form_url(page) -> bool:
    """Return True if the current URL looks like a Workday application form (not job listing)."""
    url = page.url.lower()
    return "/apply" in url or "applymanually" in url


def _fill_step1_my_information(page, applicant: dict):
    """Fill Step 1: My Information."""
    print("[workday] Filling Step 1: My Information...")
    form_url = page.url

    # Wait for fields to render
    page.wait_for_timeout(1000)

    # -----------------------------------------------------------------------
    # Name — data-automation-id first, then label-based
    # -----------------------------------------------------------------------
    first_name = applicant.get("first_name", "")
    last_name  = applicant.get("last_name", "")

    # Only fill if the field is currently empty or has wrong value
    for sel, val, lbl in (
        (_FIRST_NAME, first_name, "first_name"),
        (_LAST_NAME,  last_name,  "last_name"),
    ):
        el = page.locator(sel)
        if el.count() > 0:
            current = el.first.input_value() or ""
            if current.strip() == "":
                _fill(page, sel, val, lbl)
        else:
            _fill_by_label(
                page,
                ["Given Name", "First Name", "Legal First Name"] if "first" in lbl else
                ["Family Name", "Last Name", "Legal Last Name", "Surname"],
                val, lbl,
            )
    print(f"[workday] URL after name fill: {page.url}")

    # -----------------------------------------------------------------------
    # "How Did You Hear About Us?" — Workday search-select prompt widget
    # -----------------------------------------------------------------------
    how_hear_filled = False
    # Try several possible automation-ids across Workday tenants
    for how_hear_sel in (
        '[data-automation-id="howDidYouHearAboutUs"]',
        '[data-automation-id="referralSource"]',
        '[data-automation-id="referralSourceV2"]',
        '[data-automation-id="hearAboutUs"]',
    ):
        el = page.locator(how_hear_sel)
        if el.count() > 0:
            try:
                current_text = el.first.inner_text().strip()
                if "linkedin" not in current_text.lower():
                    how_hear_filled = _select_workday_prompt(page, how_hear_sel, "LinkedIn", "how_did_you_hear")
            except Exception:
                pass
            break

    if not how_hear_filled:
        # JS fallback: find the SMALLEST data-automation-id container that contains
        # "How Did You Hear" text AND has a prompt button inside it.
        # Using the smallest container avoids accidentally clicking buttons in larger
        # wrappers (e.g., the form wrapper's "Save and Continue" button).
        clicked = page.evaluate("""
            () => {
                let bestBtn = null;
                let bestSize = Infinity;
                const nodes = Array.from(document.querySelectorAll('[data-automation-id]'));
                for (const el of nodes) {
                    if (!el.textContent.includes('How Did You Hear')) continue;
                    // Require a button with prompt-like attributes (aria-haspopup or role="button")
                    // preferring smaller containers
                    const promptBtn = el.querySelector(
                        'button[aria-haspopup], button[aria-expanded], ' +
                        '[role="button"][aria-haspopup], [role="button"][aria-expanded]'
                    );
                    const anyBtn = el.querySelector('button');
                    const btn = promptBtn || anyBtn;
                    if (!btn) continue;
                    const size = el.querySelectorAll('*').length;
                    if (size < bestSize) {
                        bestSize = size;
                        bestBtn = btn;
                    }
                }
                if (bestBtn) { bestBtn.click(); return true; }
                return false;
            }
        """)
        if clicked:
            page.wait_for_timeout(600)
            # Type "LinkedIn" in the opened search overlay
            search_input = page.locator(
                '[data-automation-id="searchBox"] input, [placeholder*="Search"], [role="combobox"] input'
            )
            if search_input.count() > 0 and search_input.first.is_visible():
                search_input.first.fill("")
                search_input.first.type("LinkedIn", delay=40)
                page.wait_for_timeout(600)
            else:
                page.keyboard.type("LinkedIn", delay=40)
                page.wait_for_timeout(600)
            # Click matching option
            for loc in (
                page.get_by_role("option", name="LinkedIn", exact=False),
                page.locator("li").filter(has_text="LinkedIn"),
            ):
                try:
                    if loc.count() > 0:
                        loc.first.click()
                        page.wait_for_timeout(300)
                        how_hear_filled = True
                        print("[workday] 'How Did You Hear' filled via JS fallback")
                        break
                except Exception:
                    pass
            if not how_hear_filled:
                # Don't press Enter as fallback — it can trigger form navigation
                # Close the overlay and leave the field empty; will show validation error
                page.keyboard.press("Escape")
                page.wait_for_timeout(300)
                logger.warning("'How Did You Hear About Us?' — could not select an option")

    print(f"[workday] URL after how_hear: {page.url}")

    # -----------------------------------------------------------------------
    # "Previously employed by Empower / affiliated company?" → No
    # -----------------------------------------------------------------------
    # Find the Yes/No radio group and click No directly
    prev_emp_texts = [
        "previously been employed",
        "previously worked for",
        "former employee",
        "affiliated company",
    ]
    prev_emp_answered = False
    for q_text in prev_emp_texts:
        try:
            containers = page.locator("div, fieldset, section").filter(has_text=q_text)
            for i in range(min(containers.count(), 5)):
                c = containers.nth(i)
                # Look for "No" radio within this container
                no_radio = c.get_by_role("radio", name="No", exact=False)
                if no_radio.count() == 0:
                    no_radio = c.locator('input[type="radio"]').filter(has_text="No")
                if no_radio.count() == 0:
                    # Get all radios and pick the one labelled No
                    all_radios = c.locator('input[type="radio"]')
                    if all_radios.count() >= 2:
                        # Typically: first = Yes, second = No
                        no_radio = all_radios.nth(1)
                if no_radio.count() > 0:
                    try:
                        if not no_radio.first.is_checked():
                            no_radio.first.click(force=True)
                            page.wait_for_timeout(300)
                            print(f"[workday] Clicked 'No' for '{q_text[:50]}'")
                            prev_emp_answered = True
                            break
                    except Exception:
                        pass
            if prev_emp_answered:
                break
        except Exception as e:
            logger.warning(f"Previously employed click error: {e}")

    print(f"[workday] URL after prev_emp: {page.url}")

    # -----------------------------------------------------------------------
    # Country — native <select> or Workday prompt
    # -----------------------------------------------------------------------
    country_set = False
    # Try several automation-id patterns
    for country_sel in (
        '[data-automation-id="country"]',
        '[data-automation-id="addressSection_countryRegion"]',
        'select[data-automation-id="country"]',
        'select[data-automation-id*="country"]',
        'select[data-automation-id*="Country"]',
    ):
        el = page.locator(country_sel)
        if el.count() > 0:
            tag = el.first.evaluate("el => el.tagName.toLowerCase()")
            if tag == "select":
                for lbl_var in ("United States of America", "United States", "US"):
                    try:
                        el.first.select_option(label=lbl_var)
                        page.wait_for_timeout(500)
                        current = el.first.evaluate("el => el.value")
                        if current and current not in ("", "DE"):
                            country_set = True
                            print(f"[workday] Country set via select_option('{lbl_var}')")
                            break
                    except Exception:
                        pass
            else:
                country_set = _select_workday_prompt(page, country_sel, "United States of America", "country")
            if country_set:
                break
    if not country_set:
        # JS fallback: find the select element that has United States as an option
        country_set = page.evaluate("""
            () => {
                const selects = Array.from(document.querySelectorAll('select'));
                for (const sel of selects) {
                    const opts = Array.from(sel.options);
                    const usOpt = opts.find(o =>
                        o.text.includes('United States') || o.text === 'US' || o.value === 'US'
                    );
                    if (usOpt) {
                        sel.value = usOpt.value;
                        sel.dispatchEvent(new Event('change', {bubbles: true}));
                        sel.dispatchEvent(new Event('input', {bubbles: true}));
                        return true;
                    }
                }
                return false;
            }
        """)
        if country_set:
            print("[workday] Country set via JS select fallback")
            page.wait_for_timeout(500)

    print(f"[workday] URL after country: {page.url}")

    # -----------------------------------------------------------------------
    # Country Phone Code — remove existing tag, set to United States (+1)
    # -----------------------------------------------------------------------
    phone_code_found = False
    for pcs in (
        '[data-automation-id="countryPhoneCode"]',
        '[data-automation-id="phone-device-country-code"]',
        '[data-automation-id*="phoneCode"]',
        '[data-automation-id*="PhoneCode"]',
        '[data-automation-id*="countryCode"]',
    ):
        el = page.locator(pcs)
        if el.count() > 0:
            phone_code_found = True
            # Check if Germany (or any non-US) is currently selected
            try:
                current_text = el.first.inner_text()
                if "Germany" in current_text or "+49" in current_text or "United States" not in current_text:
                    _clear_workday_tag(page, pcs)
                    page.wait_for_timeout(400)
            except Exception:
                pass
            # Now set to United States
            _select_workday_prompt(page, pcs, "United States", "country_phone_code")
            break
    if not phone_code_found:
        # JS fallback: find and click the X button on any Germany/+49 phone code tag
        removed = page.evaluate("""
            () => {
                const allEls = Array.from(document.querySelectorAll('*'));
                for (const el of allEls) {
                    const txt = el.textContent || '';
                    if ((txt.includes('Germany') || txt.includes('+49')) && el.children.length < 5) {
                        const removeBtn = el.querySelector(
                            '[data-automation-id="removeButton"], button[aria-label*="Remove"], button[aria-label*="remove"]'
                        );
                        if (removeBtn) { removeBtn.click(); return true; }
                        const btns = el.querySelectorAll('button');
                        if (btns.length > 0) { btns[0].click(); return true; }
                    }
                }
                return false;
            }
        """)
        if removed:
            page.wait_for_timeout(400)
            print("[workday] Germany phone code tag removed via JS")
        # Now try to open the prompt and select United States
        # Find prompt button for phone code by looking for the list-icon near phone section
        page.evaluate("""
            () => {
                const labels = Array.from(document.querySelectorAll('label, [class*="label"]'));
                for (const lbl of labels) {
                    if (lbl.textContent.includes('Country Phone Code')) {
                        const container = lbl.closest('[data-automation-id]') || lbl.parentElement.parentElement;
                        const btn = container ? container.querySelector('button') : null;
                        if (btn) { btn.click(); return true; }
                    }
                }
                return false;
            }
        """)
        page.wait_for_timeout(600)
        search_input = page.locator(
            '[data-automation-id="searchBox"] input, [placeholder*="Search"], [role="combobox"] input'
        )
        if search_input.count() > 0 and search_input.first.is_visible():
            search_input.first.fill("")
            search_input.first.type("United States", delay=40)
            page.wait_for_timeout(600)
            for loc in (
                page.get_by_role("option", name="United States", exact=False),
                page.locator("li").filter(has_text="United States (+1)"),
                page.locator("li").filter(has_text="United States"),
            ):
                try:
                    if loc.count() > 0:
                        loc.first.click()
                        page.wait_for_timeout(300)
                        print("[workday] Country Phone Code set via JS fallback")
                        break
                except Exception:
                    pass

    print(f"[workday] URL after phone_code: {page.url}")

    # -----------------------------------------------------------------------
    # Phone Number
    # -----------------------------------------------------------------------
    raw_phone = applicant.get("phone", "")
    if raw_phone.startswith("+1"):
        raw_phone = raw_phone[2:]
    elif raw_phone.startswith("1") and len(raw_phone) == 11:
        raw_phone = raw_phone[1:]
    # Only fill if empty
    phone_el = page.locator(_PHONE_NUMBER)
    if phone_el.count() > 0:
        if not (phone_el.first.input_value() or "").strip():
            _fill(page, _PHONE_NUMBER, raw_phone, "phone")
    else:
        _fill_by_label(page, ["Phone Number", "Mobile Number", "Phone"], raw_phone, "phone_label")

    # Phone device type
    _select_dropdown(page, _PHONE_DEVICE, "Mobile", "phone_device_type")
    print(f"[workday] URL after phone: {page.url}")

    # -----------------------------------------------------------------------
    # Address
    # -----------------------------------------------------------------------
    for sel, val, labels in (
        (_ADDRESS_LINE1, "Columbia, MO", ["Street", "Address Line 1", "Street Address"]),
        (_CITY,          "Columbia",     ["City"]),
        (_POSTAL_CODE,   "65201",        ["Postal Code", "ZIP Code", "Zip"]),
    ):
        el = page.locator(sel)
        if el.count() > 0:
            if not (el.first.input_value() or "").strip():
                _fill(page, sel, val, sel)
        else:
            _fill_by_label(page, labels, val, labels[0])

    _select_dropdown(page, _STATE_REGION, "Missouri", "state")
    print(f"[workday] URL after address: {page.url}")

    # -----------------------------------------------------------------------
    # Email (sometimes editable on guest apply)
    # -----------------------------------------------------------------------
    _fill_by_label(
        page,
        ["Email", "Email Address", "Work Email"],
        applicant.get("email", ""),
        "email",
    )
    print(f"[workday] URL at end of step1 fill: {page.url}")


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
    """
    Detect the current Workday wizard step.

    Priority:
      1. aria-current="step" in the progress bar (most reliable — wizard tracks active step)
      2. h1/h2 heading inside the main form area
      3. Form-specific field presence (data-automation-id signals per step)
      4. URL fallback

    NOTE: Text-phrase detection based on page.locator("text=...") is intentionally
    NOT used here because the Workday progress bar contains ALL step names as
    visible text (My Information, My Experience, Voluntary Disclosures, etc.),
    which causes false positives if we match against them.
    """
    # -----------------------------------------------------------------------
    # 1. Progressbar aria-current — the active step indicator is the most reliable
    # -----------------------------------------------------------------------
    for sel in [
        '[data-automation-id="progressBar"] [aria-current="step"]',
        '[aria-current="step"]',
        '[data-automation-id="currentStep"]',
    ]:
        try:
            el = page.locator(sel)
            if el.count() > 0:
                text = el.first.inner_text().strip().lower()
                if text and text not in ("", "workday"):
                    return text
        except Exception:
            pass

    # -----------------------------------------------------------------------
    # 2. Heading text — iterate ALL h1/h2/h3 elements looking for known step names.
    #    The job title h1 ("Principal Software Engineer - Java") is on the same page,
    #    so we check each heading against a set of known Workday step names.
    # -----------------------------------------------------------------------
    _KNOWN_STEPS = {
        "my information": "my information",
        "my experience": "my experience",
        "application questions": "application questions",
        "voluntary disclosures": "voluntary disclosures",
        "self identify": "self identify",
        "review and submit": "review",
        "review": "review",
    }
    for sel in ['h1', 'h2', 'h3', '[role="heading"]']:
        try:
            els = page.locator(sel)
            for i in range(min(els.count(), 10)):
                text = els.nth(i).inner_text().strip().lower()
                if text in _KNOWN_STEPS:
                    return _KNOWN_STEPS[text]
        except Exception:
            pass

    # -----------------------------------------------------------------------
    # 3. Form-specific field presence (data-automation-id or label unique per step)
    # -----------------------------------------------------------------------

    # "My Information" — unique data-automation-id inputs or label text
    if page.locator('[data-automation-id="legalNameSection_firstName"]').count() > 0:
        return "my information"
    try:
        if page.get_by_label("Given Name", exact=False).count() > 0:
            return "my information"
        if page.get_by_label("How Did You Hear About Us", exact=False).count() > 0:
            return "my information"
    except Exception:
        pass

    # "My Experience" — resume section
    for sel in (
        '[data-automation-id="resumeSection"]',
        '[data-automation-id="dropResumeLink"]',
        '[data-automation-id="uploadResumeButton"]',
    ):
        if page.locator(sel).count() > 0:
            return "my experience"

    # "Review" — submit button only appears on final review step
    if page.locator('[data-automation-id="bottom-navigation-submit-button"]').count() > 0:
        return "review"
    try:
        submit = page.get_by_role("button", name="Submit", exact=False)
        if submit.count() > 0 and submit.first.is_visible():
            return "review"
    except Exception:
        pass

    # Auth / create account
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
    # Error page detection — Workday may show "Oops, an error occurred"
    # when navigating directly to a job URL without a session.
    # Recovery: navigate to the Workday candidate home, sign in, then search.
    # -----------------------------------------------------------------------
    def _is_error_page() -> bool:
        try:
            body = page.locator("body").inner_text().lower()
            return (
                ("oops" in body and "error" in body)
                or "currently unavailable" in body
                or "service interruption" in body
                or "maintenance" in page.url.lower()
                or "maintenance-page" in page.url.lower()
            )
        except Exception:
            return False

    def _recover_via_candidate_home(job_url: str) -> bool:
        """
        Try to recover from a Workday error page by navigating to the
        candidate home, signing in, and going back to the job page.
        """
        # Extract base tenant URL from job URL
        # e.g. https://empower.wd5.myworkdayjobs.com/Empower_Careers/job/...
        #  → https://empower.wd5.myworkdayjobs.com/Empower_Careers
        parts = job_url.split("/")
        if len(parts) >= 5:
            base = "/".join(parts[:5])  # scheme + host + tenant path
        else:
            base = "/".join(parts[:4])

        print(f"[workday] Error page detected — navigating to candidate home: {base}")
        page.goto(base, wait_until="domcontentloaded", timeout=30000)
        _wait_for_step(page)

        # Sign in from the candidate home
        wd_email = os.getenv("WORKDAY_EMAIL", "")
        wd_pass  = os.getenv("WORKDAY_PASSWORD", "")
        if wd_email and wd_pass:
            _attempt_login(page, wd_email, wd_pass)
            _wait_for_step(page)

        # Navigate back to the job page
        page.goto(job_url, wait_until="domcontentloaded", timeout=30000)
        _wait_for_step(page)

        if not _is_error_page():
            print("[workday] Recovery successful — job page loaded.")
            return True
        print("[workday] Recovery failed — still on error page.")
        return False

    if _is_error_page():
        shot("01b_error_page")
        if not _recover_via_candidate_home(page.url):
            # Last resort: try signing in first, then reload
            wd_email = os.getenv("WORKDAY_EMAIL", "")
            wd_pass  = os.getenv("WORKDAY_PASSWORD", "")
            if wd_email and wd_pass:
                _navigate_past_auth(page, applicant, screenshot_dir, ts)
            if _is_error_page():
                print("[workday] Cannot proceed — Workday error page persists. Try again later.")
                shot("01c_unrecoverable_error")
                return screenshots

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
    # 2. Pass auth gate — guest apply → sign-in → create account
    # -----------------------------------------------------------------------
    if _on_form(page):
        print("[workday] Already on application form.")
    else:
        if not _navigate_past_auth(page, applicant, screenshot_dir, ts):
            shot("03_auth_blocked")
            print("[workday] Could not get past auth gate. Apply manually.")
            cl_path = Path(screenshot_dir).parent / "cover_letter_tmp.txt"
            cl_path.write_text(cover_letter, encoding="utf-8")
            print(f"[workday] Cover letter text saved to: {cl_path}")
            return screenshots

    # After auth, verify we're on the application form — not the job listing or candidate home
    # If auth redirected to "Start Your Application" selection page, click Apply Manually.
    page.wait_for_timeout(2000)
    if not _on_form(page):
        print("[workday] Not on application form after auth — attempting to re-enter apply flow...")

        # Check for the post-login "Start Your Application" options (authenticated view)
        # Priority: "Apply Manually" > "Use My Last Application" > generic Apply button
        enter_form_clicked = False
        for btn_text in ("Apply Manually", "Use My Last Application", "Apply"):
            try:
                btn = page.get_by_role("button", name=btn_text, exact=False)
                if btn.count() > 0 and btn.first.is_visible():
                    btn.first.click(force=True)
                    page.wait_for_timeout(3000)
                    enter_form_clicked = True
                    print(f"[workday] Clicked '{btn_text}' to enter application form.")
                    break
            except Exception:
                pass

        if not enter_form_clicked:
            # Fall back to looking for the job-page Apply button
            for apply_sel in (_APPLY_BTN, 'a:has-text("Apply")'):
                el = page.locator(apply_sel)
                if el.count() > 0 and el.first.is_visible():
                    el.first.click(force=True)
                    page.wait_for_timeout(3000)
                    break

    # Wait for the form to fully render before detecting steps
    print("[workday] Waiting for application form to fully render...")
    _wait_for_form_ready(page)
    shot("03_on_form")

    # -----------------------------------------------------------------------
    # 3. Navigate the multi-step form
    #    We iterate up to 10 steps. At each step: detect, fill, screenshot, Next.
    # -----------------------------------------------------------------------
    max_steps = 10
    prev_step_name = None
    stuck_count = 0
    filled_steps: set = set()  # track which canonical step names we've already filled

    for step_num in range(1, max_steps + 1):
        print(f"[workday] Step {step_num}: detecting content...")
        step_name = _current_step_name(page)
        print(f"[workday] Step heading: '{step_name}'")

        # --- Stuck detection: if we're on the same step after clicking Next ---
        if step_name == prev_step_name:
            stuck_count += 1
            if stuck_count >= 3:
                print(f"[workday] Stuck on '{step_name}' for {stuck_count} iterations — stopping.")
                shot(f"0{3 + step_num}_stuck_loop")
                break
            print(f"[workday] Still on '{step_name}' (attempt {stuck_count}/3), retrying fill...")
        else:
            stuck_count = 0
        prev_step_name = step_name

        # Determine canonical step key
        if any(kw in step_name for kw in ("information", "contact", "personal")):
            step_key = "my_information"
        elif any(kw in step_name for kw in ("experience", "background", "resume", "history")):
            step_key = "my_experience"
        elif any(kw in step_name for kw in ("question", "application questions", "additional", "screening")):
            step_key = "application_questions"
        elif any(kw in step_name for kw in ("identify", "eeo", "diversity", "voluntary")):
            step_key = "self_identify"
        elif step_name.endswith("/apply") or "applymanually" in step_name or step_name.endswith("/apply/"):
            # Workday URL fallback: /apply or /apply/applymanually = first step (My Information)
            step_key = "my_information"
        else:
            step_key = step_name

        # Fill step — always fill on stuck retries, otherwise fill once per step
        should_fill = (step_key not in filled_steps) or (stuck_count > 0)

        if step_key == "my_information" and should_fill:
            _fill_step1_my_information(page, applicant)
            filled_steps.add(step_key)

        elif step_key == "my_experience" and should_fill:
            _fill_step2_my_experience(page, applicant)
            filled_steps.add(step_key)

        elif step_key == "application_questions" and should_fill:
            _fill_step3_application_questions(page, applicant)
            filled_steps.add(step_key)

        elif step_key == "self_identify" and should_fill:
            _fill_step4_self_identify(page)
            filled_steps.add(step_key)

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

        elif should_fill:
            # Unknown step — fill what we can and move on
            _fill_step3_application_questions(page, applicant)
            _sweep_checkboxes(page)
            filled_steps.add(step_key)

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