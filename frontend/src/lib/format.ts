// Display helpers. API datetimes carry their offset; we render them in the
// calendar's IANA timezone so the clock time matches the student's schedule.

const DEFAULT_TZ = 'America/Indiana/Indianapolis'

// Constructing an Intl.DateTimeFormat with a timeZone is expensive (hundreds of
// ms across a render), so formatters are built once per option set and reused.
const formatters = new Map<string, Intl.DateTimeFormat>()
const fmt = (opts: Intl.DateTimeFormatOptions) => {
  const key = JSON.stringify(opts)
  let f = formatters.get(key)
  if (!f) formatters.set(key, (f = new Intl.DateTimeFormat('en-US', opts)))
  return f
}

export const fmtTime = (iso: string, tz = DEFAULT_TZ) => fmt({ hour: 'numeric', minute: '2-digit', timeZone: tz }).format(new Date(iso))

export const fmtRange = (start: string, end: string, tz = DEFAULT_TZ) => `${fmtTime(start, tz)}–${fmtTime(end, tz)}`

export const fmtDay = (iso: string, tz = DEFAULT_TZ, opts: Intl.DateTimeFormatOptions = { weekday: 'long', month: 'short', day: 'numeric' }) =>
  fmt({ ...opts, timeZone: tz }).format(new Date(iso))

/** "YYYY-MM-DD" of an instant in the given zone. */
export const ymdIn = (iso: string, tz = DEFAULT_TZ) => {
  const parts = fmt({ year: 'numeric', month: '2-digit', day: '2-digit', timeZone: tz }).formatToParts(new Date(iso))
  const get = (t: string) => parts.find(p => p.type === t)!.value
  return `${get('year')}-${get('month')}-${get('day')}`
}

/** Format a calendar date string ("YYYY-MM-DD") without timezone drift. */
export const fmtYmd = (ymd: string, opts: Intl.DateTimeFormatOptions) => {
  const [y, m, d] = ymd.split('-').map(Number)
  return fmt({ ...opts, timeZone: 'UTC' }).format(new Date(Date.UTC(y, m - 1, d, 12)))
}

/** "2026-10-26" -> "Monday, October 26" without timezone drift. */
export const fmtDateLong = (ymd: string) => fmtYmd(ymd, { weekday: 'long', month: 'long', day: 'numeric' })
export const fmtDateHeading = (ymd: string) => fmtDateLong(ymd).toUpperCase()

export const fmtRelative = (iso: string) => {
  const diff = (Date.now() - new Date(iso).getTime()) / 1000
  if (diff < 60) return 'Just now'
  if (diff < 3600) return `${Math.round(diff / 60)} min ago`
  if (diff < 86400) return `${Math.round(diff / 3600)} hr ago`
  return fmt({ month: 'long', day: 'numeric' }).format(new Date(iso))
}

export const initials = (name: string) =>
  name.replace(/^Dr\.?\s+/i, '').split(/\s+/).filter(Boolean).slice(0, 2).map(p => p[0]!.toUpperCase()).join('') || '?'

const EVENT_LABELS: Record<string, string> = {
  CALENDAR_IMPORTED: 'Calendar imported',
  CALENDAR_DELETED: 'Calendar data removed',
  SIGNED_IN: 'Signed in',
  DEMO_RESET: 'Demo data reset',
  APPOINTMENT_DEMO_CONFIRMED: 'Demo appointment confirmed',
  APPOINTMENT_CANCELLED: 'Demo appointment cancelled',
  INTAKE_SHARED_WITH_CLINICIAN: 'Intake shared with clinician',
  INTAKE_WITHDRAWN: 'Intake sharing withdrawn',
  INTAKE_VIEWED: 'Clinician opened intake',
  ABSENCE_REQUESTED: 'Absence review requested',
  DISCLOSURE_CONSENT_GRANTED: 'Consent to send given',
  DISCLOSURE_CONSENT_REVOKED: 'Consent to send withdrawn',
  CASE_OPENED: 'Clinician opened case',
  ABSENCE_DECISION: 'Clinician decision recorded',
  DOCUMENT_RENDERED: 'Document version created',
  DOCUMENT_SIGNED: 'Clinician signed (simulated)',
  DELIVERY_QUEUED: 'Queued for test inbox',
  DELIVERY_SENT: 'Delivered to test inbox',
  DELIVERY_FAILED: 'Delivery failed',
  DELIVERY_REVOKED: 'Delivery cancelled',
  CONTACT_CORRECTED: 'Instructor contact corrected',
  SAFETY_ESCALATION_SHOWN: 'Safety guidance shown',
  SAFETY_NOTICE_ACKNOWLEDGED: 'Safety notice acknowledged',
  CONSENT_GRANTED: 'Consent given',
  CONSENT_WITHDRAWN: 'Consent withdrawn',
  SIGNATURE_ENROLLED: 'Demo signature enrolled',
  SIGNATURE_REVOKED: 'Signature revoked',
  LLM_FALLBACK: 'Assistant used scripted fallback',
  LLM_OUTPUT_GUARDED: 'Assistant reply replaced by safety guard',
}
export const eventLabel = (type: string) => EVENT_LABELS[type] ?? type.toLowerCase().replace(/_/g, ' ').replace(/^\w/, c => c.toUpperCase())

/** Minutes since local midnight of an instant in the given zone (DST-safe). */
export const minutesIn = (iso: string, tz = DEFAULT_TZ) => {
  const parts = fmt({ hour: '2-digit', minute: '2-digit', hourCycle: 'h23', timeZone: tz }).formatToParts(new Date(iso))
  const get = (t: string) => Number(parts.find(p => p.type === t)!.value)
  return get('hour') * 60 + get('minute')
}
