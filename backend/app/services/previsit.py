"""AI-assisted pre-visit summaries: one per conversation session, student-approved, versioned, never merged.

Flow: student reviews -> selects confirmed details/photos -> authorizes -> an immutable snapshot (HandoffPacket)
is stored as version N of THAT session. Corrections after submitting create version N+1; version N is kept as
SUPERSEDED. A summary approved before booking waits (encounter_id empty) and is attached when the student books.
Clinicians see a summary only through an encounter they're assigned to, and only while it isn't withdrawn.

The summary is assembled deterministically from stored fields (no model call), so it can only contain what the
student said, entered, confirmed and chose to share. AI image observations are labelled as such. Nothing here is
a diagnosis, an assessment or an absence approval.
"""

from collections import OrderedDict
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import ApiError
from app.models import Appointment, Attachment, Encounter, HandoffPacket, IntakeField, IntakeSession, User
from app.services import audit
from app.services.intake_fields import LABELS, display
from app.timeutil import to_local, utcnow

DISCLAIMER = ("Student-reported information organized by CuraLink. Not a diagnosis, clinical assessment or examination; "
              "an absence documentation request is not an approval. Clinician findings are documented separately.")
OTHER_KEYS = ("appointment_preference", "accessibility_needs", "requests")


def _label(key: str) -> str:
    return {"onset_text": "When it started", "temperature": "Temperature", "photo": "Photo", "symptoms_free_text": "Symptoms"}.get(key, LABELS.get(key, key))


def build(sess: IntakeSession, fields: list[IntakeField], photos: list[Attachment], include_purpose: bool, include_absence: bool) -> dict:
    """Structured summary of exactly what the student chose to share from ONE session."""
    by = {f.key: f for f in fields}
    symptoms = [s.strip() for s in by["symptoms_free_text"].value["text"].split(" / ")] if "symptoms_free_text" in by else []
    conv = sess.conversation or {}
    measurements = []
    if "temperature" in by:
        v = by["temperature"].value
        measurements.append({"key": "temperature", "label": "Temperature", "value": v.get("value"), "unit": v.get("unit"), "display": display("temperature", v),
                             "source": "Entered by student" if by["temperature"].provenance == "form" else "Stated by student, confirmed"})
    return {
        "session_id": sess.id,
        "session_started_at": sess.created_at.isoformat(),
        "chief_concern": symptoms[0] if symptoms else None,
        "symptoms": symptoms,
        "onset": next((display(k, by[k].value) for k in ("onset_text", "onset_date") if k in by), None),
        "measurements": measurements,
        "other": [{"key": k, "label": LABELS[k], "display": display(k, by[k].value)} for k in OTHER_KEYS if k in by],
        "photos": [{"attachment_id": a.id, "observer": a.observer, "synthetic_demo": a.synthetic_demo, "ai_generated": True,
                    "observations": a.observations, "limitations": a.limitations} for a in photos],
        "not_known": [_label(k) for k in conv.get("unknown", [])],
        "declined": [_label(k) for k in sorted(set(conv.get("declined", [])) | set(sess.skipped_fields or []))],
        "reason_for_visit": sess.purpose if include_purpose and sess.purpose else None,
        "absence_documentation": ("REQUESTED" if sess.absence_requested else "NOT_REQUESTED") if include_absence else "NOT_SHARED",
        "disclaimer": DISCLAIMER,
    }


def legacy_summary(p: HandoffPacket, sess: IntakeSession | None) -> dict:
    """Packets shared before structured summaries existed: rebuild the same shape from the field snapshot."""
    vals = {f["key"]: f for f in p.field_snapshot}
    symptoms = [s.strip() for s in vals["symptoms_free_text"]["value"]["text"].split(" / ")] if "symptoms_free_text" in vals else []
    temp = vals.get("temperature")
    return {
        "session_id": p.session_id, "session_started_at": sess.created_at.isoformat() if sess else None, "chief_concern": symptoms[0] if symptoms else None,
        "symptoms": symptoms, "onset": next((vals[k]["display"] for k in ("onset_text", "onset_date") if k in vals), None),
        "measurements": [{"key": "temperature", "label": "Temperature", "value": temp["value"].get("value"), "unit": temp["value"].get("unit"), "display": temp["display"], "source": "Student-reported"}] if temp else [],
        "other": [{"key": k, "label": vals[k]["label"], "display": vals[k]["display"]} for k in OTHER_KEYS if k in vals], "photos": [],
        "not_known": [], "declined": [], "reason_for_visit": None, "absence_documentation": "NOT_SHARED", "disclaimer": DISCLAIMER,
    }


def summary_of(db: Session, p: HandoffPacket) -> dict:
    return p.summary or legacy_summary(p, db.get(IntakeSession, p.session_id))


def _student_of(db: Session, p: HandoffPacket) -> str | None:
    if p.student_id:
        return p.student_id
    enc = db.get(Encounter, p.encounter_id) if p.encounter_id else None
    return enc.student_id if enc else None


def _upcoming(db: Session, student: User) -> list[Encounter]:
    return db.scalars(select(Encounter).where(Encounter.student_id == student.id, Encounter.status != "CANCELLED").order_by(Encounter.starts_at)).all()


def session_encounter(db: Session, sess: IntakeSession) -> Encounter | None:
    appt = db.scalar(select(Appointment).where(Appointment.intake_session_id == sess.id, Appointment.state == "DEMO_CONFIRMED").order_by(Appointment.created_at.desc()))
    return db.scalar(select(Encounter).where(Encounter.appointment_id == appt.id)) if appt else None


def latest(db: Session, session_id: str) -> HandoffPacket | None:
    return db.scalar(select(HandoffPacket).where(HandoffPacket.session_id == session_id).order_by(HandoffPacket.version.desc()))


def submit(db: Session, student: User, sess: IntakeSession, field_keys: list[str], attachment_ids: list[str], include_purpose: bool,
           include_absence: bool, encounter_id: str | None, authorized: bool) -> HandoffPacket:
    if sess.student_id != student.id:
        raise ApiError(404, "NOT_FOUND", "Conversation not found.")
    if not authorized:
        raise ApiError(400, "AUTHORIZATION_REQUIRED", "Confirm that you want to share these details with your clinician.")
    have = {f.key: f for f in db.scalars(select(IntakeField).where(IntakeField.session_id == sess.id))}
    chosen = []
    for key in dict.fromkeys(field_keys):
        f = have.get(key)
        if f is None:
            raise ApiError(422, "UNKNOWN_FIELD", "One of the selected details no longer exists.", details={"key": key})
        if not f.confirmed_by_student:
            raise ApiError(409, "FIELD_NOT_CONFIRMED", "Review and confirm each detail before sharing it.", details={"key": key})
        chosen.append(f)
    photos = []
    for aid in dict.fromkeys(attachment_ids):
        a = db.get(Attachment, aid)
        if a is None or a.student_id != student.id or a.session_id != sess.id:  # photos stay with their own session
            raise ApiError(422, "UNKNOWN_ATTACHMENT", "One of the selected photos isn't part of this conversation.")
        photos.append(a)
    if not chosen and not photos and not (include_purpose and sess.purpose) and not (include_absence and sess.absence_requested):
        raise ApiError(422, "NOTHING_SELECTED", "Choose at least one detail to share.")
    prev = latest(db, sess.id)
    if encounter_id:
        enc = db.get(Encounter, encounter_id)
        if enc is None or enc.student_id != student.id or enc.status == "CANCELLED":
            raise ApiError(404, "NOT_FOUND", "Appointment not found.")
    else:
        # A corrected version goes where the previous one went; else the appointment booked from this
        # conversation; otherwise it waits for the next booking.
        prev_enc = db.get(Encounter, prev.encounter_id) if prev and prev.encounter_id else None
        enc = prev_enc if prev_enc and prev_enc.status != "CANCELLED" else session_encounter(db, sess)
    doc = db.get(User, enc.clinician_id) if enc else None
    consent = (f"I authorize sharing the selected details with {doc.display_name} for my appointment." if doc
               else "I authorize sharing the selected details with the clinician I book my next appointment with.")
    packet = HandoffPacket(
        id=f"pkt_{uuid4().hex[:10]}", encounter_id=enc.id if enc else None, session_id=sess.id, student_id=student.id, version=(prev.version + 1) if prev else 1,
        field_snapshot=[{"key": f.key, "label": LABELS[f.key], "value": f.value, "display": display(f.key, f.value), "provenance": f.provenance,
                         "confirmed_by_student": True, "updated_at": f.updated_at.isoformat()} for f in chosen],
        summary=build(sess, chosen, photos, include_purpose, include_absence), consent_text=consent,
        attachment_ids=[a.id for a in photos], source_mode="demo",
    )
    db.add(packet)
    if prev and prev.status == "SHARED":
        prev.status = "SUPERSEDED"  # kept for the audit trail, never edited
    if enc and enc.status in ("UPCOMING", "INTAKE_SHARED", "CLINICIAN_REVIEW"):
        enc.status = "INTAKE_SHARED"
    audit.record(db, actor_role="student", actor_id=student.id, subject_student_id=student.id, action="INTAKE_SHARED_WITH_CLINICIAN",
                 object_type="intake_session", object_id=sess.id, to_state="SHARED" if enc else "SHARED_PENDING_APPOINTMENT",
                 detail=f"v{packet.version}, {len(chosen)} fields, {len(photos)} photos" + (f", encounter {enc.id}" if enc else ", awaiting booking"))
    db.commit()
    return packet


def attach_pending(db: Session, student_id: str, enc: Encounter) -> int:
    """Booking fulfils 'share with the clinician I book next': attach the student's waiting summaries."""
    waiting = db.scalars(select(HandoffPacket).where(HandoffPacket.student_id == student_id, HandoffPacket.encounter_id.is_(None), HandoffPacket.status == "SHARED")).all()
    for p in waiting:
        p.encounter_id = enc.id
        audit.record(db, actor_role="system", actor_id=None, subject_student_id=student_id, action="SUMMARY_ATTACHED_TO_APPOINTMENT",
                     object_type="encounter", object_id=enc.id, detail=f"session {p.session_id} v{p.version}")
    if waiting:
        enc.status = "INTAKE_SHARED"
    return len(waiting)


def withdraw(db: Session, student: User, packet_id: str) -> HandoffPacket:
    p = db.get(HandoffPacket, packet_id)
    if p is None or _student_of(db, p) != student.id:
        raise ApiError(404, "NOT_FOUND", "Shared summary not found.")
    if p.status == "SHARED":
        p.status, p.withdrawn_at = "WITHDRAWN", utcnow()
        enc = db.get(Encounter, p.encounter_id) if p.encounter_id else None
        if enc and enc.status in ("INTAKE_SHARED", "CLINICIAN_REVIEW") and not db.scalar(select(HandoffPacket.id).where(HandoffPacket.encounter_id == enc.id, HandoffPacket.status == "SHARED")):
            enc.status = "UPCOMING"
        audit.record(db, actor_role="student", actor_id=student.id, subject_student_id=student.id, action="INTAKE_WITHDRAWN", object_type="intake_session",
                     object_id=p.session_id, to_state="WITHDRAWN", detail=("viewed by clinician before withdrawal" if p.clinician_viewed_at else None))
        db.commit()
    return p


def status_for_session(db: Session, sess: IntakeSession) -> dict | None:
    p = latest(db, sess.id)
    if p is None:
        return None
    enc = db.get(Encounter, p.encounter_id) if p.encounter_id else None
    doc = db.get(User, enc.clinician_id) if enc else None
    return {"packet_id": p.id, "version": p.version, "status": p.status, "shared_at": p.student_approved_at.isoformat(), "encounter_id": p.encounter_id,
            "clinician_name": doc.display_name if doc else None, "appointment_at": enc.starts_at.isoformat() if enc else None,
            "field_keys": [f["key"] for f in p.field_snapshot], "attachment_ids": list(p.attachment_ids or []), "summary": summary_of(db, p)}


# ---- clinician side -----------------------------------------------------------------------------------------

def visible_packets(db: Session, clinician: User, student_id: str) -> list[HandoffPacket]:
    """Every packet of this student attached to an encounter currently assigned to this clinician."""
    return db.scalars(select(HandoffPacket).join(Encounter, HandoffPacket.encounter_id == Encounter.id)
                      .where(Encounter.clinician_id == clinician.id, Encounter.student_id == student_id)).all()


def can_view_photo(db: Session, clinician: User, student_id: str, attachment_id: str) -> bool:
    return any(p.status == "SHARED" and attachment_id in (p.attachment_ids or []) for p in visible_packets(db, clinician, student_id))


def current_for_encounter(db: Session, enc: Encounter) -> HandoffPacket | None:
    """The most recently approved summary attached to this encounter (any session); withdrawn ones stay withdrawn."""
    rows = db.scalars(select(HandoffPacket).where(HandoffPacket.encounter_id == enc.id, HandoffPacket.status.in_(("SHARED", "WITHDRAWN")))
                      .order_by(HandoffPacket.student_approved_at.desc())).all()
    return next((p for p in rows if p.status == "SHARED"), rows[0] if rows else None)


def history(db: Session, clinician: User, student_id: str, tz: str) -> dict:
    """Sessions grouped by the LOCAL date the conversation started (clinician's zone), newest first; one entry per
    session (its latest version), never merged. Withdrawn sessions show no content."""
    packets = visible_packets(db, clinician, student_id)
    per_session: dict[str, list[HandoffPacket]] = {}
    for p in packets:
        per_session.setdefault(p.session_id, []).append(p)
    sessions = []
    for sid, ps in per_session.items():
        sess = db.get(IntakeSession, sid)
        if sess is None:
            continue
        ps.sort(key=lambda p: p.version)
        cur = next((p for p in reversed(ps) if p.status in ("SHARED", "WITHDRAWN")), ps[-1])
        enc = db.get(Encounter, cur.encounter_id) if cur.encounter_id else None
        appt = db.get(Appointment, enc.appointment_id) if enc and enc.appointment_id else None
        started = to_local(sess.created_at, tz)
        shared = cur.status == "SHARED"
        sessions.append({
            "session_id": sid, "started_at": started.isoformat(), "ended_at": to_local(sess.ended_at, tz).isoformat() if sess.ended_at else None,
            "local_date": started.date().isoformat(), "status": cur.status,
            "status_label": "Approved for clinician sharing" if shared else "Withdrawn by student" if cur.status == "WITHDRAWN" else cur.status.title(),
            "version": cur.version, "packet_id": cur.id, "submitted_at": to_local(cur.student_approved_at, tz).isoformat(),
            "versions": [{"version": p.version, "status": p.status, "submitted_at": to_local(p.student_approved_at, tz).isoformat()} for p in ps],
            "consent_text": cur.consent_text if shared else None, "summary": summary_of(db, cur) if shared else None,
            "appointment": {"encounter_id": enc.id, "starts_at": to_local(enc.starts_at, tz).isoformat(), "visit_type": enc.visit_type,
                            "purpose": appt.purpose if appt else None} if enc else None,
            "_sort": sess.created_at,
        })
    sessions.sort(key=lambda s: s["_sort"])
    for i, s in enumerate(sessions, 1):
        s["label"] = f"Session {i}"
    sessions.sort(key=lambda s: s["_sort"], reverse=True)
    groups: "OrderedDict[str, list]" = OrderedDict()
    for s in sessions:
        s.pop("_sort")
        groups.setdefault(s["local_date"], []).append(s)
    latest_id = next((s["session_id"] for s in sessions if s["status"] == "SHARED"), None)
    return {"student_id": student_id, "timezone": tz, "latest_session_id": latest_id, "groups": [{"date": d, "sessions": ss} for d, ss in groups.items()]}
