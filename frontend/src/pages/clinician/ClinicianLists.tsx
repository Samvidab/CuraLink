import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Badge, Button, Card, ErrorBanner, LoadingBlock } from '../../components/ui'
import { api, ApiError } from '../../lib/api'
import { fmtDay, fmtRelative, fmtTime, fmtYmd } from '../../lib/format'
import type { ClinicianCaseRow, EncounterRow } from '../../lib/types'

const shortDate = (ymd: string) => fmtYmd(ymd, { month: 'short', day: 'numeric' })
const tone = (s: string) => (s === 'SENT' || s === 'SIGNED' ? 'teal' : s === 'FAILED' || s === 'REJECTED' ? 'rose' : s === 'REVOKED' ? 'slate' : 'amber')

function CaseList({ title, intro, filter, empty }: { title: string; intro: string; filter?: (c: ClinicianCaseRow) => boolean; empty: string }) {
  const go = useNavigate()
  const { data, error, isLoading, refetch } = useQuery({ queryKey: ['clinician-cases'], queryFn: () => api.get<ClinicianCaseRow[]>('/clinician/absence-cases') })
  const rows = (data ?? []).filter(filter ?? (() => true))
  return <><h1 className="text-3xl font-semibold">{title}</h1><p className="mt-2 text-slate-500">{intro}</p>{error&&<div className="mt-5"><ErrorBanner error={error} onRetry={()=>refetch()}/></div>}<Card className="mt-7 divide-y divide-slate-100 overflow-hidden">{isLoading&&<LoadingBlock/>}{!isLoading&&rows.length===0&&<p className="p-5 text-sm text-slate-500">{empty}</p>}{rows.map(c=><button key={c.id} onClick={()=>go(`/clinician/encounters/${c.encounter_id}`)} className="flex w-full flex-wrap items-center justify-between gap-3 p-4 text-left text-sm hover:bg-teal-50 focus-visible:bg-teal-50 focus-visible:outline-none"><span><b>{c.student_name}</b><span className="block text-xs text-slate-500">{c.visit_type} · {c.reported_missed_dates.length?`student-reported class absences: ${c.reported_missed_dates.map(shortDate).join(', ')}`:'documentation review requested'} · {fmtRelative(c.created_at)}</span></span><Badge tone={tone(c.status)}>{c.status_label}</Badge></button>)}</Card></>
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

/** Draw with mouse, trackpad, touch or pen. Saving stores it encrypted; it never signs anything by itself. */
function SignaturePad({ onSaved }: { onSaved: () => void }) {
  const canvas = useRef<HTMLCanvasElement>(null)
  const drawing = useRef(false)
  const [empty, setEmpty] = useState(true)
  const [preview, setPreview] = useState<string | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  useEffect(() => {
    const ctx = canvas.current!.getContext('2d')!
    ctx.lineWidth = 3; ctx.lineCap = 'round'; ctx.lineJoin = 'round'; ctx.strokeStyle = '#1E3A8A'
  }, [])
  const pos = (e: React.PointerEvent) => { const r = canvas.current!.getBoundingClientRect(); return [(e.clientX - r.left) * (canvas.current!.width / r.width), (e.clientY - r.top) * (canvas.current!.height / r.height)] }
  const down = (e: React.PointerEvent) => { e.preventDefault(); canvas.current!.setPointerCapture(e.pointerId); drawing.current = true; const [x, y] = pos(e); const ctx = canvas.current!.getContext('2d')!; ctx.beginPath(); ctx.moveTo(x, y) }
  const move = (e: React.PointerEvent) => { if (!drawing.current) return; const [x, y] = pos(e); const ctx = canvas.current!.getContext('2d')!; ctx.lineTo(x, y); ctx.stroke(); setEmpty(false); setPreview(null) }
  const up = () => { drawing.current = false }
  const clear = () => { canvas.current!.getContext('2d')!.clearRect(0, 0, canvas.current!.width, canvas.current!.height); setEmpty(true); setPreview(null); setError('') }
  const save = async () => {
    setBusy(true); setError('')
    try { await api.post('/clinician/signature-assets/drawn', { png_base64: canvas.current!.toDataURL('image/png') }); clear(); onSaved() }
    catch (e) { setError(e instanceof ApiError ? e.message : 'Could not save.') } finally { setBusy(false) }
  }
  return <div className="mt-5"><p className="text-sm font-semibold">Draw your signature</p><canvas ref={canvas} width={600} height={180} onPointerDown={down} onPointerMove={move} onPointerUp={up} onPointerLeave={up} aria-label="Signature drawing area: draw with mouse, trackpad, touch or pen" role="img" className="mt-2 h-36 w-full touch-none rounded-xl border-2 border-dashed border-slate-300 bg-white"/>
    <div className="mt-3 flex flex-wrap gap-2"><Button variant="ghost" onClick={clear}>Clear / redraw</Button><Button variant="secondary" disabled={empty} onClick={()=>setPreview(canvas.current!.toDataURL('image/png'))}>Preview</Button><Button disabled={empty||busy} onClick={save}>Save signature securely</Button></div>
    {preview&&<div className="mt-3 rounded-xl bg-slate-50 p-3"><p className="text-xs text-slate-500">Preview (as it will appear, with a SIMULATED label on demo certificates)</p><img src={preview} alt="Preview of your drawn signature" className="mt-1 h-16"/></div>}
    {error&&<p role="alert" className="mt-2 text-sm text-rose-600">{error}</p>}</div>
}

export function SignatureSettings() {
  const qc = useQueryClient()
  const { data, isLoading } = useQuery({ queryKey: ['signature-assets'], queryFn: () => api.get<Asset[]>('/clinician/signature-assets') })
  const refresh = () => qc.invalidateQueries({ queryKey: ['signature-assets'] })
  const enroll = useMutation({ mutationFn: () => api.post('/clinician/signature-assets'), onSuccess: refresh })
  const revoke = useMutation({ mutationFn: (id: string) => api.del(`/clinician/signature-assets/${id}`), onSuccess: refresh })
  const active = data?.find(a => !a.revoked_at)
  return <><h1 className="text-3xl font-semibold">Signature Settings</h1><p className="mt-2 text-slate-500">A stored signature NEVER authorizes use on its own. Every document version needs your fresh review, re-entered password and explicit approval.</p>
    <Card className="mt-7 p-6"><div className="flex flex-wrap items-center justify-between gap-3"><div><h2 className="text-lg font-semibold">Your signature</h2><p className="mt-1 text-sm text-slate-500">Hackathon build: signatures appear on certificates labelled “SIMULATED SIGNATURE — DEMO, NOT VALID”. Stored encrypted and tied to your account.</p></div><Badge tone={active?'teal':'slate'}>{active?(active.kind==='drawn'?'Drawn signature active':'Demo sample active'):'Not enrolled'}</Badge></div>
      <div className="mt-5 grid place-items-center rounded-xl border border-dashed border-slate-300 bg-slate-50 p-6">{!active?<p className="text-sm text-slate-500">No signature saved yet.</p>:active.kind==='drawn'?<img src={`/api/v1/clinician/signature-assets/${active.id}/preview`} alt="Your saved signature" className="h-16"/>:<svg viewBox="0 0 220 60" className="h-16 w-56" aria-label="Fictional sample signature, watermarked DEMO"><path d="M10 40 C 30 5, 40 55, 60 30 S 90 10, 100 35 S 130 50, 150 25 S 190 20, 210 32" fill="none" stroke="#1E3A8A" strokeWidth="2.5"/><text x="110" y="56" textAnchor="middle" fontSize="10" fill="#B91C1C" fontWeight="700">DEMO SAMPLE — NOT VALID</text></svg>}</div>
      <SignaturePad onSaved={refresh}/>
      {isLoading?<LoadingBlock className="mt-5 h-10"/>:<div className="mt-5 flex flex-wrap gap-3 border-t border-slate-100 pt-4">{active?<Button variant="danger" disabled={revoke.isPending} onClick={()=>revoke.mutate(active.id)}>Revoke signature</Button>:<Button variant="secondary" disabled={enroll.isPending} onClick={()=>enroll.mutate()}>Use generated demo sample instead</Button>}</div>}
      {data&&data.length>0&&<ul className="mt-5 space-y-1 text-xs text-slate-500">{data.map(a=><li key={a.id}>{a.kind==='drawn'?'Drawn':'Demo sample'} {a.id} · enrolled {fmtRelative(a.created_at)}{a.revoked_at?` · revoked ${fmtRelative(a.revoked_at)}`:''}</li>)}</ul>}
    </Card><p className="mt-5 text-xs text-slate-500">Revoking prevents any future signing until you enroll again. Documents already signed keep their audit reference. <Link to="/clinician/documents" className="font-semibold text-teal-700 underline">Go to Document Review</Link></p></>
}
