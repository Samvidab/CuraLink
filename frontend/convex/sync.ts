import { v } from 'convex/values'
import { internalMutation } from './_generated/server'
import { TABLES, type TableName } from './schema'

export const recordInput = v.object({
  table: v.string(),
  recordId: v.string(),
  studentId: v.optional(v.string()),
  clinicianIds: v.array(v.string()),
  data: v.any(),
  clinicianOnly: v.optional(v.any()),
  deleted: v.boolean(),
})

/** Demo reset: remove every synced record (the backend then re-sends the fresh fictional data). */
export const clearAll = internalMutation({
  args: {},
  handler: async ctx => {
    let removed = 0
    for (const t of TABLES) for (const row of await ctx.db.query(t).collect()) { await ctx.db.delete(row._id); removed++ }
    return { removed }
  },
})

/** Upsert committed records from the FastAPI system of record (called only by the authenticated HTTP action). */
export const upsertMany = internalMutation({
  args: { records: v.array(recordInput) },
  handler: async (ctx, { records }) => {
    const now = Date.now()
    let written = 0
    for (const r of records) {
      if (!(TABLES as readonly string[]).includes(r.table)) continue
      const table = r.table as TableName
      const { table: _t, ...fields } = r
      const row = { ...fields, updatedAt: now }
      const existing = await ctx.db.query(table).withIndex('by_recordId', q => q.eq('recordId', r.recordId)).unique()
      if (existing) await ctx.db.replace(existing._id, row)
      else await ctx.db.insert(table, row)
      written++
    }
    return { written }
  },
})
