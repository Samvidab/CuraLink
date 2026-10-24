import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Badge, Button, Card, ErrorBanner, Icon, LoadingBlock, SourceBadge } from '../../components/ui'
import { api, ApiError } from '../../lib/api'
import { fmtDay, fmtRange } from '../../lib/format'
import type { AppointmentSummary, ConfirmResult, Recommendations, SlotOption, SlotsResponse } from '../../lib/types'

const REASONS: Record<string, string> = {
  NO_CLASS_CONFLICT: 'No class conflict',
  HAS_CONFLICT_ALLOWED_BY_STUDENT: 'Overlaps a class (you allowed this)',
  SOONEST_AVAILABLE: 'Soonest available',
  SHORT_TRAVEL: 'Short travel',
  LONGER_TRAVEL: 'Longer travel',
  OUTSIDE_PREFERRED_HOURS: 'Outside your preferred hours',
  TIGHT_BETWEEN_CLASSES: 'Tight gap between classes',
  COMFORTABLE_GAP: 'Comfortable gap',
}
const REJECTED: Record<string, string> = {
  CLASS_CONFLICT: 'Overlaps a class',
  TRAVEL_BUFFER_CONFLICT: 'Not enough travel time around a class',
  PERSONAL_BLOCK_CONFLICT: 'Overlaps a personal block',
  SLOT_UNAVAILABLE: 'No longer available',
  IN_THE_PAST: 'Already passed',
  TRAVEL_TOO_LONG: 'Travel longer than your limit',
  NOT_ELIGIBLE: 'Not offered to you by the clinic',
}
const newKey = () => (crypto.randomUUID ? crypto.randomUUID() : `k-${Date.now()}-${Math.random().toString(36).slice(2)}`)

export default function FindCare() {
  const go = useNavigate()
  const qc = useQueryClient()
  const [service, setService] = useState('routine_checkup')
  const [start, setStart] = useState('2026-10-26')
  const [maxTravel, setMaxTravel] = useState<number | null>(null)
  const [earliest, setEarliest] = useState<number | null>(null)
  const [choice, setChoice] = useState<SlotOption | null>(null)
  const [dialog, setDialog] = useState(false)
  const [understood, setUnderstood] = useState(false)
  const [notice, setNotice] = useState('')
  const [confirmed, setConfirmed] = useState<ConfirmResult | null>(null)
  const [idemKey, setIdemKey] = useState(newKey)

  const types = useQuery({ queryKey: ['clinic-types'], queryFn: () => api.get<SlotsResponse>('/clinic/slots?days=1') })
  const mine = useQuery({ queryKey: ['my-appointments'], queryFn: () => api.get<AppointmentSummary[]>('/appointments/me') })
  const prefs = { max_travel_minutes: maxTravel, earliest_hour: earliest }
  const recs = useQuery({
    queryKey: ['recommendations', service, start, prefs],
    queryFn: () => api.post<Recommendations>('/schedule/recommendations', { appointment_type: service, start, days: 5, preferences: prefs }),
  })
  const confirm = useMutation({
    mutationFn: (slotId: string) => api.post<ConfirmResult>('/appointments/confirm', { slot_id: slotId, student_approved: true, idempotency_key: idemKey }),
    onSuccess: r => { setConfirmed(r); setDialog(false); qc.invalidateQueries({ queryKey: ['student-dashboard'] }); qc.invalidateQueries({ queryKey: ['my-appointments'] }) },
    onError: e => {
      if (e instanceof ApiError && (e.code === 'SLOT_UNAVAILABLE' || e.code === 'CLASS_CONFLICT')) {
        // Never silently reschedule: tell the student and show fresh options.
        setDialog(false); setChoice(null); setIdemKey(newKey()); setNotice(e.message)
        qc.invalidateQueries({ queryKey: ['recommendations'] })
      }
    },
  })
  const cancel = useMutation({
    mutationFn: (id: string) => api.post<AppointmentSummary>(`/appointments/${id}/cancel`),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['my-appointments'] }); qc.invalidateQueries({ queryKey: ['recommendations'] }); qc.invalidateQueries({ queryKey: ['student-dashboard'] }) },
  })
  const invalidate = useMutation({
    mutationFn: (id: string) => api.post(`/demo/slots/${id}/invalidate`),
    onSuccess: () => setNotice('Demo: that slot was marked as taken by someone else. If you try to confirm it, CuraLink re-checks availability first.'),
  })
  const typeLabel = useMemo(() => Object.fromEntries((types.data?.appointment_types ?? []).map(t => [t.id, t.label])), [types.data])
  const active = mine.data?.filter(a => a.state === 'DEMO_CONFIRMED') ?? []
  const options = recs.data?.options ?? []

  if (confirmed) return <div className="mx-auto max-w-2xl pt-12 text-center"><div className="mx-auto grid size-16 place-items-center rounded-full bg-teal-100 text-teal-700"><Icon name="check" size={30}/></div><div className="mt-5"><SourceBadge mode={confirmed.appointment.source_mode}/></div><h1 className="mt-4 text-3xl font-semibold">Demo time reserved</h1><p className="mt-3 text-slate-600">{typeLabel[confirmed.appointment.appointment_type] ?? confirmed.appointment.appointment_type} · {fmtDay(confirmed.appointment.starts_at)} · {fmtRange(confirmed.appointment.starts_at, confirmed.appointment.ends_at)}<br/>{confirmed.appointment.clinic_name}</p><p className="mt-3 rounded-xl bg-sky-50 p-3 text-sm text-sky-800" role="status">{confirmed.message} No request was sent to a university clinic.</p><div className="mt-7 flex flex-wrap justify-center gap-3"><Button onClick={()=>go('/student/cases')}>Prepare absence support <Icon name="arrow"/></Button><Button variant="secondary" onClick={()=>{setConfirmed(null);setChoice(null);setIdemKey(newKey())}}>Back to availability</Button></div></div>

  return <><h1 className="text-3xl font-semibold">Find care</h1><p className="mt-2 text-slate-500">Explore sample campus services and compare times with your classes.</p><div className="mt-5 rounded-xl border border-sky-200 bg-sky-50 p-3 text-sm text-sky-800"><b>Demo availability:</b> Times below come from a synthetic clinic inventory and are not connected to a university clinic. CuraLink ranks them only by fit with your schedule — never by medical urgency.</div>
    {notice&&<div role="alert" className="mt-4 flex items-start justify-between gap-3 rounded-xl border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900"><span>{notice}</span><button onClick={()=>setNotice('')} aria-label="Dismiss" className="text-amber-700">×</button></div>}
    {active.length>0&&<Card className="mt-6 p-5"><div className="flex flex-wrap items-center justify-between gap-3"><div><Badge tone="blue">Your demo appointment{active.length>1?'s':''}</Badge>{active.map(a=><p key={a.id} className="mt-2 text-sm"><b>{typeLabel[a.appointment_type] ?? a.appointment_type}</b> · {fmtDay(a.starts_at)} · {fmtRange(a.starts_at,a.ends_at)} · {a.clinic_name}</p>)}</div><div className="flex gap-2">{active.map(a=><Button key={a.id} variant="danger" disabled={cancel.isPending} onClick={()=>cancel.mutate(a.id)}>Cancel demo booking</Button>)}</div></div></Card>}
    <h2 className="mt-8 text-lg font-semibold">What do you need?</h2><div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">{(types.data?.appointment_types ?? []).map(s=><button key={s.id} onClick={()=>{setService(s.id);setChoice(null)}} aria-pressed={service===s.id} className={`rounded-2xl border p-4 text-left text-sm font-semibold transition ${service===s.id?'border-teal-500 bg-teal-50 text-teal-800':'border-slate-200 bg-white hover:border-teal-300'}`}>{s.label}</button>)}{types.isLoading&&<LoadingBlock className="h-14 sm:col-span-2 lg:col-span-4"/>}</div>
    <div className="mt-7 grid gap-5 lg:grid-cols-[.65fr_1.35fr]"><Card className="h-fit p-5"><label className="text-sm font-semibold">Search from<input type="date" value={start} min="2026-10-26" onChange={e=>{setStart(e.target.value);setChoice(null)}} className="input mt-2"/></label><label className="mt-4 block text-sm font-semibold">Travel time<select className="input mt-2" value={maxTravel ?? ''} onChange={e=>setMaxTravel(e.target.value?Number(e.target.value):null)}><option value="">Any distance</option><option value="10">Up to 10 min</option><option value="30">Up to 30 min</option></select></label><label className="mt-4 block text-sm font-semibold">Prefer times after<select className="input mt-2" value={earliest ?? ''} onChange={e=>setEarliest(e.target.value?Number(e.target.value):null)}><option value="">No preference</option><option value="10">10 AM</option><option value="12">Noon</option><option value="14">2 PM</option></select></label><p className="mt-5 text-sm leading-6 text-slate-500">{recs.data?.calendar_considered===false?<>No calendar imported, so class conflicts can’t be checked. <button className="font-semibold text-teal-700 underline" onClick={()=>go('/student/import')}>Import calendar</button></>:'CuraLink checks each time against your imported classes and travel time between them.'}</p><p className="mt-3 text-xs text-slate-400">Ranking = wait time + travel + your preferences. Ties break by start time.</p></Card>
      <Card className="p-5"><div className="flex items-center justify-between gap-2"><h2 className="font-semibold">Available times</h2>{recs.data&&<SourceBadge mode={recs.data.source_mode}/>}</div>
        {recs.error&&<div className="mt-4"><ErrorBanner error={recs.error} onRetry={()=>recs.refetch()}/></div>}
        {recs.isLoading?<div className="mt-4 grid gap-3 sm:grid-cols-2"><LoadingBlock/><LoadingBlock/></div>:options.length===0&&!recs.error?<div className="mt-4 rounded-xl bg-slate-50 p-4 text-sm text-slate-600" role="status">No eligible appointments matched your calendar. Try another date or contact the clinic.</div>:
        <div className="mt-4 grid gap-3 sm:grid-cols-2" role="radiogroup" aria-label="Ranked appointment options">{options.slice(0,6).map(o=><button key={o.slot.id} role="radio" aria-checked={choice?.slot.id===o.slot.id} onClick={()=>setChoice(o)} className={`rounded-xl border p-4 text-left transition focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-teal-200 ${choice?.slot.id===o.slot.id?'border-teal-500 bg-teal-50 ring-2 ring-teal-100':'border-slate-200 hover:border-teal-300'}`}><div className="flex items-center justify-between gap-2"><b>{fmtDay(o.slot.starts_at,undefined,{weekday:'short',month:'short',day:'numeric'})} · {fmtRange(o.slot.starts_at,o.slot.ends_at)}</b>{o.rank<=3&&<Badge tone="teal">#{o.rank}</Badge>}</div><p className="mt-1 text-xs text-slate-500">{o.slot.clinic_name} · {o.slot.travel_minutes===0?'Video visit':`${o.slot.travel_minutes} min travel`}</p><ul className="mt-2 flex flex-wrap gap-1.5" aria-label="Why this time">{o.reason_codes.map(r=><li key={r} className={`rounded-full px-2 py-0.5 text-[11px] font-semibold ${r==='TIGHT_BETWEEN_CLASSES'||r==='OUTSIDE_PREFERRED_HOURS'||r==='LONGER_TRAVEL'||r.startsWith('HAS_')?'bg-amber-50 text-amber-700':'bg-teal-50 text-teal-700'}`}>{REASONS[r] ?? r}</li>)}</ul>{o.conflicts.map(c=><p key={c.label} className="mt-2 text-xs text-amber-700">Overlaps {c.label} by {c.overlap_minutes} min</p>)}</button>)}</div>}
        {options.length>6&&<p className="mt-3 text-xs text-slate-500">{options.length-6} more option{options.length-6>1?'s':''} later in the week.</p>}
        <Button disabled={!choice} className="mt-5 w-full" onClick={()=>{setUnderstood(false);setDialog(true)}}>Confirm demo appointment</Button>
        {recs.data&&recs.data.rejected.length>0&&<details className="mt-5 rounded-xl border border-slate-200 p-4 text-sm"><summary className="cursor-pointer font-semibold">Why some times aren’t shown ({recs.data.rejected.length})</summary><ul className="mt-3 space-y-2">{recs.data.rejected.map(r=><li key={r.slot.id} className="flex flex-wrap justify-between gap-2"><span>{fmtDay(r.slot.starts_at,undefined,{weekday:'short'})} {fmtRange(r.slot.starts_at,r.slot.ends_at)} · {r.slot.clinic_name}</span><span className="text-slate-500">{REJECTED[r.reason_code] ?? r.reason_code}{r.conflicts[0]?` (${r.conflicts[0].label})`:''}</span></li>)}</ul></details>}
      </Card></div>
    <details className="mt-6 text-sm text-slate-500"><summary className="cursor-pointer">Demo controls</summary><p className="mt-2">Simulate another student taking the selected time to show stale-slot recovery.</p><Button variant="secondary" className="mt-2" disabled={!choice||invalidate.isPending} onClick={()=>choice&&invalidate.mutate(choice.slot.id)}>Mark selected slot as taken</Button></details>
    {dialog&&choice&&<div role="dialog" aria-modal="true" aria-labelledby="confirm-title" className="fixed inset-0 z-50 grid place-items-center bg-slate-950/40 p-5"><Card className="max-w-md p-6"><Badge tone="amber">DEMO BOOKING</Badge><h2 id="confirm-title" className="mt-4 text-xl font-semibold">Reserve this demo time?</h2><p className="mt-3 text-sm leading-6 text-slate-600"><b>{typeLabel[choice.slot.appointment_type]}</b><br/>{fmtDay(choice.slot.starts_at)} · {fmtRange(choice.slot.starts_at,choice.slot.ends_at)}<br/>{choice.slot.clinic_name}, {choice.slot.location}</p><p className="mt-3 rounded-xl bg-sky-50 p-3 text-sm text-sky-800">Demo appointment — not booked with a real clinic. Nothing is sent to the university health center.</p><label className="mt-4 flex items-start gap-3 text-sm"><input type="checkbox" checked={understood} onChange={e=>setUnderstood(e.target.checked)} className="mt-0.5 size-5 accent-teal-700"/><span>I understand this is a simulated reservation.</span></label>{confirm.error&&!(confirm.error instanceof ApiError&&['SLOT_UNAVAILABLE','CLASS_CONFLICT'].includes(confirm.error.code))&&<p role="alert" className="mt-3 text-sm text-rose-600">{(confirm.error as Error).message}</p>}<div className="mt-6 flex justify-end gap-2"><Button variant="ghost" onClick={()=>setDialog(false)}>Cancel</Button><Button disabled={!understood||confirm.isPending} onClick={()=>confirm.mutate(choice.slot.id)}>{confirm.isPending?'Confirming…':'Confirm demo appointment'}</Button></div></Card></div>}
  </>
}
