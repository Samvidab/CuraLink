/**
 * CuraLink records in Convex: a persistent, real-time synchronized copy of what the FastAPI backend (the
 * transactional system of record) commits. Only the backend writes (POST /curalink/sync with a server secret);
 * browsers read through queries that enforce who may see each record.
 *
 * Never stored here: password hashes, session tokens, signature images, PDF bytes, photo bytes, sign nonces.
 */
import { defineSchema, defineTable } from 'convex/server'
import { v } from 'convex/values'

export const TABLES = [
  'users', 'clinicianProfiles', 'appointments', 'intakeSessions', 'previsitSummaries',
  'clinicianFindings', 'absenceCases', 'absenceDecisions', 'documentVersions', 'deliveries',
] as const
export type TableName = (typeof TABLES)[number]
/** Readable by any signed-in user (directory data, no medical content). */
export const PUBLIC_TABLES: readonly TableName[] = ['clinicianProfiles']

const record = {
  recordId: v.string(),
  studentId: v.optional(v.string()), // the student the record belongs to (they may read it)
  clinicianIds: v.array(v.string()), // clinicians currently authorized (assigned, active appointment, consent given)
  data: v.any(), // fields visible to the student and the authorized clinicians
  clinicianOnly: v.optional(v.any()), // fields only the authorized clinicians may read (e.g. private rationale)
  deleted: v.boolean(),
  updatedAt: v.number(),
}

const recordTable = () => defineTable(record).index('by_recordId', ['recordId']).index('by_studentId', ['studentId'])

export default defineSchema({
  users: recordTable(),
  clinicianProfiles: recordTable(),
  appointments: recordTable(),
  intakeSessions: recordTable(),
  previsitSummaries: recordTable(),
  clinicianFindings: recordTable(),
  absenceCases: recordTable(),
  absenceDecisions: recordTable(),
  documentVersions: recordTable(),
  deliveries: recordTable(),
})
