"""Wire contracts (Pydantic v2). Datetimes go out as ISO 8601 with offsets."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

SourceMode = Literal["demo", "uploaded", "real"]
Role = Literal["student", "clinician"]


class IntegrationStatus(BaseModel):
    clinic_inventory: Literal["demo"] = "demo"
    email_delivery: Literal["test_only"] = "test_only"
    llm: Literal["live", "fallback", "error"]
    voice: Literal["live", "fallback"]


class Health(BaseModel):
    status: Literal["ok"] = "ok"
    demo_mode: bool
    demo_today: str
    integrations: IntegrationStatus
    llm_detail: dict | None = None  # sanitized last Claude failure: category, http_status, error_type, message
    convex: dict | None = None  # sync status (enabled, last success/error time); never URLs or secrets


class DemoResetOut(BaseModel):
    student_id: str
    source_mode: SourceMode = "demo"


class DemoPersona(BaseModel):
    role: Role
    display_name: str
    email: str
    note: str


class DemoLoginIn(BaseModel):
    persona: Role


class LoginIn(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(min_length=1, max_length=200)
    expected_role: Role | None = None


class MeOut(BaseModel):
    id: str
    role: Role
    display_name: str
    email: str
    timezone: str
    demo: bool
    credentials: str | None = None
    permissions: list[str]
    first_name: str | None = None
    last_name: str | None = None
    preferred_name: str | None = None
    clinical_role: str | None = None
    profile_complete: bool = False


class ProfileIn(BaseModel):
    first_name: str = Field(max_length=80)
    last_name: str = Field(max_length=80)
    preferred_name: str | None = Field(None, max_length=80)


class RegisterIn(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(min_length=8, max_length=200)


class ClinicianRegisterIn(RegisterIn):
    first_name: str = Field(max_length=80)
    last_name: str = Field(max_length=80)
    credentials: str = Field(min_length=1, max_length=80)
    clinical_role: str = Field(min_length=1, max_length=80)


class CourseOut(BaseModel):
    id: str
    code: str
    section: str | None
    term: str | None = None
    title: str | None
    instructor_name: str | None
    instructor_email: str | None
    contact_status: Literal["VERIFIED", "NEEDS_REVIEW", "MISSING", "STUDENT_CONFIRMED"]
    provenance: str
    color: str | None


class CalendarEventOut(BaseModel):
    id: str
    course_id: str | None
    course_code: str | None
    title: str
    start_at: datetime
    end_at: datetime
    location: str | None
    all_day: bool
    kind: str
    term: str | None = None
    rescheduled: bool
    source: SourceMode | str


class CalendarSummary(BaseModel):
    calendar_id: str
    source_mode: SourceMode | str
    filename: str | None
    timezone: str
    imported_at: datetime
    events_imported: int
    warnings: list[str]


class CalendarImportOut(BaseModel):
    calendar_id: str
    events_imported: int
    courses: list[CourseOut]
    timezone: str
    warnings: list[str]
    source_mode: SourceMode | str


class CalendarEventsOut(BaseModel):
    events: list[CalendarEventOut]
    timezone: str
    calendar: CalendarSummary | None
    term: str | None = None


class ActivityOut(BaseModel):
    id: int
    event_type: str
    actor: str
    object_type: str | None
    object_id: str | None
    from_state: str | None
    to_state: str | None
    status: str
    detail: str | None
    source_mode: str
    at: datetime


class AppointmentSummary(BaseModel):
    id: str
    state: str
    clinician_id: str | None = None
    clinician_name: str | None = None
    appointment_type: str
    clinic_name: str
    location: str
    starts_at: datetime
    ends_at: datetime
    source_mode: SourceMode | str
    purpose: str | None = None
    purpose_confirmed: bool = False
    absence_requested: bool = False
    external_booking: bool = False


class StudentDashboard(BaseModel):
    today: str
    term: str | None = None
    timezone: str
    display_name: str
    calendar: CalendarSummary | None
    courses: list[CourseOut]
    todays_classes: list[CalendarEventOut]
    next_appointment: AppointmentSummary | None
    activity: list[ActivityOut]


class EncounterRow(BaseModel):
    id: str
    student_name: str
    starts_at: datetime
    visit_type: str
    status: str
    status_label: str
    source_mode: str


class ClinicianDashboard(BaseModel):
    previsit_notes: list[dict] = Field(default_factory=list)
    today: str
    display_name: str
    appointments_today: int
    intakes_to_review: int
    absence_cases: int
    encounters: list[EncounterRow]


class EncounterDetail(EncounterRow):
    student_id: str
    student_email: str
    appointment_id: str | None
    purpose: str | None = None  # student's stated reason (detail view only; list rows stay symptom-free)
    purpose_confirmed: bool = False  # False for older bookings whose purpose wasn't confirmed by the student
    absence_requested: bool = False  # requested by the student; never an approval
    ends_at: datetime | None = None
    location: str | None = None


class SchedulePreferences(BaseModel):
    avoid_class_conflicts: bool = True
    allow_conflicts: bool = False
    max_travel_minutes: int | None = Field(None, ge=0, le=240)
    earliest_hour: int | None = Field(None, ge=0, le=23)
    latest_hour: int | None = Field(None, ge=1, le=24)


class BlockIn(BaseModel):
    start_at: datetime
    end_at: datetime
    label: str = Field("Personal block", min_length=1, max_length=60)


class IntakeFieldOut(BaseModel):
    key: str
    label: str
    value: dict
    display: str
    provenance: str
    confirmed_by_student: bool
    updated_at: datetime


class IntakeSnapshot(BaseModel):
    session_id: str
    status: str
    safety_state: str
    voice_consent: bool
    transcription_consent: bool
    photo_consent: bool
    fields: list[IntakeFieldOut]
    missing_fields: list[str]
    skipped_fields: list[str]
    conversation_state: str = "GREETING"
    declined: list[str] = Field(default_factory=list)  # student chose not to say
    unknown: list[str] = Field(default_factory=list)  # student said they don't know / haven't measured
    transcript: list[dict] = Field(default_factory=list)  # this conversation's on-screen messages (student only)
    started_at: datetime | None = None
    ended_at: datetime | None = None
    chief_concern: str | None = None
    purpose: str | None = None
    absence_requested: bool = False
    summary: dict | None = None  # latest submitted pre-visit summary for this session (status, version, sharing target)
    linked_encounter_id: str | None = None  # appointment booked from this conversation, if any
    suggested_appointment_type: str | None = None  # from what the conversation is about; the student can change it


class ConsentIn(BaseModel):
    voice_consent: bool | None = None
    transcription_consent: bool | None = None
    photo_consent: bool | None = None


class HistoryItem(BaseModel):
    role: Literal["user", "assistant"]
    text: str = Field(max_length=4000)


class IntakeMessageIn(BaseModel):
    session_id: str | None = None
    message: str = Field(min_length=1, max_length=2000)
    channel: Literal["text", "voice"] = "text"
    client_turn_id: str | None = Field(None, max_length=64)
    history: list[HistoryItem] = Field(default_factory=list, max_length=20)


class IntakeReplyOut(BaseModel):
    session_id: str
    assistant_message: str
    safety_state: Literal["GENERAL_SUPPORT", "EMERGENCY_GUIDANCE"]
    safety_category: str | None
    next_actions: list[str]
    tool_events: list[dict]
    field_updates: list[str]
    missing_fields: list[str]
    mode: Literal["claude", "scripted", "safety"]
    conversation_state: str = "GREETING"
    form: dict | None = None
    turn_id: str | None = None
    fallback_reason: dict | None = None  # why Claude wasn't used for this reply (if a key is configured)
    schedule: dict | None = None  # real clinician + time options (selectable in the chat)


class FieldWrite(BaseModel):
    key: str
    value: dict


class FieldsIn(BaseModel):
    fields: list[FieldWrite] = Field(min_length=1, max_length=10)


class ConfirmFieldIn(BaseModel):
    confirmed: bool


class SkipIn(BaseModel):
    key: str


class HandoffIn(BaseModel):
    student_authorized: bool
    field_keys: list[str] = Field(default_factory=list, max_length=10)
    attachment_ids: list[str] = Field(default_factory=list, max_length=5)


class SummarySubmitIn(HandoffIn):
    include_purpose: bool = False  # the student's own stated reason for the visit
    include_absence_request: bool = False  # whether they asked about absence documentation (a request, not an approval)
    encounter_id: str | None = None  # empty: the appointment booked from this conversation, else the next one booked


class HandoffOut(BaseModel):
    attachment_ids: list[str] = Field(default_factory=list)
    packet_id: str
    encounter_id: str | None
    session_id: str | None = None
    consent_text: str | None = None
    clinician_name: str | None = None
    version: int
    status: str
    shared_at: datetime
    field_keys: list[str]


class StudentEncounterOut(BaseModel):
    id: str
    appointment_id: str | None
    starts_at: datetime
    visit_type: str
    clinician_name: str
    status: str
    handoff: HandoffOut | None
    source_mode: str


class ClinicianIntakeOut(BaseModel):
    encounter_id: str
    status: Literal["NOT_SHARED", "SHARED", "WITHDRAWN"]
    packet_id: str | None
    version: int | None
    shared_at: datetime | None
    fields: list[IntakeFieldOut]
    consent: dict[str, bool]
    attachments: list[dict] = Field(default_factory=list)
    annotations: dict[str, dict] = Field(default_factory=dict)
    summary: dict | None = None  # structured AI-assisted pre-visit summary (student-reported only)
    session: dict | None = None  # which conversation it came from, and when
    consent_text: str | None = None


class VoiceSessionIn(BaseModel):
    voice_consent: bool


class VoiceSessionOut(BaseModel):
    session_id: str
    mode: Literal["cartesia", "browser"]
    stream_path: str | None
    stream_url: str | None = None  # absolute wss:// URL with a single-use ticket when the API is on another host
    input: dict
    output: dict
    note: str
