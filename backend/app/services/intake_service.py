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
from app.services import audit, dialog, llm_gateway, safety
from app.services.intake_fields import REQUESTED_FOR_HANDOFF, FieldError, display, extract, validate
from app.timeutil import utcnow

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
    conversation_state: str = "GREETING"
    form: dict | None = None  # contextual form to open, e.g. {"fields": ["temperature"]}
    turn_id: str | None = None


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


def _field_displays(db: Session, sess: IntakeSession) -> dict[str, str]:
    return {k: display(k, f.value) for k, f in fields_of(db, sess).items()}


def _has_photo(db: Session, sess: IntakeSession) -> bool:
    from app.models import Attachment

    return db.scalar(select(Attachment.id).where(Attachment.session_id == sess.id)) is not None


def _remember(db: Session, sess: IntakeSession, conv: dict, client_turn_id: str | None, reply: "Reply") -> "Reply":
    if client_turn_id:
        cache = dict(conv.get("processed", {}))
        cache[client_turn_id] = {k: v for k, v in reply.__dict__.items()}
        conv["processed"] = dict(list(cache.items())[-10:])
    sess.conversation = dict(conv)  # reassign so SQLAlchemy persists the JSON change
    db.commit()
    return reply


async def handle_message(db: Session, student: User, sess: IntakeSession, text: str, channel: str, history: list[dict], tool_handler, client_turn_id: str | None = None) -> Reply:
    text = (text or "").strip()[:2000]
    conv = dict(sess.conversation or dialog.blank())
    if client_turn_id and client_turn_id in conv.get("processed", {}):
        return Reply(**conv["processed"][client_turn_id])  # duplicate submit / repeated speech event: same answer, no re-processing
    turn_id = client_turn_id or f"t{conv.get('turn', 0) + 1}"
    if sess.safety_state == "EMERGENCY_GUIDANCE":
        # Routine flow stays paused on every channel until the student acknowledges the notice.
        return Reply(sess.id, safety.EMERGENCY_MESSAGE, "EMERGENCY_GUIDANCE", None, ["EMERGENCY_HELP"], mode="safety", conversation_state=conv.get("state", "GREETING"), turn_id=turn_id)
    check = safety.screen(text)
    if check.state == "EMERGENCY_GUIDANCE":
        sess.safety_state = "EMERGENCY_GUIDANCE"
        audit.record(db, actor_role="system", actor_id=None, subject_student_id=student.id, action="SAFETY_ESCALATION_SHOWN", object_type="intake_session", object_id=sess.id, detail=check.category)
        return _remember(db, sess, conv, client_turn_id, Reply(sess.id, check.message or "", "EMERGENCY_GUIDANCE", check.category, ["EMERGENCY_HELP"], mode="safety", conversation_state=conv.get("state", "GREETING"), turn_id=turn_id))

    from app.models import Calendar  # local import keeps module import graph simple

    has_calendar = db.scalar(select(Calendar.id).where(Calendar.student_id == student.id)) is not None
    if llm_gateway.available():
        context = (f"demo date {get_settings().demo_today.isoformat()}; calendar imported: {has_calendar}; channel: {channel}; "
                   + dialog.context_for_model(conv, _field_displays(db, sess)))
        try:
            turn = await llm_gateway.run_turn(history, text, context, tool_handler)
            updated = _apply_proposed(db, sess, turn.proposed_fields, channel)
            reply_text, guarded = safety.guard_output(turn.text or "")
            if guarded:
                audit.record(db, actor_role="system", actor_id=None, subject_student_id=student.id, action="LLM_OUTPUT_GUARDED", object_type="intake_session", object_id=sess.id)
            # The dialog manager still tracks state/declines and supplies actions; Claude supplies the words.
            plan = dialog.plan(conv, text, updated, _field_displays(db, sess), _has_photo(db, sess), has_calendar, [])
            conv["state"] = plan.state
            reply_text = dialog.avoid_repeat(conv, reply_text or plan.text, plan.text)
            actions = list(dict.fromkeys(turn.ui_actions + plan.actions))
            reply = Reply(sess.id, reply_text, "GENERAL_SUPPORT", None, actions, turn.tool_events, updated, missing(db, sess), "claude", plan.state, plan.form, turn_id)
            return _remember(db, sess, conv, client_turn_id, reply)
        except llm_gateway.LlmUnavailable as exc:
            audit.record(db, actor_role="system", actor_id=None, subject_student_id=student.id, action="LLM_FALLBACK", detail=str(exc)[:40])

    extracted, notes = extract(text)
    # A short direct answer to "When did this start?" is the onset, in the student's own words.
    if conv.get("pending") == "onset_text" and not any(e.key == "onset_text" for e in extracted) and len(text) <= 80 and not dialog.DECLINE.search(text):
        from app.services.intake_fields import Extracted

        extracted = [e for e in extracted if e.key != "symptoms_free_text"] + [Extracted("onset_text", {"text": text})]
    updated = [e.key for e in extracted if upsert(db, sess, e.key, e.value, channel, confirmed=False)]
    db.flush()
    plan = dialog.plan(conv, text, updated, _field_displays(db, sess), _has_photo(db, sess), has_calendar, notes)
    conv["state"] = plan.state
    text_out = _resources(text) if not updated and not plan.pending and plan.state == "COLLECTING_INITIAL_CONCERN" and _resources(text) else plan.text
    text_out = dialog.avoid_repeat(conv, text_out, "Would you like to review your information, find an appointment, or add something else?")
    reply = Reply(sess.id, text_out, "GENERAL_SUPPORT", None, plan.actions, [], updated, missing(db, sess), "scripted", plan.state, plan.form, turn_id)
    return _remember(db, sess, conv, client_turn_id, reply)


def _resources(text: str) -> str | None:
    """General campus-navigation answers (non-diagnostic)."""
    if _BRING.search(text):
        return "For this demo, bring your student ID, insurance card if you have one, a list of current medications, and any questions. Check the official health center site for the real requirements."
    if _MENTAL.search(text):
        return "Purdue students can explore counseling and psychological support through official campus resources. I can also show demo mental-health appointment times that fit your classes."
    if _SERVICES.search(text):
        return "For this demo, the campus health center may offer routine visits, vaccinations, mental health support and general consultations. Please verify current services on the official university health website."
    return None

