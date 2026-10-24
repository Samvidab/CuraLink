"""ReportLab documents. Unsigned PDFs are immutable once rendered; signing
produces a NEW PDF whose hash is recorded separately. The only signature
image is a generated, clearly watermarked DEMO sample — never a real signature."""

import hashlib
import io
from datetime import datetime

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas

W, H = letter
TEAL = colors.HexColor("#0F766E")
INK = colors.HexColor("#18303A")
SLATE = colors.HexColor("#64748B")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _wrap(c: canvas.Canvas, text: str, x: float, y: float, width: float, font="Helvetica", size=10.5, leading=15) -> float:
    c.setFont(font, size)
    for para in text.split("\n"):
        line = ""
        for word in para.split():
            trial = f"{line} {word}".strip()
            if c.stringWidth(trial, font, size) > width:
                c.drawString(x, y, line)
                y -= leading
                line = word
            else:
                line = trial
        c.drawString(x, y, line)
        y -= leading
    return y


def _watermark(c: canvas.Canvas, text: str) -> None:
    c.saveState()
    c.setFillColor(colors.Color(0.06, 0.46, 0.43, alpha=0.08))
    c.setFont("Helvetica-Bold", 64)
    c.translate(W / 2, H / 2)
    c.rotate(35)
    c.drawCentredString(0, 0, text)
    c.restoreState()


def render(content: dict, signature: dict | None = None) -> bytes:
    """content: student_name, clinician_name, start_date, end_date, wording, courses[{code, dates[]}], version, case_id.
    signature (signed copy only): signed_at, clinician_name, credentials, unsigned_sha256, authorization_id."""
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter, invariant=1)
    c.setTitle("Attendance Verification (DEMO)")
    _watermark(c, "DEMO · FICTIONAL")
    c.setFillColor(TEAL)
    c.rect(0, H - 0.9 * inch, W, 0.9 * inch, stroke=0, fill=1)
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 16)
    c.drawString(0.75 * inch, H - 0.55 * inch, "CuraLink · Attendance Verification")
    c.setFont("Helvetica", 9)
    c.drawRightString(W - 0.75 * inch, H - 0.55 * inch, f"Case {content['case_id']} · Version {content['version']}")

    y = H - 1.4 * inch
    c.setFillColor(colors.HexColor("#B45309"))
    c.setFont("Helvetica-Bold", 9.5)
    c.drawString(0.75 * inch, y, "DEMONSTRATION DOCUMENT — fictional people and data. Not an official excused absence.")
    y -= 0.4 * inch
    c.setFillColor(INK)
    for label, value in [
        ("Student", content["student_name"]),
        ("Clinician", content["clinician_name"]),
        ("Dates (inclusive)", f"{content['start_date']} through {content['end_date']}"),
    ]:
        c.setFont("Helvetica-Bold", 10.5)
        c.drawString(0.75 * inch, y, label)
        c.setFont("Helvetica", 10.5)
        c.drawString(2.2 * inch, y, value)
        y -= 0.28 * inch
    y -= 0.15 * inch
    y = _wrap(c, content["wording"], 0.75 * inch, y, W - 1.5 * inch)
    y -= 0.2 * inch
    c.setFont("Helvetica-Bold", 10.5)
    c.drawString(0.75 * inch, y, "Class meetings in this period")
    y -= 0.25 * inch
    c.setFont("Helvetica", 10)
    if not content["courses"]:
        c.drawString(0.9 * inch, y, "No class meetings fall within these dates.")
        y -= 0.22 * inch
    for course in content["courses"]:
        c.drawString(0.9 * inch, y, f"{course['code']}: {', '.join(course['dates'])}")
        y -= 0.22 * inch

    y = max(y - 0.4 * inch, 2.4 * inch)
    c.setStrokeColor(SLATE)
    c.line(0.75 * inch, y, 3.75 * inch, y)
    c.setFont("Helvetica", 8.5)
    c.setFillColor(SLATE)
    c.drawString(0.75 * inch, y - 12, "Clinician signature")
    if signature:
        c.saveState()
        c.setStrokeColor(colors.HexColor("#1E3A8A"))
        c.setLineWidth(1.6)
        p = c.beginPath()
        x0 = 0.85 * inch
        p.moveTo(x0, y + 8)
        for i, (dx, dy) in enumerate([(10, 18), (18, -10), (26, 14), (34, -6), (44, 16), (54, 0), (66, 12), (80, 4), (96, 10), (120, 2)]):
            p.curveTo(x0 + dx - 6, y + 8 + dy, x0 + dx - 2, y + 8 - dy / 2, x0 + dx, y + 8 + dy / 3)
        c.drawPath(p, stroke=1, fill=0)
        c.restoreState()
        c.setFillColor(colors.HexColor("#B91C1C"))
        c.setFont("Helvetica-Bold", 8)
        c.drawString(2.4 * inch, y + 6, "DEMO SAMPLE SIGNATURE — NOT VALID")
        c.setFillColor(INK)
        c.setFont("Helvetica", 9)
        c.drawString(0.75 * inch, y - 26, f"{signature['clinician_name']}{', ' + signature['credentials'] if signature.get('credentials') else ''}")
        c.drawString(0.75 * inch, y - 39, f"Approved and signed (simulated) {signature['signed_at']} UTC")
        c.setFont("Helvetica", 7.5)
        c.setFillColor(SLATE)
        c.drawString(0.75 * inch, y - 52, f"Audit ref {signature['authorization_id']} · unsigned v{content['version']} sha256 {signature['unsigned_sha256'][:24]}…")
    else:
        c.setFillColor(colors.HexColor("#B45309"))
        c.setFont("Helvetica-Bold", 9)
        c.drawString(4.0 * inch, y + 4, "UNSIGNED DRAFT — awaiting clinician review")

    c.setFillColor(SLATE)
    c.setFont("Helvetica", 8)
    c.drawString(0.75 * inch, 0.75 * inch, "This notice verifies a health-related appointment only. It contains no diagnosis. The university decides whether any absence is excused.")
    c.drawString(0.75 * inch, 0.6 * inch, f"Generated by CuraLink (hackathon prototype) · {datetime(2026, 10, 26):%Y} · Delivered only to a test inbox in demo mode.")
    c.showPage()
    c.save()
    return buf.getvalue()
