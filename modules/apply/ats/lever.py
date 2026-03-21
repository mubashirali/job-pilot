"""
Lever ATS handler.

Fills standard Lever application form fields.

Supported fields:
  - Full Name, Email, Phone, Current Company
  - Resume file upload
  - Cover letter textarea (if present)
  - LinkedIn, GitHub, Portfolio URL fields
  - Custom textarea questions (matched by keyword)

Usage:
    Invoked by browser_apply.py when the URL matches lever.co.
"""

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
    print(f"[lever] Screenshot: {path}")
    return path


def _fill(page, selector: str, value: str, label: str = "") -> bool:
    """Fill a field by CSS selector. Returns True on success."""
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
        logger.warning(f"Could not fill '{label}': {e}")
    return False


def _fill_by_label(page, label_texts: list[str], value: str, label: str = "") -> bool:
    """Fill a field by matching one of several label strings."""
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


def _fill_textarea(page, label_keyword: str, value: str) -> bool:
    """Find a textarea whose associated label contains label_keyword and fill it."""
    if not value:
        return False
    try:
        labels = page.locator("label").all()
        for lbl_el in labels:
            if label_keyword.lower() in (lbl_el.inner_text() or "").lower():
                lbl_for = lbl_el.get_attribute("for") or ""
                if lbl_for:
                    ta = page.locator(f"textarea#{lbl_for}, #{lbl_for}")
                    if ta.count() > 0:
                        ta.first.scroll_into_view_if_needed()
                        ta.first.triple_click()
                        ta.first.fill(value)
                        logger.debug(f"Filled textarea for '{label_keyword}'")
                        return True
    except Exception as e:
        logger.warning(f"Could not fill textarea '{label_keyword}': {e}")
    return False


# ---------------------------------------------------------------------------
# Main apply function
# ---------------------------------------------------------------------------

def apply(page, applicant: dict, cover_letter: str, mode: str, screenshot_dir: str) -> list[str]:
    """
    Fill and optionally submit a Lever application form.

    Args:
        page:           Playwright page, already navigated to the apply URL.
        applicant:      Dict from load_applicant() in browser_apply.py.
        cover_letter:   Full text of the cover letter.
        mode:           "preview" or "submit".
        screenshot_dir: Path to screenshots directory.

    Returns:
        List of screenshot file paths taken.
    """
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    screenshots: list[str] = []

    print("[lever] Waiting for form to load ...")
    page.wait_for_load_state("networkidle", timeout=30000)
    page.wait_for_timeout(1500)

    # --- Screenshot: initial state ---
    screenshots.append(_ss(page, f"{screenshot_dir}/lever_{ts}_01_loaded.png"))

    # --- Full Name ---
    _fill_by_label(page, ["Full name", "Name"], applicant.get("full_name", ""), "Full Name")

    # --- Email ---
    _fill_by_label(page, ["Email", "Email address"], applicant.get("email", ""), "Email")

    # --- Phone ---
    _fill_by_label(page, ["Phone", "Phone number"], applicant.get("phone", ""), "Phone")

    # --- Current Company (optional field, not always present) ---
    _fill_by_label(
        page,
        ["Current company", "Company", "Organization"],
        applicant.get("current_company", ""),
        "Current Company",
    )

    # --- Social / portfolio links ---
    _fill_by_label(
        page,
        ["LinkedIn", "LinkedIn URL", "LinkedIn profile"],
        applicant.get("linkedin", ""),
        "LinkedIn",
    )
    _fill_by_label(page, ["GitHub", "GitHub URL"], applicant.get("github", ""), "GitHub")
    _fill_by_label(
        page,
        ["Portfolio", "Website", "Personal website"],
        applicant.get("website", ""),
        "Portfolio",
    )

    # --- Resume upload ---
    resume_path = applicant.get("resume_path", "")
    if resume_path and Path(resume_path).exists():
        try:
            file_input = page.locator("input[type=file]").first
            if file_input.count() > 0:
                file_input.set_input_files(resume_path)
                page.wait_for_timeout(1500)
                print(f"[lever] Uploaded resume: {resume_path}")
            else:
                logger.warning("No file input found for resume")
        except Exception as e:
            logger.warning(f"Resume upload failed: {e}")
    else:
        logger.warning(f"Resume not found at: {resume_path}")

    # --- Cover letter (textarea, if present) ---
    _fill_textarea(page, "cover letter", cover_letter)

    # --- Additional info textarea (common in Lever forms) ---
    for keyword in ["additional information", "anything else", "why"]:
        if _fill_textarea(page, keyword, cover_letter):
            break  # Only fill the first matching textarea

    # --- Screenshot: after filling ---
    screenshots.append(_ss(page, f"{screenshot_dir}/lever_{ts}_02_filled.png"))

    if mode == "preview":
        print("[lever] PREVIEW mode — form filled. Not submitting.")
        return screenshots

    # --- Submit ---
    print("[lever] Submitting application ...")
    try:
        submit_btn = page.locator("button[type=submit], input[type=submit]").last
        submit_btn.scroll_into_view_if_needed()
        submit_btn.click()
        page.wait_for_load_state("networkidle", timeout=30000)
        page.wait_for_timeout(2000)
        print("[lever] Submit clicked.")
    except Exception as e:
        logger.error(f"Submit failed: {e}")
        screenshots.append(_ss(page, f"{screenshot_dir}/lever_{ts}_ERROR_submit.png"))
        return screenshots

    # --- Screenshot: confirmation ---
    screenshots.append(_ss(page, f"{screenshot_dir}/lever_{ts}_03_submitted.png"))
    print("[lever] Application submitted.")
    return screenshots
