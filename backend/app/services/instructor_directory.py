"""Instructor contact resolution. NEVER fabricates a name or address.

Order of sources for a course (code + section + term):
 1. The student's own UniTime .ics (ORGANIZER/ATTENDEE) — read during import (calendar_service).
 2. COURSE_CATALOG_SOURCE — the configured catalog (demo: sample_data/demo_courses.json).
 3. UNIVERSITY_DIRECTORY — an authorized directory connector, only if UNIVERSITY_DIRECTORY_URL is set.
 4. INSTRUCTOR_EMAIL_FALLBACK — manual entry by the student (PATCH /api/v1/courses/{id}/contact,
    Settings -> Courses & instructors, and My Cases), which requires an explicit confirmation.
Anything not from an authoritative source is NEEDS_REVIEW/MISSING and is not deliverable.
"""

import logging
from dataclasses import dataclass

import httpx

from app.config import get_settings
from app.services import catalog

log = logging.getLogger("curalink.directory")


@dataclass
class Match:
    instructor_name: str | None
    instructor_email: str | None
    contact_status: str  # VERIFIED | NEEDS_REVIEW | MISSING
    provenance: str  # demo_catalog | university_directory | none
    title: str | None = None
    color: str | None = None


NO_MATCH = Match(None, None, "MISSING", "none")


def from_catalog(code: str) -> Match | None:
    # CURALINK_CONFIG: COURSE_CATALOG_SOURCE
    # "demo_catalog" reads the FICTIONAL sample_data/demo_courses.json (via app/services/catalog.py).
    # TODO(CURALINK-MANUAL): for Purdue, connect an authorized catalog export/API here, keyed by
    # course code + section + ACADEMIC_TERM. Do not scrape pages that require a login.
    if get_settings().course_catalog_source != "demo_catalog":
        return None
    entry = catalog.lookup(code)
    if not entry:
        return None
    return Match(entry.get("instructor_name"), entry.get("instructor_email"), entry.get("contact_status", "MISSING"), "demo_catalog", entry.get("title"), entry.get("color"))


def from_directory(code: str, section: str | None, term: str) -> Match | None:
    # CURALINK_CONFIG: UNIVERSITY_DIRECTORY
    # Expected contract of an authorized connector (adapt to the real one):
    #   GET {UNIVERSITY_DIRECTORY_URL}/sections?course=CS%2018000&section=001&term=FALL-2026
    #   -> {"instructor_name": "...", "instructor_email": "...", "authoritative": true}
    # Results are VERIFIED only if the connector says authoritative AND returns an email; otherwise NEEDS_REVIEW.
    base = get_settings().university_directory_url
    if not base:
        return None
    try:
        r = httpx.get(f"{base.rstrip('/')}/sections", params={"course": code, "section": section or "", "term": term}, timeout=4.0, follow_redirects=False)
        if r.status_code != 200:
            return None
        data = r.json()
    except (httpx.HTTPError, ValueError):
        log.warning("directory lookup failed for %s", code)
        return None
    name, email = data.get("instructor_name") or None, data.get("instructor_email") or None
    if not name and not email:
        return None
    status = "VERIFIED" if (email and data.get("authoritative") is True) else "NEEDS_REVIEW"
    return Match(name, email if email and "@" in email else None, status if email else "NEEDS_REVIEW", "university_directory")


def resolve(code: str, section: str | None) -> Match:
    """Catalog, then directory. Returns NO_MATCH rather than guessing."""
    term = get_settings().academic_term_id
    return from_catalog(code) or from_directory(code, section, term) or NO_MATCH
