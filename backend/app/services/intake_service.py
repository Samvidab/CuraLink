"""Intake conversation orchestration: safety screen -> Claude (or scripted
fallback) -> validated draft fields. Shared by the text endpoint and the
voice WebSocket so both channels follow identical rules."""

import re
from dataclasses import dataclass, field
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import IntakeField, IntakeSession, User
from app.services import audit, llm_gateway, safety
from app.services.intake_fields import REQUESTED_FOR_HANDOFF, FieldError, extract, validate
from app.timeutil import utcnow

_APPOINTMENT = re.compile(r"\b(appointment|book|doctor|clinic|see (someone|a|the)|nurse|checkup|check-up|get seen|vaccin\w*)\b", re.I)
_ABSENCE = re.compile(r"\b(miss(ing)? (class|classes|lecture|lab)|absen\w+|excuse\w*|professor|instructor|note for)\b", re.I)
_SERVICES = re.compile(r"\b(what services|services does|offer)\b", re.I)
_MENTAL = re.compile(r"\b(mental health|counsel\w*|therap\w*|anxiety|stress|depress\w*)\b", re.I)
_BRING = re.compile(r"\b(what should i bring|bring to (my|the) appointment)\b", re.I)


@dataclass
class Reply:
    session_id: str
    assistant_message: str
    safety_state: str
    safety_category: str | None = None
    next_actions: list[str] = field(default_factory=list)
    tool_events: list[dict] = field(default_factory=list)
    field_updates: list[str] = field(default_factory=list)
    missing_fields: list[str] = field(default_factory=list)
    mode: str = "scripted"  # claude | scripted | safety


def current_session(db: Session, student: User, create: bool = True) -> IntakeSession | None:
    sess = db.scalar(
        select(IntakeSession).where(IntakeSession.student_id == student.id, IntakeSession.status == "OPEN").order_by(IntakeSession.created_at.desc())
    )
    if sess is None and create:
        sess = IntakeSession(id=f"ins_{uuid4().hex[:10]}", student_id=student.id, skipped_fields=[])
        db.add(sess)
        db.commit()
    return sess


def fields_of(db: Session, sess: IntakeSession) -> dict[str, IntakeField]:
    return {f.key: f for f in db.scalars(select(IntakeField).where(IntakeField.session_id == sess.id))}


def missing(db: Session, sess: IntakeSession) -> list[str]:
    have = fields_of(db, sess)
    skipped = set(sess.skipped_fields or [])
    return [k for k in REQUESTED_FOR_HANDOFF if k not in have and k not in skipped and not (k == "onset_text" and "onset_date" in have)]


def upsert(db: Session, sess: IntakeSession, key: str, value: dict, provenance: str, confirmed: bool) -> bool:
    """Returns True if the stored value changed. A changed value is unconfirmed
    again unless the student typed it directly."""
    have = fields_of(db, sess).get(key)
    if have is None:
        db.add(IntakeField(id=f"inf_{uuid4().hex[:10]}", session_id=sess.id, key=key, value=value, provenance=provenance, confirmed_by_student=confirmed, updated_at=utcnow()))
        changed = True
    else:
        if key == "symptoms_free_text" and provenance != "form" and value["text"] not in have.value.get("text", ""):
            value = {"text": f"{have.value['text']} / {value['text']}"[:1000]}
        changed = have.value != value
        if changed:
            have.value, have.provenance, have.updated_at = value, provenance, utcnow()
            have.confirmed_by_student = confirmed
        elif confirmed:
            have.confirmed_by_student = True
    if key in (sess.skipped_fields or []):
        sess.skipped_fields = [k for k in sess.skipped_fields if k != key]
    sess.updated_at = utcnow()
    return changed


def _apply_proposed(db: Session, sess: IntakeSession, proposed: list[dict], channel: str) -> list[str]:
    updated: list[str] = []
    for p in proposed:
        key = p.get("key")
        try:
            if key == "temperature":
                if p.get("temperature_unit") not in ("C", "F") or p.get("temperature_value") is None:
                    continue  # never guess a unit or value
                value = validate(key, {"value": p["temperature_value"], "unit": p["temperature_unit"]})
            else:
                value = validate(key, {"text": p.get("text") or ""})
        except FieldError:
            continue
        if upsert(db, sess, key, value, channel, confirmed=False):
            updated.append(key)
    return updated


def _scripted(text: str, updated: list[str], notes: list[str], miss: list[str], has_calendar: bool) -> tuple[str, list[str]]:
    actions: list[str] = []
    parts: list[str] = []
    if "temperature_unit_missing" in notes:
        parts.append("Was that temperature in °F or °C? I won't guess the unit.")
    if "temperature_out_of_range" in notes:
        parts.append("That temperature reading looks unusual — could you re-check it and enter it in the form?")
    if updated:
        parts.append("Thanks — I've added that to “What CuraLink knows” in your own words so you can review it.")
    if _BRING.search(text):
        parts.append("For this demo, bring your student ID, insurance card if you have one, a list of current medications, and any questions. Check the official health center site for the real requirements.")
    elif _MENTAL.search(text) and not updated:
        parts.append("Purdue students can explore counseling and psychological support through official campus resources. I can also show demo mental-health appointment times that fit your classes.")
        actions.append("FIND_CARE")
    elif _SERVICES.search(text):
        parts.append("For this demo, the campus health center may offer routine visits, vaccinations, mental health support and general consultations. Please verify current services on the official university health website.")
    if _APPOINTMENT.search(text) or (updated and "symptoms_free_text" in updated):
        actions.append("FIND_CARE")
        if not has_calendar:
            actions.append("IMPORT_CALENDAR")
            parts.append("Import your UniTime calendar and I'll only suggest demo appointment times that don't clash with classes.")
        else:
            parts.append("I can show demo appointment times that fit around your classes.")
    if _ABSENCE.search(text):
        actions.append("START_CASE")
        parts.append("For missed classes, your clinician decides whether to document an absence and for which dates — I'll help you share the details with them.")
    if miss and updated:
        ask = {"onset_text": "when it started", "temperature": "your temperature if you've measured it", "symptoms_free_text": "what you're experiencing"}
        parts.append(f"If you can, tell me {' and '.join(ask[m] for m in miss[:2])} — or use the form. You can skip anything.")
        actions.append("OPEN_INTAKE_FORM")
    if not parts:
        parts.append("I can help you describe what's going on for a clinician, find a demo appointment that fits your classes, and prepare absence paperwork for your clinician to review. I can't diagnose or decide how urgent something is.")
    return " ".join(parts), list(dict.fromkeys(actions))


async def handle_message(db: Session, student: User, sess: IntakeSession, text: str, channel: str, history: list[dict], tool_handler) -> Reply:
    text = (text or "").strip()[:2000]
    check = safety.screen(text)
    if check.state == "EMERGENCY_GUIDANCE":
        sess.safety_state = "EMERGENCY_GUIDANCE"
        audit.record(db, actor_role="system", actor_id=None, subject_student_id=student.id, action="SAFETY_ESCALATION_SHOWN", object_type="intake_session", object_id=sess.id, detail=check.category)
        db.commit()
        return Reply(sess.id, check.message or "", "EMERGENCY_GUIDANCE", check.category, ["EMERGENCY_HELP"], mode="safety")

    from app.models import Calendar  # local import keeps module import graph simple

    has_calendar = db.scalar(select(Calendar.id).where(Calendar.student_id == student.id)) is not None
    if llm_gateway.available():
        context = f"demo date {get_settings().demo_today.isoformat()}; calendar imported: {has_calendar}; channel: {channel}; missing intake fields: {', '.join(missing(db, sess)) or 'none'}"
        try:
            turn = await llm_gateway.run_turn(history, text, context, tool_handler)
            updated = _apply_proposed(db, sess, turn.proposed_fields, channel)
            reply_text, guarded = safety.guard_output(turn.text or "")
            if guarded:
                audit.record(db, actor_role="system", actor_id=None, subject_student_id=student.id, action="LLM_OUTPUT_GUARDED", object_type="intake_session", object_id=sess.id)
            miss = missing(db, sess)
            _, actions = _scripted(text, updated, [], miss, has_calendar)
            db.commit()
            return Reply(sess.id, reply_text or "Okay.", "GENERAL_SUPPORT", None, actions, turn.tool_events, updated, miss, "claude")
        except llm_gateway.LlmUnavailable as exc:
            audit.record(db, actor_role="system", actor_id=None, subject_student_id=student.id, action="LLM_FALLBACK", detail=str(exc)[:40])

    extracted, notes = extract(text)
    updated = [e.key for e in extracted if upsert(db, sess, e.key, e.value, channel, confirmed=False)]
    miss = missing(db, sess)
    reply_text, actions = _scripted(text, updated, notes, miss, has_calendar)
    db.commit()
    return Reply(sess.id, reply_text, "GENERAL_SUPPORT", None, actions, [], updated, miss, "scripted")

