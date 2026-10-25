// Mirrors backend/app/schemas.py. Keep in sync with the API contract.

export type Role = 'student' | 'clinician'
export type SourceMode = 'demo' | 'uploaded' | 'real'
export type ContactStatus = 'VERIFIED' | 'NEEDS_REVIEW' | 'MISSING' | 'STUDENT_CONFIRMED'

export interface Health {
  status: 'ok'
  demo_mode: boolean
  demo_today: string
  integrations: { clinic_inventory: 'demo'; email_delivery: 'test_only'; llm: 'live' | 'fallback' | 'error'; voice: 'live' | 'fallback' }
  llm_detail?: LlmError | null
}

export interface Me {
  id: string
  role: Role
  display_name: string
  email: string
  timezone: string
  demo: boolean
  credentials: string | null
  permissions: string[]
  first_name: string | null
  last_name: string | null
  preferred_name: string | null
  clinical_role: string | null
  profile_complete: boolean
}

export interface DemoPersona { role: Role; display_name: string; email: string; note: string }

export interface Course {
  id: string
  code: string
  section: string | null
  term?: string | null
  title: string | null
  instructor_name: string | null
  instructor_email: string | null
  contact_status: ContactStatus
  provenance: string
  color: string | null
}

export interface CalendarEvent {
  id: string
  course_id: string | null
  course_code: string | null
  title: string
  start_at: string
  end_at: string
  location: string | null
  all_day: boolean
  kind: string
  term?: string | null
  rescheduled: boolean
  source: SourceMode
}

export interface CalendarSummary {
  calendar_id: string
  source_mode: SourceMode
  filename: string | null
  timezone: string
  imported_at: string
  events_imported: number
  warnings: string[]
}

export interface CalendarImport {
  calendar_id: string
  events_imported: number
  courses: Course[]
  timezone: string
  warnings: string[]
  source_mode: SourceMode
}

export interface CalendarEvents { events: CalendarEvent[]; timezone: string; calendar: CalendarSummary | null; term?: string | null }

export interface Activity {
  id: number
  event_type: string
  actor: string
  object_type: string | null
  object_id: string | null
  from_state: string | null
  to_state: string | null
  status: string
  detail: string | null
  source_mode: string
  at: string
}

export interface AppointmentSummary {
  id: string
  state: string
  clinician_id?: string | null
  clinician_name?: string | null
  appointment_type: string
  clinic_name: string
  location: string
  starts_at: string
  ends_at: string
  source_mode: SourceMode
  external_booking: boolean
  purpose?: string | null
  purpose_confirmed?: boolean
  absence_requested?: boolean
}

export interface StudentDashboard {
  today: string
  term?: string | null
  timezone: string
  display_name: string
  calendar: CalendarSummary | null
  courses: Course[]
  todays_classes: CalendarEvent[]
  next_appointment: AppointmentSummary | null
  activity: Activity[]
}

export interface EncounterRow {
  id: string
  student_name: string
  starts_at: string
  visit_type: string
  status: string
  status_label: string
  source_mode: string
}

export interface ClinicianDashboard {
  previsit_notes?: { encounter_id: string; student_name: string; appointment_at: string; sessions: number; latest_submitted_at: string }[]
  today: string
  display_name: string
  appointments_today: number
  intakes_to_review: number
  absence_cases: number
  encounters: EncounterRow[]
}

export interface EncounterDetail extends EncounterRow { student_id: string; student_email: string; appointment_id: string | null; purpose?: string | null; absence_requested?: boolean; ends_at?: string | null; location?: string | null }

export interface ConfirmResult { appointment_id: string; status: string; external_booking: boolean; appointment: AppointmentSummary; message: string; case_id?: string | null; intake_session_id?: string | null; purpose?: string | null; absence_requested?: boolean }

export type Provenance = 'voice' | 'text' | 'form' | 'photo_observation' | 'clinician'
export interface IntakeField { key: string; label: string; value: Record<string, unknown>; display: string; provenance: Provenance; confirmed_by_student: boolean; updated_at: string }
export interface IntakeSnapshot {
  session_id: string
  status: string
  safety_state: 'GENERAL_SUPPORT' | 'EMERGENCY_GUIDANCE'
  voice_consent: boolean
  transcription_consent: boolean
  photo_consent: boolean
  fields: IntakeField[]
  missing_fields: string[]
  skipped_fields: string[]
  conversation_state?: string
  declined?: string[]
  unknown?: string[]
  transcript?: TranscriptItem[]
  started_at?: string | null
  ended_at?: string | null
  chief_concern?: string | null
  purpose?: string | null
  absence_requested?: boolean
  summary?: SummaryStatus | null
  linked_encounter_id?: string | null
  suggested_appointment_type?: string | null
}
export interface TranscriptItem { from: 'user' | 'ai'; text: string; at: string; channel?: string; actions?: string[]; form?: { fields: string[] } | null; had_schedule?: boolean }
/** Student-reported pre-visit summary of ONE conversation (backend services/previsit.py). Never a diagnosis. */
export interface PreVisitSummary {
  session_id: string; session_started_at: string | null; chief_concern: string | null; symptoms: string[]; onset: string | null
  measurements: { key: string; label: string; value: number | null; unit: string | null; display: string; source: string }[]
  other: { key: string; label: string; display: string }[]
  photos: { attachment_id: string; observer: string; synthetic_demo: boolean; ai_generated: boolean; observations: PhotoAttachment['observations']; limitations: string[] }[]
  not_known: string[]; declined: string[]; follow_ups?: { key: string; question: string; answer: string }[]; reason_for_visit: string | null; absence_documentation: 'REQUESTED' | 'NOT_REQUESTED' | 'NOT_SHARED'; disclaimer: string
}
export interface SummaryStatus { packet_id: string; version: number; status: 'SHARED' | 'SUPERSEDED' | 'WITHDRAWN'; shared_at: string; encounter_id: string | null; appointment_cancelled?: boolean; session_id?: string; started_at?: string; clinician_name: string | null; appointment_at: string | null; field_keys: string[]; attachment_ids: string[]; summary: PreVisitSummary }
export interface HistorySession {
  session_id: string; label: string; started_at: string; ended_at: string | null; local_date: string; status: string; status_label: string; version: number; packet_id: string; submitted_at: string
  versions: { version: number; status: string; submitted_at: string }[]; consent_text: string | null; summary: PreVisitSummary | null
  appointment: { encounter_id: string; starts_at: string; visit_type: string; purpose: string | null } | null
}
export interface PreVisitHistory { student_id: string; timezone: string; latest_session_id: string | null; groups: { date: string; sessions: HistorySession[] }[] }
export interface ToolEvent { tool: string; label: string; status: string }
export interface IntakeReply {
  session_id: string
  assistant_message: string
  safety_state: 'GENERAL_SUPPORT' | 'EMERGENCY_GUIDANCE'
  safety_category: string | null
  next_actions: string[]
  tool_events: ToolEvent[]
  field_updates: string[]
  missing_fields: string[]
  mode: 'claude' | 'scripted' | 'safety'
  conversation_state?: string
  form?: { fields: string[] } | null
  turn_id?: string | null
  fallback_reason?: LlmError | null
  schedule?: ScheduleResult | null
}
export interface LlmError { category: string; http_status: number | null; error_type: string | null; message: string }
export interface VoiceSessionInfo { session_id: string; mode: 'cartesia' | 'browser'; stream_path: string | null; input: { encoding: string; sample_rate: number; chunk_ms: number }; output: { encoding: string; sample_rate: number }; note: string }
export interface Handoff { packet_id: string; encounter_id: string | null; session_id?: string | null; version: number; status: string; shared_at: string; field_keys: string[]; attachment_ids: string[]; consent_text?: string | null; clinician_name?: string | null }
export interface StudentEncounter { id: string; appointment_id: string | null; starts_at: string; visit_type: string; clinician_name: string; status: string; handoff: Handoff | null; source_mode: SourceMode }
export interface ClinicianIntake { encounter_id: string; status: 'NOT_SHARED' | 'SHARED' | 'WITHDRAWN'; packet_id: string | null; version: number | null; shared_at: string | null; fields: IntakeField[]; consent: Record<string, boolean>; attachments: PhotoAttachment[]; annotations: Record<string, { decision: 'accepted' | 'corrected' | 'rejected'; corrected_value: string | null; note: string | null; at: string }>; summary?: PreVisitSummary | null; consent_text?: string | null; session?: { session_id: string; started_at: string | null; ended_at: string | null; intake_complete: boolean; version: number } | null }

export interface Recipient { course_id: string | null; course_code: string; course_title: string | null; instructor_name: string | null; email: string | null; contact_status: ContactStatus | 'STUDENT_CONFIRMED'; deliverable: boolean; blocked_reason: string | null; dates: string[]; meetings: number; contact_state?: string; contact_label?: string; demo_route?: string; route_label?: string }
export interface ImpactDay { date: string; weekday: string; weekend: boolean; meeting_count: number }
export interface Impact { start_date: string; end_date: string; days: ImpactDay[]; total_meetings: number; courses: { course_code: string; course_id: string | null; dates: string[]; meetings: { event_id: string; date: string; start_local: string; end_local: string; minutes: number }[] }[]; recipients: Recipient[] }
export interface DeliveryRow { id: string; course_code: string; destination: string; intended_recipient?: string | null; simulated?: boolean; state: 'QUEUED' | 'SENT' | 'FAILED' | 'CANCELLED'; attempts: number; error_code: string | null; receipt_id: string | null; sent_at: string | null; version_id: string }
export interface TimelineItem { event_type: string; actor: string; to_state: string | null; status: string; at: string; detail: string | null }
export interface StudentCase {
  id: string; status: string; status_label: string; origin: 'student' | 'clinician'; encounter_id: string; visit_type: string; appointment_at: string; clinician_name: string
  reported_missed_dates: string[]; legacy_requested_range: { start: string; end: string } | null; disclosure_consent: boolean; consent_revoked_at: string | null
  decision: { decision: 'CERTIFY' | 'DECLINE' | 'DEFER'; start_date: string | null; end_date: string | null } | null
  document: { version: number; state: string; signed_at: string | null } | null
  deliveries: DeliveryRow[]; timeline: TimelineItem[]; created_at: string; excused_status: string
  delivery?: DeliveryReadiness
  metrics: { request_to_delivery_seconds: number | null; student_actions: number }
}
export interface DraftMessage extends Recipient { subject: string; body: string; include: boolean }
export interface DocVersion { id: string; version: number; state: 'UNSIGNED' | 'SIGNED' | 'SUPERSEDED' | 'REVOKED'; unsigned_sha256: string; signed_sha256: string | null; signed_at: string | null; created_at: string; content: { start_date: string; end_date: string; wording: string; courses: { code: string; dates: string[] }[]; days: ImpactDay[]; messages: DraftMessage[] } }
export interface ClinicianCase {
  id: string; status: string; status_label: string; origin: 'student' | 'clinician'; encounter_id: string; visit_type: string; appointment_at: string; student_name: string
  reported_missed_dates: string[]; legacy_requested_range: { start: string; end: string } | null; student_note: string | null
  decision: { decision: 'CERTIFY' | 'DECLINE' | 'DEFER'; start_date: string | null; end_date: string | null; wording: string | null; rationale_private: string | null; version: number } | null
  impact: Impact | null; document: DocVersion | null; signature_asset: { id: string; kind: string; created_at: string } | null
  gates: { student_consent: boolean; signed: boolean; recipients_verified: boolean }
  delivery?: DeliveryReadiness
  deliveries: DeliveryRow[]; timeline: TimelineItem[]
}
export interface ClinicianCaseRow { id: string; student_name: string; encounter_id: string; visit_type: string; status: string; status_label: string; reported_missed_dates: string[]; legacy_requested_range: { start: string; end: string } | null; created_at: string }
export interface SignRequest { nonce: string; expires_at: string; document_sha256: string; version: number; recipients: { course_code: string; email: string }[]; start_date: string; end_date: string }
export interface InboxMessage { id: string; to: string; intended_recipient?: string | null; subject: string; body: string; attachment_name: string; attachment_sha256: string; received_at: string }

export interface PhotoObservation { category: string; description: string; uncertainty: string }
export interface PhotoAttachment {
  id: string; observations: PhotoObservation[]; limitations: string[]; quality: { lighting: string; clarity: string; notes: string[]; usable: boolean }
  observer: 'heuristic' | 'claude'; synthetic_demo: boolean; created_at?: string; image_url: string; labels?: Record<string, string>; disclaimer?: string; next_steps?: string[]
}

export interface TermInfo { term: string; first_meeting: string; last_meeting: string; meetings: number; courses: number; source: string }
export interface TermsResponse { terms: TermInfo[]; selected: string | null; default: string | null; today: string }

export interface ScheduleSlot {
  id: string; clinician_id: string; clinician_name: string; appointment_type: string; appointment_label: string
  starts_at: string; ends_at: string; minutes: number; clinic_name: string; location: string | null; travel_minutes: number
  score: number | null; reason_codes: string[]; source_mode: SourceMode
}
export interface ClinicianCardData {
  clinician_id: string; name: string; credentials: string | null; specialty: string; clinic_name: string; location: string | null
  appointment_types: string[]; photo_url: string | null; bio: string | null; offers_type?: boolean; slots: ScheduleSlot[]; total_available?: number; excluded?: Record<string, number>
}
export interface ScheduleResult {
  appointment_type: string; appointment_label: string; start: string; days: number; part_of_day: string; sort: string; clinician_id: string | null
  clinicians: ClinicianCardData[]; options: ScheduleSlot[]; excluded: Record<string, number>; notice: string | null
  alternatives: { same_clinician: ScheduleSlot[]; other_clinicians: ScheduleSlot[] }; calendar_considered: boolean; term: string | null; source_mode: SourceMode
}
export interface ClinicianListing { clinicians: ClinicianCardData[]; appointment_types: { id: string; label: string }[]; specialties: string[] }

/** Shared by both portals (backend absence_service.delivery_readiness): each problem is its own code. */
export interface DeliveryRecipient { course_code: string; course_id: string | null; course_title: string | null; instructor_name: string | null; email: string | null; deliver_to: string | null; contact_state: string; contact_label: string; demo_route: string; route_label: string; deliverable: boolean; blocked_reason: string | null }
export interface DeliveryReadiness {
  clinician_signed: boolean; signed_version: number | null; student_consent: boolean; contacts_confirmed: boolean; recipients: DeliveryRecipient[]
  blockers: { code: string; message: string; courses?: string[] }[]; ready: boolean; delivered: boolean; uses_isolated_test_inbox: boolean
}
