"""Bridge to Convex: (1) RS256 tokens so browsers can read their authorized records from Convex, and
(2) an after-commit outbox that pushes authorized PROJECTIONS of committed records to Convex.

The FastAPI database stays the transactional system of record (booking locks, consent gates, signing policy).
Convex holds a persistent synchronized copy for real-time views. Projections never include password hashes,
session tokens, sign nonces, signature images, PDF bytes or photo bytes, and each carries its access list:
  studentId     -> the owning student may read it
  clinicianIds  -> clinicians currently authorized (assigned to an ACTIVE appointment, consent in effect)
"""

import base64
import hashlib
import json
import logging
import queue
import threading
import time
from collections.abc import Iterable

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from sqlalchemy import event, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import (
    AbsenceCase, Appointment, AvailabilityException, AvailabilityRule, ClinicalEvaluation, ClinicianAbsenceDecision, ClinicianProfile,
    ClinicSlot, Delivery, DocumentVersion, Encounter, HandoffPacket, IntakeSession, SignAuthorization, User,
)
from app.timeutil import as_utc

log = logging.getLogger("curalink.convex")
AUDIENCE = "curalink-convex"
TOKEN_TTL = 600


# ---- tokens ------------------------------------------------------------------------------------------------

def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


_key: rsa.RSAPrivateKey | None = None


def signing_key() -> rsa.RSAPrivateKey:
    """Generated once and kept in SECRETS_DIR (persistent volume in production, git-ignored locally)."""
    global _key
    if _key is None:
        pem = get_settings().convex_jwt_private_key
        path = get_settings().secrets_dir / "convex_jwt.pem"
        if pem:
            _key = serialization.load_pem_private_key(pem.replace("\\n", "\n").encode(), password=None)  # type: ignore[assignment]
        elif path.exists():
            _key = serialization.load_pem_private_key(path.read_bytes(), password=None)  # type: ignore[assignment]
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            _key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
            path.write_bytes(_key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
            path.chmod(0o600)
    return _key  # type: ignore[return-value]


def _public_numbers() -> tuple[str, str, str]:
    nums = signing_key().public_key().public_numbers()
    n = nums.n.to_bytes((nums.n.bit_length() + 7) // 8, "big")
    e = nums.e.to_bytes((nums.e.bit_length() + 7) // 8, "big")
    return _b64(n), _b64(e), hashlib.sha256(n).hexdigest()[:16]


def jwks() -> dict:
    n, e, kid = _public_numbers()
    return {"keys": [{"kty": "RSA", "n": n, "e": e, "alg": "RS256", "use": "sig", "kid": kid}]}


def issuer() -> str:
    s = get_settings()
    return (s.convex_jwt_issuer or s.public_api_url or "http://127.0.0.1:8000").rstrip("/")


def jwks_data_uri() -> str:
    """The PUBLIC key set as a data: URI for Convex's CURALINK_JWKS (contains no secret)."""
    return "data:text/plain;charset=utf-8;base64," + base64.b64encode(json.dumps(jwks()).encode()).decode()


def mint(user: User, now: int | None = None) -> str:
    now = now or int(time.time())
    _, _, kid = _public_numbers()
    header = {"alg": "RS256", "typ": "JWT", "kid": kid}
    payload = {"iss": issuer(), "sub": user.id, "aud": AUDIENCE, "iat": now, "exp": now + TOKEN_TTL, "role": user.role}
    signing_input = f"{_b64(json.dumps(header, separators=(',', ':')).encode())}.{_b64(json.dumps(payload, separators=(',', ':')).encode())}"
    sig = signing_key().sign(signing_input.encode(), padding.PKCS1v15(), hashes.SHA256())
    return f"{signing_input}.{_b64(sig)}"


# ---- projections -------------------------------------------------------------------------------------------

def _iso(dt) -> str | None:
    return as_utc(dt).isoformat() if dt is not None else None


def _rec(table: str, rid: str, student_id: str | None, clinicians: Iterable[str | None], data: dict, clinician_only: dict | None = None, deleted: bool = False) -> dict:
    r = {"table": table, "recordId": rid, "clinicianIds": sorted({c for c in clinicians if c}), "data": data, "deleted": deleted}
    if student_id:
        r["studentId"] = student_id
    if clinician_only is not None:
        r["clinicianOnly"] = clinician_only
    return r


def _active_clinician(enc: Encounter | None) -> list[str]:
    return [enc.clinician_id] if enc is not None and enc.status != "CANCELLED" else []


def project(db: Session, kind: str, rid: str) -> list[dict]:
    """Current authorized projection(s) for one changed row, plus rows whose access depends on it."""
    out: list[dict] = []
    if kind == "users":
        u = db.get(User, rid)
        if u:
            out.append(_rec("users", u.id, u.id if u.role == "student" else None, [], {
                "role": u.role, "displayName": u.display_name, "firstName": u.first_name, "lastName": u.last_name, "preferredName": u.preferred_name,
                "credentials": u.credentials, "clinicalRole": u.clinical_role, "verified": bool(u.clinician_verified)}))
    elif kind == "clinicianProfiles":
        p, u = db.get(ClinicianProfile, rid), db.get(User, rid)
        if p and u:
            rules = db.scalars(select(AvailabilityRule).where(AvailabilityRule.clinician_id == rid)).all()
            excs = db.scalars(select(AvailabilityException).where(AvailabilityException.clinician_id == rid)).all()
            out.append(_rec("clinicianProfiles", rid, None, [], {
                "name": u.display_name, "credentials": u.credentials, "specialty": p.specialty, "clinicName": p.clinic_name, "location": p.location,
                "timezone": p.timezone, "appointmentTypes": p.appointment_types, "accepting": bool(p.accepting) and bool(u.clinician_verified),
                "weeklyHours": [{"weekday": r.weekday, "start": r.start_time, "end": r.end_time} for r in rules],
                "exceptions": [{"from": e.start_date.isoformat(), "to": e.end_date.isoformat(), "kind": e.kind, "start": e.start_time, "end": e.end_time} for e in excs]}))
    elif kind == "appointments":
        a = db.get(Appointment, rid)
        if a:
            slot = db.get(ClinicSlot, a.slot_id)
            enc = db.scalar(select(Encounter).where(Encounter.appointment_id == a.id))
            out.append(_rec("appointments", a.id, a.student_id, _active_clinician(enc) if a.state == "DEMO_CONFIRMED" else [], {
                "state": a.state, "clinicianId": a.clinician_id, "appointmentType": a.appointment_type, "startsAt": _iso(slot.starts_at) if slot else None,
                "endsAt": _iso(slot.ends_at) if slot else None, "clinicName": slot.clinic_name if slot else None, "location": slot.location if slot else None,
                "purpose": a.purpose, "purposeConfirmed": bool(a.purpose_confirmed), "absenceRequested": bool(a.absence_requested),
                "caseId": enc.id if enc else None, "caseStatus": enc.status if enc else None, "intakeSessionId": a.intake_session_id}))
    elif kind == "intakeSessions":
        s = db.get(IntakeSession, rid)
        if s:  # the student's own conversation metadata; never visible to clinicians (drafts are private)
            out.append(_rec("intakeSessions", s.id, s.student_id, [], {
                "status": s.status, "startedAt": _iso(s.created_at), "endedAt": _iso(s.ended_at), "conversationState": (s.conversation or {}).get("state"),
                "purposeSuggestion": s.purpose, "absenceRequested": bool(s.absence_requested)}))
    elif kind == "previsitSummaries":
        p = db.get(HandoffPacket, rid)
        if p:
            enc = db.get(Encounter, p.encounter_id) if p.encounter_id else None
            student = p.student_id or (enc.student_id if enc else None)
            shared = p.status == "SHARED"
            from app.services import previsit

            out.append(_rec("previsitSummaries", p.id, student, _active_clinician(enc) if shared else [], {
                "sessionId": p.session_id, "version": p.version, "status": p.status, "submittedAt": _iso(p.student_approved_at), "caseId": p.encounter_id,
                "consentText": p.consent_text if shared else None, "summary": previsit.summary_of(db, p) if shared else None,
                "attachmentIds": list(p.attachment_ids or []) if shared else []}))
    elif kind == "clinicianFindings":
        ev = db.get(ClinicalEvaluation, rid)
        enc = db.get(Encounter, ev.encounter_id) if ev else None
        if ev and enc:
            out.append(_rec("clinicianFindings", ev.id, enc.student_id, _active_clinician(enc), {"caseId": enc.id, "updatedAt": _iso(ev.updated_at)},
                            {"values": ev.values, "clinicianId": ev.clinician_id}))
    elif kind == "absenceCases":
        c = db.get(AbsenceCase, rid)
        enc = db.get(Encounter, c.encounter_id) if c else None
        if c:
            out.append(_rec("absenceCases", c.id, c.student_id, _active_clinician(enc), {
                "status": c.status, "origin": c.origin or "student", "caseId": c.encounter_id, "reportedMissedDates": list(c.reported_missed_dates or []),
                "consent": {"given": bool(c.disclosure_consent and c.consent_revoked_at is None), "at": _iso(c.disclosure_consent_at), "revokedAt": _iso(c.consent_revoked_at)}},
                {"studentNote": c.student_note}))
    elif kind == "absenceDecisions":
        d = db.get(ClinicianAbsenceDecision, rid)
        c = db.get(AbsenceCase, d.case_id) if d else None
        enc = db.get(Encounter, c.encounter_id) if c else None
        if d and c:
            out.append(_rec("absenceDecisions", d.id, c.student_id, _active_clinician(enc), {
                "absenceCaseId": c.id, "decision": d.decision, "startDate": d.start_date.isoformat() if d.start_date else None,
                "endDate": d.end_date.isoformat() if d.end_date else None, "version": d.version, "decidedBy": d.clinician_id, "decidedAt": _iso(d.created_at)},
                {"rationalePrivate": d.rationale_private, "wording": d.wording}))
    elif kind == "documentVersions":
        v = db.get(DocumentVersion, rid)
        c = db.get(AbsenceCase, v.case_id) if v else None
        enc = db.get(Encounter, c.encounter_id) if c else None
        if v and c:
            auth = db.scalar(select(SignAuthorization).where(SignAuthorization.version_id == v.id))
            out.append(_rec("documentVersions", v.id, c.student_id, _active_clinician(enc), {
                "absenceCaseId": c.id, "version": v.version, "state": v.state, "unsignedSha256": v.unsigned_sha256, "signedSha256": v.signed_sha256,
                "signedAt": _iso(v.signed_at), "signedBy": auth.clinician_id if auth else None, "signatureAuthorizationId": auth.id if auth else None}))
    elif kind == "deliveries":
        d = db.get(Delivery, rid)
        c = db.get(AbsenceCase, d.case_id) if d else None
        enc = db.get(Encounter, c.encounter_id) if c else None
        if d and c:
            out.append(_rec("deliveries", d.id, c.student_id, _active_clinician(enc), {
                "absenceCaseId": c.id, "versionId": d.version_id, "courseCode": d.course_code, "deliveredTo": d.destination,
                "intendedRecipient": d.intended_recipient, "simulated": bool(d.intended_recipient), "state": d.state, "errorCode": d.error_code, "sentAt": _iso(d.sent_at)}))
    return out


def _related(db: Session, cls_name: str, obj) -> list[tuple[str, str]]:
    """Which projections a changed row affects (its own, and anything whose access depends on it)."""
    pk = str(getattr(obj, "id", "") or getattr(obj, "clinician_id", ""))
    if cls_name == "User":
        keys = [("users", obj.id)] + ([("clinicianProfiles", obj.id)] if obj.role == "clinician" else [])
    elif cls_name == "ClinicianProfile":
        keys = [("clinicianProfiles", obj.clinician_id)]
    elif cls_name in ("AvailabilityRule", "AvailabilityException"):
        keys = [("clinicianProfiles", obj.clinician_id)]
    elif cls_name == "Appointment":
        keys = [("appointments", obj.id)]
    elif cls_name == "ClinicSlot":
        keys = [("appointments", a) for a in db.scalars(select(Appointment.id).where(Appointment.slot_id == obj.id))]
    elif cls_name == "Encounter":  # access for everything attached to the case follows the encounter
        keys = ([("appointments", obj.appointment_id)] if obj.appointment_id else [])
        keys += [("previsitSummaries", p) for p in db.scalars(select(HandoffPacket.id).where(HandoffPacket.encounter_id == obj.id))]
        keys += [("clinicianFindings", e) for e in db.scalars(select(ClinicalEvaluation.id).where(ClinicalEvaluation.encounter_id == obj.id))]
        for cid in db.scalars(select(AbsenceCase.id).where(AbsenceCase.encounter_id == obj.id)):
            keys.append(("absenceCases", cid))
            keys += [("absenceDecisions", d) for d in db.scalars(select(ClinicianAbsenceDecision.id).where(ClinicianAbsenceDecision.case_id == cid))]
            keys += [("documentVersions", v) for v in db.scalars(select(DocumentVersion.id).where(DocumentVersion.case_id == cid))]
            keys += [("deliveries", d) for d in db.scalars(select(Delivery.id).where(Delivery.case_id == cid))]
    elif cls_name == "SignAuthorization":
        keys = [("documentVersions", obj.version_id)]
    else:
        keys = [(KIND[cls_name], pk)]
    return keys


KIND = {"User": "users", "ClinicianProfile": "clinicianProfiles", "Appointment": "appointments", "IntakeSession": "intakeSessions",
        "HandoffPacket": "previsitSummaries", "ClinicalEvaluation": "clinicianFindings", "AbsenceCase": "absenceCases",
        "ClinicianAbsenceDecision": "absenceDecisions", "DocumentVersion": "documentVersions", "Delivery": "deliveries"}
WATCHED = set(KIND) | {"AvailabilityRule", "AvailabilityException", "ClinicSlot", "Encounter", "SignAuthorization"}


# ---- outbox ------------------------------------------------------------------------------------------------

def enabled() -> bool:
    s = get_settings()
    return bool(s.convex_site_url and s.convex_sync_secret)


def post(records: list[dict], reset_all: bool = False) -> None:
    """Authenticated batches to the Convex HTTP action. Swappable in tests."""
    s = get_settings()
    batches = [records[i:i + 400] for i in range(0, len(records), 400)] or [[]]
    for n, batch in enumerate(batches):
        r = httpx.post(f"{s.convex_site_url.rstrip('/')}/curalink/sync", json={"records": batch, "resetAll": reset_all and n == 0},
                       headers={"Authorization": f"Bearer {s.convex_sync_secret}"}, timeout=30)
        r.raise_for_status()


_queue: "queue.Queue[tuple[set[tuple[str, str]], set[tuple[str, str]]]]" = queue.Queue()
_worker: threading.Thread | None = None
STATUS: dict = {"last_ok": None, "last_error": None, "pending": 0, "pushed": 0}


def push_keys(keys: set[tuple[str, str]], deleted: set[tuple[str, str]] = frozenset(), reset_all: bool = False) -> int:
    from app import db as dbmod

    gen = dbmod.get_db()
    db = next(gen)
    try:
        records = [r for kind, rid in sorted(keys) for r in project(db, kind, rid)]
        records += [_rec(kind, rid, None, [], {}, deleted=True) for kind, rid in deleted if kind in KIND.values() and (kind, rid) not in keys]
    finally:
        gen.close()
    if records or reset_all:
        post(records, reset_all=reset_all)
    return len(records)


def _run() -> None:
    while True:
        keys, deleted = _queue.get()
        while not _queue.empty():  # coalesce bursts
            k, d = _queue.get_nowait()
            keys |= k
            deleted |= d
        for attempt in range(4):
            try:
                STATUS["pushed"] += push_keys(keys, deleted)
                STATUS["last_ok"], STATUS["pending"] = time.time(), _queue.qsize()
                break
            except Exception as exc:  # never log record contents or secrets
                STATUS["last_error"] = f"{type(exc).__name__} at {time.strftime('%H:%M:%S')}"
                log.warning("Convex sync attempt %d failed (%s); %d records pending", attempt + 1, type(exc).__name__, len(keys))
                time.sleep(2 ** attempt)


def _after_flush(session: Session, _ctx) -> None:
    # In after_flush the session still lists the pre-flush new/dirty/deleted objects (rows are written already).
    pending = session.info.setdefault("convex_keys", set())
    gone = session.info.setdefault("convex_deleted", set())
    deleted = set(session.deleted)
    with session.no_autoflush:
        for obj in list(session.new) + list(session.dirty) + list(deleted):
            name = type(obj).__name__
            if name not in WATCHED:
                continue
            try:
                if obj in deleted and name in KIND:
                    gone.add((KIND[name], str(obj.clinician_id if name == "ClinicianProfile" else obj.id)))
                else:
                    pending.update(_related(session, name, obj))
            except Exception:
                log.exception("Convex sync: couldn't compute related records")


def _after_commit(session: Session) -> None:
    keys, gone = session.info.pop("convex_keys", set()), session.info.pop("convex_deleted", set())
    if not (keys or gone):
        return
    if get_settings().convex_sync_inline:
        # Serverless: no background thread survives the response, so push now (failures are recorded, never raised;
        # an admin resync repairs any gap).
        try:
            STATUS["pushed"] += push_keys(set(keys), set(gone))
            STATUS["last_ok"] = time.time()
        except Exception as exc:
            STATUS["last_error"] = f"{type(exc).__name__} at {time.strftime('%H:%M:%S')}"
            log.warning("Convex inline sync failed (%s); %d records not pushed", type(exc).__name__, len(keys))
        return
    _queue.put((set(keys), set(gone)))


def _after_rollback(session: Session) -> None:
    session.info.pop("convex_keys", None)
    session.info.pop("convex_deleted", None)


def install() -> None:
    """Start the outbox (idempotent). Called at startup only when Convex sync is configured."""
    global _worker
    if not event.contains(Session, "after_flush", _after_flush):
        event.listen(Session, "after_flush", _after_flush)
        event.listen(Session, "after_commit", _after_commit)
        event.listen(Session, "after_rollback", _after_rollback)
    if get_settings().convex_sync_inline:
        return
    if _worker is None or not _worker.is_alive():
        _worker = threading.Thread(target=_run, name="convex-sync", daemon=True)
        _worker.start()


def all_keys(db: Session) -> set[tuple[str, str]]:
    keys: set[tuple[str, str]] = set()
    for cls, kind in ((User, "users"), (Appointment, "appointments"), (IntakeSession, "intakeSessions"), (HandoffPacket, "previsitSummaries"),
                      (ClinicalEvaluation, "clinicianFindings"), (AbsenceCase, "absenceCases"), (ClinicianAbsenceDecision, "absenceDecisions"),
                      (DocumentVersion, "documentVersions"), (Delivery, "deliveries")):
        keys |= {(kind, i) for i in db.scalars(select(cls.id))}
    keys |= {("clinicianProfiles", i) for i in db.scalars(select(ClinicianProfile.clinician_id))}
    return keys


def full_sync(reset_all: bool = False) -> int:
    """Push every current projection (startup, after a demo reset, or `python -m app.admin convex-sync`).
    reset_all clears Convex's copy first, so records deleted by a demo reset don't linger there."""
    from app import db as dbmod

    gen = dbmod.get_db()
    db = next(gen)
    try:
        keys = all_keys(db)
    finally:
        gen.close()
    return push_keys(keys, reset_all=reset_all)
