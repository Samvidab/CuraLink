"""Requirement 12: every manual-configuration placeholder is present in code and documented."""

import importlib.util
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOC = (ROOT / "docs" / "DEVELOPER_CONFIGURATION.md").read_text()
CHECKLIST = (ROOT / "docs" / "MANUAL_SETUP_CHECKLIST.md").read_text()

REQUIRED = {
    "ANTHROPIC_API_KEY", "CARTESIA_API_KEY", "CARTESIA_VOICE_ID", "VISION_MODEL", "INTAKE_FIELDS",
    "CLINIC_PROFILE", "CLINICIAN_CREDENTIALS", "EXAMINATION_FIELDS", "ABSENCE_CERTIFICATION_FIELDS",
    "UNIVERSITY_DIRECTORY", "COURSE_CATALOG_SOURCE", "ACADEMIC_TERM", "INSTRUCTOR_EMAIL_FALLBACK", "CALENDAR_IMPORT",
    "CLINIC_CERTIFICATE_TEMPLATE", "CERTIFICATE_BRANDING", "CERTIFICATE_LANGUAGE", "DOCUMENT_VERIFICATION",
    "SIGNATURE_STORAGE", "SIGNATURE_ENCRYPTION", "SIGNATURE_PLACEMENT", "SIGNING_POLICY",
    "EMAIL_PROVIDER", "EMAIL_SENDER", "EMAIL_DELIVERY_MODE", "NOTIFICATION_TEMPLATES", "DOCUMENT_RECIPIENT_RULES",
    "DEMO_CLINICIAN_AVAILABILITY", "CLINICIAN_PROFILE_DATA", "APPOINTMENT_DURATION", "SCHEDULING_TIMEZONE",
}


def _index():
    spec = importlib.util.spec_from_file_location("config_index", ROOT / "scripts" / "config_index.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.scan()


def test_all_required_markers_exist_in_code():
    configs, _ = _index()
    assert REQUIRED - {name for name, _ in configs} == set()


def test_every_marker_is_indexed_in_docs():
    configs, todos = _index()
    for name, _ in configs:
        assert f"`{name}`" in DOC, f"{name} missing from docs/DEVELOPER_CONFIGURATION.md (run scripts/config_index.py)"
    for loc, _ in todos:
        assert loc.split(":")[0] in DOC, f"TODO in {loc} not indexed"
    doc_todo_rows = len(re.findall(r"^\| `[^`]+:\d+` \|", DOC.split("TODO(CURALINK-MANUAL) location")[1], re.M))
    assert doc_todo_rows == len(todos), "TODO(CURALINK-MANUAL) index is stale; regenerate it"


def test_checklist_covers_required_groups_and_fields():
    for heading in ("A. Required for the live hackathon demo", "B. University information", "C. Demo clinic information", "D. Production-only information"):
        assert heading in CHECKLIST
    for env in ("ANTHROPIC_API_KEY", "CARTESIA_API_KEY", "CARTESIA_VOICE_ID", "UNIVERSITY_DIRECTORY_URL", "COURSE_CATALOG_SOURCE", "ACADEMIC_TERM_ID", "SIGNATURE_ENCRYPTION_KEY", "EMAIL_DELIVERY_MODE"):
        assert env in CHECKLIST
        assert env in (ROOT / ".env.example").read_text()


def test_no_secrets_in_frontend_source():
    for f in (ROOT / "frontend" / "src").rglob("*.ts*"):
        text = f.read_text()
        assert "ANTHROPIC_API_KEY" not in text and "CARTESIA_API_KEY" not in text and "VITE_" not in text, f
        assert not re.search(r"sk-ant-[A-Za-z0-9]", text), f
