"""Central, non-secret configuration objects that teams edit by hand.

Secrets and per-deployment values come from environment variables (app/config.py).
Everything here is safe to commit. Search the repo for "CURALINK_CONFIG" and for
"CURALINK-MANUAL" TODOs to find every manual setting; docs/DEVELOPER_CONFIGURATION.md
indexes them. Nothing in this file can bypass clinician approval, student consent,
or signature authorization; those are enforced in app/services/absence_service.py.
"""

from app.config import get_settings

# CURALINK_CONFIG: CLINIC_PROFILE
# Name/address/contact come from env (CLINIC_NAME, CLINIC_ADDRESS, CLINIC_PHONE, CLINIC_EMAIL);
# defaults are fictional. TODO(CURALINK-MANUAL): a participating clinic's verified details for production.
def clinic_profile() -> dict:
    s = get_settings()
    return {"name": s.clinic_name, "address": s.clinic_address, "phone": s.clinic_phone, "email": s.clinic_email, "demo": s.demo_mode}


# CURALINK_CONFIG: CLINICIAN_CREDENTIALS
# Demo clinician identities/credentials/verification live in sample_data/demo_users.json and are
# loaded into the database by app/seed.py (passwords are hashed with scrypt; the shared demo
# password is published in README). Authorization = users.role == "clinician" AND clinician_verified.
# TODO(CURALINK-MANUAL): production needs verified identity (SSO/OIDC) and license verification,
# managed server-side; never put real clinician passwords or credentials in source.

# CURALINK_CONFIG: EXAMINATION_FIELDS
# Clinician-only fields shown in "Medical Evaluation & Absence Determination". Never shown to
# professors; never shown to students. Add/remove entries here; the UI renders them automatically.
EXAMINATION_FIELDS: list[dict] = [
    {"key": "examination_findings", "label": "Examination findings", "type": "textarea", "required": False},
    {"key": "assessment", "label": "Clinician assessment", "type": "textarea", "required": False},
    {"key": "activity_restrictions", "label": "Activity / attendance restrictions", "type": "textarea", "required": False},
    {"key": "measured_temperature", "label": "Temperature measured in clinic", "type": "text", "required": False},
]

# CURALINK_CONFIG: ABSENCE_CERTIFICATION_FIELDS
# Fields that must be present on a medical certificate. render_version() refuses to render if any is empty.
ABSENCE_CERTIFICATION_FIELDS: list[str] = [
    "student_name", "appointment_date", "clinician_name", "clinician_credentials", "clinic_name",
    "start_date", "end_date", "issue_date", "clinic_contact", "verification_id",
]

# CURALINK_CONFIG: CERTIFICATE_LANGUAGE
# Provider-approved wording. Placeholders: {student} {start} {end}. Must not include diagnoses,
# symptoms or photos, and must not promise the university will excuse the absence.
# TODO(CURALINK-MANUAL): replace with wording approved by the participating clinic.
CERTIFICATE_LANGUAGE = {
    "title": "Medical Certificate — Attendance Verification",
    "default_statement": (
        "{student} was evaluated by a healthcare professional and, in the clinician's judgment, may be unable to attend "
        "class from {start} through {end}. This certificate contains no medical details."
    ),
    "excusal_disclaimer": "This certificate does not determine whether an absence is excused. The university decides under its own policies.",
    "demo_banner": "DEMONSTRATION DOCUMENT — fictional people and data. Not a real medical certificate.",
}

# CURALINK_CONFIG: CERTIFICATE_BRANDING
# Header colour/logo for app/services/pdf_builder.py. logo_path: a PNG the clinic has approved (None = text header).
# TODO(CURALINK-MANUAL): approved clinic logo file and brand colour.
CERTIFICATE_BRANDING = {"header_hex": "#0F766E", "logo_path": None}

# CURALINK_CONFIG: SIGNATURE_PLACEMENT
# Where the clinician's signature image is drawn on the certificate (points from the bottom-left; 72 pt = 1 inch).
SIGNATURE_PLACEMENT = {"x": 54, "y_offset": 6, "max_width": 200, "max_height": 48}

# CURALINK_CONFIG: NOTIFICATION_TEMPLATES
# Professor notice. Placeholders: {instructor} {student} {course} {dates} {start} {end} {clinician} {clinic}.
# Minimum necessary information only: no diagnosis, symptoms, intake details or photos.
NOTIFICATION_TEMPLATES = {
    "subject": "Attendance verification: {student} · {course}",
    "body": (
        "Dear {instructor},\n\n"
        "{student} was seen at {clinic} and, per the treating clinician, may be absent from {course} on {dates} "
        "(medically supported period {start} to {end}).\n\n"
        "This message contains no medical information and does not determine whether the absence is excused; "
        "please apply your course and university policies.\n\n"
        "Sent on behalf of {clinician} via CuraLink (demo). The signed certificate is attached."
    ),
}
