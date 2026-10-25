import { query } from './_generated/server'
import { visible, viewer } from './access'
import { TABLES } from './schema'

/** Real-time change cursor for the signed-in user: the newest update among records they may read, per type.
 *  The app subscribes to this and refreshes the affected screens when it moves. */
export const cursor = query({
  args: {},
  handler: async ctx => {
    const who = await viewer(ctx)
    if (!who) return null
    const out: Record<string, number> = {}
    for (const t of TABLES) out[t] = Math.max(0, ...(await visible(ctx, t, who)).map(r => r.updatedAt))
    return { viewer: who.id, role: who.role, tables: out }
  },
})
