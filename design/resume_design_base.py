"""
RESUME DESIGN BASE — Warm Architect Style
==========================================
This file is the canonical design template for all future resume variants.
It contains ZERO content. Import this and pass your data module to `build()`.

USAGE:
    from resume_design_base import build
    import resume_data_tpm_aiml as data
    build(data, output_path="Styled Resumes/MyResume.pdf")

WHAT TO PASS IN YOUR DATA MODULE:
    NAME        str
    EMAIL       str
    PHONE       str
    LOCATION    str
    LINKEDIN    str   (without https://)
    GITHUB      str   (without https://)
    SUMMARY     str   (HTML, bold via <b> tags)
    EXPERIENCE  list of dicts:
                  { title, company, location, dates, bullets: [str, ...] }
    EDUCATION   list of dicts:
                  { degree, school, dates, detail }
    SKILLS      dict  { "Category Name": "Comma, separated, values" }
    PROJECTS    list of str (HTML)
    CERTS       list of str (plain text)
    PHOTO       str   (absolute path to photo jpg, or None to skip photo)
"""

import pathlib
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm, inch
from reportlab.lib.colors import HexColor
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_JUSTIFY
from reportlab.platypus import Paragraph
from reportlab.pdfgen import canvas as rl_canvas

W, H = A4

# ═══════════════════════════════════════════════════════════════
#  COLOUR PALETTE
# ═══════════════════════════════════════════════════════════════

TERRA       = "#C75B39"   # accent — name, section headers, links, pills text
NEAR_BLACK  = "#1C1C1C"   # primary body text
DARK_GREY   = "#555555"   # secondary text (contact, job meta)
MID_GREY    = "#777777"   # tertiary text (dates)
DETAIL_GREY = "#444444"   # education detail text
WARM_BG     = "#F2ECE6"   # skill pill background fill
BORDER_GREY = "#DDDDDD"   # photo border

# ═══════════════════════════════════════════════════════════════
#  LAYOUT CONSTANTS
# ═══════════════════════════════════════════════════════════════

MX          = 16 * mm     # left/right margin
MW          = W - 2 * MX  # usable content width
BOTTOM_MARGIN = 16 * mm   # minimum y before page break
PAGE2_TOP   = H - 16 * mm # y start on continuation pages

PHOTO_SIZE  = 1.1 * inch  # square photo dimension
PHOTO_RADIUS = 5           # corner radius in points
PHOTO_X     = MX
PHOTO_Y_TOP = H - 14 * mm  # photo top-left y (from page top)

DATE_COL_W  = 90           # reserved width for right-aligned dates
COL_GAP     = 10           # gap between two-column sections
COL_W       = (MW - COL_GAP) / 2  # each column width in two-col layout

# ═══════════════════════════════════════════════════════════════
#  TYPOGRAPHY
# ═══════════════════════════════════════════════════════════════
#  All fonts are Helvetica family (ATS-safe, no custom fonts needed).
#  Sizes in points. Leading = line height.
#
#  Element              Font                  Size   Leading  Color
#  ─────────────────────────────────────────────────────────────────
#  Name                 Helvetica-Bold         26     31      TERRA
#  Contact line         Helvetica               8.5   11      DARK_GREY
#  Section header       Helvetica-Bold         10     13      TERRA
#  Summary body         Helvetica               9     11.5    NEAR_BLACK  (justified)
#  Job title            Helvetica-Bold         10     12      NEAR_BLACK
#  Job meta (co/loc)    Helvetica               8.5   10.5    DARK_GREY
#  Job date             Helvetica               8.5   10.5    MID_GREY
#  Bullet body          Helvetica               9     11.2    NEAR_BLACK  (justified)
#  Edu degree           Helvetica-Bold          9.5   12      NEAR_BLACK
#  Edu school           Helvetica-Oblique       8.5   10.5    DARK_GREY
#  Edu detail           Helvetica               8.5   10.5    DETAIL_GREY
#  Skill cat label      Helvetica               8     10      TERRA
#  Skill pill text      Helvetica               8     —       TERRA
#  Cert / proj body     Helvetica               8.8   11      NEAR_BLACK
# ═══════════════════════════════════════════════════════════════

# ═══════════════════════════════════════════════════════════════
#  DESIGN ELEMENTS — VISUAL RULES
# ═══════════════════════════════════════════════════════════════
#
#  PHOTO BLOCK (header, page 1 only)
#  - Square crop, 1.1" × 1.1", rounded corners (r=5pt)
#  - Position: flush with left margin, top of page
#  - Border: 0.5pt stroke, #DDDDDD
#
#  NAME + CONTACT (header, page 1 only)
#  - Positioned to the right of the photo, 12pt gap
#  - Name on its own line, 26pt bold TERRA
#  - Contact line 1: email | phone | location  (8.5pt DARK_GREY)
#  - Contact line 2: linkedin link | github link  (8.5pt, links TERRA colored)
#  - Links use <a href> tags with color=TERRA, no default blue underline
#
#  HEADER SEPARATOR
#  - Double horizontal rule spanning full content width
#  - Top rule: 0.8pt, TERRA
#  - Bottom rule: 0.4pt, NEAR_BLACK, 4pt below top rule
#  - Placed 8pt below the lower of (contact block bottom, photo bottom)
#
#  SECTION HEADERS
#  - Text: ALL CAPS with &nbsp;&nbsp; between every character (wide-spaced effect)
#  - Font: Helvetica-Bold 10pt TERRA
#  - 12pt space above section header text
#  - 4pt space below text, then double rule (same as header separator)
#  - 4pt space below double rule before content begins
#  - Check for page break before drawing (need >= 30pt below)
#
#  BULLET POINTS
#  - Character: ▪ (small black square, Unicode U+25AA)
#  - Indent: 10pt from left margin, gap 4pt between bullet and text
#  - Body text wraps within (MW - 10 - 4) width
#  - 2pt spacing between bullets within a job block
#
#  JOB BLOCKS
#  - Row 1: Job title (left, bold) + Date (right-aligned, 90pt column)
#  - Row 2: Italic company name - location  (8.5pt DARK_GREY)
#  - Then bullets
#  - 7pt spacing after each job block
#
#  SKILL PILLS
#  - Category label: bold TERRA, 8pt, followed by colon
#  - 4pt below label, pills begin
#  - Pill: warm beige (#F2ECE6) rounded rect (r=4pt), height 14pt, pad 6pt L/R
#  - Pill text: Helvetica 8pt TERRA
#  - Pills flow left-to-right, wrap to next row when width exceeded
#  - 5pt horizontal gap, 4pt vertical gap between pills
#  - 2pt spacing below each skill category
#
#  TWO-COLUMN FOOTER (Selected Projects | Certifications)
#  - Triggered after Skills section, ensure >= 80pt remaining
#  - Each column = (MW - 10gap) / 2
#  - Both columns start at same y, render independently
#  - Column headers use same wide-spaced ALL CAPS style as section headers
#  - Column header followed by same double rule (but spanning only col width)
#  - Bullets use ▪, 3pt spacing between items
#
#  PAGE BREAKS
#  - Triggered when y < BOTTOM_MARGIN + need_pts
#  - Continuation pages start at y = H - 16mm (no repeated header)
#
# ═══════════════════════════════════════════════════════════════
#  SPACING REFERENCE
# ═══════════════════════════════════════════════════════════════
#
#  Photo top from page top:           14mm
#  Left margin (MX):                  16mm
#  Bottom margin:                     16mm
#  Section header space above:        12pt
#  Section header → double rule gap:   4pt
#  Double rule height (top+gap+bot):   8pt total (4pt gap between rules)
#  Double rule → content gap:          4pt
#  Job block spacing after:            7pt
#  Education block spacing after:      6pt
#  Bullet spacing:                     2pt
#  Two-col trigger minimum:           80pt remaining
#  Two-col header → content gap:      12pt
# ═══════════════════════════════════════════════════════════════


# ═══════════════════════════════════════════════════════════════
#  RENDERING ENGINE  (import and call build() to use)
# ═══════════════════════════════════════════════════════════════

def build(data, output_path: str):
    """
    Render the resume using the Warm Architect design.

    Args:
        data:        A module (or object) with NAME, EMAIL, PHONE, LOCATION,
                     LINKEDIN, GITHUB, SUMMARY, EXPERIENCE, EDUCATION,
                     SKILLS, PROJECTS, CERTS, and optionally PHOTO.
        output_path: Absolute or relative path for the output PDF.
    """
    photo_path = getattr(data, "PHOTO", None)

    c = rl_canvas.Canvas(str(output_path), pagesize=A4)

    # ── Styles ──────────────────────────────────────────────────
    s_name      = ParagraphStyle("name",    fontName="Helvetica-Bold",    fontSize=26,  textColor=HexColor(TERRA),       leading=31)
    s_contact   = ParagraphStyle("contact", fontName="Helvetica",         fontSize=8.5, textColor=HexColor(DARK_GREY),   leading=11)
    s_section   = ParagraphStyle("sec",     fontName="Helvetica-Bold",    fontSize=10,  textColor=HexColor(TERRA),       leading=13)
    s_summary   = ParagraphStyle("sum",     fontName="Helvetica",         fontSize=9,   textColor=HexColor(NEAR_BLACK),  leading=11.5, alignment=TA_JUSTIFY)
    s_job_title = ParagraphStyle("jt",      fontName="Helvetica-Bold",    fontSize=10,  textColor=HexColor(NEAR_BLACK),  leading=12)
    s_job_meta  = ParagraphStyle("jm",      fontName="Helvetica",         fontSize=8.5, textColor=HexColor(DARK_GREY),   leading=10.5)
    s_job_date  = ParagraphStyle("jd",      fontName="Helvetica",         fontSize=8.5, textColor=HexColor(MID_GREY),    leading=10.5)
    s_bullet    = ParagraphStyle("bl",      fontName="Helvetica",         fontSize=8.5, textColor=HexColor(NEAR_BLACK),  leading=10.5, alignment=TA_JUSTIFY)
    s_edu_deg   = ParagraphStyle("ed",      fontName="Helvetica-Bold",    fontSize=9.5, textColor=HexColor(NEAR_BLACK),  leading=12)
    s_edu_sch   = ParagraphStyle("es",      fontName="Helvetica-Oblique", fontSize=8.5, textColor=HexColor(DARK_GREY),   leading=10.5)
    s_edu_det   = ParagraphStyle("edt",     fontName="Helvetica",         fontSize=8.5, textColor=HexColor(DETAIL_GREY), leading=10.5)
    s_skill_tag = ParagraphStyle("st",      fontName="Helvetica",         fontSize=8,   textColor=HexColor(TERRA),       leading=10)
    s_cert      = ParagraphStyle("cert",    fontName="Helvetica",         fontSize=8.8, textColor=HexColor(NEAR_BLACK),  leading=11)
    s_proj      = ParagraphStyle("proj",    fontName="Helvetica",         fontSize=8.5, textColor=HexColor(NEAR_BLACK),  leading=10.5, alignment=TA_JUSTIFY)

    page = [1]

    # ── Core drawing helpers ─────────────────────────────────────

    def _draw_para(html, x, y, width, style):
        p = Paragraph(html, style)
        _, ph = p.wrap(width, 9999)
        p.drawOn(c, x, y - ph)
        return y - ph

    def _draw_bullet(html, x, y, width, style):
        bp = Paragraph("▪", ParagraphStyle("bchar", parent=style, fontSize=style.fontSize))
        _, bh = bp.wrap(20, 9999)
        p = Paragraph(html, style)
        _, ph = p.wrap(width - 14, 9999)
        top = max(ph, bh)
        bp.drawOn(c, x, y - top + (top - bh))
        p.drawOn(c, x + 14, y - top + (top - ph))
        return y - top

    def _check_break(y, need=45):
        if y < BOTTOM_MARGIN + need:
            c.showPage()
            page[0] += 1
            return PAGE2_TOP
        return y

    def _double_rule(y, x=MX, w=MW):
        c.setStrokeColor(HexColor(TERRA));    c.setLineWidth(0.8); c.line(x, y, x + w, y)
        c.setStrokeColor(HexColor(NEAR_BLACK)); c.setLineWidth(0.4); c.line(x, y - 4, x + w, y - 4)
        return y - 8

    def _section_header(y, text):
        # FIX 1: charSpace gives visual letter-spacing; ATS reads plain text correctly
        # 90pt minimum: header consumes ~50pt + 35pt for first content + 5pt buffer
        # prevents orphaned heading at page bottom with content on next page
        y = _check_break(y, 90)
        y -= 12
        # FIX 1: charSpace set on text object then immediately reset to 0
        # saveState/restoreState wraps q/Q operators which save Tc in graphics state
        y -= 9
        c.saveState()
        t = c.beginText(MX, y - 10)
        t.setFont("Helvetica-Bold", 10)
        t.setFillColor(HexColor(TERRA))
        t.setCharSpace(5.5)
        t.textLine(text.upper())
        c.drawText(t)
        c.restoreState()
        y -= 13
        y -= 4
        y = _double_rule(y)
        y -= 4
        return y

    def _col_header(y, text, x, w):
        c.saveState()
        t = c.beginText(x, y - 10)
        t.setFont("Helvetica-Bold", 10)
        t.setFillColor(HexColor(TERRA))
        t.setCharSpace(5.5)
        t.textLine(text.upper())
        c.drawText(t)
        c.restoreState()
        y -= 13
        y -= 4
        c.setStrokeColor(HexColor(TERRA));      c.setLineWidth(0.8); c.line(x, y, x + w, y)
        c.setStrokeColor(HexColor(NEAR_BLACK)); c.setLineWidth(0.4); c.line(x, y - 4, x + w, y - 4)
        return y - 12

    def _skill_pills(y, cat, vals):
        y = _check_break(y, 20)
        y = _draw_para(f'<b><font color="{TERRA}">{cat}:</font></b>', MX, y, MW, s_skill_tag)
        y -= 4
        px = MX
        pill_h, pad, gap_x, gap_y = 14, 6, 5, 4
        for skill in [s.strip() for s in vals.split(",")]:
            # Escape XML special chars so Paragraph parses correctly (& → &amp; etc.)
            safe = skill.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            c.setFont("Helvetica", 8)
            # stringWidth measures raw chars; +2pt buffer prevents Paragraph wrap mismatch
            pill_w = c.stringWidth(skill, "Helvetica", 8) + pad * 2 + 2
            if px + pill_w > MX + MW:
                px = MX; y -= pill_h + gap_y
            if y < BOTTOM_MARGIN + pill_h:
                c.showPage(); page[0] += 1; y = PAGE2_TOP; px = MX
            # FIX 2: Paragraph for pill text so ATS can extract skill names
            c.setFillColor(HexColor(WARM_BG))
            c.roundRect(px, y - pill_h + 2, pill_w, pill_h, 4, fill=1, stroke=0)
            sp = Paragraph(safe, ParagraphStyle("pt", fontName="Helvetica", fontSize=8,
                           textColor=HexColor(TERRA), leading=10))
            _, sh = sp.wrap(pill_w - pad * 2 + 2, pill_h)
            sp.drawOn(c, px + pad, y - pill_h + 2 + (pill_h - sh) / 2)
            px += pill_w + gap_x
        return y - pill_h - gap_y

    # ── HEADER BLOCK ─────────────────────────────────────────────

    if photo_path:
        photo_y = PHOTO_Y_TOP - PHOTO_SIZE
        c.saveState()
        path = c.beginPath()
        path.roundRect(PHOTO_X, photo_y, PHOTO_SIZE, PHOTO_SIZE, PHOTO_RADIUS)
        c.clipPath(path, stroke=0)
        c.drawImage(photo_path, PHOTO_X, photo_y, PHOTO_SIZE, PHOTO_SIZE,
                    preserveAspectRatio=True, mask='auto')
        c.restoreState()
        c.setStrokeColor(HexColor(BORDER_GREY)); c.setLineWidth(0.5)
        c.roundRect(PHOTO_X, photo_y, PHOTO_SIZE, PHOTO_SIZE, PHOTO_RADIUS, stroke=1, fill=0)
        text_x = PHOTO_X + PHOTO_SIZE + 12
        text_w = MW - PHOTO_SIZE - 12
        photo_bottom = photo_y
    else:
        text_x = MX
        text_w = MW
        photo_bottom = H  # won't be used in min() below

    ty = H - 16 * mm
    ty = _draw_para(data.NAME, text_x, ty, text_w, s_name)
    ty -= 4
    ln = f'<a href="https://{data.LINKEDIN}" color="{TERRA}">{data.LINKEDIN}</a>'
    gh = f'<a href="https://{data.GITHUB}"   color="{TERRA}">{data.GITHUB}</a>'
    ty = _draw_para(f"{data.EMAIL} &nbsp;|&nbsp; {data.PHONE} &nbsp;|&nbsp; {data.LOCATION}", text_x, ty, text_w, s_contact)
    ty -= 2
    ty = _draw_para(f"{ln} &nbsp;|&nbsp; {gh}", text_x, ty, text_w, s_contact)

    my = min(ty, photo_bottom if photo_path else ty) - 8
    my = _double_rule(my)
    my -= 4

    # ── PROFESSIONAL SUMMARY ─────────────────────────────────────

    my = _section_header(my, "Professional Summary")
    my = _draw_para(data.SUMMARY, MX, my, MW, s_summary)
    my -= 2

    # ── PROFESSIONAL EXPERIENCE ──────────────────────────────────

    my = _section_header(my, "Professional Experience")
    for exp in data.EXPERIENCE:
        my = _check_break(my, 55)
        tp = Paragraph(exp["title"], s_job_title)
        _, th = tp.wrap(MW - DATE_COL_W, 9999)
        dp = Paragraph(exp["dates"], s_job_date)
        _, dh = dp.wrap(DATE_COL_W, 9999)
        rh = max(th, dh)
        tp.drawOn(c, MX, my - rh)
        dp.drawOn(c, MX + MW - DATE_COL_W, my - rh + (rh - dh))
        my -= rh + 1
        my = _draw_para(f'<i>{exp["company"]}</i> - {exp["location"]}', MX, my, MW, s_job_meta)
        my -= 3
        for bullet in exp["bullets"]:
            my = _draw_bullet(bullet, MX, my, MW, s_bullet)
            my -= 1
        my -= 4

    # ── EDUCATION ────────────────────────────────────────────────

    my = _section_header(my, "Education")
    for ed in data.EDUCATION:
        my = _check_break(my, 35)
        dp = Paragraph(ed["degree"], s_edu_deg)
        _, dh = dp.wrap(MW - DATE_COL_W, 9999)
        datp = Paragraph(ed["dates"], s_job_date)
        _, dath = datp.wrap(DATE_COL_W, 9999)
        rh = max(dh, dath)
        dp.drawOn(c, MX, my - rh)
        datp.drawOn(c, MX + MW - DATE_COL_W, my - rh + (rh - dath))
        my -= rh + 1
        my = _draw_para(ed["school"], MX, my, MW, s_edu_sch)
        my -= 1
        my = _draw_para(ed["detail"], MX, my, MW, s_edu_det)
        my -= 4

    # ── SKILLS (pill tags) ────────────────────────────────────────

    my = _section_header(my, "Skills")
    for cat, vals in data.SKILLS.items():
        my = _skill_pills(my, cat, vals)
        my -= 1

    # ── SELECTED PROJECTS (full width, stacked) ──────────────────
    # FIX 3: Stacked layout — ATS reads linear text top-to-bottom correctly

    my = _section_header(my, "Selected Projects")
    for p in data.PROJECTS:
        my = _check_break(my, 16)
        my = _draw_bullet(p, MX, my, MW, s_proj)
        my -= 3

    # ── CERTIFICATIONS (full width, stacked) ─────────────────────

    my = _section_header(my, "Certifications")
    for cert in data.CERTS:
        my = _check_break(my, 14)
        my = _draw_bullet(cert, MX, my, MW, s_cert)
        my -= 3

    c.save()
    print(f"  OK  {output_path}  [{page[0]} pages]")
