import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Badge, Button, Card } from './ui'
import { useAuth } from '../lib/auth'
import { api, ApiError } from '../lib/api'
import { fmtDay, fmtRange, initials, ymdIn } from '../lib/format'
import type { ClinicianCardData, ConfirmResult, ScheduleSlot } from '../lib/types'

const TYPE: Record<string, string> = { routine_checkup: 'Routine checkup', vaccination: 'Vaccinations', mental_health: 'Mental health', general_consultation: 'General consultation' }
const newKey = () => (crypto.randomUUID ? crypto.randomUUID() : `k-${Date.now()}-${Math.random().toString(36).slice(2)}`)
const dayKey = (iso: string) => ymdIn(iso)

/** One clinician with selectable times (all from the scheduling backend; demo data). */
export function ClinicianCard({ c, onPick, selectedId, compact = false, maxSlots }: { c: ClinicianCardData; onPick: (s: ScheduleSlot) => void; selectedId?: string; compact?: boolean; maxSlots?: number }) {
  const slots = maxSlots ? c.slots.slice(0, maxSlots) : c.slots
  const byDay: Record<string, ScheduleSlot[]> = {}
  for (const s of slots) (byDay[dayKey(s.starts_at)] ??= []).push(s)
  return <Card className={compact ? 'p-4' : 'p-5'}><div className="flex items-start gap-3">
    {c.photo_url?<img src={c.photo_url} alt={`Photo of ${c.name}`} className="size-11 rounded-full object-cover"/>:<div className="grid size-11 shrink-0 place-items-center rounded-full bg-sky-100 text-sm font-bold text-sky-800" aria-hidden="true">{initials(c.name)}</div>}
    <div className="min-w-0 flex-1"><h3 className="font-semibold">{c.name}{c.credentials?<span className="font-normal text-slate-500"> · {c.credentials}</span>:null}</h3><p className="text-sm text-slate-600">{c.specialty}</p><p className="text-xs text-slate-500">{c.clinic_name}{c.location?` · ${c.location}`:''}</p>{!compact&&<p className="mt-1 text-xs text-slate-500">Offers: {c.appointment_types.map(t=>TYPE[t] ?? t).join(', ')}</p>}</div>
    <Badge tone="amber">DEMO</Badge></div>
    {c.offers_type===false?<p className="mt-3 text-sm text-slate-500">Doesn’t offer this appointment type.</p>:slots.length===0?<p className="mt-3 text-sm text-slate-500">No openings that fit your classes in this window.</p>:
    <div className="mt-3 space-y-2">{Object.entries(byDay).map(([d,list])=><div key={d}><p className="text-xs font-semibold text-slate-500">{fmtDay(list[0].starts_at,undefined,{weekday:'long',month:'short',day:'numeric'})}</p><div className="mt-1 flex flex-wrap gap-2" role="group" aria-label={`${c.name} on ${fmtDay(list[0].starts_at)}`}>{list.map(s=><button key={s.id} onClick={()=>onPick(s)} aria-pressed={selectedId===s.id} aria-label={`${c.name}, ${fmtDay(s.starts_at)} ${fmtRange(s.starts_at,s.ends_at)}`} className={`min-h-9 rounded-lg border px-3 text-sm font-semibold transition focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-teal-200 ${selectedId===s.id?'border-teal-500 bg-teal-50 text-teal-800':'border-slate-200 bg-white hover:border-teal-300'}`}>{fmtRange(s.starts_at,s.ends_at).split('–')[0]}</button>)}</div></div>)}
      {(c.total_available ?? 0)>slots.length&&<p className="text-xs text-slate-500">{(c.total_available ?? 0)-slots.length} more opening{(c.total_available ?? 0)-slots.length>1?'s':''} — narrow by date to see them.</p>}</div>}
  </Card>
}

/** Explicit booking confirmation; the backend re-checks availability at this moment. */
export function SlotConfirmDialog({ slot, onClose, onBooked, onStale }: { slot: ScheduleSlot; onClose: () => void; onBooked: (r: ConfirmResult) => void; onStale: (message: string) => void }) {
  const { me } = useAuth()
  const qc = useQueryClient()
  const [ok, setOk] = useState(false)
  const [key] = useState(newKey)
  const book = useMutation({
    mutationFn: () => api.post<ConfirmResult>('/appointments/confirm', { slot_id: slot.id, student_approved: true, idempotency_key: key }),
    onSuccess: r => { for (const k of ['student-dashboard', 'my-appointments', 'my-encounters', 'schedule-search']) qc.invalidateQueries({ queryKey: [k] }); onBooked(r) },
    onError: e => { if (e instanceof ApiError && ['SLOT_UNAVAILABLE', 'CLASS_CONFLICT'].includes(e.code)) { qc.invalidateQueries({ queryKey: ['schedule-search'] }); onStale(e.message) } },
  })
  const rows: [string, string][] = [['Student', me?.display_name ?? ''], ['Clinician', slot.clinician_name], ['Appointment type', slot.appointment_label], ['Date', fmtDay(slot.starts_at, undefined, { weekday: 'long', month: 'long', day: 'numeric' })], ['Time', `${fmtRange(slot.starts_at, slot.ends_at)} (${slot.minutes} min)`], ['Location', `${slot.clinic_name}${slot.location ? `, ${slot.location}` : ''}`]]
  return <div role="dialog" aria-modal="true" aria-labelledby="confirm-title" className="fixed inset-0 z-50 grid place-items-center bg-slate-950/40 p-5"><Card className="w-full max-w-md p-6"><Badge tone="amber">DEMO BOOKING</Badge><h2 id="confirm-title" className="mt-4 text-xl font-semibold">Confirm this appointment?</h2>
    <dl className="mt-4 space-y-2 text-sm">{rows.map(([k,v])=><div key={k} className="flex justify-between gap-4"><dt className="text-slate-500">{k}</dt><dd className="text-right font-semibold">{v}</dd></div>)}</dl>
    <p className="mt-4 rounded-xl bg-sky-50 p-3 text-sm text-sky-800">Demo appointment — not booked with a real clinic. Availability is re-checked when you confirm.</p>
    <label className="mt-4 flex items-start gap-3 text-sm"><input type="checkbox" checked={ok} onChange={e=>setOk(e.target.checked)} className="mt-0.5 size-5 accent-teal-700"/><span>I want to book this simulated appointment with {slot.clinician_name}.</span></label>
    {book.error&&!(book.error instanceof ApiError&&['SLOT_UNAVAILABLE','CLASS_CONFLICT'].includes(book.error.code))&&<p role="alert" className="mt-3 text-sm text-rose-600">{(book.error as Error).message}</p>}
    <div className="mt-6 flex justify-end gap-2"><Button variant="ghost" onClick={onClose}>Cancel</Button><Button disabled={!ok||book.isPending} onClick={()=>book.mutate()}>{book.isPending?'Confirming…':'Confirm appointment'}</Button></div></Card></div>
}
