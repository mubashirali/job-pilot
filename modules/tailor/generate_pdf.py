"""
generate_pdf.py — Generate tailored PDF documents for job applications.

Produces two outputs per job:
  1. Cover letter PDF  — from a tailored .md file
  2. Resume PDF        — from data/resume.md, with an optional custom summary

Usage:
    # Both documents
    python modules/tailor/generate_pdf.py \\
        --cover-letter ".tmp/cover_letter_Affirm_Backend_2026-03-04.md" \\
        --company "Affirm" \\
        --position "Senior Software Engineer, Backend" \\
        --summary "Results-driven backend engineer with deep payments expertise..."

    # Cover letter only
    python modules/tailor/generate_pdf.py \\
        --cover-letter ".tmp/cover_letter_Affirm_Backend_2026-03-04.md" \\
        --company "Affirm" \\
        --position "Senior Software Engineer, Backend" \\
        --no-resume

Outputs (saved to .tmp/):
    .tmp/cover_letter_<Company>_<Position>_<Date>.pdf
    .tmp/resume_<Company>_<Position>_<Date>.pdf
"""

import argparse
import re
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent  # modules/tailor/ → modules/ → ClaudeAgent/
sys.path.insert(0, str(ROOT))

RESUME_SOURCE = ROOT / "data" / "resume.md"
OUTPUT_DIR = ROOT / ".tmp"

# ---------------------------------------------------------------------------
# Layout constants
# ---------------------------------------------------------------------------
NAVY = (31, 56, 100)
DARK_GRAY = (60, 60, 60)
MID_GRAY = (100, 100, 100)
LIGHT_GRAY = (220, 220, 220)
BLACK = (0, 0, 0)

MARGIN = 18
LINE_H = 5
BULLET_INDENT = 5


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_fpdf():
    try:
        from fpdf import FPDF
        return FPDF
    except ImportError:
        print("[generate_pdf] ERROR: fpdf2 not installed. Run: .venv/bin/pip install fpdf2")
        sys.exit(1)


def _slug(text: str) -> str:
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"\s+", "_", text.strip())
    return text[:40]


# Characters outside Latin-1 that fpdf2 core fonts can't handle.
_UNICODE_MAP = str.maketrans({
    "\u2013": "-",    # en-dash
    "\u2014": "-",    # em-dash
    "\u2022": "-",    # bullet
    "\u2019": "'",    # right single quote
    "\u2018": "'",    # left single quote
    "\u201c": '"',    # left double quote
    "\u201d": '"',    # right double quote
    "\u2026": "...",  # ellipsis
    "\u00a0": " ",    # non-breaking space
    "\u2012": "-",    # figure dash
    "\u2015": "-",    # horizontal bar
})


def _s(text: str) -> str:
    """Sanitize text to Latin-1 safe for fpdf2 core fonts."""
    return text.translate(_UNICODE_MAP)


def _strip_md_inline(text: str) -> str:
    """Remove inline markdown formatting."""
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"\*(.+?)\*", r"\1", text)
    text = re.sub(r"`(.+?)`", r"\1", text)
    text = re.sub(r"\[(.+?)\]\(.+?\)", r"\1", text)
    return text


def _strip_html_comments(text: str) -> str:
    return re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)


# ---------------------------------------------------------------------------
# Resume .md parser
# ---------------------------------------------------------------------------

class ResumeSection:
    def __init__(self, title: str):
        self.title = title
        self.items: list = []


def parse_resume_md(path: Path, override_summary: str | None = None) -> list[ResumeSection]:
    """
    Parse data/resume.md into ResumeSection objects.

    Item tuples:
        ("body",  text)
        ("job",   text)          — ### subsection (job entry header)
        ("bullet", text)
        ("skill",  label, value) — **Label:** value
    """
    raw = _strip_html_comments(path.read_text(encoding="utf-8"))

    sections: list[ResumeSection] = []
    current: ResumeSection | None = None
    in_summary = False

    for line in raw.splitlines():
        s = line.strip()
        if not s:
            continue

        if s.startswith("## "):
            title = s[3:].strip()
            current = ResumeSection(title)
            sections.append(current)
            in_summary = title.lower() == "professional summary"
            continue

        if s.startswith("# "):      # top-level heading — skip
            continue

        if s.startswith("### "):
            if current is not None:
                current.items.append(("job", s[4:].strip()))
            continue

        if s.startswith("- ") or s.startswith("* "):
            body = s[2:].strip()
            skill_m = re.match(r"\*\*(.+?):\*\*\s*(.*)", body)
            if skill_m and current is not None:
                current.items.append(("skill", skill_m.group(1), skill_m.group(2).strip()))
            elif current is not None:
                current.items.append(("bullet", _strip_md_inline(body)))
            continue

        # plain body text
        if current is not None:
            if in_summary and override_summary:
                continue   # will be replaced below
            current.items.append(("body", _strip_md_inline(s)))

    if override_summary:
        for sec in sections:
            if sec.title.lower() == "professional summary":
                sec.items = [("body", override_summary)]
                break

    return sections


# ---------------------------------------------------------------------------
# Cover letter .md parser
# ---------------------------------------------------------------------------

def parse_cover_letter_md(path: Path) -> list[str]:
    """Return list of plain-text paragraphs from a cover letter .md file."""
    raw = Path(path).read_text(encoding="utf-8")
    raw = re.sub(r"^---\s*\n.*?\n---\s*\n", "", raw, flags=re.DOTALL)

    paragraphs: list[str] = []
    buf: list[str] = []

    for line in raw.splitlines():
        s = line.strip()
        if s.startswith("#"):
            continue
        if s == "":
            if buf:
                paragraphs.append(" ".join(buf))
                buf = []
        else:
            buf.append(_strip_md_inline(s))

    if buf:
        paragraphs.append(" ".join(buf))

    return [p for p in paragraphs if p]


# ---------------------------------------------------------------------------
# PDF builder — Cover Letter
# ---------------------------------------------------------------------------

def build_cover_letter_pdf(paragraphs: list[str], output_path: Path) -> None:
    FPDF = _get_fpdf()

    pdf = FPDF(orientation="P", unit="mm", format="A4")
    pdf.set_margins(MARGIN, 20, MARGIN)
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.add_page()
    pw = pdf.w - 2 * MARGIN

    # Name
    pdf.set_font("Helvetica", "B", 20)
    pdf.set_text_color(*NAVY)
    pdf.cell(pw, 9, "Mubashir Ali", ln=True)

    # Contact
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(*MID_GRAY)
    pdf.cell(
        pw, 5,
        "mubashir.ali.memon@gmail.com  |  +1 (573) 435-2970  |  "
        "linkedin.com/in/mubashir-ali992  |  mubashir-ali.netlify.app",
        ln=True,
    )

    # Separator
    pdf.set_draw_color(*NAVY)
    pdf.set_line_width(0.5)
    pdf.line(MARGIN, pdf.get_y() + 2, pdf.w - MARGIN, pdf.get_y() + 2)
    pdf.ln(6)

    # Date
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(*DARK_GRAY)
    pdf.cell(pw, LINE_H, datetime.now().strftime("%B %d, %Y"), ln=True)
    pdf.ln(4)

    # Body
    pdf.set_font("Helvetica", "", 10.5)
    pdf.set_text_color(*BLACK)

    for para in paragraphs:
        text = _s(para)
        if text.strip().lower().startswith("sincerely"):
            pdf.ln(4)
            pdf.multi_cell(pw, LINE_H + 1, text, align="L")
        else:
            pdf.multi_cell(pw, LINE_H + 1, text, align="J")
            pdf.ln(3)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    pdf.output(str(output_path))
    print(f"[generate_pdf] Cover letter PDF: {output_path}")


# ---------------------------------------------------------------------------
# PDF builder — Resume
# ---------------------------------------------------------------------------

def build_resume_pdf(sections: list[ResumeSection], output_path: Path,
                     override_location: str = None, override_phone: str = None) -> None:
    FPDF = _get_fpdf()

    pdf = FPDF(orientation="P", unit="mm", format="A4")
    pdf.set_margins(MARGIN, 15, MARGIN)
    pdf.set_auto_page_break(auto=True, margin=14)
    pdf.add_page()
    pw = pdf.w - 2 * MARGIN   # 174mm usable width

    # ------------------------------------------------------------------
    # Helper: print a bullet with proper hanging indent.
    # Continuation lines align with the text start, not the "-" marker.
    # ------------------------------------------------------------------
    def bullet(text: str, font_size: float = 9.2) -> None:
        pdf.set_font("Helvetica", "", font_size)
        pdf.set_x(MARGIN)
        pdf.cell(BULLET_INDENT, LINE_H, "-", ln=False)
        # Temporarily push left margin to indent position so multi_cell
        # continuation lines align with line 1 of the text, not the "-".
        pdf.set_left_margin(MARGIN + BULLET_INDENT)
        pdf.set_x(MARGIN + BULLET_INDENT)
        pdf.multi_cell(pw - BULLET_INDENT, LINE_H, text)
        pdf.set_left_margin(MARGIN)
        pdf.set_x(MARGIN)

    # ------------------------------------------------------------------
    # Helper: two-cell row — bold title left, gray info right.
    # Uses cell() for both so there is no wrapping misalignment.
    # ------------------------------------------------------------------
    def job_header(title: str, info: str) -> None:
        left_w  = pw * 0.54
        right_w = pw * 0.46
        pdf.set_font("Helvetica", "B", 9.8)
        pdf.set_text_color(*DARK_GRAY)
        pdf.set_x(MARGIN)
        pdf.cell(left_w, LINE_H + 1, title, ln=False)
        pdf.set_font("Helvetica", "", 8.8)
        pdf.set_text_color(*MID_GRAY)
        pdf.cell(right_w, LINE_H + 1, info, ln=True, align="R")
        pdf.set_text_color(*DARK_GRAY)
        pdf.set_x(MARGIN)

    # ------------------------------------------------------------------
    # Helper: skill row — bold label left, regular value right (with
    # proper indented continuation when the value wraps).
    # ------------------------------------------------------------------
    def skill_row(label: str, value: str) -> None:
        pdf.set_font("Helvetica", "B", 9.3)
        pdf.set_text_color(*DARK_GRAY)
        pdf.set_x(MARGIN)
        lw = pdf.get_string_width(label + ":  ") + 0.5
        pdf.cell(lw, LINE_H, label + ":", ln=False)
        pdf.set_font("Helvetica", "", 9.3)
        pdf.set_left_margin(MARGIN + lw)
        pdf.set_x(MARGIN + lw)
        pdf.multi_cell(pw - lw, LINE_H, " " + value)
        pdf.set_left_margin(MARGIN)
        pdf.set_x(MARGIN)

    # ------------------------------------------------------------------
    # Helper: section header bar
    # ------------------------------------------------------------------
    def section_header(title: str) -> None:
        pdf.set_font("Helvetica", "B", 10)
        pdf.set_text_color(*NAVY)
        pdf.set_fill_color(*LIGHT_GRAY)
        pdf.set_x(MARGIN)
        pdf.cell(pw, 5.5, _s(title.upper()), ln=True, fill=True)
        pdf.ln(0.5)
        pdf.set_text_color(*DARK_GRAY)
        pdf.set_x(MARGIN)

    # ==================== HEADER ====================
    # Build contact map
    contact_map: dict[str, str] = {}
    contact_sec = next((s for s in sections if s.title.lower() == "contact"), None)
    if contact_sec:
        for item in contact_sec.items:
            if item[0] == "bullet" and ":" in item[1]:
                k, v = item[1].split(":", 1)
                contact_map[k.strip().lower()] = v.strip()

    email     = _s(contact_map.get("email",     ""))
    phone     = _s(override_phone or contact_map.get("phone",     ""))
    linkedin  = _s(contact_map.get("linkedin",  "").replace("https://", ""))
    github    = _s(contact_map.get("github",    "").replace("https://", ""))
    portfolio = _s(contact_map.get("portfolio", "").replace("https://", ""))
    location  = _s(override_location or contact_map.get("location",  ""))

    pdf.set_font("Helvetica", "B", 21)
    pdf.set_text_color(*NAVY)
    pdf.cell(pw, 9, "MUBASHIR ALI", ln=True, align="C")

    pdf.set_font("Helvetica", "", 8.5)
    pdf.set_text_color(*MID_GRAY)
    pdf.cell(pw, 4, "  |  ".join(filter(None, [email, phone, location])), ln=True, align="C")
    pdf.cell(pw, 4, "  |  ".join(filter(None, [linkedin, github, portfolio])), ln=True, align="C")

    pdf.set_draw_color(*NAVY)
    pdf.set_line_width(0.5)
    pdf.line(MARGIN, pdf.get_y() + 1.5, pdf.w - MARGIN, pdf.get_y() + 1.5)
    pdf.ln(4)

    # ==================== SECTIONS ====================
    SKIP = {"contact"}

    for sec in sections:
        if sec.title.lower() in SKIP or not sec.items:
            continue

        section_header(sec.title)

        # --- Professional Summary (and other generic) ---
        if sec.title.lower() == "professional summary":
            pdf.set_font("Helvetica", "", 9.5)
            pdf.set_text_color(*DARK_GRAY)
            for item in sec.items:
                if item[0] in ("body", "bullet"):
                    pdf.set_x(MARGIN)
                    pdf.multi_cell(pw, LINE_H, _s(item[1]), align="J")
            pdf.ln(2)

        # --- Technical Skills ---
        elif sec.title.lower() == "technical skills":
            for item in sec.items:
                if item[0] == "skill":
                    skill_row(_s(item[1]), _s(item[2]))
                elif item[0] == "bullet":
                    bullet(_s(item[1]))
            pdf.ln(2)

        # --- Work Experience ---
        elif sec.title.lower() == "work experience":
            first_job = True
            for item in sec.items:
                if item[0] == "job":
                    if not first_job:
                        pdf.ln(1.5)
                    first_job = False
                    parts = [_s(p.strip()) for p in item[1].split("|")]
                    title_str = parts[0]
                    info_str  = "  |  ".join(parts[1:]) if len(parts) > 1 else ""
                    job_header(title_str, info_str)

                elif item[0] == "bullet":
                    bullet(_s(item[1]))

                elif item[0] == "body":
                    pdf.set_font("Helvetica", "", 9.2)
                    pdf.set_x(MARGIN)
                    pdf.multi_cell(pw, LINE_H, _s(item[1]))
            pdf.ln(2)

        # --- Education ---
        elif sec.title.lower() == "education":
            for item in sec.items:
                if item[0] == "job":
                    parts = [_s(p.strip()) for p in item[1].split("|")]
                    pdf.set_font("Helvetica", "B", 9.5)
                    pdf.set_text_color(*DARK_GRAY)
                    pdf.set_x(MARGIN)
                    pdf.cell(pw, LINE_H, parts[0], ln=True)
                    if len(parts) > 1:
                        pdf.set_font("Helvetica", "", 9)
                        pdf.set_text_color(*MID_GRAY)
                        pdf.set_x(MARGIN)
                        pdf.cell(pw, LINE_H, "  |  ".join(parts[1:]), ln=True)
                elif item[0] == "body":
                    pdf.set_font("Helvetica", "", 9.2)
                    pdf.set_text_color(*MID_GRAY)
                    pdf.set_x(MARGIN)
                    pdf.cell(pw, LINE_H, _s(item[1]), ln=True)
            pdf.set_text_color(*DARK_GRAY)
            pdf.ln(2)

        # --- Certifications ---
        elif sec.title.lower() == "certifications":
            pdf.set_text_color(*DARK_GRAY)
            for item in sec.items:
                if item[0] == "bullet":
                    bullet(_s(item[1]), font_size=9.3)
                elif item[0] == "body":
                    pdf.set_font("Helvetica", "", 9.3)
                    pdf.set_x(MARGIN)
                    pdf.multi_cell(pw, LINE_H, _s(item[1]))
            pdf.ln(2)

        # --- Languages ---
        elif sec.title.lower() == "languages":
            pdf.set_font("Helvetica", "", 9.3)
            pdf.set_text_color(*DARK_GRAY)
            langs = [_s(item[1]) for item in sec.items if item[0] in ("bullet", "body")]
            if langs:
                pdf.set_x(MARGIN)
                pdf.cell(pw, LINE_H, "  |  ".join(langs), ln=True)
            pdf.ln(2)

        # --- Fallback ---
        else:
            pdf.set_font("Helvetica", "", 9.5)
            pdf.set_text_color(*DARK_GRAY)
            for item in sec.items:
                if item[0] in ("body", "bullet"):
                    pdf.set_x(MARGIN)
                    pdf.multi_cell(pw, LINE_H + 1, _s(item[1]), align="J")
                    pdf.ln(0.5)
            pdf.ln(2)

    # ==================== PAGE-COUNT GUARD ====================
    page_count = pdf.page
    if page_count > 2:
        print(f"[generate_pdf] ERROR: Resume is {page_count} pages — maximum is 2.")
        print("[generate_pdf] Shorten bullet points in data/resume.md and regenerate.")
        sys.exit(1)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    pdf.output(str(output_path))
    print(f"[generate_pdf] Resume PDF ({page_count}p): {output_path}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Generate tailored cover letter and resume PDFs")
    parser.add_argument("--cover-letter", required=True, help="Path to .md cover letter file")
    parser.add_argument("--company",      required=True, help="Company name (used in filenames)")
    parser.add_argument("--position",     required=True, help="Job position title (used in filenames)")
    parser.add_argument(
        "--summary", default=None,
        help="Custom professional summary for this job (overrides default in resume.md)",
    )
    parser.add_argument(
        "--no-resume", action="store_true",
        help="Skip resume PDF — only generate cover letter PDF",
    )
    parser.add_argument(
        "--location", default=None,
        help="Override location shown in resume header (e.g. 'Berlin, Germany' for EU roles)",
    )
    parser.add_argument(
        "--phone", default=None,
        help="Override phone number shown in resume header (e.g. EU phone for EU roles)",
    )
    args = parser.parse_args()

    date_str     = datetime.now().strftime("%Y-%m-%d")
    base         = f"{_slug(args.company)}_{_slug(args.position)}_{date_str}"

    # Cover letter
    paragraphs = parse_cover_letter_md(args.cover_letter)
    build_cover_letter_pdf(paragraphs, OUTPUT_DIR / f"cover_letter_{base}.pdf")

    # Resume
    if not args.no_resume:
        if not RESUME_SOURCE.exists():
            print(f"[generate_pdf] ERROR: {RESUME_SOURCE} not found. Create data/resume.md first.")
            sys.exit(1)
        sections = parse_resume_md(RESUME_SOURCE, override_summary=args.summary)
        build_resume_pdf(
            sections,
            OUTPUT_DIR / f"resume_{base}.pdf",
            override_location=args.location,
            override_phone=args.phone,
        )

    print("\n[generate_pdf] Done. Files saved to .tmp/")


if __name__ == "__main__":
    main()
