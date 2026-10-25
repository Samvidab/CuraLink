import { v } from 'convex/values'
import { query } from './_generated/server'
import { visible, view, viewer } from './access'
import { TABLES, type TableName } from './schema'

/** Records of one type the signed-in user may read (empty when signed out). */
export const list = query({
  args: { table: v.string() },
  handler: async (ctx, { table }) => {
    const who = await viewer(ctx)
    if (!who || !(TABLES as readonly string[]).includes(table)) return []
    return (await visible(ctx, table as TableName, who)).map(r => view(r, who))
  },
})
