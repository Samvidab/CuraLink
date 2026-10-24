import { useState } from 'react'
import { Badge } from './ui'
import { fmtDay, fmtTime } from '../lib/format'
import type { HistorySession, PreVisitHistory, PreVisitSummary } from '../lib/types'

const ABSENCE = { REQUESTED: 'Requested — not medically approved', NOT_REQUESTED: 'Not requested', NOT_SHARED: 'Not shared by student' } as const
const CATEGORY: Record<string, string> = { apparent_swelling: 'Apparent puffiness or asymmetry', red_area_possible_blood: 'Red-appearing area (not verified as blood)', dry_or_flaky_skin: 'Dry or flaky-looking texture', discoloration_possible_bruise: 'Discoloration (cannot confirm bruising)', other: 'Other visible feature' }

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return <div className="grid gap-1 sm:grid-cols-[150px_1fr]"><dt className="text-xs font-semibold text-slate-500">{label}</dt><dd className="text-sm text-slate-800">{children}</dd></div>
}

/** Student-reported content of one approved summary. Every line is attributed; nothing here is a finding. */
export function SummaryBody({ s, photoUrl }: { s: PreVisitSummary; photoUrl: (attachmentId: string) => string }) {
  return <dl className="space-y-2.5">
    <Row label="Chief concern">{s.chief_concern ?? <span className="text-slate-500">Not provided</span>}</Row>
    {s.symptoms.length>1&&<Row label="Reported symptoms"><ul className="list-disc pl-4">{s.symptoms.map(x=><li key={x}>{x}</li>)}</ul></Row>}
    <Row label="Onset / duration">{s.onset ?? <span className="text-slate-500">Not provided</span>}</Row>
    <Row label="Measurements">{s.measurements.length?s.measurements.map(m=><span key={m.key} className="block">{m.label}: <b>{m.display}</b> <span className="text-xs text-slate-500">· {m.source}</span></span>):<span className="text-slate-500">{s.not_known.includes('Temperature')?'Temperature: not measured / not known':s.declined.includes('Temperature')?'Temperature: declined':'Not provided'}</span>}</Row>
    {s.other.map(o=><Row key={o.key} label={o.label}>{o.display}</Row>)}
    <Row label="Photos">{s.photos.length?<div className="space-y-2">{s.photos.map(p=><figure key={p.attachment_id} className="rounded-lg border border-slate-200 bg-white p-2"><img src={photoUrl(p.attachment_id)} alt={`Student-approved photo${p.synthetic_demo?' (synthetic demo image)':''}`} className="max-h-48 w-full rounded object-contain"/><figcaption className="mt-1 text-xs text-slate-600"><Badge tone="amber">AI-generated observation</Badge> {p.observer==='claude'?'Claude vision':'Basic colour analysis'} — non-diagnostic: {p.observations.map(o=>`${CATEGORY[o.category] ?? o.category}: ${o.description}`).join(' ')||'nothing clear enough to describe'}</figcaption></figure>)}</div>:<span className="text-slate-500">None shared</span>}</Row>
    <Row label="Reason for visit">{s.reason_for_visit ?? <span className="text-slate-500">Not shared</span>}</Row>
    <Row label="Absence documentation"><Badge tone={s.absence_documentation==='REQUESTED'?'amber':'slate'}>{ABSENCE[s.absence_documentation]}</Badge></Row>
    {(s.not_known.length>0||s.declined.length>0)&&<Row label="Not provided">{[...s.not_known.map(x=>`${x} (student didn’t know)`),...s.declined.map(x=>`${x} (declined)`)].join(' · ')}</Row>}
  </dl>
}

function SessionCard({ s, latest, photoUrl }: { s: HistorySession; latest: boolean; photoUrl: (id: string) => string }) {
  const [open, setOpen] = useState(latest)
  const id = `sess-${s.session_id}`
  return <li className={`rounded-xl border ${latest?'border-teal-300 bg-teal-50/40':'border-slate-200 bg-white'}`}>
    <button className="flex w-full flex-wrap items-center justify-between gap-2 p-3 text-left" aria-expanded={open} aria-controls={id} onClick={()=>setOpen(!open)}>
      <span><b className="text-sm">{s.label} — {fmtTime(s.started_at)}</b>{latest&&<Badge tone="teal">Latest approved</Badge>}<span className="block text-xs text-slate-600">{s.summary?.chief_concern ?? (s.status==='WITHDRAWN'?'Withdrawn by student':'—')}{s.appointment?` · linked to ${s.appointment.visit_type} ${fmtDay(s.appointment.starts_at,undefined,{month:'short',day:'numeric'})}`:''}</span></span>
      <span className="flex items-center gap-2"><Badge tone={s.status==='SHARED'?'blue':'slate'}>{s.status_label}</Badge><span className="text-xs text-slate-500">v{s.version}</span><span aria-hidden="true">{open?'▾':'▸'}</span></span>
    </button>
    {open&&<div id={id} className="border-t border-slate-200 p-3">{s.summary?<SummaryBody s={s.summary} photoUrl={photoUrl}/>:<p className="text-sm text-slate-600">The student withdrew sharing for this conversation. Its content is no longer available to you.</p>}
      <p className="mt-3 text-[11px] text-slate-500">Session {s.session_id} · started {fmtDay(s.started_at)} {fmtTime(s.started_at)}{s.ended_at?` · ended ${fmtTime(s.ended_at)}`:' · conversation still open'} · submitted {fmtDay(s.submitted_at,undefined,{month:'short',day:'numeric'})} {fmtTime(s.submitted_at)} · versions: {s.versions.map(v=>`v${v.version} ${v.status.toLowerCase()}`).join(', ')}</p>
      {s.consent_text&&<p className="mt-1 text-[11px] text-slate-500">Consent: “{s.consent_text}”</p>}</div>}
  </li>
}

/** Chronological, per-session history: grouped by the local date each conversation started, newest first. */
export function PreVisitHistoryView({ data, studentName, photoUrl }: { data: PreVisitHistory; studentName: string; photoUrl: (id: string) => string }) {
  return <section aria-labelledby="history-title"><h2 id="history-title" className="text-lg font-semibold">AI-Assisted Pre-Visit History — {studentName}</h2>
    <p className="mt-1 text-xs text-slate-500">Separate conversations are never merged. Older entries are historical and may not describe current symptoms.</p>
    {data.groups.length===0?<p className="mt-3 text-sm text-slate-500">No approved pre-visit summaries for your appointments with this student.</p>:
    <div className="mt-3 space-y-4">{data.groups.map(g=><div key={g.date}><h3 className="text-sm font-semibold text-slate-700">{fmtDay(`${g.date}T12:00:00Z`,undefined,{month:'long',day:'numeric',year:'numeric'})}</h3><ul className="mt-2 space-y-2">{g.sessions.map(s=><SessionCard key={s.session_id} s={s} latest={s.session_id===data.latest_session_id} photoUrl={photoUrl}/>)}</ul></div>)}</div>}
  </section>
}
