import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Badge, Button, Card, ErrorBanner, Icon, LoadingBlock, SourceBadge } from '../../components/ui'
import { api, ApiError } from '../../lib/api'
import { eventLabel, fmtDay, fmtRelative, fmtTime, fmtYmd } from '../../lib/format'
import type { Impact, Recipient, StudentCase, StudentEncounter } from '../../lib/types'

const shortDate = (ymd: string) => fmtYmd(ymd, { weekday: 'short', month: 'short', day: 'numeric' })
const statusTone = (s: string) => (s === 'SENT' ? 'teal' : s === 'FAILED' || s === 'REJECTED' ? 'rose' : s === 'REVOKED' ? 'slate' : 'amber')
const contactLabel = (r: Recipient) => r.deliverable ? (r.contact_status === 'STUDENT_CONFIRMED' ? 'Recipient confirmed by you' : 'Recipient verified') : r.blocked_reason ?? 'Contact needed'

function ContactFix({ r, onSaved }: { r: Recipient; onSaved: () => void }) {
  const [email, setEmail] = useState(r.email ?? '')
  const [ok, setOk] = useState(false)
  const [error, setError] = useState('')
  const save = useMutation({
    mutationFn: () => api.patch(`/courses/${r.course_id}/contact`, { instructor_email: email, confirm: ok }),
    onSuccess: onSaved,
    onError: e => setError(e instanceof ApiError ? e.message : 'Could not save.'),
  })
  return <div className="mt-3 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm"><p className="text-amber-900">We couldn't verify this instructor's contact information. Please check it before sending.</p><div className="mt-2 flex flex-wrap gap-2"><input value={email} onChange={e=>setEmail(e.target.value)} className="input max-w-xs bg-white" placeholder="instructor@example.com" aria-label={`Instructor email for ${r.course_code}`}/><label className="flex items-center gap-2 text-xs"><input type="checkbox" checked={ok} onChange={e=>setOk(e.target.checked)} className="size-4 accent-teal-700"/>I checked this address on the official course page</label><Button variant="secondary" disabled={!ok||!email.includes('@')||save.isPending} onClick={()=>save.mutate()}>Save contact</Button></div>{error&&<p role="alert" className="mt-1 text-xs text-rose-600">{error}</p>}<p className="mt-1 text-xs text-amber-800">Demo deliveries only go to example.com test addresses.</p></div>
}

function CaseCard({ c }: { c: StudentCase }) {
  const qc = useQueryClient()
  const consent = useMutation({ mutationFn: (v: boolean) => api.post(`/absence-cases/${c.id}/consent`, { consent: v }), onSuccess: () => qc.invalidateQueries({ queryKey: ['my-cases'] }) })
  const sent = c.deliveries.filter(d => d.state === 'SENT').length
  return <Card className="p-5"><div className="flex flex-wrap items-start justify-between gap-3"><div><div className="flex flex-wrap items-center gap-2"><b>Case {c.id.replace('case_', 'CL-').toUpperCase()}</b><Badge tone={statusTone(c.status)}>{c.status_label}</Badge><SourceBadge mode="demo"/></div><p className="mt-1 text-sm text-slate-500">{c.visit_type} · {fmtDay(c.appointment_at)} {fmtTime(c.appointment_at)} · {c.clinician_name}</p></div><p className="text-xs text-slate-400">Opened {fmtRelative(c.created_at)}</p></div>
    <dl className="mt-4 grid gap-3 text-sm sm:grid-cols-3"><div><dt className="text-xs font-semibold text-slate-500">You requested</dt><dd>{shortDate(c.requested_start)} – {shortDate(c.requested_end)}</dd></div><div><dt className="text-xs font-semibold text-slate-500">Clinician decision</dt><dd>{!c.decision?'Not yet':c.decision.decision==='DECLINE'?'Declined to document':`${shortDate(c.decision.start_date!)} – ${shortDate(c.decision.end_date!)}`}</dd></div><div><dt className="text-xs font-semibold text-slate-500">University excusal</dt><dd>Decided by your university</dd></div></dl>
    {c.status==='PENDING_CLINICIAN_SIGNATURE'||c.status==='STUDENT_REQUESTED'||c.status==='CLINICIAN_REVIEW'||c.status==='DATES_SET'?<div className="mt-4 rounded-xl bg-amber-50 p-3 text-sm text-amber-800">Waiting for provider review. No medical verification has been issued. Nothing has been sent yet.</div>:null}
    {c.status==='REJECTED'&&<div className="mt-4 rounded-xl bg-slate-50 p-3 text-sm text-slate-700">Your clinician chose not to document an absence. Nothing was sent.</div>}
    {c.deliveries.length>0&&<div className="mt-4"><p className="text-xs font-semibold text-slate-500">Delivery receipts ({sent}/{c.deliveries.length})</p><ul className="mt-2 space-y-1.5 text-sm">{c.deliveries.map(d=><li key={d.id} className="flex flex-wrap justify-between gap-2"><span>{d.course_code} → {d.destination}</span><span className={d.state==='SENT'?'text-teal-700':d.state==='FAILED'?'text-rose-700':'text-slate-500'}>{d.state==='SENT'?`Delivered to test inbox ${d.sent_at?fmtRelative(d.sent_at).toLowerCase():''}`:d.state==='FAILED'?`Failed (${d.error_code}) — clinician can retry`:d.state==='CANCELLED'?'Cancelled':'Queued'}</span></li>)}</ul>{c.status==='SENT'&&<p className="mt-2 text-xs text-slate-500">Delivered to a test inbox. Your university decides whether any absence is excused. <Link to="/demo/inbox" className="font-semibold text-teal-700 underline">View test inbox</Link></p>}</div>}
    {c.metrics.request_to_delivery_seconds!==null&&<p className="mt-3 text-xs text-slate-500">Measured for this case: request to delivered in {Math.max(1,Math.round(c.metrics.request_to_delivery_seconds/60))} min with {c.metrics.student_actions} student action{c.metrics.student_actions===1?'':'s'} (from the activity log).</p>}<details className="mt-4 text-sm"><summary className="cursor-pointer font-semibold text-slate-600">Activity ({c.timeline.length})</summary><ol className="mt-2 space-y-1.5 border-l border-slate-200 pl-4">{c.timeline.map((t,i)=><li key={i}><b className="text-slate-700">{eventLabel(t.event_type)}</b> <span className="text-slate-500">· {t.actor} · {fmtRelative(t.at)}</span></li>)}</ol></details>
    <div className="mt-4 flex flex-wrap items-center justify-between gap-3 border-t border-slate-100 pt-4 text-sm">{c.disclosure_consent?<><span className="text-slate-600">You consented to sending minimal verification after your clinician signs.</span>{c.status!=='SENT'&&<Button variant="danger" disabled={consent.isPending} onClick={()=>consent.mutate(false)}>Withdraw consent</Button>}</>:<><span className="text-slate-600">{c.consent_revoked_at?'You withdrew consent. Nothing further will be sent; already-delivered messages can’t be recalled.':'No consent to send yet. Your clinician can review, but nothing will be sent.'}</span>{!['SENT','REJECTED'].includes(c.status)&&<Button variant="secondary" disabled={consent.isPending} onClick={()=>consent.mutate(true)}>Give consent to send</Button>}</>}</div>
  </Card>
}

export default function AbsenceCenter() {
  const qc = useQueryClient()
  const cases = useQuery({ queryKey: ['my-cases'], queryFn: () => api.get<StudentCase[]>('/students/me/cases') })
  const encounters = useQuery({ queryKey: ['my-encounters'], queryFn: () => api.get<StudentEncounter[]>('/students/me/encounters') })
  const [step, setStep] = useState(0) // 0 list, 1 request, 2 review, 3 submitted
  const [encId, setEncId] = useState('')
  const [start, setStart] = useState('2026-10-27'); const [end, setEnd] = useState('2026-10-28')
  const [note, setNote] = useState('')
  const [consent, setConsent] = useState(false)
  const [error, setError] = useState('')
  const upcoming = encounters.data ?? []
  useEffect(() => { if (!encId && upcoming[0]) setEncId(upcoming[0].id) }, [upcoming, encId])
  const impact = useQuery({ queryKey: ['impact-preview', start, end], enabled: step === 2, queryFn: () => api.post<Impact>('/absence-cases/preview', { start_date: start, end_date: end }) })
  const submit = useMutation({
    mutationFn: () => api.post<StudentCase>('/absence-cases', { encounter_id: encId, requested_start: start, requested_end: end, note: note || null, disclosure_consent: consent }),
    onSuccess: () => { setStep(3); qc.invalidateQueries({ queryKey: ['my-cases'] }) },
    onError: e => setError(e instanceof ApiError ? e.message : 'Could not submit.'),
  })
  const latest = cases.data?.[0]

  if (step===3&&latest) return <div className="mx-auto max-w-2xl pt-8 text-center"><div className="mx-auto grid size-16 place-items-center rounded-full bg-teal-100 text-teal-700"><Icon name="check" size={30}/></div><div className="mt-5"><Badge tone="amber">PENDING CLINICIAN REVIEW</Badge></div><h1 className="mt-5 text-3xl font-semibold">Case submitted securely</h1><p className="mt-3 leading-7 text-slate-600">Your clinician—not you—will decide whether documentation is appropriate and choose the medically supported date range. Nothing has been sent to professors.</p><div className="mt-7 text-left"><CaseCard c={latest}/></div><Button className="mt-7" onClick={()=>setStep(0)}>Back to my cases</Button></div>

  if (step===0) return <><div className="flex flex-wrap items-end justify-between gap-4"><div><h1 className="text-3xl font-semibold">My Cases</h1><p className="mt-2 text-slate-500">Share possible schedule impact with your clinician for independent review, and track what happens next.</p></div><Button onClick={()=>{setStep(1);setError('');setConsent(false)}}><Icon name="plus" size={18}/>Request absence review</Button></div>
    <div className="mt-7 space-y-5">{cases.error&&<ErrorBanner error={cases.error} onRetry={()=>cases.refetch()}/>}{cases.isLoading&&<LoadingBlock className="h-40"/>}{cases.data?.length===0&&<Card className="p-8 text-center"><h2 className="text-lg font-semibold">No cases yet</h2><p className="mt-2 text-sm text-slate-500">If a health appointment may affect your classes, request a review. Your clinician decides what, if anything, to document.</p></Card>}{cases.data?.map(c=><CaseCard key={c.id} c={c}/>)}</div></>

  return <><div className="flex flex-wrap items-end justify-between gap-4"><div><h1 className="text-3xl font-semibold">My Cases</h1><p className="mt-2 text-slate-500">Share possible schedule impact with your clinician for independent review.</p></div><Badge tone="blue">Step {step} of 3</Badge></div><div className="mt-7 flex gap-2">{[1,2,3].map(i=><div key={i} className={`h-1.5 flex-1 rounded-full ${i<=step?'bg-teal-600':'bg-slate-200'}`}/>)}</div>
    <Card className="mx-auto mt-7 max-w-4xl p-6 md:p-8">
      {step===1&&<><h2 className="text-xl font-semibold">Tell your clinician what may be affected</h2><p className="mt-2 text-sm text-slate-500">This is a request, not self-approved absence documentation.</p>
        {upcoming.length===0&&!encounters.isLoading?<p className="mt-6 rounded-xl bg-slate-50 p-4 text-sm text-slate-600">You need a demo appointment first so the right clinician can review this. <Link to="/student/appointments" className="font-semibold text-teal-700 underline">Find an appointment</Link></p>:<>
        <label className="mt-6 block text-sm font-semibold">Appointment<select className="input mt-2" value={encId} onChange={e=>setEncId(e.target.value)}>{upcoming.map(e=><option key={e.id} value={e.id}>{e.visit_type} · {fmtDay(e.starts_at)} {fmtTime(e.starts_at)} · {e.clinician_name}</option>)}</select></label>
        <div className="mt-5 grid gap-5 md:grid-cols-2"><label className="text-sm font-semibold">First date you may miss<input type="date" value={start} onChange={e=>{setStart(e.target.value);if(e.target.value>end)setEnd(e.target.value)}} className="input mt-2"/></label><label className="text-sm font-semibold">Last date you may miss<input type="date" min={start} value={end} onChange={e=>setEnd(e.target.value)} className="input mt-2"/></label></div>
        <label className="mt-5 block text-sm font-semibold">Optional note for your clinician <span className="font-normal text-slate-400">— no diagnosis required, never sent to professors</span><textarea value={note} onChange={e=>setNote(e.target.value)} maxLength={1000} className="input mt-2 min-h-24" placeholder="Administrative context for your clinician"/></label>
        <div className="mt-6 flex justify-between"><Button variant="ghost" onClick={()=>setStep(0)}>Cancel</Button><Button disabled={!encId} onClick={()=>setStep(2)}>Review impacted classes <Icon name="arrow"/></Button></div></>}</>}
      {step===2&&<><h2 className="text-xl font-semibold">Possible impacted classes</h2><p className="mt-2 text-slate-500">Based on your imported calendar for {shortDate(start)} – {shortDate(end)}. Your clinician will choose the final inclusive date range.</p>
        {impact.isLoading&&<LoadingBlock className="mt-5 h-32"/>}{impact.error&&<div className="mt-5"><ErrorBanner error={impact.error}/></div>}
        {impact.data&&<><div className="mt-5 flex flex-wrap gap-2">{impact.data.days.map(d=><span key={d.date} className={`rounded-lg px-2.5 py-1 text-xs ${d.meeting_count?'bg-teal-50 text-teal-800':'bg-slate-100 text-slate-500'}`}>{shortDate(d.date)} · {d.meeting_count?`${d.meeting_count} class${d.meeting_count>1?'es':''}`:d.weekend?'weekend':'no classes'}</span>)}</div>
          <div className="mt-5 space-y-3">{impact.data.recipients.length===0&&<p className="text-sm text-slate-500">No class meetings fall in these dates.</p>}{impact.data.recipients.map(r=><div key={r.course_code} className="rounded-xl border border-slate-200 p-4"><div className="flex flex-wrap items-center justify-between gap-2"><b>{r.course_code} · {r.course_title}</b><span className={`text-xs font-semibold ${r.deliverable?'text-teal-700':'text-amber-700'}`}>{contactLabel(r)}</span></div><p className="text-sm text-slate-500">{r.dates.map(shortDate).join(', ')} · {r.instructor_name ?? 'Instructor not listed'}{r.email?` · ${r.email}`:''}</p>{!r.deliverable&&r.course_id&&<ContactFix r={r} onSaved={()=>impact.refetch()}/>}</div>)}</div></>}
        <label className="mt-5 flex items-start gap-3 rounded-xl bg-slate-50 p-4 text-sm"><input type="checkbox" checked={consent} onChange={e=>setConsent(e.target.checked)} className="mt-0.5 size-5 accent-teal-700"/><span>I consent to CuraLink sending a minimal attendance verification (no symptoms or diagnosis) to the instructors above <b>only after</b> my clinician reviews and signs it. I can withdraw this before anything is sent.</span></label>
        <p className="mt-2 text-xs text-slate-500">You can also submit without consenting now; your clinician can still review, but nothing will be sent.</p>
        {error&&<p role="alert" className="mt-3 text-sm text-rose-600">{error}</p>}
        <div className="mt-6 flex justify-between"><Button variant="ghost" onClick={()=>setStep(1)}>Back</Button><Button disabled={submit.isPending||!impact.data} onClick={()=>submit.mutate()}>Submit for clinician review</Button></div></>}
    </Card></>
}
