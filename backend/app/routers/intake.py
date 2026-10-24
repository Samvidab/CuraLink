from datetime import date
from uuid import uuid4

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.errors import ApiError
from app.models import Encounter, HandoffPacket, IntakeField, IntakeSession, User
from app.routers.scheduling import recommendations
from app.schemas import (
    ConfirmFieldIn,
    ConsentIn,
    FieldsIn,
    HandoffIn,
    HandoffOut,
    IntakeFieldOut,
    IntakeMessageIn,
    IntakeReplyOut,
    IntakeSnapshot,
    RecommendationIn,
    SkipIn,
    StudentEncounterOut,
)
from app.security import require_student
from app.services import audit, intake_service, llm_gateway
from app.services.intake_fields import FIELD_KEYS, LABELS, FieldError, display, validate
from app.timeutil import to_local, utcnow

router = APIRouter(prefix="/api/v1", tags=["intake"])


def field_out(f: IntakeField) -> IntakeFieldOut:
    return IntakeFieldOut(
        key=f.key, label=LABELS.get(f.key, f.key), value=f.value, display=display(f.key, f.value), provenance=f.provenance,
        confirmed_by_student=f.confirmed_by_student, updated_at=f.updated_at,
    )


def snapshot(db: Session, sess: IntakeSession) -> IntakeSnapshot:
    fields = sorted(intake_service.fields_of(db, sess).values(), key=lambda f: FIELD_KEYS.index(f.key))
    return IntakeSnapshot(
        session_id=sess.id, status=sess.status, safety_state=sess.safety_state, voice_consent=sess.voice_consent,
        transcription_consent=sess.transcription_consent, photo_consent=sess.photo_consent, fields=[field_out(f) for f in fields],
        missing_fields=intake_service.missing(db, sess), skipped_fields=list(sess.skipped_fields or []),
        conversation_state=(sess.conversation or {}).get("state", "GREETING"), declined=list((sess.conversation or {}).get("declined", [])),
    )


def own_session(db: Session, user: User, session_id: str) -> IntakeSession:
    sess = db.get(IntakeSession, session_id)
    if sess is None or sess.student_id != user.id:
        raise ApiError(404, "NOT_FOUND", "Intake session not found.")
    if sess.status != "OPEN":
        raise ApiError(409, "SESSION_CLOSED", "This intake was already shared. Start a new conversation to add details.")
    return sess


def tool_handler_for(db: Session, user: User):
    """Read-only tool implementations exposed to the model."""

    async def handle(name: str, args: dict) -> str:
        if name == "propose_intake_fields":
            return "Recorded as unconfirmed drafts for the student to review."
        if name == "request_ui_action":
            return f"Shown on the student's screen: {args.get('action')}."
        if name == "get_ranked_slots":
            t = args.get("appointment_type")
            recs = recommendations(RecommendationIn(appointment_type=None if t in (None, "any") else t), user, db)
            top = [
                {"when": f"{o.slot.starts_at:%a %b %d %I:%M %p}", "clinic": o.slot.clinic_name, "travel_min": o.slot.travel_minutes, "reasons": o.reason_codes}
                for o in recs.options[:3]
            ]
            return llm_gateway.dumps({"source_mode": "demo", "calendar_considered": recs.calendar_considered, "top_options": top, "note": "Synthetic demo inventory. The student books on the Appointments screen."})
        if name == "list_calendar_events":
            from app.routers.student import calendar_events

            d = date.fromisoformat(args["date"])
            ev = calendar_events(d, date.fromordinal(d.toordinal() + 1), user, db)
            return llm_gateway.dumps([{"course": e.course_code or e.title, "start": f"{e.start_at:%I:%M %p}", "end": f"{e.end_at:%I:%M %p}"} for e in ev.events])
        raise ValueError("unknown tool")

    return handle


@router.post("/intake/sessions", response_model=IntakeSnapshot)
def start_session(user: User = Depends(require_student), db: Session = Depends(get_db)) -> IntakeSnapshot:
    return snapshot(db, intake_service.current_session(db, user))


@router.get("/intake/sessions/current", response_model=IntakeSnapshot)
def get_current(user: User = Depends(require_student), db: Session = Depends(get_db)) -> IntakeSnapshot:
    return snapshot(db, intake_service.current_session(db, user))


AI_GENERATED = {"photo_observation"}


@router.get("/intake/sessions/current/summary")
def summary(user: User = Depends(require_student), db: Session = Depends(get_db)) -> dict:
    """Structured intake summary, attributed by source. Built deterministically from stored fields
    (no model call), so it can't add anything the student didn't say or confirm."""
    sess = intake_service.current_session(db, user)
    fields = sorted(intake_service.fields_of(db, sess).values(), key=lambda f: FIELD_KEYS.index(f.key))

    def item(f: IntakeField) -> dict:
        return {"key": f.key, "label": LABELS[f.key], "display": display(f.key, f.value), "source": f.provenance, "confirmed": f.confirmed_by_student}

    sections = {
        "symptoms": [item(f) for f in fields if f.key == "symptoms_free_text"],
        "onset": [item(f) for f in fields if f.key in ("onset_text", "onset_date")],
        "temperature": [item(f) for f in fields if f.key == "temperature"],
        "additional": [item(f) for f in fields if f.key in ("appointment_preference", "accessibility_needs", "requests")],
        "image_observations": [item(f) for f in fields if f.provenance in AI_GENERATED],
    }
    return {
        "session_id": sess.id,
        "student_reported": {k: v for k, v in sections.items() if k != "image_observations"},
        "ai_generated": sections["image_observations"],
        "clinician_verified": [],  # filled only by the clinician after the visit, never by the AI
        "missing": [{"key": k, "label": LABELS[k]} for k in intake_service.missing(db, sess)],
        "uncertain": [{"key": f.key, "label": LABELS[f.key], "reason": "Not yet confirmed by you"} for f in fields if not f.confirmed_by_student],
        "skipped": list(sess.skipped_fields or []),
        "disclaimer": "Organized from what you said, entered or uploaded. Not a diagnosis; your clinician decides about any absence.",
    }


@router.post("/intake/sessions/new", response_model=IntakeSnapshot)
def new_session(user: User = Depends(require_student), db: Session = Depends(get_db)) -> IntakeSnapshot:
    old = intake_service.current_session(db, user, create=False)
    if old:
        old.status = "CLOSED"
        db.commit()
    return snapshot(db, intake_service.current_session(db, user))


@router.patch("/intake/sessions/{session_id}/consent", response_model=IntakeSnapshot)
def set_consent(session_id: str, body: ConsentIn, user: User = Depends(require_student), db: Session = Depends(get_db)) -> IntakeSnapshot:
    sess = own_session(db, user, session_id)
    for k, v in body.model_dump(exclude_none=True).items():
        if getattr(sess, k) != v:
            setattr(sess, k, v)
            audit.record(db, actor_role="student", actor_id=user.id, subject_student_id=user.id, action="CONSENT_GRANTED" if v else "CONSENT_WITHDRAWN", object_type="intake_session", object_id=sess.id, detail=k)
    db.commit()
    return snapshot(db, sess)


@router.post("/intake/messages", response_model=IntakeReplyOut)
async def message(body: IntakeMessageIn, user: User = Depends(require_student), db: Session = Depends(get_db)) -> IntakeReplyOut:
    sess = own_session(db, user, body.session_id) if body.session_id else intake_service.current_session(db, user)
    if body.channel == "voice" and not sess.voice_consent:
        raise ApiError(403, "VOICE_CONSENT_REQUIRED", "Turn on voice consent before sending spoken messages.")
    reply = await intake_service.handle_message(db, user, sess, body.message, body.channel, [h.model_dump() for h in body.history], tool_handler_for(db, user), body.client_turn_id)
    return IntakeReplyOut(**reply.__dict__)


@router.patch("/intake/sessions/{session_id}/fields", response_model=IntakeSnapshot)
def write_fields(session_id: str, body: FieldsIn, user: User = Depends(require_student), db: Session = Depends(get_db)) -> IntakeSnapshot:
    """Form entries are typed by the student, so they count as confirmed."""
    sess = own_session(db, user, session_id)
    for f in body.fields:
        try:
            value = validate(f.key, f.value)
        except FieldError as exc:
            raise ApiError(422, "INVALID_FIELD", str(exc), details={"key": f.key}) from exc
        intake_service.upsert(db, sess, f.key, value, "form", confirmed=True)
    db.commit()
    return snapshot(db, sess)


@router.post("/intake/sessions/{session_id}/fields/{key}/confirm", response_model=IntakeSnapshot)
def confirm_field(session_id: str, key: str, body: ConfirmFieldIn, user: User = Depends(require_student), db: Session = Depends(get_db)) -> IntakeSnapshot:
    sess = own_session(db, user, session_id)
    f = intake_service.fields_of(db, sess).get(key)
    if f is None:
        raise ApiError(404, "NOT_FOUND", "That field hasn't been recorded.")
    f.confirmed_by_student = body.confirmed
    db.commit()
    return snapshot(db, sess)


@router.delete("/intake/sessions/{session_id}/fields/{key}", response_model=IntakeSnapshot)
def delete_field(session_id: str, key: str, user: User = Depends(require_student), db: Session = Depends(get_db)) -> IntakeSnapshot:
    sess = own_session(db, user, session_id)
    f = intake_service.fields_of(db, sess).get(key)
    if f:
        db.delete(f)
        db.commit()
    return snapshot(db, sess)


@router.post("/intake/sessions/{session_id}/skip", response_model=IntakeSnapshot)
def skip_field(session_id: str, body: SkipIn, user: User = Depends(require_student), db: Session = Depends(get_db)) -> IntakeSnapshot:
    sess = own_session(db, user, session_id)
    if body.key not in FIELD_KEYS:
        raise ApiError(422, "INVALID_FIELD", "Unknown field.")
    sess.skipped_fields = sorted(set(sess.skipped_fields or []) | {body.key})
    db.commit()
    return snapshot(db, sess)


@router.post("/intake/sessions/{session_id}/safety/acknowledge", response_model=IntakeSnapshot)
def acknowledge_safety(session_id: str, user: User = Depends(require_student), db: Session = Depends(get_db)) -> IntakeSnapshot:
    """Student states they are not in an emergency and wants to continue. Recorded, never inferred."""
    sess = own_session(db, user, session_id)
    if sess.safety_state == "EMERGENCY_GUIDANCE":
        sess.safety_state = "GENERAL_SUPPORT"
        audit.record(db, actor_role="student", actor_id=user.id, subject_student_id=user.id, action="SAFETY_NOTICE_ACKNOWLEDGED", object_type="intake_session", object_id=sess.id)
        db.commit()
    return snapshot(db, sess)


# ---- consentful handoff to the assigned clinician ---------------------------

def _handoff_out(p: HandoffPacket) -> HandoffOut:
    return HandoffOut(packet_id=p.id, encounter_id=p.encounter_id, version=p.version, status=p.status, shared_at=p.student_approved_at, field_keys=[f["key"] for f in p.field_snapshot], attachment_ids=list(p.attachment_ids or []))


def _latest_packet(db: Session, encounter_id: str) -> HandoffPacket | None:
    return db.scalar(select(HandoffPacket).where(HandoffPacket.encounter_id == encounter_id).order_by(HandoffPacket.version.desc()))


@router.get("/students/me/encounters", response_model=list[StudentEncounterOut])
def my_encounters(user: User = Depends(require_student), db: Session = Depends(get_db)) -> list[StudentEncounterOut]:
    rows = db.execute(select(Encounter, User).join(User, Encounter.clinician_id == User.id).where(Encounter.student_id == user.id, Encounter.status != "CANCELLED").order_by(Encounter.starts_at)).all()
    out = []
    for enc, doc in rows:
        p = _latest_packet(db, enc.id)
        out.append(StudentEncounterOut(id=enc.id, appointment_id=enc.appointment_id, starts_at=to_local(enc.starts_at, user.timezone), visit_type=enc.visit_type, clinician_name=doc.display_name, status=enc.status, handoff=_handoff_out(p) if p else None, source_mode=enc.source_mode))
    return out


@router.post("/encounters/{encounter_id}/handoff", response_model=HandoffOut)
def handoff(encounter_id: str, body: HandoffIn, user: User = Depends(require_student), db: Session = Depends(get_db)) -> HandoffOut:
    enc = db.get(Encounter, encounter_id)
    if enc is None or enc.student_id != user.id or enc.status == "CANCELLED":
        raise ApiError(404, "NOT_FOUND", "Appointment not found.")
    if not body.student_authorized:
        raise ApiError(400, "AUTHORIZATION_REQUIRED", "Confirm that you want to share these details with your clinician.")
    sess = intake_service.current_session(db, user, create=False)
    if sess is None:
        raise ApiError(409, "NO_INTAKE", "There's nothing to share yet.")
    have = intake_service.fields_of(db, sess)
    chosen = []
    for key in dict.fromkeys(body.field_keys):
        f = have.get(key)
        if f is None:
            raise ApiError(422, "UNKNOWN_FIELD", "One of the selected details no longer exists.", details={"key": key})
        if not f.confirmed_by_student:
            raise ApiError(409, "FIELD_NOT_CONFIRMED", "Review and confirm each detail before sharing it.", details={"key": key})
        chosen.append(f)
    from app.models import Attachment

    for aid in body.attachment_ids:
        a = db.get(Attachment, aid)
        if a is None or a.student_id != user.id or a.session_id != sess.id:
            raise ApiError(422, "UNKNOWN_ATTACHMENT", "One of the selected photos no longer exists.")
    prev = _latest_packet(db, enc.id)
    packet = HandoffPacket(attachment_ids=list(dict.fromkeys(body.attachment_ids)),
        id=f"pkt_{uuid4().hex[:10]}", encounter_id=enc.id, session_id=sess.id, version=(prev.version + 1) if prev else 1,
        field_snapshot=[{"key": f.key, "label": LABELS[f.key], "value": f.value, "display": display(f.key, f.value), "provenance": f.provenance, "confirmed_by_student": True, "updated_at": f.updated_at.isoformat()} for f in chosen],
        source_mode="demo",
    )
    db.add(packet)
    if prev and prev.status == "SHARED":
        prev.status = "SUPERSEDED"
    sess.status = "SHARED"
    from_state, enc.status = enc.status, "INTAKE_SHARED"
    audit.record(db, actor_role="student", actor_id=user.id, subject_student_id=user.id, action="INTAKE_SHARED_WITH_CLINICIAN", object_type="encounter", object_id=enc.id, from_state=from_state, to_state="INTAKE_SHARED", detail=f"{len(chosen)} fields, {len(packet.attachment_ids)} photos, v{packet.version}")
    db.commit()
    return _handoff_out(packet)


@router.post("/handoffs/{packet_id}/withdraw", response_model=HandoffOut)
def withdraw(packet_id: str, user: User = Depends(require_student), db: Session = Depends(get_db)) -> HandoffOut:
    p = db.get(HandoffPacket, packet_id)
    enc = db.get(Encounter, p.encounter_id) if p else None
    if p is None or enc is None or enc.student_id != user.id:
        raise ApiError(404, "NOT_FOUND", "Shared intake not found.")
    if p.status == "SHARED":
        p.status, p.withdrawn_at = "WITHDRAWN", utcnow()
        enc.status = "UPCOMING"
        audit.record(db, actor_role="student", actor_id=user.id, subject_student_id=user.id, action="INTAKE_WITHDRAWN", object_type="encounter", object_id=enc.id, to_state="WITHDRAWN", detail="viewed by clinician before withdrawal" if p.clinician_viewed_at else None)
        db.commit()
    return _handoff_out(p)
