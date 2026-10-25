"""ORM models mirroring TRD §4 and the v1.2 amendment (§16).

Datetimes are stored as UTC via the `DateTime` decorator below, which
normalises aware values on write and returns aware UTC values on read.
"""

from datetime import UTC, date, datetime

from sqlalchemy import JSON, Boolean, Date, ForeignKey, Index, Integer, LargeBinary, String, Text, UniqueConstraint, text
from sqlalchemy.types import DateTime as _DateTime, TypeDecorator
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.timeutil import utcnow


class DateTime(TypeDecorator):
    """Stores UTC; always returns tz-aware UTC. Rejects naive input so a local
    wall-clock time can never be mistaken for UTC."""

    impl = _DateTime
    cache_ok = True

    def __init__(self, timezone: bool = True):
        super().__init__(timezone=False)

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("naive datetime passed to a UTC column")
        return value.astimezone(UTC).replace(tzinfo=None)

    def process_result_value(self, value, dialect):
        return None if value is None else value.replace(tzinfo=UTC)


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    role: Mapped[str] = mapped_column(String)  # student | clinician (server-assigned, never client-set)
    display_name: Mapped[str] = mapped_column(String)
    email: Mapped[str] = mapped_column(String, unique=True)
    password_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    timezone: Mapped[str] = mapped_column(String, default="America/Indiana/Indianapolis")
    consent_version: Mapped[str | None] = mapped_column(String, nullable=True)
    clinician_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    credentials: Mapped[str | None] = mapped_column(String, nullable=True)
    demo: Mapped[bool] = mapped_column(Boolean, default=True)
    # Profile names (app/services/names.py). display_name stays the formal name shown to clinicians/students.
    first_name: Mapped[str | None] = mapped_column(String, nullable=True)
    last_name: Mapped[str | None] = mapped_column(String, nullable=True)
    preferred_name: Mapped[str | None] = mapped_column(String, nullable=True)
    clinical_role: Mapped[str | None] = mapped_column(String, nullable=True)  # self-described at sign-up; not a verification


class AuthSession(Base):
    __tablename__ = "auth_sessions"

    token_hash: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Course(Base):
    __tablename__ = "courses"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    student_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    code: Mapped[str] = mapped_column(String)
    section: Mapped[str | None] = mapped_column(String, nullable=True)
    term: Mapped[str | None] = mapped_column(String, nullable=True)  # e.g. "Fall 2026" (inferred from meeting dates)
    title: Mapped[str | None] = mapped_column(String, nullable=True)
    instructor_name: Mapped[str | None] = mapped_column(String, nullable=True)
    instructor_email: Mapped[str | None] = mapped_column(String, nullable=True)
    # VERIFIED | NEEDS_REVIEW | MISSING. Emails are never synthesized.
    contact_status: Mapped[str] = mapped_column(String, default="MISSING")
    provenance: Mapped[str] = mapped_column(String, default="ics")  # ics | demo_catalog | manual
    color: Mapped[str | None] = mapped_column(String, nullable=True)


class Calendar(Base):
    __tablename__ = "calendars"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    student_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    source_mode: Mapped[str] = mapped_column(String)  # demo | uploaded
    filename: Mapped[str | None] = mapped_column(String, nullable=True)
    timezone: Mapped[str] = mapped_column(String)
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    events_imported: Mapped[int] = mapped_column(Integer, default=0)
    warnings: Mapped[list] = mapped_column(JSON, default=list)
    selected_term: Mapped[str | None] = mapped_column(String, nullable=True)  # student's chosen semester view


class CalendarEvent(Base):
    __tablename__ = "calendar_events"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    calendar_id: Mapped[str] = mapped_column(ForeignKey("calendars.id", ondelete="CASCADE"))
    student_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    uid: Mapped[str] = mapped_column(String)
    course_id: Mapped[str | None] = mapped_column(ForeignKey("courses.id", ondelete="SET NULL"), nullable=True)
    summary: Mapped[str] = mapped_column(String)
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    tzid: Mapped[str | None] = mapped_column(String, nullable=True)
    location: Mapped[str | None] = mapped_column(String, nullable=True)
    recurrence_id: Mapped[str | None] = mapped_column(String, nullable=True)
    all_day: Mapped[bool] = mapped_column(Boolean, default=False)
    kind: Mapped[str] = mapped_column(String, default="class")  # class | personal_block
    source: Mapped[str] = mapped_column(String)  # demo | uploaded | manual
    term: Mapped[str | None] = mapped_column(String, nullable=True)


class ClinicSlot(Base):
    """A BOOKED clinician interval (created at confirmation). Candidate times are generated from availability rules.
    The partial unique index blocks two active bookings for one clinician at the same start; overlapping
    starts are rejected inside the booking transaction (services/availability.book)."""

    __tablename__ = "clinic_slots"
    __table_args__ = (Index("uq_clinician_active_start", "clinician_id", "starts_at", unique=True, sqlite_where=text("status = 'BOOKED'")),)

    id: Mapped[str] = mapped_column(String, primary_key=True)
    clinic_id: Mapped[str] = mapped_column(String)
    clinic_name: Mapped[str] = mapped_column(String)
    location: Mapped[str] = mapped_column(String)
    appointment_type: Mapped[str] = mapped_column(String)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    travel_minutes: Mapped[int] = mapped_column(Integer, default=10)
    clinician_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    status: Mapped[str] = mapped_column(String, default="AVAILABLE")  # AVAILABLE | BOOKED | UNAVAILABLE
    permitted: Mapped[bool] = mapped_column(Boolean, default=True)
    source_mode: Mapped[str] = mapped_column(String, default="demo")


class Appointment(Base):
    __tablename__ = "appointments"
    __table_args__ = (UniqueConstraint("student_id", "idempotency_key"),)

    id: Mapped[str] = mapped_column(String, primary_key=True)
    student_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    slot_id: Mapped[str] = mapped_column(ForeignKey("clinic_slots.id"))
    clinician_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)  # the clinician the student chose
    appointment_type: Mapped[str | None] = mapped_column(String, nullable=True)
    state: Mapped[str] = mapped_column(String)  # DEMO_CONFIRMED | CANCELLED
    confirmation_mode: Mapped[str] = mapped_column(String, default="demo")
    idempotency_key: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    # Booking context. purpose = the student's own stated reason (never inferred symptoms); an absence request
    # is only a request, never an approval. The case (Encounter) links appointment, clinician and summaries.
    intake_session_id: Mapped[str | None] = mapped_column(ForeignKey("intake_sessions.id"), nullable=True)
    purpose: Mapped[str | None] = mapped_column(Text, nullable=True)
    absence_requested: Mapped[bool | None] = mapped_column(Boolean, nullable=True)


class Encounter(Base):
    __tablename__ = "encounters"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    student_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    clinician_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    appointment_id: Mapped[str | None] = mapped_column(ForeignKey("appointments.id"), nullable=True)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    visit_type: Mapped[str] = mapped_column(String)
    # UPCOMING | INTAKE_SHARED | CLINICIAN_REVIEW | COMPLETED | CANCELLED
    status: Mapped[str] = mapped_column(String, default="UPCOMING")
    source_mode: Mapped[str] = mapped_column(String, default="demo")


class AuditEvent(Base):
    """Workflow trace. Never stores symptom narratives, documents or secrets."""

    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    actor_role: Mapped[str] = mapped_column(String)  # student | clinician | system
    actor_id: Mapped[str | None] = mapped_column(String, nullable=True)
    subject_student_id: Mapped[str | None] = mapped_column(String, nullable=True)
    action: Mapped[str] = mapped_column(String)
    object_type: Mapped[str | None] = mapped_column(String, nullable=True)
    object_id: Mapped[str | None] = mapped_column(String, nullable=True)
    from_state: Mapped[str | None] = mapped_column(String, nullable=True)
    to_state: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, default="ok")
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_mode: Mapped[str] = mapped_column(String, default="demo")
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class IntakeSession(Base):
    """One structured intake conversation. Raw transcripts and audio are NOT
    stored; only structured fields the student can review and correct."""

    __tablename__ = "intake_sessions"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    student_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    status: Mapped[str] = mapped_column(String, default="OPEN")  # OPEN | CLOSED (legacy rows may say SHARED)
    safety_state: Mapped[str] = mapped_column(String, default="GENERAL_SUPPORT")
    voice_consent: Mapped[bool] = mapped_column(Boolean, default=False)
    transcription_consent: Mapped[bool] = mapped_column(Boolean, default=False)
    photo_consent: Mapped[bool] = mapped_column(Boolean, default=False)
    skipped_fields: Mapped[list] = mapped_column(JSON, default=list)
    # Dialog state (services/dialog.py) plus the on-screen message list for this conversation, so reopening shows
    # what was actually said instead of silently continuing. Never shared with clinicians; no audio is stored.
    conversation: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)  # conversation start (UTC)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    chief_concern: Mapped[str | None] = mapped_column(Text, nullable=True)  # the student's first description, verbatim
    purpose: Mapped[str | None] = mapped_column(Text, nullable=True)  # student's stated reason for an appointment, verbatim
    absence_requested: Mapped[bool | None] = mapped_column(Boolean, nullable=True)  # student asked about absence documentation


class IntakeField(Base):
    __tablename__ = "intake_fields"
    __table_args__ = (UniqueConstraint("session_id", "key"),)

    id: Mapped[str] = mapped_column(String, primary_key=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("intake_sessions.id", ondelete="CASCADE"))
    key: Mapped[str] = mapped_column(String)
    value: Mapped[dict] = mapped_column(JSON)  # typed payload, e.g. {"text": ...} or {"value": 38.4, "unit": "C"}
    provenance: Mapped[str] = mapped_column(String)  # voice | text | form | photo_observation | clinician
    confirmed_by_student: Mapped[bool] = mapped_column(Boolean, default=False)
    observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class HandoffPacket(Base):
    """AI-assisted pre-visit summary: an immutable, versioned snapshot of ONE conversation session that the
    student reviewed and authorized. Versions are per session (v1, v2 … after corrections); older versions are
    kept as SUPERSEDED, never edited. encounter_id is empty until the student has an appointment: approving
    before booking is allowed, and booking attaches it. The clinician's access follows the encounter's
    assigned clinician, so a legitimate reassignment moves access with it (audited)."""

    __tablename__ = "handoff_packets"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    encounter_id: Mapped[str | None] = mapped_column(ForeignKey("encounters.id", ondelete="CASCADE"), nullable=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("intake_sessions.id"))
    student_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    field_snapshot: Mapped[list] = mapped_column(JSON)
    summary: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # structured pre-visit summary (services/previsit.py)
    consent_text: Mapped[str | None] = mapped_column(Text, nullable=True)  # exactly what the student agreed to
    status: Mapped[str] = mapped_column(String, default="SHARED")  # SHARED | SUPERSEDED | WITHDRAWN
    student_approved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    clinician_viewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    withdrawn_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attachment_ids: Mapped[list] = mapped_column(JSON, default=list)  # photos the student chose to share
    source_mode: Mapped[str] = mapped_column(String, default="demo")


class AbsenceCase(Base):
    """STUDENT_REQUESTED -> CLINICIAN_REVIEW -> DATES_SET -> PENDING_CLINICIAN_SIGNATURE -> SIGNED
    -> DELIVERY_QUEUED -> SENT | FAILED, with REJECTED / REVOKED branches (TRD §16).
    University excusal status is never tracked: it is independent and unknown."""

    __tablename__ = "absence_cases"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    student_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    encounter_id: Mapped[str] = mapped_column(ForeignKey("encounters.id"))
    status: Mapped[str] = mapped_column(String, default="STUDENT_REQUESTED")
    # LEGACY: older student requests carried a date range. Students no longer choose dates; these stay only so
    # old rows remain readable (shown as "student-reported", never as certified). Certified dates live ONLY in
    # ClinicianAbsenceDecision, which only the assigned clinician's routes can write.
    requested_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    requested_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    reported_missed_dates: Mapped[list | None] = mapped_column(JSON, nullable=True)  # student-reported class absences (factual)
    student_note: Mapped[str | None] = mapped_column(Text, nullable=True)  # clinician-only; never in professor messages
    origin: Mapped[str | None] = mapped_column(String, nullable=True)  # student | clinician (NULL = student, older rows)
    disclosure_consent: Mapped[bool] = mapped_column(Boolean, default=False)
    disclosure_consent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    consent_revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ClinicianAbsenceDecision(Base):
    __tablename__ = "clinician_absence_decisions"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("absence_cases.id", ondelete="CASCADE"))
    clinician_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    decision: Mapped[str] = mapped_column(String)  # CERTIFY | DECLINE (no certificate indicated) | DEFER
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    wording: Mapped[str | None] = mapped_column(Text, nullable=True)
    rationale_private: Mapped[str | None] = mapped_column(Text, nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class DocumentVersion(Base):
    """Immutable rendered document. Any edit creates a new version (prior approval void)."""

    __tablename__ = "document_versions"
    __table_args__ = (UniqueConstraint("case_id", "version"),)

    id: Mapped[str] = mapped_column(String, primary_key=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("absence_cases.id", ondelete="CASCADE"))
    decision_id: Mapped[str] = mapped_column(ForeignKey("clinician_absence_decisions.id"))
    version: Mapped[int] = mapped_column(Integer)
    content: Mapped[dict] = mapped_column(JSON)  # dates, wording, courses, messages, recipients
    unsigned_pdf: Mapped[bytes] = mapped_column(LargeBinary)
    unsigned_sha256: Mapped[str] = mapped_column(String)
    signed_pdf: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    signed_sha256: Mapped[str | None] = mapped_column(String, nullable=True)
    state: Mapped[str] = mapped_column(String, default="UNSIGNED")  # UNSIGNED | SIGNED | SUPERSEDED | REVOKED
    rendering_template_version: Mapped[str] = mapped_column(String, default="attendance-v1")
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    signed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SignatureAsset(Base):
    """Demo: a generated, watermarked sample only. A stored asset never signs or sends by itself."""

    __tablename__ = "signature_assets"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    clinician_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String, default="demo_sample")  # demo_sample | drawn
    # CURALINK_CONFIG: SIGNATURE_STORAGE
    # Drawn signatures are stored here, AES-GCM encrypted (app/services/signature_vault.py), never as plain
    # images and never in browser storage. Production: move blobs to a managed secret/object store.
    encrypted_blob: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    mime_type: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SignNonce(Base):
    __tablename__ = "sign_nonces"

    nonce: Mapped[str] = mapped_column(String, primary_key=True)
    clinician_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    version_id: Mapped[str] = mapped_column(ForeignKey("document_versions.id", ondelete="CASCADE"))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SignAuthorization(Base):
    __tablename__ = "sign_authorizations"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    clinician_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    version_id: Mapped[str] = mapped_column(ForeignKey("document_versions.id", ondelete="CASCADE"))
    signature_asset_id: Mapped[str] = mapped_column(ForeignKey("signature_assets.id"))
    document_sha256: Mapped[str] = mapped_column(String)
    approved_destinations_hash: Mapped[str] = mapped_column(String)
    approved_destinations: Mapped[list] = mapped_column(JSON)
    nonce: Mapped[str] = mapped_column(String, unique=True)
    approved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Delivery(Base):
    __tablename__ = "deliveries"
    __table_args__ = (UniqueConstraint("version_id", "destination"),)

    id: Mapped[str] = mapped_column(String, primary_key=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("absence_cases.id", ondelete="CASCADE"))
    version_id: Mapped[str] = mapped_column(ForeignKey("document_versions.id", ondelete="CASCADE"))
    course_code: Mapped[str] = mapped_column(String)
    destination: Mapped[str] = mapped_column(String)
    state: Mapped[str] = mapped_column(String, default="QUEUED")  # QUEUED | SENT | FAILED | CANCELLED
    idempotency_key: Mapped[str] = mapped_column(String)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    error_code: Mapped[str | None] = mapped_column(String, nullable=True)
    receipt_id: Mapped[str | None] = mapped_column(String, nullable=True)
    queued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class TestInboxMessage(Base):
    """The demo transport's destination: a local inbox, never a real mail server."""

    __tablename__ = "test_inbox"
    __test__ = False  # not a pytest class

    id: Mapped[str] = mapped_column(String, primary_key=True)
    delivery_id: Mapped[str] = mapped_column(ForeignKey("deliveries.id", ondelete="CASCADE"))
    to: Mapped[str] = mapped_column(String)
    subject: Mapped[str] = mapped_column(String)
    body: Mapped[str] = mapped_column(Text)
    attachment_name: Mapped[str] = mapped_column(String)
    attachment_sha256: Mapped[str] = mapped_column(String)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Attachment(Base):
    """Student photo, metadata-stripped on upload. Deletable; shared only if selected in a handoff."""

    __tablename__ = "attachments"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("intake_sessions.id", ondelete="CASCADE"))
    student_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    media_type: Mapped[str] = mapped_column(String, default="image/png")
    data: Mapped[bytes] = mapped_column(LargeBinary)
    sha256: Mapped[str] = mapped_column(String)
    quality: Mapped[dict] = mapped_column(JSON)
    observations: Mapped[list] = mapped_column(JSON)
    limitations: Mapped[list] = mapped_column(JSON)
    observer: Mapped[str] = mapped_column(String)
    synthetic_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class IntakeAnnotation(Base):
    """Clinician review of a shared field. The student's original value is never overwritten."""

    __tablename__ = "intake_annotations"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    packet_id: Mapped[str] = mapped_column(ForeignKey("handoff_packets.id", ondelete="CASCADE"))
    field_key: Mapped[str] = mapped_column(String)
    clinician_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    decision: Mapped[str] = mapped_column(String)  # accepted | corrected | rejected
    corrected_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ClinicalEvaluation(Base):
    """Clinician-entered findings for an encounter. Clinician-only: never shown to students or professors."""

    __tablename__ = "clinical_evaluations"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    encounter_id: Mapped[str] = mapped_column(ForeignKey("encounters.id", ondelete="CASCADE"), unique=True)
    clinician_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    values: Mapped[dict] = mapped_column(JSON, default=dict)  # keys from curalink_config.EXAMINATION_FIELDS
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ClinicianProfile(Base):
    # CURALINK_CONFIG: CLINICIAN_PROFILE_DATA
    # Loaded from sample_data/demo_users.json ("profile" on each clinician) by app/seed.py. Specialty, clinic,
    # supported appointment types and optional SELF-REPORTED attributes (never inferred from names/photos).
    __tablename__ = "clinician_profiles"

    clinician_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    specialty: Mapped[str] = mapped_column(String)
    clinic_id: Mapped[str] = mapped_column(String)
    clinic_name: Mapped[str] = mapped_column(String)
    location: Mapped[str | None] = mapped_column(String, nullable=True)
    travel_minutes: Mapped[int] = mapped_column(Integer, default=10)
    timezone: Mapped[str] = mapped_column(String, default="America/Indiana/Indianapolis")
    appointment_types: Mapped[list] = mapped_column(JSON, default=list)
    attributes: Mapped[dict] = mapped_column(JSON, default=dict)  # {"gender": {"value": ..., "source": ...}}
    bio: Mapped[str | None] = mapped_column(Text, nullable=True)
    photo_url: Mapped[str | None] = mapped_column(String, nullable=True)
    accepting: Mapped[bool] = mapped_column(Boolean, default=True)


class AvailabilityRule(Base):
    """Weekly recurring working hours (local to the clinician's timezone)."""

    __tablename__ = "availability_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    clinician_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    weekday: Mapped[int] = mapped_column(Integer)  # 0 = Monday
    start_time: Mapped[str] = mapped_column(String)  # "HH:MM"
    end_time: Mapped[str] = mapped_column(String)
    effective_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)


class AvailabilityException(Base):
    """Date-specific change: 'unavailable' (whole day if no times; vacations via end_date) or 'extra' hours."""

    __tablename__ = "availability_exceptions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    clinician_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    kind: Mapped[str] = mapped_column(String)  # unavailable | extra
    start_time: Mapped[str | None] = mapped_column(String, nullable=True)
    end_time: Mapped[str | None] = mapped_column(String, nullable=True)
    reason: Mapped[str | None] = mapped_column(String, nullable=True)
