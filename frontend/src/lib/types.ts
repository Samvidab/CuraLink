// Mirrors backend/app/schemas.py. Keep in sync with the API contract.

export type Role = 'student' | 'clinician'
export type SourceMode = 'demo' | 'uploaded' | 'real'
export type ContactStatus = 'VERIFIED' | 'NEEDS_REVIEW' | 'MISSING' | 'STUDENT_CONFIRMED'

export interface Health {
  status: 'ok'
  demo_mode: boolean
  demo_today: string
  integrations: { clinic_inventory: 'demo'; email_delivery: 'test_only'; llm: 'live' | 'fallback'; voice: 'live' | 'fallback' }
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
}

export interface DemoPersona { role: Role; display_name: string; email: string; note: string }

export interface Course {
  id: string
  code: string
  section: string | null
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

export interface CalendarEvents { events: CalendarEvent[]; timezone: string; calendar: CalendarSummary | null }

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
  appointment_type: string
  clinic_name: string
  location: string
  starts_at: string
  ends_at: string
  source_mode: SourceMode
  external_booking: boolean
}

export interface StudentDashboard {
  today: string
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
  today: string
  display_name: string
  appointments_today: number
  intakes_to_review: number
  absence_cases: number
  encounters: EncounterRow[]
}

export interface EncounterDetail extends EncounterRow { student_id: string; student_email: string; appointment_id: string | null }

export interface AppointmentType { id: string; label: string }

export interface Slot {
  id: string
  clinic_id: string
  clinic_name: string
  location: string
  appointment_type: string
  starts_at: string
  ends_at: string
  travel_minutes: number
  status: string
  permitted: boolean
  source_mode: SourceMode
}

export interface Conflict { label: string; event_id: string | null; kind: 'CLASS_OVERLAP' | 'TRAVEL_BUFFER' | 'PERSONAL_BLOCK'; overlap_minutes: number }
export interface SlotOption { rank: number; slot: Slot; score: number; reason_codes: string[]; conflicts: Conflict[]; source_mode: SourceMode }
export interface RejectedSlot { slot: Slot; reason_code: string; conflicts: Conflict[] }

export interface Recommendations {
  options: SlotOption[]
  rejected: RejectedSlot[]
  calendar_considered: boolean
  generated_at: string
  source_mode: SourceMode
  scoring: Record<string, number>
}

export interface SlotsResponse { slots: Slot[]; inventory_updated_at: string; source_mode: SourceMode; appointment_types: AppointmentType[] }

export interface ConfirmResult { appointment_id: string; status: string; external_booking: boolean; appointment: AppointmentSummary; message: string }

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
}
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
}
export interface VoiceSessionInfo { session_id: string; mode: 'cartesia' | 'browser'; stream_path: string | null; input: { encoding: string; sample_rate: number; chunk_ms: number }; output: { encoding: string; sample_rate: number }; note: string }
export interface Handoff { packet_id: string; encounter_id: string; version: number; status: string; shared_at: string; field_keys: string[]; attachment_ids: string[] }
export interface StudentEncounter { id: string; appointment_id: string | null; starts_at: string; visit_type: string; clinician_name: string; status: string; handoff: Handoff | null; source_mode: SourceMode }
export interface ClinicianIntake { encounter_id: string; status: 'NOT_SHARED' | 'SHARED' | 'WITHDRAWN'; packet_id: string | null; version: number | null; shared_at: string | null; fields: IntakeField[]; consent: Record<string, boolean>; attachments: PhotoAttachment[]; annotations: Record<string, { decision: 'accepted' | 'corrected' | 'rejected'; corrected_value: string | null; note: string | null; at: string }> }

export interface Recipient { course_id: string | null; course_code: string; course_title: string | null; instructor_name: string | null; email: string | null; contact_status: ContactStatus | 'STUDENT_CONFIRMED'; deliverable: boolean; blocked_reason: string | null; dates: string[]; meetings: number }
export interface ImpactDay { date: string; weekday: string; weekend: boolean; meeting_count: number }
export interface Impact { start_date: string; end_date: string; days: ImpactDay[]; total_meetings: number; courses: { course_code: string; course_id: string | null; dates: string[]; meetings: { event_id: string; date: string; start_local: string; end_local: string; minutes: number }[] }[]; recipients: Recipient[] }
export interface DeliveryRow { id: string; course_code: string; destination: string; state: 'QUEUED' | 'SENT' | 'FAILED' | 'CANCELLED'; attempts: number; error_code: string | null; receipt_id: string | null; sent_at: string | null; version_id: string }
export interface TimelineItem { event_type: string; actor: string; to_state: string | null; status: string; at: string; detail: string | null }
export interface StudentCase {
  id: string; status: string; status_label: string; origin: 'student' | 'clinician'; encounter_id: string; visit_type: string; appointment_at: string; clinician_name: string
  requested_start: string; requested_end: string; disclosure_consent: boolean; consent_revoked_at: string | null
  decision: { decision: 'CERTIFY' | 'DECLINE' | 'DEFER'; start_date: string | null; end_date: string | null } | null
  document: { version: number; state: string; signed_at: string | null } | null
  deliveries: DeliveryRow[]; timeline: TimelineItem[]; created_at: string; excused_status: string
  metrics: { request_to_delivery_seconds: number | null; student_actions: number }
}
export interface DraftMessage extends Recipient { subject: string; body: string; include: boolean }
export interface DocVersion { id: string; version: number; state: 'UNSIGNED' | 'SIGNED' | 'SUPERSEDED' | 'REVOKED'; unsigned_sha256: string; signed_sha256: string | null; signed_at: string | null; created_at: string; content: { start_date: string; end_date: string; wording: string; courses: { code: string; dates: string[] }[]; days: ImpactDay[]; messages: DraftMessage[] } }
export interface ClinicianCase {
  id: string; status: string; status_label: string; origin: 'student' | 'clinician'; encounter_id: string; visit_type: string; appointment_at: string; student_name: string
  requested_start: string; requested_end: string; student_note: string | null
  decision: { decision: 'CERTIFY' | 'DECLINE' | 'DEFER'; start_date: string | null; end_date: string | null; wording: string | null; rationale_private: string | null; version: number } | null
  impact: Impact | null; document: DocVersion | null; signature_asset: { id: string; kind: string; created_at: string } | null
  gates: { student_consent: boolean; signed: boolean; recipients_verified: boolean }
  deliveries: DeliveryRow[]; timeline: TimelineItem[]
}
export interface ClinicianCaseRow { id: string; student_name: string; encounter_id: string; visit_type: string; status: string; status_label: string; requested_start: string; requested_end: string; created_at: string }
export interface SignRequest { nonce: string; expires_at: string; document_sha256: string; version: number; recipients: { course_code: string; email: string }[]; start_date: string; end_date: string }
export interface InboxMessage { id: string; to: string; subject: string; body: string; attachment_name: string; attachment_sha256: string; received_at: string }

export interface PhotoObservation { category: string; description: string; uncertainty: string }
export interface PhotoAttachment {
  id: string; observations: PhotoObservation[]; limitations: string[]; quality: { lighting: string; clarity: string; notes: string[]; usable: boolean }
  observer: 'heuristic' | 'claude'; synthetic_demo: boolean; created_at?: string; image_url: string; labels?: Record<string, string>; disclaimer?: string; next_steps?: string[]
}
