import { Link, useNavigate } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Badge, Button, Card, ErrorBanner, LoadingBlock } from '../../components/ui'
import { api } from '../../lib/api'
import { fmtDay, fmtRelative, fmtTime, fmtYmd } from '../../lib/format'
import type { ClinicianCaseRow, EncounterRow } from '../../lib/types'

const shortDate = (ymd: string) => fmtYmd(ymd, { month: 'short', day: 'numeric' })
const tone = (s: string) => (s === 'SENT' || s === 'SIGNED' ? 'teal' : s === 'FAILED' || s === 'REJECTED' ? 'rose' : s === 'REVOKED' ? 'slate' : 'amber')

function CaseList({ title, intro, filter, empty }: { title: string; intro: string; filter?: (c: ClinicianCaseRow) => boolean; empty: string }) {
  const go = useNavigate()
  const { data, error, isLoading, refetch } = useQuery({ queryKey: ['clinician-cases'], queryFn: () => api.get<ClinicianCaseRow[]>('/clinician/absence-cases') })
  const rows = (data ?? []).filter(filter ?? (() => true))
  return <><h1 className="text-3xl font-semibold">{title}</h1><p className="mt-2 text-slate-500">{intro}</p>{error&&<div className="mt-5"><ErrorBanner error={error} onRetry={()=>refetch()}/></div>}<Card className="mt-7 divide-y divide-slate-100 overflow-hidden">{isLoading&&<LoadingBlock/>}{!isLoading&&rows.length===0&&<p className="p-5 text-sm text-slate-500">{empty}</p>}{rows.map(c=><button key={c.id} onClick={()=>go(`/clinician/encounters/${c.encounter_id}`)} className="flex w-full flex-wrap items-center justify-between gap-3 p-4 text-left text-sm hover:bg-teal-50 focus-visible:bg-teal-50 focus-visible:outline-none"><span><b>{c.student_name}</b><span className="block text-xs text-slate-500">{c.visit_type} · requested {shortDate(c.requested_start)}–{shortDate(c.requested_end)} · {fmtRelative(c.created_at)}</span></span><Badge tone={tone(c.status)}>{c.status_label}</Badge></button>)}</Card></>
}

export const AbsenceCases = () => <CaseList title="Absence Cases" intro="Student requests for assigned appointments. Only you set certified dates — or decline." empty="No absence requests yet."/>
export const DocumentReview = () => <CaseList title="Document Review" intro="Unsigned or signed-but-unsent document versions." filter={c=>['PENDING_CLINICIAN_SIGNATURE','SIGNED','FAILED'].includes(c.status)} empty="Nothing waiting for review or signature."/>

export function IntakeQueue() {
  const go = useNavigate()
  const { data, isLoading } = useQuery({ queryKey: ['clinician-encounters'], queryFn: () => api.get<EncounterRow[]>('/clinician/encounters') })
  const rows = (data ?? []).filter(e => e.status === 'INTAKE_SHARED' || e.status === 'CLINICIAN_REVIEW')
  return <><h1 className="text-3xl font-semibold">Intake Queue</h1><p className="mt-2 text-slate-500">Encounters where the student explicitly shared intake details with you. List rows never preview symptoms.</p><Card className="mt-7 divide-y divide-slate-100 overflow-hidden">{isLoading&&<LoadingBlock/>}{!isLoading&&rows.length===0&&<p className="p-5 text-sm text-slate-500">No shared intakes right now.</p>}{rows.map(e=><button key={e.id} onClick={()=>go(`/clinician/encounters/${e.id}`)} className="flex w-full flex-wrap items-center justify-between gap-3 p-4 text-left text-sm hover:bg-teal-50"><span><b>{e.student_name}</b><span className="block text-xs text-slate-500">{e.visit_type} · {fmtDay(e.starts_at)} {fmtTime(e.starts_at)}</span></span><Badge tone={e.status==='INTAKE_SHARED'?'blue':'amber'}>{e.status_label}</Badge></button>)}</Card></>
}

type Asset = { id: string; kind: string; created_at: string; revoked_at: string | null }

export function SignatureSettings() {
  const qc = useQueryClient()
  const { data, isLoading } = useQuery({ queryKey: ['signature-assets'], queryFn: () => api.get<Asset[]>('/clinician/signature-assets') })
  const refresh = () => qc.invalidateQueries({ queryKey: ['signature-assets'] })
  const enroll = useMutation({ mutationFn: () => api.post('/clinician/signature-assets'), onSuccess: refresh })
  const revoke = useMutation({ mutationFn: (id: string) => api.del(`/clinician/signature-assets/${id}`), onSuccess: refresh })
  const active = data?.find(a => !a.revoked_at)
  return <><h1 className="text-3xl font-semibold">Signature Settings</h1><p className="mt-2 text-slate-500">A stored signature NEVER authorizes use on its own. Every document version needs your fresh review, re-entered password and explicit approval.</p>
    <Card className="mt-7 p-6"><div className="flex flex-wrap items-center justify-between gap-3"><div><h2 className="text-lg font-semibold">Demo sample signature</h2><p className="mt-1 text-sm text-slate-500">Hackathon build: only a generated, watermarked fictional sample is supported. Real signature uploads are disabled.</p></div><Badge tone={active?'teal':'slate'}>{active?'Active':'Not enrolled'}</Badge></div>
      <div className="mt-5 grid place-items-center rounded-xl border border-dashed border-slate-300 bg-slate-50 p-6"><svg viewBox="0 0 220 60" className="h-16 w-56" aria-label="Fictional sample signature, watermarked DEMO"><path d="M10 40 C 30 5, 40 55, 60 30 S 90 10, 100 35 S 130 50, 150 25 S 190 20, 210 32" fill="none" stroke="#1E3A8A" strokeWidth="2.5"/><text x="110" y="56" textAnchor="middle" fontSize="10" fill="#B91C1C" fontWeight="700">DEMO SAMPLE — NOT VALID</text></svg></div>
      {isLoading?<LoadingBlock className="mt-5 h-10"/>:<div className="mt-5 flex flex-wrap gap-3">{active?<Button variant="danger" disabled={revoke.isPending} onClick={()=>revoke.mutate(active.id)}>Revoke signature</Button>:<Button disabled={enroll.isPending} onClick={()=>enroll.mutate()}>Enroll demo sample signature</Button>}</div>}
      {data&&data.length>0&&<ul className="mt-5 space-y-1 text-xs text-slate-500">{data.map(a=><li key={a.id}>{a.id} · enrolled {fmtRelative(a.created_at)}{a.revoked_at?` · revoked ${fmtRelative(a.revoked_at)}`:''}</li>)}</ul>}
    </Card><p className="mt-5 text-xs text-slate-500">Revoking prevents any future signing until you enroll again. Documents already signed keep their audit reference. <Link to="/clinician/documents" className="font-semibold text-teal-700 underline">Go to Document Review</Link></p></>
}
