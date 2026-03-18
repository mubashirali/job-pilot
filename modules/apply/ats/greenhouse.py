"""
Greenhouse ATS handler.

Fills (and optionally submits) Greenhouse job application forms.

Key design decisions:
- Standard fields (#first_name, #last_name, #email, #phone, #resume, #cover_letter)
  use direct ID selectors — these are consistent across all Greenhouse forms.
- Custom question fields (work auth, sponsorship, EEO, State, etc.) use label-based
  detection + combobox interaction, since question IDs differ per company.
- Combobox pattern: click input → wait for dropdown → click matching option.
- Cover letter is a file upload (#cover_letter), not a textarea.
"""

import logging
import sys
import time
from datetime import datetime
from pathlib import Path

_ROOT = Path(__file__).parent.parent.parent.parent  # modules/apply/ats → project root
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------------------------

def _safe_fill(page, selector: str, value: str, field_name: str = "") -> bool:
    """Fill a text input by CSS selector. Returns True on success."""
    if not value:
        return False
    try:
        el = page.locator(selector)
        if el.count() > 0:
            el.first.fill(value)
            logger.debug(f"Filled '{field_name}' via '{selector}'")
            return True
    except Exception as e:
        logger.warning(f"Could not fill '{field_name}' via '{selector}': {e}")
    return False


def _safe_upload(page, selector: str, file_path: str, field_name: str = "") -> bool:
    """Upload a file to an <input type='file'>. Returns True on success."""
    if not file_path or not Path(file_path).exists():
        logger.warning(f"File not found for '{field_name}': {file_path}")
        return False
    try:
        el = page.locator(selector)
        if el.count() > 0:
            el.first.set_input_files(file_path)
            logger.debug(f"Uploaded '{field_name}' from '{file_path}'")
            return True
    except Exception as e:
        logger.warning(f"Could not upload '{field_name}': {e}")
    return False


def _fill_by_label(page, label_texts: list, value: str, field_name: str = "") -> bool:
    """Fill a plain text input by its associated label. Tries multiple label variants."""
    if not value:
        return False
    for label in label_texts:
        try:
            el = page.get_by_label(label, exact=False)
            if el.count() > 0:
                el.first.fill(value)
                logger.debug(f"Filled '{field_name}' via label '{label}'")
                return True
        except Exception:
            pass
    logger.warning(f"Could not find text field '{field_name}' by label")
    return False


def _pick_option(page, value: str) -> bool:
    """
    Click the first visible dropdown option matching value.
    Uses Playwright .filter(has_text=) to avoid CSS apostrophe issues.
    """
    # ARIA role=option (most Greenhouse dropdowns)
    option = page.get_by_role("option", name=value, exact=False)
    if option.count() > 0:
        option.first.click()
        return True
    # Fallback: any visible <li> containing the text
    option = page.locator("li").filter(has_text=value)
    if option.count() > 0:
        option.first.click()
        return True
    return False


def _fill_combobox(page, selector: str, value: str, field_name: str = "") -> bool:
    """
    Fill a Greenhouse custom combobox by CSS selector.
    Pattern: click input → wait for dropdown → click matching option.
    Returns True on success.
    """
    if not value:
        return False
    try:
        el = page.locator(selector)
        if el.count() == 0:
            return False

        el.first.click()
        page.wait_for_timeout(600)

        if _pick_option(page, value):
            logger.debug(f"Combobox '{field_name}' set to '{value}'")
            return True

        try:
            el.first.press("Escape")
        except Exception:
            pass
        logger.warning(f"Combobox '{field_name}': no option matching '{value}'")
    except Exception as e:
        logger.warning(f"Combobox '{field_name}' error: {e}")
    return False


def _find_el_by_label(page, label_text: str):
    """
    Locate an input/select associated with a label containing label_text.
    Tries three strategies:
      1. Playwright get_by_label (works when label has 'for' attr)
      2. label.filter(has_text) → read 'for' attr → locate by ID
      3. label.filter(has_text) → sibling/child input in same container
    Returns a Playwright locator (may have count==0 if not found).
    """
    # Strategy 1: proper for/id association
    el = page.get_by_label(label_text, exact=False)
    if el.count() > 0:
        return el.first

    # Strategy 2: label → for attr → #id
    lbl = page.locator("label").filter(has_text=label_text).first
    if lbl.count() > 0:
        for_id = lbl.get_attribute("for")
        if for_id:
            el = page.locator(f"#{for_id}")
            if el.count() > 0:
                return el.first

        # Strategy 3: find an input in the same parent container
        el = lbl.locator("xpath=../descendant::input[1]")
        if el.count() > 0:
            return el.first
        el = lbl.locator("xpath=../../descendant::input[1]")
        if el.count() > 0:
            return el.first

    return page.locator("__notfound__")  # always count==0


def _fill_typeahead_combobox(
    page,
    selector: str,
    type_value: str,
    pick_value: str = "",
    field_name: str = "",
) -> bool:
    """
    Fill a typeahead / autocomplete combobox (e.g. Greenhouse #candidate-location).
    type_value: what to type to trigger suggestions (e.g. "Columbia")
    pick_value: substring to match when picking an option (e.g. "Columbia, Missouri");
                defaults to type_value if not provided.
    Uses press_sequentially (character-by-character) to trigger React onChange events.
    Falls back to picking the first available suggestion if no exact match is found.
    """
    if not type_value:
        return False
    target = pick_value or type_value
    try:
        el = page.locator(selector)
        if el.count() == 0:
            return False
        el.first.click()
        page.wait_for_timeout(400)
        # Press sequentially so React sees each keystroke and fires onChange
        el.first.press_sequentially(type_value, delay=60)
        page.wait_for_timeout(1500)   # wait for async suggestions to load

        if _pick_option(page, target):
            logger.debug(f"Typeahead combobox '{field_name}' set to '{target}'")
            return True

        # No exact match — pick the first visible suggestion
        opts = page.get_by_role("option")
        if opts.count() > 0:
            opts.first.click()
            logger.debug(f"Typeahead combobox '{field_name}' picked first suggestion")
            return True

        logger.warning(f"Typeahead combobox '{field_name}': no suggestions for '{type_value}'")
    except Exception as e:
        logger.warning(f"Typeahead combobox '{field_name}' error: {e}")
    return False


def _check_consent_checkbox(page, label_texts: list, field_name: str = "") -> bool:
    """
    Tick a consent checkbox by finding its associated label text.
    Tries three approaches:
      1. get_by_label → check if it's a checkbox and click if unchecked
      2. Find label element → click the associated checkbox via 'for' attr or sibling
      3. Click the label itself (checks the checkbox via label click)
    Returns True if the checkbox was successfully checked.
    """
    for label in label_texts:
        # Strategy 1: get_by_label
        try:
            el = page.get_by_label(label, exact=False)
            if el.count() > 0:
                el_type = el.first.get_attribute("type") or ""
                if el_type == "checkbox":
                    if not el.first.is_checked():
                        el.first.click()
                    logger.debug(f"Checked checkbox '{field_name}' via label '{label}'")
                    return True
        except Exception:
            pass

        # Strategy 2: find <label> element, resolve the checkbox it controls
        try:
            lbl = page.locator("label").filter(has_text=label).first
            if lbl.count() > 0:
                for_id = lbl.get_attribute("for")
                if for_id:
                    cb = page.locator(f"#{for_id}")
                    if cb.count() > 0 and cb.first.get_attribute("type") == "checkbox":
                        if not cb.first.is_checked():
                            cb.first.click()
                        logger.debug(f"Checked checkbox '{field_name}' via for-id '{for_id}'")
                        return True

                # Strategy 3: click the label itself to toggle the checkbox
                lbl.click()
                page.wait_for_timeout(200)
                logger.debug(f"Clicked label '{label}' to check consent '{field_name}'")
                return True
        except Exception:
            pass

    logger.warning(f"Could not check consent checkbox '{field_name}'")
    return False


def _fill_combobox_by_label(
    page,
    label_texts: list,
    value: str,
    try_values: list = None,
    field_name: str = "",
) -> bool:
    """
    Find a Greenhouse combobox by label text (using all three label strategies),
    then select the matching option from the dropdown.
    """
    if not value:
        return False

    attempts = [value] + (try_values or [])

    for label in label_texts:
        el = _find_el_by_label(page, label)
        if el.count() == 0:
            continue

        for attempt in attempts:
            try:
                el.click()
                page.wait_for_timeout(600)

                if _pick_option(page, attempt):
                    logger.debug(f"Combobox '{field_name}' = '{attempt}' via label '{label}'")
                    return True

                try:
                    el.press("Escape")
                    page.wait_for_timeout(300)
                except Exception:
                    pass
            except Exception:
                pass

    logger.warning(f"Could not fill combobox '{field_name}' — no label/option match")
    return False


# ---------------------------------------------------------------------------
# Main handler
# ---------------------------------------------------------------------------

def apply(page, applicant: dict, cover_letter: str, mode: str, screenshot_dir: str) -> list:
    """
    Fill (and optionally submit) a Greenhouse job application.

    Args:
        page: Playwright page, already navigated to the application URL
        applicant: dict with applicant data (see browser_apply.py load_applicant())
        cover_letter: plain text of the cover letter (used as fallback if PDF not found)
        mode: "preview" (fill + screenshot only) or "submit" (fill + click submit)
        screenshot_dir: directory to save screenshots

    Returns:
        list of screenshot file paths
    """
    screenshots = []
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    print("[greenhouse] Waiting for page to load...")
    page.wait_for_load_state("networkidle", timeout=30000)

    # Screenshot: initial state
    s = f"{screenshot_dir}/greenhouse_{ts}_01_initial.png"
    page.screenshot(path=s, full_page=True)
    screenshots.append(s)
    print(f"[greenhouse] Screenshot: {s}")

    # -----------------------------------------------------------------------
    # 1. Standard contact fields (IDs are consistent across all Greenhouse forms)
    # -----------------------------------------------------------------------
    print("[greenhouse] Filling contact fields...")
    _safe_fill(page, "#first_name", applicant.get("first_name", ""), "first_name")
    _safe_fill(page, "#last_name",  applicant.get("last_name",  ""), "last_name")
    _safe_fill(page, "#email",      applicant.get("email",      ""), "email")
    _safe_fill(page, "#phone",      applicant.get("phone",      ""), "phone")

    # Country — combobox on most Greenhouse forms; fallback to plain fill
    if not _fill_combobox(page, "#country", "United States", "country"):
        _safe_fill(page, "#country", "United States", "country")

    # City/Location field — typeahead combobox: type city name to load suggestions,
    # then pick the option matching our specific city+state.
    _fill_typeahead_combobox(
        page,
        "#candidate-location",
        type_value=applicant.get("city_typeahead_type", "Columbia"),
        pick_value=applicant.get("city_typeahead_pick", "Columbia, Missouri"),
        field_name="candidate_location",
    )

    # -----------------------------------------------------------------------
    # 2. Resume upload
    # -----------------------------------------------------------------------
    resume_path = applicant.get("resume_path", "")
    print("[greenhouse] Uploading resume...")
    if not _safe_upload(page, "#resume", resume_path, "resume"):
        logger.warning("Falling back to first file input for resume")
        _safe_upload(page, "input[type='file']", resume_path, "resume_fallback")

    # -----------------------------------------------------------------------
    # 3. Cover letter — file upload (Greenhouse uses a file input, not textarea)
    # -----------------------------------------------------------------------
    cl_pdf_path = applicant.get("cover_letter_pdf_path", "")
    if cl_pdf_path and Path(cl_pdf_path).exists():
        print("[greenhouse] Uploading cover letter PDF...")
        _safe_upload(page, "#cover_letter", cl_pdf_path, "cover_letter")
    elif cover_letter:
        # Fallback: write text to a temp file and upload
        cl_tmp = Path(screenshot_dir).parent / "cover_letter_tmp.txt"
        cl_tmp.write_text(cover_letter, encoding="utf-8")
        print("[greenhouse] Uploading cover letter as text file (PDF not found)...")
        _safe_upload(page, "#cover_letter", str(cl_tmp), "cover_letter_text")
    else:
        logger.warning("No cover letter available to upload")

    # -----------------------------------------------------------------------
    # 4. Profile links — label-based (question IDs differ per company)
    # -----------------------------------------------------------------------
    print("[greenhouse] Filling profile links...")
    _fill_by_label(
        page,
        ["LinkedIn", "LinkedIn Profile", "LinkedIn URL", "LinkedIn profile"],
        applicant.get("linkedin", ""),
        "linkedin",
    )
    _fill_by_label(
        page,
        ["GitHub", "Github", "GitHub URL", "Github URL"],
        applicant.get("github", ""),
        "github",
    )
    _fill_by_label(
        page,
        ["Website", "Portfolio", "Personal Website", "Personal website", "Portfolio URL"],
        applicant.get("website", ""),
        "website",
    )
    _fill_by_label(
        page,
        ["Current Company", "Current company", "Company"],
        applicant.get("current_company", "Delivery Hero"),
        "current_company",
    )
    _fill_by_label(
        page,
        ["Current Position", "Current Title", "Current Job Title", "Current Position/Title", "Job Title"],
        applicant.get("current_title", "Senior Software Engineer"),
        "current_title",
    )

    # -----------------------------------------------------------------------
    # 5. Optional personal fields
    # -----------------------------------------------------------------------
    _fill_by_label(
        page,
        ["Preferred Name", "Preferred name", "Preferred First Name", "Preferred first name"],
        applicant.get("first_name", ""),
        "preferred_name",
    )
    _fill_combobox_by_label(
        page,
        ["Pronouns", "Your pronouns", "Preferred pronouns"],
        "He/him/his",
        try_values=["He/Him/His", "He/Him", "He/him"],
        field_name="pronouns",
    )
    # Name pronunciation — leave blank (skip by passing empty string)
    _fill_by_label(page, ["Name Pronunciation", "Name pronunciation"], "", "name_pronunciation")

    # -----------------------------------------------------------------------
    # 5b. Additional plain-text custom fields (company-specific labels)
    # -----------------------------------------------------------------------
    _fill_by_label(
        page,
        ["full legal name", "legal name", "What is your full legal name"],
        applicant.get("full_name", "Mubashir Ali"),
        "legal_name",
    )
    _fill_by_label(
        page,
        ["What City do you live in", "What city do you"],
        applicant.get("city_plain", "Columbia"),
        "city_plain",
    )
    _fill_by_label(
        page,
        ["What State do you live in", "What state do you"],
        "Missouri",
        "state_text",
    )
    _fill_by_label(
        page,
        [
            "expectations for pay",
            "pay expectations",
            "salary expectations",
            "expected salary",
            "compensation expectations",
        ],
        "$140,000 - $170,000",
        "pay_expectations",
    )
    _fill_by_label(
        page,
        ["referred to this position by a current", "referred by a current", "employee referral name"],
        "N/A",
        "referral",
    )
    _fill_by_label(
        page,
        ["Do you have any relatives", "relatives at", "family members at"],
        "N/A",
        "relatives",
    )
    _fill_by_label(
        page,
        [
            "describe your current work authorization",
            "current work authorization status",
            "work authorization status",
        ],
        "J-2 visa with EAD. Authorized to work in the United States. No sponsorship required.",
        "work_auth_description",
    )

    # -----------------------------------------------------------------------
    # 6. Work authorization — combobox, label-based
    # -----------------------------------------------------------------------
    print("[greenhouse] Filling work authorization...")
    _fill_combobox_by_label(
        page,
        [
            "legally authorized to work",
            "authorized to work in the United States",
            "authorized to work",
            "work authorization",
            "authorization",
        ],
        "Yes",
        field_name="work_authorized",
    )
    _fill_combobox_by_label(
        page,
        [
            "require visa sponsorship",
            "sponsorship",
            "visa sponsorship",
            "require sponsorship",
        ],
        "No",
        field_name="requires_sponsorship",
    )

    # -----------------------------------------------------------------------
    # 7. US State / Province — combobox, label-based
    # -----------------------------------------------------------------------
    _fill_combobox_by_label(
        page,
        ["US State", "State", "Province", "US State/Canadian Province", "State/Province"],
        "Missouri",
        field_name="state",
    )

    # -----------------------------------------------------------------------
    # 8. How did you hear about us — combobox, label-based; text fallback
    # -----------------------------------------------------------------------
    heard_combobox = _fill_combobox_by_label(
        page,
        [
            "learn about Affirm",   # "How did you first learn about Affirm as an employer?"
            "first learn",
            "How did you hear",
            "hear about",
            "How did you find",
        ],
        "LinkedIn",
        try_values=["Other"],
        field_name="how_did_you_hear",
    )
    if not heard_combobox:
        # Some forms use a plain text input instead of a combobox
        _fill_by_label(
            page,
            ["How did you hear", "hear about", "How did you find", "How did you learn about"],
            "LinkedIn",
            "how_did_you_hear_text",
        )

    # -----------------------------------------------------------------------
    # 9. Previously employed — combobox, label-based
    # -----------------------------------------------------------------------
    _fill_combobox_by_label(
        page,
        [
            "previously been employed",
            "previously employed at",
            "previously employed",
            "previously worked for",
            "Are you now or have you been employed",   # Marqeta variant
            "Have you previously worked for",           # Life360 variant
            "been employed by",
            "previously at",
        ],
        "No",
        try_values=["I have not previously been employed at Affirm", "No, I have not", "Never"],
        field_name="previously_employed",
    )

    # -----------------------------------------------------------------------
    # 9b. Consent / privacy / agreement fields — checkbox-first, combobox fallback
    # -----------------------------------------------------------------------
    # Greenhouse consent fields are rendered as EITHER:
    #   a) <input type="checkbox"> — must be clicked (not select_option'd)
    #   b) <select> combobox with options like "I Consent" / "Yes" / "I Agree"
    # We try the checkbox approach first, fall back to combobox if not found.
    CONSENT_FIELDS = [
        ("pre-employment screening",     "I Consent"),
        ("background check",             "I Consent"),
        ("confirm that you have read",   "Yes"),
        ("Job Applicant Privacy Policy", "Yes"),
        ("privacy notice",               "I Consent"),
        ("privacy statement",            "I Consent"),
        ("data privacy",                 "I Consent"),
        ("electronic consent",           "I Consent"),
        ("terms and conditions",         "I Agree"),
        ("acknowledge",                  "Yes"),
    ]
    for consent_label, consent_value in CONSENT_FIELDS:
        fname = f"consent:{consent_label[:30]}"
        # Try checkbox first
        checked = _check_consent_checkbox(page, [consent_label], field_name=fname)
        if not checked:
            # Fall back to combobox (select element with option values)
            _fill_combobox_by_label(
                page,
                [consent_label],
                consent_value,
                try_values=["Yes, I have read", "I Consent", "I Agree", "Agree", "Yes"],
                field_name=fname,
            )

    # -----------------------------------------------------------------------
    # 9c. Known company-specific question IDs — GHX screening questions
    # -----------------------------------------------------------------------
    # These question IDs are specific to GHX's Greenhouse form. We fill them
    # by attribute selector and pick the best option (C. or D. ratings, Yes/No,
    # or "I Consent"). Safe to run on all forms — the locator returns count==0
    # for non-GHX forms and the fill is skipped.
    GHX_COMBOBOX_ANSWERS = {
        "question_8373559005": "Yes",         # legally authorized to work in the US
        "question_8373560005": "No",          # require visa sponsorship
        "question_8373563005": "C.",          # Java/J2EE experience level
        "question_8373564005": "D.",          # design patterns experience
        "question_8373565005": "D.",          # performance/resiliency experience
        "question_8373566005": "D.",          # AWS architecture experience
        "question_8373567005": "D.",          # event-driven architecture experience
        "question_8373568005": "C.",          # AWS security experience
        "question_8373569005": "D.",          # database experience
        "question_8373570005": "D.",          # technical design / architecture
        "question_8373571005": "D.",          # cross-functional / global team experience
        "question_8373573005": "No",          # previously worked for GHX?
        "question_8373574005": "No",          # are you a GHX customer?
        "question_8373579005": "I Consent",   # pre-employment screening consent
        "question_8373580005": "I Consent",   # privacy policy consent
        "question_8373581005": "I Consent",   # additional consent field
    }
    for qid, answer in GHX_COMBOBOX_ANSWERS.items():
        sel = f"[id='{qid}']"
        if page.locator(sel).count() > 0:
            _fill_combobox(page, sel, answer, f"ghx:{qid}")

    # Life360: existing employee question — options: Tile/Life360/Jiobit/Not an Existing Employee
    _fill_combobox_by_label(
        page,
        [
            "Are you an existing employee at Life360",
            "existing employee at Life360",
            "existing employee at",
        ],
        "Not an Existing Employee",
        try_values=["No", "N/A"],
        field_name="life360_existing_employee",
    )

    # -----------------------------------------------------------------------
    # 10. EEO fields
    # -----------------------------------------------------------------------
    print("[greenhouse] Filling EEO fields...")

    # Standard Greenhouse EEO dropdowns (consistent IDs across forms)
    _fill_combobox(page, "#gender",             "Male",                         "gender_eeo")
    _fill_combobox(page, "#hispanic_ethnicity", "No",                           "hispanic_ethnicity")
    _fill_combobox(page, "#veteran_status",     "I am not a protected veteran", "veteran_status")
    _fill_combobox(page, "#disability_status",  "I do not want to answer",      "disability_status")

    # Custom EEO comboboxes — IDs starting with digits need attribute selector (not #NNN)
    _fill_combobox_by_label(
        page,
        ["gender identity", "How do you identify? (gender"],
        "Man",
        try_values=["Male", "Decline to self identify", "Decline"],
        field_name="gender_identity_custom",
    )
    _fill_combobox_by_label(
        page,
        ["race/ethnicity", "How do you identify? (race"],
        "Asian (not Hispanic or Latino)",
        try_values=["Asian", "Decline to self identify", "Decline"],
        field_name="race_ethnicity_custom",
    )

    # -----------------------------------------------------------------------
    # Security code (some Greenhouse forms have an anti-spam code field)
    # -----------------------------------------------------------------------
    security_code = applicant.get("security_code", "")
    if security_code:
        print(f"[greenhouse] Filling security code ({len(security_code)} chars)...")
        for i, char in enumerate(security_code):
            inp = page.locator(f"#security-input-{i}")
            if inp.count() > 0:
                inp.first.fill(char)
        logger.debug(f"Security code filled: {len(security_code)} characters")

    # -----------------------------------------------------------------------
    # 11. Sweep: tick any remaining unchecked checkboxes (native + custom)
    # -----------------------------------------------------------------------
    # Greenhouse consent fields appear in two forms:
    #   a) Native:  <input type="checkbox"> — use :not(:checked) selector
    #   b) Custom:  <div role="checkbox" aria-checked="false"> — click to toggle
    # We sweep both. This catches privacy policy, background check, etc.
    # regardless of exact label wording.
    try:
        # Native checkboxes
        unchecked = page.locator("input[type='checkbox']:not(:checked)")
        count = unchecked.count()
        if count > 0:
            print(f"[greenhouse] Ticking {count} native unchecked checkbox(es)...")
            for i in range(count):
                try:
                    cb = unchecked.nth(i)
                    cb.scroll_into_view_if_needed()
                    cb.click()
                    page.wait_for_timeout(150)
                except Exception:
                    pass
    except Exception as e:
        logger.warning(f"Native checkbox sweep error: {e}")

    try:
        # Custom ARIA checkboxes (role="checkbox" with aria-checked="false")
        custom_unchecked = page.locator("[role='checkbox'][aria-checked='false']")
        count = custom_unchecked.count()
        if count > 0:
            print(f"[greenhouse] Ticking {count} custom (ARIA) unchecked checkbox(es)...")
            for i in range(count):
                try:
                    cb = custom_unchecked.nth(i)
                    cb.scroll_into_view_if_needed()
                    cb.click()
                    page.wait_for_timeout(150)
                except Exception:
                    pass
    except Exception as e:
        logger.warning(f"Custom checkbox sweep error: {e}")

    # -----------------------------------------------------------------------
    # Screenshot: after filling
    # -----------------------------------------------------------------------
    page.wait_for_timeout(1000)
    s = f"{screenshot_dir}/greenhouse_{ts}_02_filled.png"
    page.screenshot(path=s, full_page=True)
    screenshots.append(s)
    print(f"[greenhouse] Screenshot: {s}")

    # -----------------------------------------------------------------------
    # Submit (submit mode only)
    # -----------------------------------------------------------------------
    if mode == "submit":
        print("[greenhouse] Submitting application...")
        try:
            submit_btn = page.get_by_role("button", name="Submit", exact=False)
            if submit_btn.count() == 0:
                submit_btn = page.get_by_role("button", name="Apply", exact=False)

            if submit_btn.count() == 0:
                logger.warning("Submit button not found — could not submit")
                s = f"{screenshot_dir}/greenhouse_{ts}_03_submit_failed.png"
                page.screenshot(path=s, full_page=True)
                screenshots.append(s)
            else:
                # Record time just before clicking submit so Gmail filter is accurate
                submit_ts = int(time.time())
                submit_btn.first.click()

                # Wait for modal OR page navigation
                page.wait_for_timeout(5000)

                # Detect email-verification modal by the specific Greenhouse input IDs.
                # Only match #security-input-0 — the narrow selector avoids false positives
                # from regular form fields whose names/placeholders contain "code".
                modal_input = page.locator("#security-input-0")

                if modal_input.count() > 0:
                    modal_input.first.scroll_into_view_if_needed()
                    print("[greenhouse] Email verification code modal detected.")
                    s = f"{screenshot_dir}/greenhouse_{ts}_03_code_prompt.png"
                    page.screenshot(path=s, full_page=True)
                    screenshots.append(s)
                    print(f"[greenhouse] Screenshot: {s}")

                    # Fetch the code from Gmail
                    code = None
                    try:
                        from modules.tracker.gmail import fetch_security_code
                        print("[greenhouse] Fetching security code from Gmail...")
                        code = fetch_security_code(
                            sender_filter="greenhouse",
                            after_epoch=submit_ts - 600,  # 10-min lookback covers prior attempts
                            wait_seconds=90,
                        )
                    except Exception as gmail_err:
                        logger.error(f"Gmail fetch failed: {gmail_err}")

                    # Fallback: use --security-code value passed via CLI
                    if not code:
                        code = applicant.get("security_code", "") or None
                        if code:
                            print(f"[greenhouse] Using --security-code fallback: {code}")

                    if code:
                        print(f"[greenhouse] Security code retrieved: {code}")
                        for i, char in enumerate(code):
                            inp = page.locator(f"#security-input-{i}")
                            if inp.count() > 0:
                                inp.first.scroll_into_view_if_needed()
                                inp.first.fill(char)
                                page.wait_for_timeout(80)

                        page.wait_for_timeout(800)

                        # Screenshot after code is entered (helps debug)
                        s = f"{screenshot_dir}/greenhouse_{ts}_03_code_filled.png"
                        page.screenshot(path=s, full_page=True)
                        screenshots.append(s)

                        # Confirm: look for button inside the modal dialog first,
                        # then fall back to the named button list.
                        confirmed = False
                        dialog = page.locator("[role='dialog']")
                        if dialog.count() > 0:
                            dialog_btn = dialog.first.get_by_role("button")
                            if dialog_btn.count() > 0:
                                dialog_btn.last.click()
                                confirmed = True
                                print("[greenhouse] Clicked modal confirm button.")

                        if not confirmed:
                            for btn_name in ("Submit Application", "Submit", "Confirm", "Verify", "Apply"):
                                confirm_btn = page.get_by_role("button", name=btn_name, exact=False)
                                if confirm_btn.count() > 0:
                                    confirm_btn.last.click()
                                    confirmed = True
                                    print(f"[greenhouse] Clicked '{btn_name}' button.")
                                    break

                        if not confirmed:
                            page.keyboard.press("Enter")
                            print("[greenhouse] Pressed Enter to confirm code.")

                        page.wait_for_load_state("networkidle", timeout=30000)
                    else:
                        logger.warning(
                            "Could not retrieve security code from Gmail — "
                            "manual entry required."
                        )

                else:
                    # No security code modal — page either submitted cleanly or has validation errors
                    page.wait_for_load_state("networkidle", timeout=30000)

                s = f"{screenshot_dir}/greenhouse_{ts}_03_submitted.png"
                page.screenshot(path=s, full_page=True)
                screenshots.append(s)
                print(f"[greenhouse] Submitted! Screenshot: {s}")

        except Exception as e:
            logger.error(f"Submission error: {e}")
            s = f"{screenshot_dir}/greenhouse_{ts}_03_error.png"
            page.screenshot(path=s, full_page=True)
            screenshots.append(s)
    else:
        print("[greenhouse] Preview mode — form filled but not submitted.")

    return screenshots
