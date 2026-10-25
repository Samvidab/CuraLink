import { convexTest } from 'convex-test'
import { describe, expect, test } from 'vitest'
import { api } from './_generated/api'
import schema from './schema'

const modules = import.meta.glob('./**/*.ts')
const SECRET = 'x'.repeat(40)
const sam = { subject: 'demo-student-1', role: 'student' }
const jordan = { subject: 'demo-student-2', role: 'student' }
const rivera = { subject: 'demo-clinician-1', role: 'clinician' }
const hale = { subject: 'demo-clinician-2', role: 'clinician' }

async function seed() {
  process.env.CURALINK_SYNC_SECRET = SECRET
  const t = convexTest(schema, modules)
  const r = await t.fetch('/curalink/sync', { method: 'POST', headers: { Authorization: `Bearer ${SECRET}` }, body: JSON.stringify({ records: [
    { table: 'previsitSummaries', recordId: 'pkt_1', studentId: 'demo-student-1', clinicianIds: ['demo-clinician-1'], data: { chief: 'fever' }, deleted: false },
    { table: 'absenceDecisions', recordId: 'dec_1', studentId: 'demo-student-1', clinicianIds: ['demo-clinician-1'], data: { start: '2026-10-27' }, clinicianOnly: { rationale: 'private note' }, deleted: false },
    { table: 'clinicianProfiles', recordId: 'demo-clinician-1', clinicianIds: [], data: { name: 'Dr. Avery Rivera' }, deleted: false },
    { table: 'intakeSessions', recordId: 'ins_1', studentId: 'demo-student-1', clinicianIds: [], data: { status: 'OPEN' }, deleted: false },
  ] }) })
  expect(r.status).toBe(200)
  return t
}

describe('write path', () => {
  test('rejects missing or wrong secret, accepts the server secret', async () => {
    process.env.CURALINK_SYNC_SECRET = SECRET
    const t = convexTest(schema, modules)
    const body = JSON.stringify({ records: [] })
    expect((await t.fetch('/curalink/sync', { method: 'POST', body })).status).toBe(403)
    expect((await t.fetch('/curalink/sync', { method: 'POST', headers: { Authorization: 'Bearer wrong' }, body })).status).toBe(403)
    expect((await t.fetch('/curalink/sync', { method: 'POST', headers: { Authorization: `Bearer ${SECRET}` }, body })).status).toBe(200)
  })
  test('refuses to run with a weak or missing secret', async () => {
    process.env.CURALINK_SYNC_SECRET = 'short'
    const t = convexTest(schema, modules)
    expect((await t.fetch('/curalink/sync', { method: 'POST', headers: { Authorization: 'Bearer short' }, body: '{"records":[]}' })).status).toBe(403)
  })
})

describe('read authorization', () => {
  test('signed-out users and unknown roles see nothing', async () => {
    const t = await seed()
    expect(await t.query(api.records.list, { table: 'previsitSummaries' })).toEqual([])
    expect(await t.withIdentity({ subject: 'x', role: 'admin' } as never).query(api.records.list, { table: 'previsitSummaries' })).toEqual([])
    expect(await t.query(api.live.cursor, {})).toBeNull()
  })
  test('students see only their own records, without clinician-only fields', async () => {
    const t = await seed()
    const mine = await t.withIdentity(sam as never).query(api.records.list, { table: 'absenceDecisions' })
    expect(mine).toHaveLength(1)
    expect(mine[0]).not.toHaveProperty('clinicianOnly')
    expect(await t.withIdentity(jordan as never).query(api.records.list, { table: 'previsitSummaries' })).toEqual([])
    expect(await t.withIdentity(jordan as never).query(api.records.list, { table: 'intakeSessions' })).toEqual([])
  })
  test('only authorized clinicians see a record; intake drafts are never visible to clinicians', async () => {
    const t = await seed()
    const riv = await t.withIdentity(rivera as never).query(api.records.list, { table: 'absenceDecisions' })
    expect(riv[0].clinicianOnly).toEqual({ rationale: 'private note' })
    expect(await t.withIdentity(hale as never).query(api.records.list, { table: 'previsitSummaries' })).toEqual([])
    expect(await t.withIdentity(rivera as never).query(api.records.list, { table: 'intakeSessions' })).toEqual([])
  })
  test('directory data is visible to any signed-in user; unknown tables return nothing', async () => {
    const t = await seed()
    expect(await t.withIdentity(jordan as never).query(api.records.list, { table: 'clinicianProfiles' })).toHaveLength(1)
    expect(await t.withIdentity(sam as never).query(api.records.list, { table: 'nope' })).toEqual([])
  })
  test('revoked access (deleted or clinician removed) takes effect on the next read', async () => {
    const t = await seed()
    await t.fetch('/curalink/sync', { method: 'POST', headers: { Authorization: `Bearer ${SECRET}` }, body: JSON.stringify({ records: [
      { table: 'previsitSummaries', recordId: 'pkt_1', studentId: 'demo-student-1', clinicianIds: [], data: { chief: 'fever' }, deleted: false },
    ] }) })
    expect(await t.withIdentity(rivera as never).query(api.records.list, { table: 'previsitSummaries' })).toEqual([])
    expect(await t.withIdentity(sam as never).query(api.records.list, { table: 'previsitSummaries' })).toHaveLength(1)
  })
  test('the live cursor moves only for records the viewer may read', async () => {
    const t = await seed()
    const before = await t.withIdentity(hale as never).query(api.live.cursor, {})
    await t.fetch('/curalink/sync', { method: 'POST', headers: { Authorization: `Bearer ${SECRET}` }, body: JSON.stringify({ records: [
      { table: 'previsitSummaries', recordId: 'pkt_2', studentId: 'demo-student-1', clinicianIds: ['demo-clinician-1'], data: {}, deleted: false },
    ] }) })
    const after = await t.withIdentity(hale as never).query(api.live.cursor, {})
    expect(after?.tables.previsitSummaries).toBe(before?.tables.previsitSummaries)
    const riv = await t.withIdentity(rivera as never).query(api.live.cursor, {})
    expect(riv?.tables.previsitSummaries).toBeGreaterThan(0)
  })
  test('a demo reset clears every synced record', async () => {
    const t = await seed()
    const r = await t.fetch('/curalink/sync', { method: 'POST', headers: { Authorization: `Bearer ${SECRET}` }, body: JSON.stringify({ records: [], resetAll: true }) })
    expect((await r.json()).cleared).toBeGreaterThan(0)
    expect(await t.withIdentity(sam as never).query(api.records.list, { table: 'previsitSummaries' })).toEqual([])
  })
})
