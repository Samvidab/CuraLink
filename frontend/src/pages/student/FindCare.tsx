import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Badge, Button, Card, ErrorBanner, Icon, LoadingBlock, SourceBadge } from '../../components/ui'
import { ClinicianCard, SlotConfirmDialog } from '../../components/ClinicianSlots'
import { api } from '../../lib/api'
import { fmtDay, fmtRange } from '../../lib/format'
import type { AppointmentSummary, ClinicianListing, ConfirmResult, ScheduleResult, ScheduleSlot } from '../../lib/types'

const REJECTED: Record<string, string> = {
  CLASS_CONFLICT: 'Overlaps a class',
  TRAVEL_BUFFER_CONFLICT: 'Not enough travel time around a class',
  PERSONAL_BLOCK_CONFLICT: 'Overlaps a personal block',
  APPOINTMENT_CONFLICT: 'Overlaps another appointment of yours',
  OUTSIDE_PART_OF_DAY: 'Outside the part of day you chose',
  TRAVEL_TOO_LONG: 'Travel longer than your limit',
}
type View = 'all' | 'clinician' | 'earliest'
const VIEWS: [View, string][] = [['all', 'All clinicians'], ['clinician', 'Specific clinician'], ['earliest', 'Earliest available']]

export default function FindCare() {
  const go = useNavigate()
  const qc = useQueryClient()
  const [service, setService] = useState('routine_checkup')
  const [view, setView] = useState<View>('all')
  const [clinician, setClinician] = useState('')
  const [specialty, setSpecialty] = useState('')
  const [start, setStart] = useState('2026-10-26')
  const [part, setPart] = useState('any')
  const [choice, setChoice] = useState<ScheduleSlot | null>(null)
  const [dialog, setDialog] = useState(false)
  const [notice, setNotice] = useState('')
  const [confirmed, setConfirmed] = useState<ConfirmResult | null>(null)

  const listing = useQuery({ queryKey: ['clinicians'], queryFn: () => api.get<ClinicianListing>('/clinicians') })
  const mine = useQuery({ queryKey: ['my-appointments'], queryFn: () => api.get<AppointmentSummary[]>('/appointments/me') })
  const chosenClinician = view === 'clinician' ? clinician || listing.data?.clinicians[0]?.clinician_id || null : null
  const body = { appointment_type: service, start, days: view === 'earliest' ? 14 : 5, part_of_day: part, sort: view === 'earliest' ? 'earliest' : 'best', clinician_id: chosenClinician, specialty: view === 'all' && specialty ? specialty : null }
  const res = useQuery({ queryKey: ['schedule-search', body], queryFn: () => api.post<ScheduleResult>('/schedule/search', body), enabled: view !== 'clinician' || !!chosenClinician })
  const cancel = useMutation({
    mutationFn: (id: string) => api.post<AppointmentSummary>(`/appointments/${id}/cancel`),
    onSuccess: () => { for (const k of ['my-appointments', 'schedule-search', 'student-dashboard']) qc.invalidateQueries({ queryKey: [k] }) },
  })
  const takeAsOther = useMutation({
    mutationFn: (id: string) => api.post('/demo/book-as-other', { slot_id: id }),
    onSuccess: () => setNotice('Demo: another student just booked that time. If you try to confirm it, CuraLink re-checks availability first.'),
  })
  const pick = (s: ScheduleSlot) => { setChoice(s); setDialog(true) }
  const typeLabel = Object.fromEntries((listing.data?.appointment_types ?? []).map(t => [t.id, t.label]))
  const active = mine.data?.filter(a => a.state === 'DEMO_CONFIRMED') ?? []
  const data = res.data
  const excluded = Object.entries(data?.excluded ?? {}).filter(([, n]) => n > 0)
  const alternatives = [...(data?.alternatives.same_clinician ?? []), ...(data?.alternatives.other_clinicians ?? [])]

  if (confirmed) return <div className="mx-auto max-w-2xl pt-12 text-center"><div className="mx-auto grid size-16 place-items-center rounded-full bg-teal-100 text-teal-700"><Icon name="check" size={30}/></div><div className="mt-5"><SourceBadge mode={confirmed.appointment.source_mode}/></div><h1 className="mt-4 text-3xl font-semibold">Demo appointment booked</h1><p className="mt-3 text-slate-600">{confirmed.appointment.clinician_name} · {typeLabel[confirmed.appointment.appointment_type] ?? confirmed.appointment.appointment_type}<br/>{fmtDay(confirmed.appointment.starts_at)} · {fmtRange(confirmed.appointment.starts_at, confirmed.appointment.ends_at)} · {confirmed.appointment.clinic_name}</p><p className="mt-3 rounded-xl bg-sky-50 p-3 text-sm text-sky-800" role="status">{confirmed.message} No request was sent to a university clinic.</p><div className="mt-7 flex flex-wrap justify-center gap-3"><Button onClick={()=>go('/student/cases')}>Prepare absence support <Icon name="arrow"/></Button><Button variant="secondary" onClick={()=>{setConfirmed(null);setChoice(null)}}>Back to availability</Button></div></div>

  return <><h1 className="text-3xl font-semibold">Find care</h1><p className="mt-2 text-slate-500">Choose a clinician and a time that fits around your classes.</p><div className="mt-5 rounded-xl border border-sky-200 bg-sky-50 p-3 text-sm text-sky-800"><b>Demo availability:</b> Clinicians and their hours are fictional and not connected to a university clinic. CuraLink ranks times only by fit with your schedule — never by medical urgency.</div>
    {notice&&<div role="alert" className="mt-4 flex items-start justify-between gap-3 rounded-xl border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900"><span>{notice}</span><button onClick={()=>setNotice('')} aria-label="Dismiss" className="text-amber-700">×</button></div>}
    {active.length>0&&<Card className="mt-6 p-5"><Badge tone="blue">Your demo appointment{active.length>1?'s':''}</Badge><ul className="mt-2 space-y-2">{active.map(a=><li key={a.id} className="flex flex-wrap items-center justify-between gap-3 text-sm"><span><b>{a.clinician_name ?? a.clinic_name}</b> · {typeLabel[a.appointment_type] ?? a.appointment_type} · {fmtDay(a.starts_at)} · {fmtRange(a.starts_at,a.ends_at)} · {a.clinic_name}</span><Button variant="danger" disabled={cancel.isPending} onClick={()=>cancel.mutate(a.id)}>Cancel demo booking</Button></li>)}</ul></Card>}
    <h2 className="mt-8 text-lg font-semibold">What do you need?</h2><div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">{(listing.data?.appointment_types ?? []).map(s=><button key={s.id} onClick={()=>{setService(s.id);setChoice(null)}} aria-pressed={service===s.id} className={`rounded-2xl border p-4 text-left text-sm font-semibold transition ${service===s.id?'border-teal-500 bg-teal-50 text-teal-800':'border-slate-200 bg-white hover:border-teal-300'}`}>{s.label}</button>)}{listing.isLoading&&<LoadingBlock className="h-14 sm:col-span-2 lg:col-span-4"/>}</div>
    <div className="mt-7 flex flex-wrap gap-2" role="tablist" aria-label="Browse by">{VIEWS.map(([v,label])=><button key={v} role="tab" aria-selected={view===v} onClick={()=>{setView(v);setChoice(null)}} className={`min-h-10 rounded-full border px-4 text-sm font-semibold transition ${view===v?'border-teal-600 bg-teal-700 text-white':'border-slate-200 bg-white text-slate-700 hover:border-teal-300'}`}>{label}</button>)}</div>
    <div className="mt-5 grid gap-5 lg:grid-cols-[.65fr_1.35fr]"><Card className="h-fit p-5">
      {view==='clinician'&&<label className="mb-4 block text-sm font-semibold">Clinician<select className="input mt-2" value={chosenClinician ?? ''} onChange={e=>{setClinician(e.target.value);setChoice(null)}}>{(listing.data?.clinicians ?? []).map(c=><option key={c.clinician_id} value={c.clinician_id}>{c.name} — {c.specialty}</option>)}</select></label>}
      {view==='all'&&<label className="mb-4 block text-sm font-semibold">Specialty<select className="input mt-2" value={specialty} onChange={e=>setSpecialty(e.target.value)}><option value="">Any specialty</option>{(listing.data?.specialties ?? []).map(s=><option key={s}>{s}</option>)}</select></label>}
      <label className="text-sm font-semibold">Search from<input type="date" value={start} min="2026-10-26" onChange={e=>{setStart(e.target.value);setChoice(null)}} className="input mt-2"/></label>
      <label className="mt-4 block text-sm font-semibold">Part of day<select className="input mt-2" value={part} onChange={e=>setPart(e.target.value)}><option value="any">Any time</option><option value="morning">Morning</option><option value="afternoon">Afternoon</option></select></label>
      <p className="mt-5 text-sm leading-6 text-slate-500">{data?.calendar_considered===false?<>No calendar imported, so class conflicts can’t be checked. <button className="font-semibold text-teal-700 underline" onClick={()=>go('/student/import')}>Import calendar</button></>:<>CuraLink checks each time against your {data?.term?<b>{data.term}</b>:null} classes, travel time and the clinician’s working hours.</>}</p>
      <p className="mt-3 text-xs text-slate-400">{view==='earliest'?'Sorted by start time across all clinicians (next 14 days).':'Ranking = wait time + travel + your preferences. Ties break by start time.'}</p></Card>
      <div className="space-y-4"><div className="flex items-center justify-between gap-2"><h2 className="font-semibold">{view==='earliest'?'Earliest openings':'Clinicians and times'}</h2>{data&&<SourceBadge mode={data.source_mode}/>}</div>
        {res.error&&<ErrorBanner error={res.error} onRetry={()=>res.refetch()}/>}
        {data?.notice&&<div role="status" className="rounded-xl border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">{data.notice}</div>}
        {res.isLoading?<div className="grid gap-3"><LoadingBlock/><LoadingBlock/></div>:
          view==='earliest'?<Card className="p-5">{(data?.options ?? []).length===0?<p className="text-sm text-slate-600">No openings fit your calendar in the next two weeks.</p>:<ul className="divide-y divide-slate-100" aria-label="Earliest openings">{data!.options.map(s=><li key={s.id} className="flex flex-wrap items-center justify-between gap-3 py-3"><div><p className="font-semibold">{fmtDay(s.starts_at,undefined,{weekday:'short',month:'short',day:'numeric'})} · {fmtRange(s.starts_at,s.ends_at)}</p><p className="text-sm text-slate-500">{s.clinician_name} · {s.clinic_name}</p></div><Button variant="secondary" onClick={()=>pick(s)} aria-label={`Book ${s.clinician_name}, ${fmtDay(s.starts_at)} ${fmtRange(s.starts_at,s.ends_at)}`}>Select</Button></li>)}</ul>}</Card>:
          (data?.clinicians ?? []).map(c=><ClinicianCard key={c.clinician_id} c={c} onPick={pick} selectedId={choice?.id}/>)}
        {alternatives.length>0&&<Card className="p-5"><h3 className="font-semibold">Other options</h3><ul className="mt-2 divide-y divide-slate-100">{alternatives.map(s=><li key={s.id} className="flex flex-wrap items-center justify-between gap-3 py-2 text-sm"><span><b>{s.clinician_name}</b> · {fmtDay(s.starts_at,undefined,{weekday:'short',month:'short',day:'numeric'})} · {fmtRange(s.starts_at,s.ends_at)}</span><Button variant="secondary" onClick={()=>pick(s)}>Select</Button></li>)}</ul></Card>}
        {excluded.length>0&&<details className="rounded-xl border border-slate-200 bg-white p-4 text-sm"><summary className="cursor-pointer font-semibold">Why some times aren’t shown</summary><ul className="mt-3 space-y-1">{excluded.map(([k,n])=><li key={k} className="flex justify-between gap-2"><span>{REJECTED[k] ?? k}</span><span className="text-slate-500">{n}</span></li>)}</ul></details>}
      </div></div>
    <details className="mt-6 text-sm text-slate-500"><summary className="cursor-pointer">Demo controls</summary><p className="mt-2">Simulate another student booking the selected time to show stale-slot recovery.</p><Button variant="secondary" className="mt-2" disabled={!choice||takeAsOther.isPending} onClick={()=>choice&&takeAsOther.mutate(choice.id)}>Mark selected slot as taken</Button></details>
    {dialog&&choice&&<SlotConfirmDialog slot={choice} onClose={()=>setDialog(false)} onBooked={r=>{setDialog(false);setConfirmed(r)}} onStale={m=>{setDialog(false);setChoice(null);setNotice(m)}}/>}
  </>
}
