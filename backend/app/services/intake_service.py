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
from app.services import names as profile_names
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
    fallback_reason: dict | None = None
    schedule: dict | None = None  # REAL clinician + time options from the scheduling backend


def current_session(db: Session, student: User, create: bool = True) -> IntakeSession | None:
    sess = db.scalar(
        select(IntakeSession).where(IntakeSession.student_id == student.id, IntakeSession.status == "OPEN").order_by(IntakeSession.created_at.desc())
    )
    if sess is None and create:
        sess = IntakeSession(id=f"ins_{uuid4().hex[:10]}", student_id=student.id, skipped_fields=[])
        db.add(sess)
        db.commit()
    return sess


def close_untranscribed_sessions(db: Session) -> int:
    """Upgrade step: conversations started before transcripts were kept can't be shown on reopening, so continuing
    them would silently reuse old answers. End them (nothing is deleted); the student's next visit starts fresh."""
    n = 0
    for sess in db.scalars(select(IntakeSession).where(IntakeSession.status == "OPEN")).all():
        conv = sess.conversation or {}
        if conv.get("turn", 0) > 0 and "transcript" not in conv:
            sess.status, sess.ended_at = "CLOSED", sess.ended_at or sess.updated_at
            n += 1
    if n:
        db.commit()
    return n


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


def _schedule_context(db: Session, student: User):
    from app.models import Appointment
    from app.services import availability

    names = [(p.clinician_id, availability.profile_out(db, p)["name"]) for p in availability.active_profiles(db)]
    last = db.scalar(select(Appointment.clinician_id).where(Appointment.student_id == student.id, Appointment.clinician_id.is_not(None)).order_by(Appointment.created_at.desc()))
    return names, last


def _appointment_type_for(conv: dict, sched: dict) -> str:
    if sched.get("appointment_type"):
        return sched["appointment_type"]
    concerns = set(conv.get("concerns", []))
    return "general_consultation" if "symptom" in concerns else "routine_checkup"


def _run_search(db: Session, student: User, conv: dict, sched: dict) -> dict:
    from datetime import date as _date

    from app.routers.scheduling import SearchIn, search

    req = SearchIn(appointment_type=_appointment_type_for(conv, sched), clinician_id=sched.get("clinician_id"), attribute=sched.get("attribute"),
                   start=_date.fromisoformat(sched["start"]) if sched.get("start") else None, days=sched.get("days", 5),
                   part_of_day=sched.get("part_of_day", "any"), sort=sched.get("sort", "best"), per_clinician=4)
    result = search(db, student, req)
    result["options"] = result["options"][:6]
    return result


def _field_displays(db: Session, sess: IntakeSession) -> dict[str, str]:
    return {k: display(k, f.value) for k, f in fields_of(db, sess).items()}


def _has_photo(db: Session, sess: IntakeSession) -> bool:
    from app.models import Attachment

    return db.scalar(select(Attachment.id).where(Attachment.session_id == sess.id)) is not None


TRANSCRIPT_LIMIT = 80


def _remember(db: Session, sess: IntakeSession, conv: dict, client_turn_id: str | None, reply: "Reply", text: str = "", channel: str = "text") -> "Reply":
    if client_turn_id:
        cache = dict(conv.get("processed", {}))
        cache[client_turn_id] = {k: v for k, v in reply.__dict__.items()}
        conv["processed"] = dict(list(cache.items())[-10:])
    # What was said on screen in THIS conversation (text and voice alike), so reopening shows it instead of a
    # blank chat silently continuing. Shown only to the student; never part of a clinician summary.
    now = utcnow().isoformat()
    conv["transcript"] = (list(conv.get("transcript", [])) + [
        {"from": "user", "text": text, "channel": channel, "at": now},
        {"from": "ai", "text": reply.assistant_message, "actions": reply.next_actions, "form": reply.form, "had_schedule": bool(reply.schedule), "at": now},
    ])[-TRANSCRIPT_LIMIT:]
    sess.chief_concern = conv.get("chief_concern") or sess.chief_concern
    sess.purpose = conv.get("purpose") or sess.purpose
    sess.absence_requested = bool(conv.get("absence_requested")) or bool(sess.absence_requested)
    sess.updated_at = utcnow()
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
        return _remember(db, sess, conv, client_turn_id, Reply(sess.id, check.message or "", "EMERGENCY_GUIDANCE", check.category, ["EMERGENCY_HELP"], mode="safety", conversation_state=conv.get("state", "GREETING"), turn_id=turn_id), text, channel)

    from app.models import Calendar  # local import keeps module import graph simple

    has_calendar = db.scalar(select(Calendar.id).where(Calendar.student_id == student.id)) is not None
    dialog.note_context(conv, text)
    names, last = _schedule_context(db, student)
    sched = dialog.scheduling_intent(conv, text, names, get_settings().demo_today, last)  # uses the PREVIOUS state
    live = llm_gateway.available()
    fallback_reason = None if live else (llm_gateway.detail() if get_settings().anthropic_api_key else None)

    # 1) Deterministic extraction. Scripted mode stores it; Claude mode only uses it to decide the next step
    #    (Claude's own validated proposals are what get stored).
    extracted, notes = extract(text)
    looks_like_onset = bool(dialog.TIME_WORDS.search(text)) or not dialog.describes_concern(text)  # "swollen and bruised" isn't a time
    if conv.get("pending") == "onset_text" and not any(e.key == "onset_text" for e in extracted) and len(text) <= 80 and not dialog.DECLINE.search(text) and looks_like_onset:
        from app.services.intake_fields import Extracted

        # A short direct answer to "When did this start?" is the onset, in the student's own words.
        extracted = [e for e in extracted if e.key != "symptoms_free_text"] + [Extracted("onset_text", {"text": text})]
    if live:
        updated = [e.key for e in extracted]
        displays = {**_field_displays(db, sess), **{e.key: display(e.key, e.value) for e in extracted}}
    else:
        updated = [e.key for e in extracted if upsert(db, sess, e.key, e.value, channel, confirmed=False)]
        db.flush()
        displays = _field_displays(db, sess)

    # 2) ONE decision for both modes: which follow-up and which structured component (temperature card,
    #    photo card, scheduling cards). Made before Claude speaks so its words match what's on screen.
    plan = dialog.plan(conv, text, updated, displays, _has_photo(db, sess), has_calendar, notes)
    conv["state"] = plan.state
    actions, form = list(plan.actions), plan.form
    schedule = None
    if sched is not None:
        schedule = _run_search(db, student, conv, sched)  # real lookup against stored availability
        conv["state"] = "COORDINATING_APPOINTMENT"
        offers = [a for a in actions if a in (dialog.OFFER_TEMPERATURE, dialog.OFFER_PHOTO)]
        if not offers:  # a pure scheduling turn: no pending follow-up
            conv["pending"], form = None, None
        actions = list(dict.fromkeys([dialog.SCHEDULING, *offers] + ([] if has_calendar else ["IMPORT_CALENDAR"])))

    if live:
        name = profile_names.address_name(student)
        context = (f"demo date {get_settings().demo_today.isoformat()}; calendar imported: {has_calendar}; channel: {channel}; "
                   + (f"student's preferred name: {name}; " if name else "")
                   + dialog.context_for_model(conv, _field_displays(db, sess)) + " " + dialog.directive(plan)
                   + (" Real appointment options are on screen as clinician cards; summarize them briefly." if schedule else ""))
        tool_handler.sched_type = _appointment_type_for(conv, sched or {})
        try:
            turn = await llm_gateway.run_turn(history, text, context, tool_handler)
            claude_updated = _apply_proposed(db, sess, turn.proposed_fields, channel)
            reply_text, guarded = safety.guard_output(turn.text or "")
            if guarded:
                audit.record(db, actor_role="system", actor_id=None, subject_student_id=student.id, action="LLM_OUTPUT_GUARDED", object_type="intake_session", object_id=sess.id)
            reply_text = dialog.avoid_repeat(conv, reply_text or plan.text, plan.text)
            schedule = schedule or getattr(tool_handler, "last_schedule", None)
            extra = [a for a in turn.ui_actions if a in (dialog.SCHEDULING, "START_CASE", "IMPORT_CALENDAR")]
            if schedule:
                conv["state"] = "COORDINATING_APPOINTMENT"
                extra.append(dialog.SCHEDULING)
            actions = list(dict.fromkeys(actions + extra))
            reply = Reply(sess.id, reply_text, "GENERAL_SUPPORT", None, actions, turn.tool_events, claude_updated, missing(db, sess), "claude", conv["state"], form, turn_id, None, schedule)
            return _remember(db, sess, conv, client_turn_id, reply, text, channel)
        except llm_gateway.LlmUnavailable as exc:
            audit.record(db, actor_role="system", actor_id=None, subject_student_id=student.id, action="LLM_FALLBACK", detail=str(exc)[:40])
            fallback_reason = llm_gateway.detail() or {"category": str(exc), "http_status": None, "error_type": None, "message": ""}
            # Same decision, scripted words: store what the deterministic extractor found.
            updated = [e.key for e in extracted if upsert(db, sess, e.key, e.value, channel, confirmed=False)]

    text_out = _resources(text) if not updated and not plan.pending and plan.state == "COLLECTING_INITIAL_CONCERN" and _resources(text) else plan.text
    if schedule is not None:  # the reply text summarises what the backend actually returned
        ack = dialog._ack(updated, _field_displays(db, sess))
        follow = plan.text if form else ""
        text_out = " ".join(x for x in (ack, dialog.describe_schedule(schedule, sched or {}), follow if follow != ack else "") if x)
    text_out = dialog.avoid_repeat(conv, text_out, "Would you like to review your information, find an appointment, or add something else?")
    reply = Reply(sess.id, text_out, "GENERAL_SUPPORT", None, actions, [], updated, missing(db, sess), "scripted", conv["state"], form, turn_id, fallback_reason, schedule)
    return _remember(db, sess, conv, client_turn_id, reply, text, channel)


def _resources(text: str) -> str | None:
    """General campus-navigation answers (non-diagnostic)."""
    if _BRING.search(text):
        return "For this demo, bring your student ID, insurance card if you have one, a list of current medications, and any questions. Check the official health center site for the real requirements."
    if _MENTAL.search(text):
        return "Purdue students can explore counseling and psychological support through official campus resources. I can also show demo mental-health appointment times that fit your classes."
    if _SERVICES.search(text):
        return "For this demo, the campus health center may offer routine visits, vaccinations, mental health support and general consultations. Please verify current services on the official university health website."
    return None

