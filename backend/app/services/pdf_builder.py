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


# CURALINK_CONFIG: CLINIC_CERTIFICATE_TEMPLATE
# This function IS the medical certificate template (ReportLab). Layout below; wording comes from
# curalink_config.CERTIFICATE_LANGUAGE, colours/logo from CERTIFICATE_BRANDING, signature box from
# SIGNATURE_PLACEMENT, clinic details from CLINIC_PROFILE. Professor-facing: never add diagnoses,
# symptoms, intake details or photos here.
def render(content: dict, signature: dict | None = None) -> bytes:
    """content: certificate fields (see curalink_config.ABSENCE_CERTIFICATION_FIELDS) + wording, courses, version, case_id.
    signature (signed copy only): signed_at, clinician_name, credentials, unsigned_sha256, authorization_id, image_png?"""
    from reportlab.lib.utils import ImageReader

    from app import curalink_config as cfg

    lang, brand, place = cfg.CERTIFICATE_LANGUAGE, cfg.CERTIFICATE_BRANDING, cfg.SIGNATURE_PLACEMENT
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter, invariant=1)
    c.setTitle(lang["title"] + " (DEMO)")
    _watermark(c, "DEMO · FICTIONAL")
    # CURALINK_CONFIG: CERTIFICATE_BRANDING (header colour / optional approved logo)
    c.setFillColor(colors.HexColor(brand["header_hex"]))
    c.rect(0, H - 0.9 * inch, W, 0.9 * inch, stroke=0, fill=1)
    if brand.get("logo_path"):
        c.drawImage(ImageReader(brand["logo_path"]), W - 1.6 * inch, H - 0.8 * inch, width=0.8 * inch, height=0.6 * inch, mask="auto")
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 15)
    c.drawString(0.75 * inch, H - 0.5 * inch, content.get("clinic_name") or "Clinic")
    c.setFont("Helvetica", 9)
    c.drawString(0.75 * inch, H - 0.7 * inch, lang["title"])

    y = H - 1.3 * inch
    c.setFillColor(colors.HexColor("#B45309"))
    c.setFont("Helvetica-Bold", 9)
    c.drawString(0.75 * inch, y, lang["demo_banner"])
    y -= 0.35 * inch
    rows = [
        ("Student", content["student_name"]),
        ("Appointment date", content.get("appointment_date", "")),
        ("Medically supported absence", f"{content['start_date']} through {content['end_date']} (inclusive)"),
        ("Clinician", f"{content['clinician_name']}{', ' + content['clinician_credentials'] if content.get('clinician_credentials') else ''}"),
        ("Issue date", content.get("issue_date", "")),
        ("Verification ID", f"{content.get('verification_id', '')}  (demo reference)"),
    ]
    for label, value in rows:
        c.setFillColor(INK)
        c.setFont("Helvetica-Bold", 10)
        c.drawString(0.75 * inch, y, label)
        c.setFont("Helvetica", 10)
        c.drawString(2.6 * inch, y, value)
        y -= 0.26 * inch
    y -= 0.12 * inch
    y = _wrap(c, content["wording"], 0.75 * inch, y, W - 1.5 * inch)
    y = _wrap(c, lang["excusal_disclaimer"], 0.75 * inch, y - 4, W - 1.5 * inch, size=9.5)
    y -= 0.15 * inch
    c.setFont("Helvetica-Bold", 10)
    c.drawString(0.75 * inch, y, "Class meetings in this period")
    y -= 0.24 * inch
    c.setFont("Helvetica", 9.5)
    if not content["courses"]:
        c.drawString(0.9 * inch, y, "No class meetings fall within these dates.")
        y -= 0.2 * inch
    for course in content["courses"]:
        c.drawString(0.9 * inch, y, f"{course['code']}: {', '.join(course['dates'])}")
        y -= 0.2 * inch

    # CURALINK_CONFIG: SIGNATURE_PLACEMENT (box position/size from curalink_config)
    y = max(y - 0.5 * inch, 2.3 * inch)
    x = place["x"]
    c.setStrokeColor(SLATE)
    c.line(x, y, x + 3 * inch, y)
    c.setFont("Helvetica", 8.5)
    c.setFillColor(SLATE)
    c.drawString(x, y - 12, "Authorized clinician signature")
    if signature:
        if signature.get("image_png"):
            img = ImageReader(io.BytesIO(signature["image_png"]))
            iw, ih = img.getSize()
            scale = min(place["max_width"] / iw, place["max_height"] / ih, 1.0)
            c.drawImage(img, x, y + place["y_offset"], width=iw * scale, height=ih * scale, mask="auto")
        else:
            c.saveState()
            c.setStrokeColor(colors.HexColor("#1E3A8A"))
            c.setLineWidth(1.6)
            p = c.beginPath()
            p.moveTo(x + 8, y + 8)
            for dx, dy in [(10, 18), (18, -10), (26, 14), (34, -6), (44, 16), (54, 0), (66, 12), (80, 4), (96, 10), (120, 2)]:
                p.curveTo(x + 8 + dx - 6, y + 8 + dy, x + 8 + dx - 2, y + 8 - dy / 2, x + 8 + dx, y + 8 + dy / 3)
            c.drawPath(p, stroke=1, fill=0)
            c.restoreState()
        c.setFillColor(colors.HexColor("#B91C1C"))
        c.setFont("Helvetica-Bold", 8)
        c.drawString(x + 3.1 * inch, y + 6, "SIMULATED SIGNATURE — DEMO, NOT VALID")
        c.setFillColor(INK)
        c.setFont("Helvetica", 9)
        c.drawString(x, y - 26, f"{signature['clinician_name']}{', ' + signature['credentials'] if signature.get('credentials') else ''}")
        c.drawString(x, y - 39, f"Approved and signed (simulated) {signature['signed_at']} UTC")
        c.setFont("Helvetica", 7.5)
        c.setFillColor(SLATE)
        c.drawString(x, y - 52, f"Audit ref {signature['authorization_id']} · unsigned v{content['version']} sha256 {signature['unsigned_sha256'][:24]}…")
    else:
        c.setFillColor(colors.HexColor("#B45309"))
        c.setFont("Helvetica-Bold", 9)
        c.drawString(x + 3.1 * inch, y + 4, "UNSIGNED DRAFT — awaiting clinician review")

    c.setFillColor(SLATE)
    c.setFont("Helvetica", 8)
    c.drawString(0.75 * inch, 0.8 * inch, f"{content.get('clinic_name', '')} · {content.get('clinic_contact', '')}"[:130])
    c.drawString(0.75 * inch, 0.62 * inch, f"Case {content['case_id']} · Version {content['version']} · Generated by CuraLink (hackathon prototype) · test-inbox delivery only")
    c.showPage()
    c.save()
    return buf.getvalue()
