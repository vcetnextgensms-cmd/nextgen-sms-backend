"""Official attendance-register PDF — printable anytime (Boss's request),
not gated by the 24h faculty edit lock (viewing/printing isn't editing).

Layout follows Boss's mockup: VCET logo + header, session meta block,
S.No/Roll No/Name/Status table with a light-red background on Absent rows
so the state isn't communicated by colour alone (status text stays too).
"""

import io
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.platypus import Image as RLImage
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_CENTER

LOGO_PATH = Path(__file__).parent.parent.parent / "webapp" / "static" / "img" / "vcet_logo.png"

RED_BG = colors.Color(0.99, 0.90, 0.91)   # matches app.css --red tint
GREEN_BG = colors.Color(0.91, 0.98, 0.94)


def build_attendance_pdf(session, roster) -> bytes:
    """session: sqlite Row from session_details(). roster: list of dicts with
    roll_no, name, present (bool) — same shape load_register() produces."""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=14 * mm, bottomMargin=14 * mm,
                             leftMargin=16 * mm, rightMargin=16 * mm)
    story = []

    center = ParagraphStyle("center", alignment=TA_CENTER, fontName="Helvetica-Bold", fontSize=13, leading=16)
    sub = ParagraphStyle("sub", alignment=TA_CENTER, fontName="Helvetica", fontSize=9, leading=12, textColor=colors.HexColor("#475467"))
    title = ParagraphStyle("title", alignment=TA_CENTER, fontName="Helvetica-Bold", fontSize=12, spaceBefore=8, spaceAfter=10)

    if LOGO_PATH.exists():
        try:
            story.append(RLImage(str(LOGO_PATH), width=22 * mm, height=19 * mm))
        except Exception:
            pass
    story.append(Paragraph("Visvesvaraya College of Engineering &amp; Technology", center))
    story.append(Paragraph("An Autonomous Institution &middot; Affiliated to JNTU, Hyderabad", sub))
    story.append(Paragraph("Bongloor X Road, MP Patelguda (V), Ibrahimpatnam (M), Hyderabad-501510", sub))
    story.append(Paragraph("DEPARTMENT OF CSE (DATA SCIENCE)", sub))
    story.append(Paragraph("ATTENDANCE REGISTER", title))

    meta_rows = [
        ["Date", session["attendance_date"], "Semester", session["semester_code"]],
        ["Subject", f"{session['subject_name']} ({session['subject_code']})", "Faculty", session["faculty_name"] or session["faculty_username"]],
        ["Session", "Lab" if session["session_type"] == "LAB" else "Class", "Duration", f"{session['duration_hours']} Hour(s)"],
        ["Topic", session["topic"], "", ""],
    ]
    meta = Table(meta_rows, colWidths=[24 * mm, 68 * mm, 24 * mm, 62 * mm])
    meta.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"), ("FONTNAME", (2, 0), (2, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("SPAN", (1, 3), (3, 3)),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4), ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("LINEBELOW", (0, -1), (-1, -1), 0.5, colors.HexColor("#d0d5dd")),
    ]))
    story.append(meta)
    story.append(Spacer(1, 10))

    present_count = sum(1 for r in roster if r["present"])
    data = [["S.No", "Roll No", "Name", "Status"]]
    for i, r in enumerate(roster, 1):
        data.append([str(i), r["roll_no"], r["name"], "PRESENT" if r["present"] else "ABSENT"])

    table = Table(data, colWidths=[14 * mm, 32 * mm, 90 * mm, 22 * mm], repeatRows=1)
    style = [
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f3f5f8")),
        ("ALIGN", (0, 0), (0, -1), "CENTER"), ("ALIGN", (3, 0), (3, -1), "CENTER"),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#e4e7ec")),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5), ("TOPPADDING", (0, 0), (-1, -1), 5),
    ]
    for i, r in enumerate(roster, start=1):
        style.append(("BACKGROUND", (0, i), (-1, i), GREEN_BG if r["present"] else RED_BG))
        style.append(("TEXTCOLOR", (3, i), (3, i), colors.HexColor("#067647") if r["present"] else colors.HexColor("#b42318")))
    table.setStyle(TableStyle(style))
    story.append(table)

    story.append(Spacer(1, 10))
    story.append(Paragraph(f"Present: {present_count} &nbsp;&nbsp; Absent: {len(roster) - present_count} &nbsp;&nbsp; Total: {len(roster)}",
                            ParagraphStyle("footer", fontName="Helvetica-Bold", fontSize=10)))

    doc.build(story)
    return buf.getvalue()
