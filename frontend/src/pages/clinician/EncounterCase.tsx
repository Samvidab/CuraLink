import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Badge, Button, Card, ErrorBanner, LoadingBlock, SourceBadge } from '../../components/ui'
import { PROVENANCE } from '../../components/IntakePanel'
import { api, ApiError } from '../../lib/api'
import { fmtDay, fmtRelative, fmtTime, fmtYmd } from '../../lib/format'
import type { ClinicianCase, ClinicianCaseRow, ClinicianIntake, EncounterDetail, Impact, SignRequest } from '../../lib/types'

const shortDate = (ymd: string) => fmtYmd(ymd, { weekday: 'short', month: 'short', day: 'numeric' })
const tone = (s: string) => (s === 'SENT' || s === 'SIGNED' ? 'teal' : s === 'FAILED' || s === 'REJECTED' ? 'rose' : s === 'REVOKED' ? 'slate' : 'amber')
const newKey = () => (crypto.randomUUID ? crypto.randomUUID() : `k-${Date.now()}-${Math.random().toString(36).slice(2)}`)
// Mirrors the server's str.replace (all occurrences).
const fill = (tpl: string, student: string, start: string, end: string) => tpl.split('{student}').join(student).split('{start}').join(start).split('{end}').join(end)

function PdfPreview({ versionId, signed }: { versionId: string; signed: boolean }) {
  const [url, setUrl] = useState<string | null>(null)
  const [failed, setFailed] = useState(false)
  useEffect(() => {
    let revoke: string | null = null
    fetch(`/api/v1/clinician/documents/${versionId}/preview${signed ? '?signed=true' : ''}`, { credentials: 'same-origin' })
      .then(r => (r.ok ? r.blob() : Promise.reject()))
      .then(b => { revoke = URL.createObjectURL(b); setUrl(revoke) })
      .catch(() => setFailed(true))
    return () => { if (revoke) URL.revokeObjectURL(revoke) }
  }, [versionId, signed])
  if (failed) return <p className="text-sm text-rose-600">Preview unavailable.</p>
  if (!url) return <LoadingBlock className="h-96"/>
  return <><iframe title="Document preview" src={url} className="hidden h-[520px] w-full rounded-xl border border-slate-200 md:block"/><a href={url} target="_blank" rel="noreferrer" className="inline-flex min-h-11 items-center rounded-xl border border-slate-200 px-4 text-sm font-semibold text-teal-700 md:hidden">Open preview</a></>
}

export default function EncounterCase() {
  const { id } = useParams()
  const navigate = useNavigate()
  const qc = useQueryClient()
  const { data: enc, error } = useQuery({ queryKey: ['encounter', id], queryFn: () => api.get<EncounterDetail>(`/clinician/encounters/${id}`), retry: false })
  const { data: intake } = useQuery({ queryKey: ['encounter-intake', id], queryFn: () => api.get<ClinicianIntake>(`/clinician/encounters/${id}/intake`), retry: false, enabled: !!enc })
  const cases = useQuery({ queryKey: ['clinician-cases'], queryFn: () => api.get<ClinicianCaseRow[]>('/clinician/absence-cases'), enabled: !!enc })
  const caseRow = cases.data?.find(c => c.encounter_id === id)
  const caseQ = useQuery({ queryKey: ['clinician-case', caseRow?.id], queryFn: () => api.get<ClinicianCase>(`/clinician/absence-cases/${caseRow!.id}`), enabled: !!caseRow })
  const c = caseQ.data
  const setCase = (x: ClinicianCase) => { qc.setQueryData(['clinician-case', x.id], x); qc.invalidateQueries({ queryKey: ['clinician-cases'] }); qc.invalidateQueries({ queryKey: ['clinician-dashboard'] }) }

  const [start, setStart] = useState(''); const [end, setEnd] = useState('')
  const [wording, setWording] = useState('')
  const [excluded, setExcluded] = useState<string[]>([])
  const [actionError, setActionError] = useState('')
  const [signReq, setSignReq] = useState<SignRequest | null>(null)
  const [password, setPassword] = useState(''); const [ack, setAck] = useState(false)
  const [deliverKey] = useState(newKey)
  useEffect(() => {
    if (!c) return
    setStart(s => s || (c.decision?.start_date ?? c.requested_start)); setEnd(e => e || (c.decision?.end_date ?? c.requested_end))
    setWording(w => w || c.decision?.wording || '{student} has been seen by a healthcare professional and may be unable to attend class from {start} through {end}. This notice does not include medical details and does not determine whether an absence is excused.')
  }, [c])
  const preview = useQuery({ queryKey: ['clin-preview', c?.id, start, end], enabled: !!c && !!start && !!end && end >= start, queryFn: () => api.post<Impact>(`/clinician/absence-cases/${c!.id}/preview`, { start_date: start, end_date: end }) })
  const days = start && end && end >= start ? Math.round((Date.parse(end) - Date.parse(start)) / 86400000) + 1 : 0

  const run = (fn: () => Promise<ClinicianCase | void>) => async () => { setActionError(''); try { const r = await fn(); if (r) setCase(r) } catch (e) { setActionError(e instanceof ApiError ? e.message : 'Action failed.') } }
  const decide = (decision: 'CERTIFY' | 'DECLINE') => run(() => api.post<ClinicianCase>(`/clinician/absence-cases/${c!.id}/decision`, decision === 'CERTIFY' ? { decision, start_date: start, end_date: end, wording } : { decision }))
  const renderDoc = run(() => api.post<ClinicianCase>(`/clinician/absence-cases/${c!.id}/render`, { wording, excluded_courses: excluded }))
  const openSign = run(async () => { setPassword(''); setAck(false); setSignReq(await api.post<SignRequest>(`/clinician/documents/${c!.document!.id}/sign-request`)) })
  const sign = useMutation({
    mutationFn: () => api.post<{ case: ClinicianCase }>(`/clinician/documents/${c!.document!.id}/approve-sign`, { nonce: signReq!.nonce, document_sha256: signReq!.document_sha256, recipient_courses: signReq!.recipients.map(r => r.course_code), password, confirm: ack }),
    onSuccess: r => { setCase(r.case); setSignReq(null) },
  })
  const deliver = run(() => api.post<ClinicianCase>(`/clinician/documents/${c!.document!.id}/deliver`, { idempotency_key: deliverKey }))
  const retry = (dId: string) => run(() => api.post<ClinicianCase>(`/clinician/deliveries/${dId}/retry`))()

  const doc = c?.document && c.document.state !== 'SUPERSEDED' ? c.document : null
  const decided = c?.decision?.decision === 'CERTIFY' && c.decision.start_date === start && c.decision.end_date === end
  const docCurrent = !!doc && !!c && doc.content.start_date === start && doc.content.end_date === end && doc.content.wording === fill(wording, c.student_name, start, end)
  const status = c?.status ?? enc?.status ?? 'NEEDS_REVIEW'
  const closed = c ? ['SENT', 'DELIVERY_QUEUED', 'REJECTED', 'REVOKED'].includes(c.status) : true
  const blocked = useMemo(() => doc?.content.messages.filter(m => m.include && !m.deliverable) ?? [], [doc])

  return <div className="min-h-screen bg-[#f6f8f8] text-slate-900"><header className="sticky top-0 z-20 flex h-20 items-center justify-between border-b border-slate-200 bg-white px-5 md:px-9"><button onClick={()=>navigate('/clinician/dashboard')} className="text-sm font-semibold text-teal-700">← Back to queue</button><div className="text-center"><b>{c?`Case ${c.id.replace('case_','CL-').toUpperCase()}`:enc?enc.visit_type:'Encounter'}</b><p className="text-xs text-slate-500">Fictional clinician demo</p></div><Badge tone={tone(status)}>{c?.status_label ?? enc?.status_label ?? status}</Badge></header><main className="mx-auto max-w-7xl p-5 md:p-9">{error&&<div className="mb-5"><ErrorBanner error={error}/></div>}{actionError&&<div className="mb-5"><ErrorBanner error={new Error(actionError)}/></div>}<div className="grid gap-6 lg:grid-cols-[.7fr_1.3fr]"><div className="space-y-5"><Card className="p-6"><p className="text-xs font-semibold text-slate-500">PATIENT</p><h1 className="mt-2 text-2xl font-semibold">{enc?.student_name ?? '…'}</h1><p className="mt-1 text-sm text-slate-500">{enc?`Demo appointment · ${fmtDay(enc.starts_at,undefined,{month:'short',day:'numeric'})}, ${fmtTime(enc.starts_at)} · ${enc.visit_type}`:''}</p><div className="mt-5 rounded-xl bg-sky-50 p-4 text-sm leading-6 text-sky-900"><div className="flex items-center justify-between gap-2"><b>Student-reported intake</b>{intake?.version&&intake.status==='SHARED'?<Badge tone="blue">v{intake.version}</Badge>:null}</div>{!intake?<p>Loading…</p>:intake.status==='NOT_SHARED'?<p>The student hasn’t shared intake details for this appointment.</p>:intake.status==='WITHDRAWN'?<p>The student withdrew this packet. It’s no longer available.</p>:<dl className="mt-2 space-y-2">{intake.fields.map(f=><div key={f.key}><dt className="text-xs font-semibold text-sky-800">{f.label} <span className="font-normal">· {PROVENANCE[f.provenance]} by student</span></dt><dd className="break-words">{f.display}</dd></div>)}</dl>}</div>{c?.student_note&&<div className="mt-3 rounded-xl bg-slate-50 p-3 text-sm"><b className="text-xs text-slate-500">Student’s note (private to you)</b><p className="mt-1">{c.student_note}</p></div>}<p className="mt-4 text-xs leading-5 text-slate-500">Patient report is distinct from clinician findings. No private narrative appears in professor-facing documents.</p></Card><Card className="p-6"><h2 className="font-semibold">Consent & provenance</h2><div className="mt-4 space-y-3 text-sm"><div className="flex justify-between gap-2"><span>Intake shared by student</span><Badge tone={intake?.status==='SHARED'?'teal':'slate'}>{intake?.status==='SHARED'?'Consented':intake?.status==='WITHDRAWN'?'Withdrawn':'Not shared'}</Badge></div><div className="flex justify-between gap-2"><span>Consent to send to instructors</span><Badge tone={c?.gates.student_consent?'teal':'amber'}>{c?(c.gates.student_consent?'Given':'Not given'):'—'}</Badge></div><div className="flex justify-between gap-2"><span>Voice transcript / photos</span><Badge tone="slate">Not shared</Badge></div><div className="flex justify-between gap-2"><span>Source</span><SourceBadge mode={enc?.source_mode ?? 'demo'}/></div></div></Card></div>
    <div className="space-y-5">
      {!c?<Card className="p-6"><h2 className="text-xl font-semibold">Clinician absence determination</h2><p className="mt-3 text-sm text-slate-500">{cases.isLoading||caseQ.isLoading?'Loading…':'The student hasn’t requested an absence review for this appointment. Absence documentation starts with a student request.'}</p></Card>:<>
      <Card className="p-6"><div className="flex flex-wrap items-start justify-between gap-3"><div><h2 className="text-xl font-semibold">Clinician absence determination</h2><p className="mt-1 text-sm text-slate-500">No duration is AI-generated or preselected as a clinical recommendation. Student requested {shortDate(c.requested_start)} – {shortDate(c.requested_end)}.</p></div><Badge tone="blue">{days} calendar day{days!==1?'s':''}</Badge></div><div className="mt-6 grid gap-4 sm:grid-cols-2"><label className="text-sm font-semibold">Inclusive first date<input type="date" disabled={closed} value={start} onChange={e=>setStart(e.target.value)} className="input mt-2"/></label><label className="text-sm font-semibold">Inclusive last date<input type="date" disabled={closed} min={start} value={end} onChange={e=>setEnd(e.target.value)} className="input mt-2"/></label></div>
        <div className="mt-5 rounded-xl border border-slate-200 bg-slate-50 p-4"><b className="text-sm">Impacted occurrences</b>{preview.isLoading?<LoadingBlock className="mt-3 h-16"/>:preview.data&&<><div className="mt-3 space-y-2">{preview.data.recipients.length===0&&<p className="text-sm text-slate-500">No class meetings in this range.</p>}{preview.data.recipients.map(r=><div key={r.course_code} className="flex flex-wrap items-center justify-between gap-2 text-sm"><span>{r.course_code} · {r.instructor_name ?? 'Instructor unknown'}</span><span className="text-slate-500">{r.dates.map(shortDate).join(' & ')} · <span className={r.deliverable?'text-teal-700':'text-amber-700'}>{r.deliverable?'recipient verified':r.blocked_reason}</span></span></div>)}</div><p className="mt-3 text-xs text-slate-500">{preview.data.days.filter(d=>d.meeting_count===0).length>0?`No classes on: ${preview.data.days.filter(d=>d.meeting_count===0).map(d=>shortDate(d.date)+(d.weekend?' (weekend)':'')).join(', ')}.`:'Every day in this range has class meetings.'}</p></>}</div>
        <label className="mt-5 block text-sm font-semibold">Minimal-disclosure wording<textarea disabled={closed} className="input mt-2 min-h-28" value={wording} onChange={e=>setWording(e.target.value)}/><span className="mt-1 block text-xs font-normal text-slate-500">Placeholders: {'{student}'}, {'{start}'}, {'{end}'}. No diagnosis, symptoms or intake details.</span></label>
        {!closed&&<div className="mt-5 flex flex-wrap gap-3"><Button variant="secondary" onClick={decide('DECLINE')}>Decline certification</Button><Button disabled={!days} onClick={decide('CERTIFY')}>{decided?'Dates set ✓ — update':'Approve date range'}</Button></div>}{c.status==='REJECTED'&&<p className="mt-4 rounded-xl bg-slate-50 p-3 text-sm">You declined to document an absence. Nothing can be generated or sent.</p>}</Card>
      <Card className="p-6"><div className="flex items-center justify-between gap-2"><div><h2 className="text-lg font-semibold">Document review</h2><p className="text-sm text-slate-500">{doc?`Version ${doc.version} · ${doc.state==='SIGNED'?'signed (simulated)':'unsigned'}`:'No document yet'}</p></div><Badge tone={doc?.state==='SIGNED'?'teal':'slate'}>{doc?.state==='SIGNED'?'SIGNED':'DRAFT'}</Badge></div>
        {c.decision?.decision==='CERTIFY'&&!closed&&!docCurrent&&<div className="mt-4 rounded-xl border border-dashed border-slate-300 p-4 text-sm"><p className="text-slate-600">{doc?'Changes will invalidate the existing signature and require another review.':'Generate an immutable, unsigned PDF and per-instructor drafts from the dates above.'}</p>{preview.data&&preview.data.recipients.length>0&&<fieldset className="mt-3"><legend className="text-xs font-semibold text-slate-500">Include instructors</legend><div className="mt-1 flex flex-wrap gap-3">{preview.data.recipients.map(r=><label key={r.course_code} className="flex items-center gap-2"><input type="checkbox" className="size-4 accent-teal-700" checked={!excluded.includes(r.course_code)} onChange={e=>setExcluded(x=>e.target.checked?x.filter(y=>y!==r.course_code):[...x,r.course_code])}/>{r.course_code}</label>)}</div></fieldset>}<Button className="mt-3" disabled={!decided} onClick={renderDoc}>{doc?'Generate new version':'Generate document'}</Button>{!decided&&<p className="mt-2 text-xs text-amber-700">Approve the date range first.</p>}</div>}
        {doc&&<><div className="mt-5"><PdfPreview versionId={doc.id} signed={doc.state==='SIGNED'}/></div>
          <details className="mt-4 text-sm" open><summary className="cursor-pointer font-semibold">Instructor messages ({doc.content.messages.filter(m=>m.include).length})</summary><div className="mt-3 space-y-3">{doc.content.messages.map(m=><div key={m.course_code} className={`rounded-xl border p-3 ${m.include?'border-slate-200':'border-dashed border-slate-200 opacity-60'}`}><div className="flex flex-wrap justify-between gap-2"><b>{m.course_code} → {m.email ?? 'no verified address'}</b><span className={`text-xs font-semibold ${!m.include?'text-slate-500':m.deliverable?'text-teal-700':'text-amber-700'}`}>{!m.include?'Excluded':m.deliverable?'Verified recipient':m.blocked_reason}</span></div><p className="mt-1 text-xs text-slate-500">{m.subject}</p><pre className="mt-2 whitespace-pre-wrap font-sans text-xs leading-5 text-slate-600">{m.body}</pre></div>)}</div></details>
          <p className="mt-3 break-all text-[11px] text-slate-400">sha256 {doc.state==='SIGNED'?doc.signed_sha256:doc.unsigned_sha256}</p>
          <div className="mt-5 flex flex-wrap items-center justify-end gap-3">
            {doc.state==='UNSIGNED'&&docCurrent&&(c.signature_asset?<Button onClick={openSign}>Approve & sign this version</Button>:<p className="text-sm text-amber-700">Enroll your demo signature in <Link to="/clinician/signatures" className="font-semibold underline">Signature Settings</Link> to sign.</p>)}
            {doc.state==='SIGNED'&&c.status!=='SENT'&&c.status!=='FAILED'&&(blocked.length?<p className="text-sm text-amber-700">Recipient not verified: {blocked.map(b=>b.course_code).join(', ')}. The student must confirm these contacts; then generate and sign a new version.</p>:!c.gates.student_consent?<p className="text-sm text-amber-700">The student hasn’t consented to sending. Nothing will be sent.</p>:<Button onClick={deliver}>Send authorized copies (test inbox)</Button>)}
          </div></>}
        {c.deliveries.length>0&&<div className="mt-5 rounded-xl bg-slate-50 p-4 text-sm"><b>Delivery receipts</b><ul className="mt-2 space-y-1.5">{c.deliveries.map(d=><li key={d.id} className="flex flex-wrap items-center justify-between gap-2"><span>{d.course_code} → {d.destination}</span><span className="flex items-center gap-2"><span className={d.state==='SENT'?'text-teal-700':d.state==='FAILED'?'text-rose-700':'text-slate-500'}>{d.state}{d.error_code?` · ${d.error_code}`:''}{d.sent_at?` · ${fmtRelative(d.sent_at)}`:''}</span>{d.state==='FAILED'&&<Button variant="secondary" className="min-h-8 py-1" onClick={()=>retry(d.id)}>Retry</Button>}</span></li>)}</ul><p className="mt-3 text-xs text-slate-500">Delivered to verified test inboxes only. This never claims university approval. <Link to="/demo/inbox" className="font-semibold text-teal-700 underline">Open test inbox</Link></p></div>}
      </Card></>}
    </div></div></main>
    {signReq&&c?.document&&<div role="dialog" aria-modal="true" aria-labelledby="sign-title" className="fixed inset-0 z-50 grid place-items-center bg-slate-950/50 p-5"><Card className="max-w-md p-6"><Badge tone="amber">FRESH CONFIRMATION REQUIRED</Badge><h2 id="sign-title" className="mt-4 text-xl font-semibold">Sign this exact version?</h2><p className="mt-3 text-sm leading-6 text-slate-500">Version {signReq.version}: {shortDate(signReq.start_date)} through {shortDate(signReq.end_date)} (inclusive). Any later edit invalidates this signature. The sample signature is fictional and watermarked DEMO.</p><div className="mt-3 rounded-lg bg-slate-50 p-3 text-xs"><b>Recipients</b><ul className="mt-1">{signReq.recipients.map(r=><li key={r.course_code}>{r.course_code} → {r.email ?? 'no verified address'}</li>)}</ul><p className="mt-2 break-all text-slate-400">Document sha256 {signReq.document_sha256.slice(0,32)}…</p></div><label className="mt-4 block text-sm font-semibold">Re-enter your password<input type="password" value={password} onChange={e=>setPassword(e.target.value)} className="input mt-2" autoComplete="current-password"/></label><label className="mt-3 flex items-start gap-3 text-sm"><input type="checkbox" checked={ack} onChange={e=>setAck(e.target.checked)} className="mt-0.5 size-5 accent-teal-700"/><span>I reviewed the full preview, dates and recipients, and approve this version.</span></label>{sign.error&&<p role="alert" className="mt-3 text-sm text-rose-600">{(sign.error as Error).message}</p>}<div className="mt-6 flex justify-end gap-2"><Button variant="ghost" onClick={()=>setSignReq(null)}>Cancel</Button><Button disabled={!ack||!password||sign.isPending} onClick={()=>sign.mutate()}>Confirm demo signature</Button></div></Card></div>}
  </div>
}
