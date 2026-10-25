import { httpRouter } from 'convex/server'
import { httpAction } from './_generated/server'
import { internal } from './_generated/api'

function sameSecret(a: string, b: string): boolean {
  if (!a || !b || a.length !== b.length) return false
  let diff = 0
  for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i)
  return diff === 0
}

const http = httpRouter()

// Write path for the FastAPI backend only. CURALINK_SYNC_SECRET is a Convex deployment environment variable.
http.route({
  path: '/curalink/sync',
  method: 'POST',
  handler: httpAction(async (ctx, request) => {
    const expected = process.env.CURALINK_SYNC_SECRET ?? ''
    const supplied = (request.headers.get('Authorization') ?? '').replace(/^Bearer /, '')
    if (expected.length < 32 || !sameSecret(supplied, expected)) return new Response('Forbidden', { status: 403 })
    let body: { records?: unknown; resetAll?: unknown }
    try { body = await request.json() } catch { return new Response('Bad request', { status: 400 }) }
    if (!Array.isArray(body.records) || body.records.length > 500) return new Response('Bad request', { status: 400 })
    const cleared = body.resetAll === true ? await ctx.runMutation(internal.sync.clearAll, {}) : null
    const result = await ctx.runMutation(internal.sync.upsertMany, { records: body.records as never })
    return Response.json({ ...result, cleared: cleared?.removed ?? 0 })
  }),
})

http.route({ path: '/curalink/health', method: 'GET', handler: httpAction(async () => Response.json({ ok: true })) })

export default http
