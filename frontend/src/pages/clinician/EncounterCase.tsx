import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Badge, Button, Card, ErrorBanner, LoadingBlock, SourceBadge } from '../../components/ui'
import { PROVENANCE } from '../../components/IntakePanel'
import { api, ApiError } from '../../lib/api'
import { fmtDay, fmtRelative, fmtTime, fmtYmd } from '../../lib/format'
import type { ClinicianCase, ClinicianCaseRow, ClinicianIntake, EncounterDetail, Impact, PreVisitHistory, SignRequest } from '../../lib/types'
import { PreVisitHistoryView, SummaryBody } from '../../components/PreVisit'

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

type EvalData = { fields: { key: string; label: string; type: string }[]; values: Record<string, string>; updated_at: string | null }

/** Clinician-only examination fields (CURALINK_CONFIG: EXAMINATION_FIELDS). Never shown to students or professors. */
function EvaluationCard({ encounterId }: { encounterId: string }) {
  const qc = useQueryClient()
  const { data } = useQuery({ queryKey: ['evaluation', encounterId], queryFn: () => api.get<EvalData>(`/clinician/encounters/${encounterId}/evaluation`) })
  const [values, setValues] = useState<Record<string, string> | null>(null)
  const [saved, setSaved] = useState('')
  const [error, setError] = useState('')
  const current = values ?? data?.values ?? {}
  const save = async () => {
    setError(''); setSaved('')
    try { qc.setQueryData(['evaluation', encounterId], await api.put<EvalData>(`/clinician/encounters/${encounterId}/evaluation`, { values: current })); setSaved('Saved. Visible only to clinicians.') }
    catch (e) { setError(e instanceof ApiError ? e.message : 'Could not save.') }
  }
  return <Card className="p-6"><h2 className="text-xl font-semibold">Medical Evaluation & Absence Determination</h2><p className="mt-1 text-sm text-slate-500">Your findings from the appointment. Clinician-verified information is kept separate from what the student reported and from AI-generated observations.</p>
    <div className="mt-5 space-y-4">{data?.fields.map(f=><label key={f.key} className="block text-sm font-semibold">{f.label}{f.type==='textarea'?<textarea className="input mt-2 min-h-20 font-normal" value={current[f.key] ?? ''} onChange={e=>setValues({ ...current, [f.key]: e.target.value })}/>:<input className="input mt-2 font-normal" value={current[f.key] ?? ''} onChange={e=>setValues({ ...current, [f.key]: e.target.value })}/>}</label>)}</div>
    {error&&<p role="alert" className="mt-3 text-sm text-rose-600">{error}</p>}{saved&&<p role="status" className="mt-3 text-sm text-teal-700">{saved}</p>}
    <Button className="mt-4" variant="secondary" disabled={!data} onClick={save}>Save clinician findings</Button></Card>
}

type Review = { decision: 'accepted' | 'corrected' | 'rejected'; corrected_value: string | null }

/** Clinician review of a student/AI-provided detail. The student's original is never overwritten. */
function FieldReview({ encounterId, field, review }: { encounterId: string; field: ClinicianIntake['fields'][number]; review?: Review }) {
  const qc = useQueryClient()
  const [editing, setEditing] = useState(false)
  const [value, setValue] = useState('')
  const [error, setError] = useState('')
  const send = async (decision: Review['decision'], corrected_value?: string) => {
    setError('')
    try { await api.post(`/clinician/encounters/${encounterId}/intake/annotations`, { field_key: field.key, decision, corrected_value }); setEditing(false); qc.invalidateQueries({ queryKey: ['encounter-intake', encounterId] }) }
    catch (e) { setError(e instanceof ApiError ? e.message : 'Could not save.') }
  }
  return <div><dt className="text-xs font-semibold text-sky-800">{field.label} <span className="font-normal">· {PROVENANCE[field.provenance]} by student</span></dt><dd className="break-words">{field.display}</dd>
    {review&&<p className="mt-1 text-xs"><Badge tone={review.decision==='rejected'?'rose':review.decision==='corrected'?'amber':'teal'}>{review.decision==='accepted'?'Clinician accepted':review.decision==='rejected'?'Clinician rejected':'Clinician corrected'}</Badge>{review.corrected_value&&<span className="ml-2">→ {review.corrected_value}</span>}</p>}
    <div className="mt-1 flex flex-wrap gap-3 text-xs"><button className="font-semibold text-teal-700 underline" onClick={()=>send('accepted')}>Accept</button><button className="font-semibold text-amber-700 underline" onClick={()=>{setEditing(!editing);setValue(review?.corrected_value ?? '')}}>Correct</button><button className="font-semibold text-rose-700 underline" onClick={()=>send('rejected')}>Reject</button></div>
    {editing&&<div className="mt-2 flex gap-2"><input value={value} onChange={e=>setValue(e.target.value)} className="input bg-white" aria-label={`Corrected value for ${field.label}`}/><Button variant="secondary" disabled={!value.trim()} onClick={()=>send('corrected', value)}>Save</Button></div>}
    {error&&<p role="alert" className="text-xs text-rose-600">{error}</p>}</div>
}

export default function EncounterCase() {
  const { id } = useParams()
  const navigate = useNavigate()
  const qc = useQueryClient()
  const { data: enc, error } = useQuery({ queryKey: ['encounter', id], queryFn: () => api.get<EncounterDetail>(`/clinician/encounters/${id}`), retry: false })
  const history = useQuery({ queryKey: ['previsit-history', id], queryFn: () => api.get<PreVisitHistory>(`/clinician/encounters/${id}/previsit-history`), retry: false })
  const { data: intake } = useQuery({ queryKey: ['encounter-intake', id], queryFn: () => api.get<ClinicianIntake>(`/clinician/encounters/${id}/intake`), retry: false, enabled: !!enc })
  const cases = useQuery({ queryKey: ['clinician-cases'], queryFn: () => api.get<ClinicianCaseRow[]>('/clinician/absence-cases'), enabled: !!enc })
  const caseRow = cases.data?.find(c => c.encounter_id === id)
  const caseQ = useQuery({ queryKey: ['clinician-case', caseRow?.id], queryFn: () => api.get<ClinicianCase>(`/clinician/absence-cases/${caseRow!.id}`), enabled: !!caseRow })
  const c = caseQ.data
  const setCase = (x: ClinicianCase) => { qc.setQueryData(['clinician-case', x.id], x); qc.invalidateQueries({ queryKey: ['clinician-cases'] }); qc.invalidateQueries({ queryKey: ['clinician-dashboard'] }) }

  const [start, setStart] = useState(''); const [end, setEnd] = useState('')
  const [choice, setChoice] = useState<'CERTIFY' | 'DECLINE' | 'DEFER' | ''>('')
  const [wording, setWording] = useState('')
  const [excluded, setExcluded] = useState<string[]>([])
  const [actionError, setActionError] = useState('')
  const [signReq, setSignReq] = useState<SignRequest | null>(null)
  const [password, setPassword] = useState(''); const [ack, setAck] = useState(false)
  const [deliverKey] = useState(newKey)
  useEffect(() => {
    if (!c) return
    // No pre-filled dates: the clinician enters them (only an existing clinician decision is restored).
    setStart(s => s || (c.decision?.start_date ?? '')); setEnd(e => e || (c.decision?.end_date ?? ''))
    setChoice(x => x || (c.decision?.decision ?? ''))
    setWording(w => w || c.decision?.wording || '')  // empty = clinic's configured CERTIFICATE_LANGUAGE
  }, [c])
  const preview = useQuery({ queryKey: ['clin-preview', c?.id, start, end], enabled: !!c && c.decision?.decision === 'CERTIFY' && !!start && !!end && end >= start, queryFn: () => api.post<Impact>(`/clinician/absence-cases/${c!.id}/preview`, { start_date: start, end_date: end }) })
  const days = start && end && end >= start ? Math.round((Date.parse(end) - Date.parse(start)) / 86400000) + 1 : 0

  const run = (fn: () => Promise<ClinicianCase | void>) => async () => { setActionError(''); try { const r = await fn(); if (r) setCase(r) } catch (e) { setActionError(e instanceof ApiError ? e.message : 'Action failed.') } }
  const saveDecision = run(async () => {
    // Clinician-initiated determination is allowed after the visit even without a student request.
    const target = c ?? await api.post<ClinicianCase>(`/clinician/encounters/${id}/absence-case`)
    if (!c) { qc.setQueryData(['clinician-case', target.id], target); qc.invalidateQueries({ queryKey: ['clinician-cases'] }) }
    return api.post<ClinicianCase>(`/clinician/absence-cases/${target.id}/decision`, choice === 'CERTIFY' ? { decision: choice, start_date: start, end_date: end, wording: wording.trim() || undefined } : { decision: choice })
  })
  const renderDoc = run(() => api.post<ClinicianCase>(`/clinician/absence-cases/${c!.id}/render`, { wording: wording.trim() || undefined, excluded_courses: excluded }))
  const openSign = run(async () => { setPassword(''); setAck(false); setSignReq(await api.post<SignRequest>(`/clinician/documents/${c!.document!.id}/sign-request`)) })
  const sign = useMutation({
    mutationFn: () => api.post<{ case: ClinicianCase }>(`/clinician/documents/${c!.document!.id}/approve-sign`, { nonce: signReq!.nonce, document_sha256: signReq!.document_sha256, recipient_courses: signReq!.recipients.map(r => r.course_code), password, confirm: ack }),
    onSuccess: r => { setCase(r.case); setSignReq(null) },
  })
  const deliver = run(() => api.post<ClinicianCase>(`/clinician/documents/${c!.document!.id}/deliver`, { idempotency_key: deliverKey }))
  const retry = (dId: string) => run(() => api.post<ClinicianCase>(`/clinician/deliveries/${dId}/retry`))()

  const doc = c?.document && c.document.state !== 'SUPERSEDED' ? c.document : null
  const decided = c?.decision?.decision === 'CERTIFY' && c.decision.start_date === start && c.decision.end_date === end
  const docCurrent = !!doc && !!c && doc.content.start_date === start && doc.content.end_date === end && (!wording.trim() || doc.content.wording === fill(wording, c.student_name, start, end))
  const status = c?.status ?? enc?.status ?? 'NEEDS_REVIEW'
  const closed = c ? ['SENT', 'DELIVERY_QUEUED', 'REVOKED'].includes(c.status) : false
  const blocked = useMemo(() => doc?.content.messages.filter(m => m.include && !m.deliverable) ?? [], [doc])

  return <div className="min-h-screen bg-[#f6f8f8] text-slate-900"><header className="sticky top-0 z-20 flex h-20 items-center justify-between border-b border-slate-200 bg-white px-5 md:px-9"><button onClick={()=>navigate('/clinician/dashboard')} className="text-sm font-semibold text-teal-700">← Back to queue</button><div className="text-center"><b>{c?`Case ${c.id.replace('case_','CL-').toUpperCase()}`:enc?enc.visit_type:'Encounter'}</b><p className="text-xs text-slate-500">Fictional clinician demo</p></div><Badge tone={tone(status)}>{c?.status_label ?? enc?.status_label ?? status}</Badge></header><main className="mx-auto max-w-7xl p-5 md:p-9">{error&&<div className="mb-5"><ErrorBanner error={error}/></div>}{actionError&&<div className="mb-5"><ErrorBanner error={new Error(actionError)}/></div>}<div className="grid gap-6 lg:grid-cols-[.7fr_1.3fr]"><div className="space-y-5"><Card className="p-6"><p className="text-xs font-semibold text-slate-500">PATIENT</p><h1 className="mt-2 text-2xl font-semibold">{enc?.student_name ?? '…'}</h1><p className="mt-1 text-sm text-slate-500">{enc?`Demo appointment · ${fmtDay(enc.starts_at,undefined,{month:'short',day:'numeric'})}, ${fmtTime(enc.starts_at)} · ${enc.visit_type}`:''}</p>{c?.student_note&&<div className="mt-3 rounded-xl bg-slate-50 p-3 text-sm"><b className="text-xs text-slate-500">Student’s note (private to you)</b><p className="mt-1">{c.student_note}</p></div>}<p className="mt-4 text-xs leading-5 text-slate-500">Patient report is distinct from clinician findings. No private narrative appears in professor-facing documents.</p></Card><Card className="p-6"><section aria-labelledby="notes-title"><div className="flex flex-wrap items-center justify-between gap-2"><h2 id="notes-title" className="text-lg font-semibold">AI-Assisted Pre-Visit Notes</h2><Badge tone="amber">Student-reported · not clinician findings</Badge></div><p className="mt-1 text-xs text-slate-500">Only details the student confirmed and authorized for this appointment. Not a diagnosis; your examination findings are recorded separately.</p><section className="mt-4 rounded-xl bg-sky-50 p-4 text-sm leading-6 text-sky-900" aria-labelledby="pvs-title"><div className="flex flex-wrap items-center justify-between gap-2"><h3 id="pvs-title" className="font-semibold">AI-Assisted Pre-Visit Summary — Student-Reported Information</h3>{intake?.version&&intake.status==='SHARED'?<Badge tone="blue">v{intake.version}</Badge>:null}</div>
  {enc&&<dl className="mt-2 space-y-1 text-xs text-sky-900"><div><b>Student:</b> {enc.student_name}</div><div><b>Appointment:</b> {fmtDay(enc.starts_at,undefined,{weekday:'short',month:'short',day:'numeric'})}, {fmtTime(enc.starts_at)}{enc.ends_at?`–${fmtTime(enc.ends_at)}`:''} · {enc.visit_type}{enc.location?` · ${enc.location}`:''}</div>{enc.purpose&&<div><b>Requested purpose (student’s words):</b> {enc.purpose}</div>}<div><b>Absence documentation:</b> {enc.absence_requested?'Requested — not medically approved':'Not requested at booking'}</div></dl>}
  {!intake?<p className="mt-2">Loading…</p>:intake.status==='NOT_SHARED'?<p className="mt-2">The student hasn’t approved a pre-visit summary for this appointment.</p>:intake.status==='WITHDRAWN'?<p className="mt-2">The student withdrew this summary. It’s no longer available.</p>:<>
    <p className="mt-2 text-xs text-sky-800">Submitted {intake.shared_at?`${fmtDay(intake.shared_at,undefined,{month:'short',day:'numeric'})} ${fmtTime(intake.shared_at)}`:''} · intake {intake.session?.intake_complete?'completed':'conversation still open'} · consent: shared by the student{intake.consent_text?` (“${intake.consent_text}”)`:''}</p>
    {intake.summary&&<div className="mt-3 rounded-lg bg-white p-3"><SummaryBody s={intake.summary} photoUrl={aid=>`/api/v1/clinician/encounters/${id}/attachments/${aid}`}/><p className="mt-3 text-[11px] text-slate-500">{intake.summary.disclaimer}</p></div>}
    <details className="mt-3"><summary className="cursor-pointer text-xs font-semibold text-sky-800">Authorized source details — accept, correct or reject each</summary><dl className="mt-2 space-y-3">{intake.fields.map(f=><FieldReview key={f.key} encounterId={id!} field={f} review={intake.annotations?.[f.key]}/>)}</dl></details></>}
</section>{history.data&&enc&&<div className="mt-6"><PreVisitHistoryView data={history.data} studentName={enc.student_name} photoUrl={aid=>`/api/v1/clinician/encounters/${id}/attachments/${aid}`}/></div>}</section></Card><Card className="p-6"><h2 className="font-semibold">Consent & provenance</h2><div className="mt-4 space-y-3 text-sm"><div className="flex justify-between gap-2"><span>Intake shared by student</span><Badge tone={intake?.status==='SHARED'?'teal':'slate'}>{intake?.status==='SHARED'?'Consented':intake?.status==='WITHDRAWN'?'Withdrawn':'Not shared'}</Badge></div><div className="flex justify-between gap-2"><span>Consent to send to instructors</span><Badge tone={c?.gates.student_consent?'teal':'amber'}>{c?(c.gates.student_consent?'Given':'Not given'):'—'}</Badge></div><div className="flex justify-between gap-2"><span>Voice transcript</span><Badge tone="slate">Never shared</Badge></div><div className="flex justify-between gap-2"><span>Photos</span><Badge tone={intake?.consent?.photo_shared?'teal':'slate'}>{intake?.consent?.photo_shared?'Shared by student':'Not shared'}</Badge></div><div className="flex justify-between gap-2"><span>Source</span><SourceBadge mode={enc?.source_mode ?? 'demo'}/></div></div></Card></div>
    <div className="space-y-5">
      <EvaluationCard encounterId={id!}/>
      <Card className="p-6"><div className="flex flex-wrap items-start justify-between gap-3"><div><h2 className="text-xl font-semibold">Absence determination</h2><p className="mt-1 text-sm text-slate-500">Your independent clinical judgment. CuraLink never suggests a duration, and the student's class schedule is only used after you decide.</p></div>{c&&c.decision?.decision==='CERTIFY'&&<Badge tone="blue">{days} calendar day{days!==1?'s':''}</Badge>}</div>
        {c?.origin!=='clinician'&&c&&<p className="mt-3 rounded-lg bg-slate-50 p-3 text-xs text-slate-600"><b>Student-reported class absences</b> (the student’s own report — context only, not a request for specific certified dates): {c.reported_missed_dates.length?c.reported_missed_dates.map(shortDate).join(', '):c.legacy_requested_range?`${shortDate(c.legacy_requested_range.start)} – ${shortDate(c.legacy_requested_range.end)}`:'none reported'}. Any medically supported dates are yours to decide.</p>}
        <fieldset disabled={closed&&!!c} className="mt-5"><legend className="text-sm font-semibold">Decision</legend><div className="mt-2 grid gap-2">{([['DECLINE','No medical absence certificate indicated'],['CERTIFY','Approve an absence period'],['DEFER','Defer determination pending further evaluation']] as const).map(([v,l])=><label key={v} className={`flex items-center gap-3 rounded-xl border p-3 text-sm ${choice===v?'border-teal-500 bg-teal-50':'border-slate-200'}`}><input type="radio" name="determination" value={v} checked={choice===v} onChange={()=>setChoice(v)} className="size-4 accent-teal-700"/>{l}</label>)}</div></fieldset>
        {choice==='CERTIFY'&&<div className="mt-5 grid gap-4 sm:grid-cols-2"><label className="text-sm font-semibold">Inclusive first date<input type="date" disabled={closed&&!!c} value={start} onChange={e=>setStart(e.target.value)} className="input mt-2"/></label><label className="text-sm font-semibold">Inclusive last date<input type="date" disabled={closed&&!!c} min={start} value={end} onChange={e=>setEnd(e.target.value)} className="input mt-2"/></label><p className="text-xs text-slate-500 sm:col-span-2">Choose dates manually. One-day absences: same first and last date.</p></div>}
        {!(closed&&c)&&<div className="mt-5 flex flex-wrap gap-3"><Button disabled={!choice||(choice==='CERTIFY'&&!days)} onClick={saveDecision}>{!choice?'Choose a decision':choice==='CERTIFY'?(decided?'Dates saved ✓ — update':'Save absence period'):choice==='DEFER'?'Save: defer':'Save: no certificate'}</Button></div>}
        {c?.status==='REJECTED'&&<p className="mt-4 rounded-xl bg-slate-50 p-3 text-sm">No medical absence certificate indicated. Nothing can be generated or sent.</p>}
        {c?.status==='DEFERRED'&&<p className="mt-4 rounded-xl bg-amber-50 p-3 text-sm text-amber-900">Deferred pending further evaluation. No documents are generated until you decide.</p>}
        {c&&c.decision?.decision==='CERTIFY'&&<><div className="mt-6 rounded-xl border border-slate-200 bg-slate-50 p-4"><b className="text-sm">Administrative: affected class meetings</b><p className="text-xs text-slate-500">Computed from the student's imported calendar after your decision.</p>{preview.isLoading?<LoadingBlock className="mt-3 h-16"/>:preview.data&&<><div className="mt-3 space-y-2">{preview.data.recipients.length===0&&<p className="text-sm text-slate-500">No class meetings in this range.</p>}{preview.data.recipients.map(r=><div key={r.course_code} className="flex flex-wrap items-center justify-between gap-2 text-sm"><span>{r.course_code} · {r.instructor_name ?? 'Instructor unknown'}</span><span className="text-slate-500">{r.dates.map(shortDate).join(' & ')} · <span className={r.deliverable?'text-teal-700':'text-amber-700'}>{r.deliverable?'recipient verified':r.blocked_reason}</span></span></div>)}</div><p className="mt-3 text-xs text-slate-500">{preview.data.days.filter(d=>d.meeting_count===0).length>0?`No classes on: ${preview.data.days.filter(d=>d.meeting_count===0).map(d=>shortDate(d.date)+(d.weekend?' (weekend)':'')).join(', ')}.`:'Every day in this range has class meetings.'}</p></>}</div>
        <label className="mt-5 block text-sm font-semibold">Certificate wording (optional override)<textarea disabled={closed} className="input mt-2 min-h-28 font-normal" value={wording} placeholder="Leave empty to use the clinic's provider-approved wording." onChange={e=>setWording(e.target.value)}/><span className="mt-1 block text-xs font-normal text-slate-500">Placeholders: {'{student}'}, {'{start}'}, {'{end}'}. No diagnosis, symptoms or intake details.</span></label></>}
      </Card>
      {c&&<Card className="p-6"><div className="flex items-center justify-between gap-2"><div><h2 className="text-lg font-semibold">Document review</h2><p className="text-sm text-slate-500">{doc?`Version ${doc.version} · ${doc.state==='SIGNED'?'signed (simulated)':'unsigned'}`:'No document yet'}</p></div><Badge tone={doc?.state==='SIGNED'?'teal':'slate'}>{doc?.state==='SIGNED'?'SIGNED':'DRAFT'}</Badge></div>
        {c.decision?.decision==='CERTIFY'&&!closed&&!docCurrent&&<div className="mt-4 rounded-xl border border-dashed border-slate-300 p-4 text-sm"><p className="text-slate-600">{doc?'Changes will invalidate the existing signature and require another review.':'Generate an immutable, unsigned PDF and per-instructor drafts from the dates above.'}</p>{preview.data&&preview.data.recipients.length>0&&<fieldset className="mt-3"><legend className="text-xs font-semibold text-slate-500">Include instructors</legend><div className="mt-1 flex flex-wrap gap-3">{preview.data.recipients.map(r=><label key={r.course_code} className="flex items-center gap-2"><input type="checkbox" className="size-4 accent-teal-700" checked={!excluded.includes(r.course_code)} onChange={e=>setExcluded(x=>e.target.checked?x.filter(y=>y!==r.course_code):[...x,r.course_code])}/>{r.course_code}</label>)}</div></fieldset>}<Button className="mt-3" disabled={!decided} onClick={renderDoc}>{doc?'Generate new version':'Generate document'}</Button>{!decided&&<p className="mt-2 text-xs text-amber-700">Approve the date range first.</p>}</div>}
        {doc&&<><div className="mt-5"><PdfPreview versionId={doc.id} signed={doc.state==='SIGNED'}/></div>
          <details className="mt-4 text-sm" open><summary className="cursor-pointer font-semibold">Instructor messages ({doc.content.messages.filter(m=>m.include).length})</summary><div className="mt-3 space-y-3">{doc.content.messages.map(m=><div key={m.course_code} className={`rounded-xl border p-3 ${m.include?'border-slate-200':'border-dashed border-slate-200 opacity-60'}`}><div className="flex flex-wrap justify-between gap-2"><b>{m.course_code} → {m.email ?? 'no verified address'}</b><span className={`text-xs font-semibold ${!m.include?'text-slate-500':m.deliverable?'text-teal-700':'text-amber-700'}`}>{!m.include?'Excluded':m.deliverable?'Verified recipient':m.blocked_reason}</span></div><p className="mt-1 text-xs text-slate-500">{m.subject}</p><pre className="mt-2 whitespace-pre-wrap font-sans text-xs leading-5 text-slate-600">{m.body}</pre></div>)}</div></details>
          <p className="mt-3 break-all text-[11px] text-slate-400">sha256 {doc.state==='SIGNED'?doc.signed_sha256:doc.unsigned_sha256}</p>
          <div className="mt-5 flex flex-wrap items-center justify-end gap-3">
            {doc.state==='UNSIGNED'&&docCurrent&&(c.signature_asset?<Button onClick={openSign}>Approve & sign this version</Button>:<p className="text-sm text-amber-700">Enroll your demo signature in <Link to="/clinician/signatures" className="font-semibold underline">Signature Settings</Link> to sign.</p>)}
            {doc.state==='SIGNED'&&c.status!=='SENT'&&c.status!=='FAILED'&&(blocked.length?<p className="text-sm text-amber-700">Recipient not verified: {blocked.map(b=>b.course_code).join(', ')}. The student must confirm these contacts; then generate and sign a new version.</p>:!c.gates.student_consent?<p className="text-sm text-amber-700">The student hasn’t consented to sending. Nothing will be sent.</p>:<Button onClick={deliver}>Send authorized copies (test inbox)</Button>)}
          </div></>}
        {c.deliveries.length>0&&<div className="mt-5 rounded-xl bg-slate-50 p-4 text-sm"><b>Delivery receipts</b><ul className="mt-2 space-y-1.5">{c.deliveries.map(d=><li key={d.id} className="flex flex-wrap items-center justify-between gap-2"><span>{d.course_code} → {d.destination}</span><span className="flex items-center gap-2"><span className={d.state==='SENT'?'text-teal-700':d.state==='FAILED'?'text-rose-700':'text-slate-500'}>{d.state}{d.error_code?` · ${d.error_code}`:''}{d.sent_at?` · ${fmtRelative(d.sent_at)}`:''}</span>{d.state==='FAILED'&&<Button variant="secondary" className="min-h-8 py-1" onClick={()=>retry(d.id)}>Retry</Button>}</span></li>)}</ul><p className="mt-3 text-xs text-slate-500">Delivered to verified test inboxes only. This never claims university approval. <Link to="/demo/inbox" className="font-semibold text-teal-700 underline">Open test inbox</Link></p></div>}
      </Card>}
    </div></div></main>
    {signReq&&c?.document&&<div role="dialog" aria-modal="true" aria-labelledby="sign-title" className="fixed inset-0 z-50 grid place-items-center bg-slate-950/50 p-5"><Card className="max-w-md p-6"><Badge tone="amber">FRESH CONFIRMATION REQUIRED</Badge><h2 id="sign-title" className="mt-4 text-xl font-semibold">Sign this exact version?</h2><p className="mt-3 text-sm leading-6 text-slate-500">Version {signReq.version}: {shortDate(signReq.start_date)} through {shortDate(signReq.end_date)} (inclusive). Any later edit invalidates this signature. The sample signature is fictional and watermarked DEMO.</p><div className="mt-3 rounded-lg bg-slate-50 p-3 text-xs"><b>Recipients</b><ul className="mt-1">{signReq.recipients.map(r=><li key={r.course_code}>{r.course_code} → {r.email ?? 'no verified address'}</li>)}</ul><p className="mt-2 break-all text-slate-400">Document sha256 {signReq.document_sha256.slice(0,32)}…</p></div><label className="mt-4 block text-sm font-semibold">Re-enter your password<input type="password" value={password} onChange={e=>setPassword(e.target.value)} className="input mt-2" autoComplete="current-password"/></label><label className="mt-3 flex items-start gap-3 text-sm"><input type="checkbox" checked={ack} onChange={e=>setAck(e.target.checked)} className="mt-0.5 size-5 accent-teal-700"/><span>I reviewed the full preview, dates and recipients, and approve this version.</span></label>{sign.error&&<p role="alert" className="mt-3 text-sm text-rose-600">{(sign.error as Error).message}</p>}<div className="mt-6 flex justify-end gap-2"><Button variant="ghost" onClick={()=>setSignReq(null)}>Cancel</Button><Button disabled={!ack||!password||sign.isPending} onClick={()=>sign.mutate()}>Confirm demo signature</Button></div></Card></div>}
  </div>
}
