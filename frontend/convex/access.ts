import type { Doc, TableNames } from './_generated/dataModel'
import type { QueryCtx } from './_generated/server'
import { PUBLIC_TABLES, type TableName } from './schema'

export type Viewer = { id: string; role: 'student' | 'clinician' }

/** The signed-in CuraLink user, from the JWT FastAPI issued (sub = user id, role claim). */
export async function viewer(ctx: QueryCtx): Promise<Viewer | null> {
  const identity = await ctx.auth.getUserIdentity()
  if (!identity) return null
  const role = (identity as unknown as Record<string, unknown>)['role']
  if (role !== 'student' && role !== 'clinician') return null
  return { id: identity.subject, role }
}

type Rec = Doc<TableNames>

/** Server-side authorization: owner student, an authorized clinician, or a public directory table. */
export function canRead(table: TableName, r: Rec, who: Viewer): boolean {
  if (r.deleted) return false
  if (PUBLIC_TABLES.includes(table)) return true
  if (table === 'users') return r.recordId === who.id || (r.data as { role?: string })?.role === 'clinician'
  if (who.role === 'student') return r.studentId === who.id
  return r.clinicianIds.includes(who.id)
}

/** What a viewer receives: clinician-only fields are removed for everyone but authorized clinicians. */
export function view(r: Rec, who: Viewer) {
  const base = { recordId: r.recordId, studentId: r.studentId, data: r.data, updatedAt: r.updatedAt }
  return who.role === 'clinician' && r.clinicianIds.includes(who.id) && r.clinicianOnly !== undefined ? { ...base, clinicianOnly: r.clinicianOnly } : base
}

export async function visible(ctx: QueryCtx, table: TableName, who: Viewer): Promise<Rec[]> {
  const rows = who.role === 'student' && !PUBLIC_TABLES.includes(table) && table !== 'users'
    ? await ctx.db.query(table).withIndex('by_studentId', q => q.eq('studentId', who.id)).collect()
    : await ctx.db.query(table).collect()
  return rows.filter(r => canRead(table, r, who))
}
