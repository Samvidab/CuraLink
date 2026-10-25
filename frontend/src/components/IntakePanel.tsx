import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Badge, Button, Card } from './ui'
import { api, ApiError } from '../lib/api'
import { fmtDay, fmtTime } from '../lib/format'
import type { Handoff, IntakeSnapshot, PhotoAttachment, Provenance, StudentEncounter } from '../lib/types'

type SummaryItem = { key: string; label: string; display: string; source: string; confirmed: boolean }
type IntakeSummary = { student_reported: Record<string, SummaryItem[]>; ai_generated: SummaryItem[]; missing: { key: string; label: string }[]; uncertain: { key: string; label: string }[]; disclaimer: string }

export const PROVENANCE: Record<Provenance, string> = { voice: 'Spoken', text: 'Typed in chat', form: 'Entered', photo_observation: 'AI image observation', clinician: 'Clinician' }
const NEEDS: Record<string, string> = { symptoms_free_text: 'what you’re experiencing', onset_text: 'when it started', temperature: 'temperature' }

const ACCEPT = 'image/jpeg,image/png,image/webp,image/heic,image/heif,.jpg,.jpeg,.png,.webp,.heic,.heif'
const CATEGORY_LABEL: Record<string, string> = { apparent_swelling: 'Apparent puffiness or asymmetry', red_area_possible_blood: 'Red-appearing area (not verified as blood)', dry_or_flaky_skin: 'Dry or flaky-looking texture', discoloration_possible_bruise: 'Discoloration (cannot confirm bruising)', other: 'Other visible feature' }

export function usePhotos() {
  return useQuery({ queryKey: ['photos'], queryFn: () => api.get<PhotoAttachment[]>('/vision/observations') })
}

/** Optional, consent-gated photo observations (PRD §11). Never a diagnosis; never sent to professors. */
export function PhotoSection() {
  const qc = useQueryClient()
  const photos = usePhotos()
  const [consent, setConsent] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const done = () => { qc.invalidateQueries({ queryKey: ['photos'] }); qc.invalidateQueries({ queryKey: ['intake'] }) }
  const [dragging, setDragging] = useState(false)
  const upload = async (file?: File) => {
    if (!file) return
    if (!consent) { setError('Tick the photo consent box first.'); return }
    if (file.size > 12 * 1024 * 1024) { setError(`That file is ${(file.size / 1048576).toFixed(1)} MB; the limit is 12 MB.`); return }
    setBusy(true); setError('')
    const form = new FormData(); form.append('file', file); form.append('consent', String(consent))
    try { await api.post('/vision/observations', form); done() } catch (e) { setError(e instanceof ApiError ? e.message : 'Upload failed.') } finally { setBusy(false) }
  }
  const demo = async (name: string) => {
    setBusy(true); setError('')
    try { await api.post(`/vision/demo-images/${name}?consent=${consent}`); done() } catch (e) { setError(e instanceof ApiError ? e.message : 'Failed.') } finally { setBusy(false) }
  }
  const remove = async (id: string) => { await api.del(`/vision/observations/${id}`); done() }
  return <fieldset className="rounded-xl border border-slate-200 p-4"><legend className="px-1 text-sm font-semibold">Add a photo (optional)</legend>
    <p className="text-xs leading-5 text-slate-600">CuraLink can describe some visible features, but a photo cannot tell us what is causing them. This is not a diagnosis, and photos will not be shared with your professor. Location and camera data are removed; you decide later whether your clinician sees it.</p>
    <label className="mt-3 flex items-start gap-2 text-xs"><input type="checkbox" checked={consent} onChange={e=>setConsent(e.target.checked)} className="mt-0.5 size-4 accent-teal-700"/><span>I agree to have this photo analyzed for possible visual observations.</span></label>
    <p className="mt-2 text-[11px] text-slate-500">Tips: good light, in focus, only the area of concern — avoid your face or anything identifying.</p>
    <div onDragOver={e=>{e.preventDefault();if(consent)setDragging(true)}} onDragLeave={()=>setDragging(false)} onDrop={e=>{e.preventDefault();setDragging(false);upload(e.dataTransfer.files[0])}} className={`mt-3 rounded-xl border-2 border-dashed p-3 transition ${dragging?'border-teal-500 bg-teal-50':'border-slate-200'} ${!consent?'opacity-60':''}`}>
      <div className="flex flex-wrap gap-2">
        <label className={`inline-flex min-h-10 cursor-pointer items-center rounded-xl border border-slate-200 bg-white px-3 text-xs font-semibold focus-within:ring-4 focus-within:ring-teal-200 ${!consent||busy?'pointer-events-none opacity-50':''}`}>Choose photo<input type="file" accept={ACCEPT} className="sr-only" disabled={!consent||busy} onChange={e=>{upload(e.target.files?.[0]);e.target.value=''}} aria-describedby="photo-formats" aria-label="Choose a photo from your files or photo library"/></label>
        <label className={`inline-flex min-h-10 cursor-pointer items-center rounded-xl border border-slate-200 bg-white px-3 text-xs font-semibold focus-within:ring-4 focus-within:ring-teal-200 sm:hidden ${!consent||busy?'pointer-events-none opacity-50':''}`}>Take a photo<input type="file" accept="image/*" capture="environment" className="sr-only" disabled={!consent||busy} onChange={e=>{upload(e.target.files?.[0]);e.target.value=''}} aria-label="Take a photo with your camera"/></label>
        <Button variant="ghost" className="min-h-10 text-xs" disabled={!consent||busy} onClick={()=>demo('red_area')}>Use synthetic demo image</Button>
      </div>
      <p id="photo-formats" className="mt-2 text-xs text-slate-600">Upload a photo (JPG, PNG, WebP, or iPhone HEIC/HEIF) · up to 12 MB{dragging?'':' · or drag it here'}</p>
    </div>
    {busy&&<p className="mt-2 text-xs text-slate-500" role="status">Checking image quality and describing visible features…</p>}
    {error&&<p role="alert" className="mt-2 text-xs text-rose-600">{error} You can continue without a photo.</p>}
    {photos.data?.map(p=><div key={p.id} className="mt-4 rounded-xl bg-slate-50 p-3"><div className="flex gap-3"><img src={p.image_url} alt={`Your uploaded photo${p.synthetic_demo?' (synthetic demo image)':''}`} className="size-20 rounded-lg object-cover"/><div className="min-w-0 flex-1"><p className="text-xs font-semibold">Possible visual observations <Badge tone="amber">AI-generated</Badge></p><p className="text-[11px] text-slate-500">{p.observer==='claude'?'Described by Claude vision — not a diagnosis.':'Visual analysis unavailable — limited demo fallback (basic colour check, not a medical model).'}</p>{p.observations.length===0?<p className="mt-1 text-xs text-slate-600">Nothing clear enough to describe.</p>:<ul className="mt-1 space-y-1 text-xs">{p.observations.map((o,i)=><li key={i}><b>{CATEGORY_LABEL[o.category] ?? o.category}:</b> {o.description} <span className="text-slate-500">{o.uncertainty}</span></li>)}</ul>}</div></div>
      {p.quality.notes.length>0&&<p className="mt-2 text-[11px] text-amber-700">Image quality: {p.quality.notes.join(' ')}</p>}<ul className="mt-2 list-disc pl-4 text-[11px] text-slate-500">{p.limitations.map(l=><li key={l}>{l}</li>)}</ul><p className="mt-2 text-[11px] text-slate-600">This does not establish a diagnosis or severity. If you’re concerned, contact a healthcare professional; for severe symptoms call 911.</p><div className="mt-2 flex flex-wrap gap-2"><Button variant="danger" className="min-h-9 py-1 text-xs" onClick={()=>remove(p.id)}>Remove photo</Button><label className={`inline-flex min-h-9 cursor-pointer items-center rounded-xl border border-slate-200 bg-white px-3 text-xs font-semibold ${!consent||busy?'pointer-events-none opacity-50':''}`}>Replace<input type="file" accept={ACCEPT} className="sr-only" disabled={!consent||busy} onChange={async e=>{const f=e.target.files?.[0];e.target.value='';if(f){await remove(p.id);await upload(f)}}} aria-label="Replace this photo"/></label></div></div>)}
  </fieldset>
}

export function useIntake() {
  return useQuery({ queryKey: ['intake'], queryFn: () => api.get<IntakeSnapshot>('/intake/sessions/current') })
}

/** "What CuraLink knows": structured, provenance-labelled, student-confirmed. */
export function KnowsCard({ snap, onEdit, onShare }: { snap: IntakeSnapshot; onEdit: () => void; onShare: () => void }) {
  const qc = useQueryClient()
  const set = (s: IntakeSnapshot) => qc.setQueryData(['intake'], s)
  const confirm = (key: string, confirmed: boolean) => {
    // Optimistic: reflect the click immediately, then settle on the server's answer.
    set({ ...snap, fields: snap.fields.map(f => (f.key === key ? { ...f, confirmed_by_student: confirmed } : f)) })
    return api.post<IntakeSnapshot>(`/intake/sessions/${snap.session_id}/fields/${key}/confirm`, { confirmed }).then(set, () => qc.invalidateQueries({ queryKey: ['intake'] }))
  }
  const remove = (key: string) => api.del<IntakeSnapshot>(`/intake/sessions/${snap.session_id}/fields/${key}`).then(set)
  return <Card className="p-5"><div className="flex items-center justify-between gap-2"><h2 className="font-semibold">What CuraLink knows</h2><Badge tone="slate">You control this</Badge></div>
    <p className="mt-1 text-xs leading-5 text-slate-500">Only what you said or entered. Nothing here is a diagnosis. Check each item before sharing.</p>
    {snap.fields.length===0?<p className="mt-4 text-sm text-slate-500">Nothing yet. Describe what’s going on in your own words, or add details in the form.</p>:
    <ul className="mt-4 space-y-3" aria-live="polite">{snap.fields.map(f=><li key={f.key} className={`rounded-xl border p-3 text-sm ${f.confirmed_by_student?'border-teal-200 bg-teal-50/40':'border-amber-200 bg-amber-50/40'}`}><div className="flex items-start justify-between gap-2"><span className="text-xs font-semibold text-slate-500">{f.label}</span><Badge tone={f.provenance==='form'?'blue':'slate'}>{PROVENANCE[f.provenance]}</Badge></div><p className="mt-1 break-words text-slate-800">{f.display}</p><div className="mt-2 flex flex-wrap items-center gap-3"><label className="flex items-center gap-2 text-xs font-semibold"><input type="checkbox" className="size-4 accent-teal-700" checked={f.confirmed_by_student} onChange={e=>confirm(f.key,e.target.checked)}/>{f.confirmed_by_student?'Confirmed':'Is this correct?'}</label><button onClick={onEdit} className="text-xs font-semibold text-teal-700 underline">Correct</button><button onClick={()=>remove(f.key)} className="text-xs font-semibold text-slate-500 underline">Remove</button></div></li>)}</ul>}
    {snap.missing_fields.length>0&&<p className="mt-4 text-xs text-slate-500">Helpful for your clinician: {snap.missing_fields.map(k=>NEEDS[k]??k).join(', ')}. Optional.</p>}
    {snap.summary&&<p className="mt-4 rounded-lg bg-slate-50 p-2 text-xs text-slate-600" role="status">Pre-visit summary v{snap.summary.version}: {snap.summary.status==='WITHDRAWN'?'withdrawn':snap.summary.appointment_cancelled?'its appointment was cancelled — you can share it when you book again':snap.summary.clinician_name?`shared with ${snap.summary.clinician_name}`:'saved — will be shared with the clinician you book next'}.</p>}
    <div className="mt-4 grid gap-2"><Button variant="secondary" onClick={onEdit}>Add or correct details</Button><Button disabled={!snap.fields.some(f=>f.confirmed_by_student)&&!snap.purpose&&!snap.absence_requested} onClick={onShare}>Review your pre-visit summary</Button></div>
  </Card>
}

/** Contextual data-collection drawer (US-11): right panel on desktop, bottom sheet on mobile. */
export function IntakeDrawer({ snap, open, onClose, focus }: { snap: IntakeSnapshot; open: boolean; onClose: () => void; focus?: string[] | null }) {
  const [showAll, setShowAll] = useState(false)
  useEffect(() => { if (open) setShowAll(false) }, [open, focus])
  const show = (k: string) => showAll || !focus?.length || focus.includes(k)
  const qc = useQueryClient()
  const val = (k: string, sub = 'text') => String(snap.fields.find(f => f.key === k)?.value?.[sub] ?? '')
  const [temp, setTemp] = useState(''); const [unit, setUnit] = useState('F'); const [measured, setMeasured] = useState('')
  const [onsetDate, setOnsetDate] = useState(''); const [symptoms, setSymptoms] = useState(''); const [pref, setPref] = useState(''); const [access, setAccess] = useState('')
  const [error, setError] = useState('')
  useEffect(() => {
    if (!open) return
    setTemp(val('temperature', 'value')); setUnit(val('temperature', 'unit') || 'F'); setMeasured(val('temperature', 'measured_at'))
    setOnsetDate(val('onset_date', 'date')); setSymptoms(val('symptoms_free_text')); setPref(val('appointment_preference')); setAccess(val('accessibility_needs')); setError('')
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open])
  const save = useMutation({
    mutationFn: () => {
      const fields: { key: string; value: Record<string, unknown> }[] = []
      if (temp.trim()) fields.push({ key: 'temperature', value: { value: Number(temp), unit, measured_at: measured || undefined } })
      if (onsetDate) fields.push({ key: 'onset_date', value: { date: onsetDate } })
      if (symptoms.trim() && symptoms.trim() !== val('symptoms_free_text')) fields.push({ key: 'symptoms_free_text', value: { text: symptoms } })
      if (pref.trim()) fields.push({ key: 'appointment_preference', value: { text: pref } })
      if (access.trim()) fields.push({ key: 'accessibility_needs', value: { text: access } })
      return fields.length ? api.patch<IntakeSnapshot>(`/intake/sessions/${snap.session_id}/fields`, { fields }) : Promise.resolve(snap)
    },
    onSuccess: s => { qc.setQueryData(['intake'], s); onClose() },
    onError: e => setError(e instanceof ApiError ? e.message : 'Could not save.'),
  })
  const skip = (key: string) => api.post<IntakeSnapshot>(`/intake/sessions/${snap.session_id}/skip`, { key }).then(s => qc.setQueryData(['intake'], s))
  if (!open) return null
  return <div className="fixed inset-0 z-50 flex items-end justify-end bg-slate-950/30 md:items-stretch" role="dialog" aria-modal="true" aria-labelledby="drawer-title"><div className="max-h-[90vh] w-full overflow-y-auto rounded-t-3xl bg-white p-6 shadow-2xl md:max-h-none md:w-[420px] md:rounded-none md:rounded-l-3xl"><div className="flex items-start justify-between"><div><h2 id="drawer-title" className="text-xl font-semibold">Add details</h2><p className="mt-1 text-sm text-slate-500">Everything here is optional. Leave out anything you’d rather not share.</p></div><button onClick={onClose} aria-label="Close" className="text-2xl text-slate-400">×</button></div>
    <div className="mt-6 space-y-5">
      {focus?.length&&!showAll?<p className="rounded-lg bg-teal-50 p-2 text-xs text-teal-900">Showing what CuraLink just asked about. <button type="button" className="font-semibold underline" onClick={()=>setShowAll(true)}>Show all fields</button></p>:null}
      {show('temperature')&&<fieldset><legend className="text-sm font-semibold">Temperature you measured</legend><div className="mt-2 grid grid-cols-[1fr_90px] gap-2"><input inputMode="decimal" value={temp} onChange={e=>setTemp(e.target.value)} className="input" placeholder="e.g. 100.4" aria-label="Temperature value"/><select value={unit} onChange={e=>setUnit(e.target.value)} className="input" aria-label="Unit"><option value="F">°F</option><option value="C">°C</option></select></div><input value={measured} onChange={e=>setMeasured(e.target.value)} className="input mt-2" placeholder="When measured (e.g. this morning)" aria-label="When measured"/><p className="mt-1 text-xs text-slate-500">CuraLink records the number you enter; it doesn’t interpret it. <button type="button" onClick={()=>skip('temperature')} className="font-semibold underline">I haven’t measured it</button></p></fieldset>}
      {show('onset')&&<label className="block text-sm font-semibold">When it started<input type="date" value={onsetDate} max="2026-10-26" onChange={e=>setOnsetDate(e.target.value)} className="input mt-2"/><span className="mt-1 block text-xs font-normal text-slate-500">{val('onset_text')?`You said: “${val('onset_text')}”. `:''}<button type="button" onClick={()=>skip('onset_text')} className="font-semibold underline">Skip</button></span></label>}
      {show('other')&&<><label className="block text-sm font-semibold">What you’re experiencing, in your words<textarea value={symptoms} onChange={e=>setSymptoms(e.target.value)} className="input mt-2 min-h-24" placeholder="Describe it however you like"/></label>
      <label className="block text-sm font-semibold">Appointment preference<input value={pref} onChange={e=>setPref(e.target.value)} className="input mt-2" placeholder="e.g. afternoons, telehealth"/></label>
      <label className="block text-sm font-semibold">Accessibility needs<input value={access} onChange={e=>setAccess(e.target.value)} className="input mt-2" placeholder="Optional"/></label></>}
      {show('photo')&&<PhotoSection/>}
      {error&&<p role="alert" className="text-sm text-rose-600">{error}</p>}
      <div className="flex justify-end gap-2"><Button variant="ghost" onClick={onClose}>Cancel</Button><Button disabled={save.isPending} onClick={()=>save.mutate()}>Save details</Button></div>
    </div></div></div>
}

/** Inline temperature entry shown when the assistant asks (structured action OFFER_TEMPERATURE_INPUT).
 *  Only a number the student enters is stored (as confirmed); "feeling feverish" is never a measurement. */
export function TemperatureCard({ snap, onSay, disabled }: { snap: IntakeSnapshot; onSay: (text: string) => void; disabled?: boolean }) {
  const qc = useQueryClient()
  const [value, setValue] = useState('')
  const [unit, setUnit] = useState<'F' | 'C'>('F')
  const [error, setError] = useState('')
  const save = useMutation({
    mutationFn: () => api.patch<IntakeSnapshot>(`/intake/sessions/${snap.session_id}/fields`, { fields: [{ key: 'temperature', value: { value: Number(value), unit } }] }),
    onSuccess: s => { qc.setQueryData(['intake'], s); onSay(`I measured ${value}°${unit}`) },
    onError: e => setError(e instanceof ApiError ? e.message : 'Could not save.'),
  })
  return <div className="mt-2 rounded-2xl border border-teal-200 bg-white p-4" role="group" aria-label="Temperature entry">
    <p className="text-sm font-semibold">Temperature you measured <span className="font-normal text-slate-500">(optional)</span></p>
    <form className="mt-2 flex flex-wrap gap-2" onSubmit={e=>{e.preventDefault();if(!value.trim()||Number.isNaN(Number(value)))return setError('Enter the number you measured.');setError('');save.mutate()}}>
      <input inputMode="decimal" value={value} onChange={e=>setValue(e.target.value)} className="input w-28" placeholder="e.g. 100.4" aria-label="Measured temperature"/>
      <div className="flex overflow-hidden rounded-xl border border-slate-200" role="radiogroup" aria-label="Unit">{(['F','C'] as const).map(u=><button key={u} type="button" role="radio" aria-checked={unit===u} onClick={()=>setUnit(u)} className={`min-h-10 px-3 text-sm font-semibold ${unit===u?'bg-teal-700 text-white':'bg-white text-slate-700'}`}>°{u}</button>)}</div>
      <Button type="submit" className="min-h-10 py-1" disabled={disabled||save.isPending}>Save temperature</Button>
    </form>
    {error&&<p role="alert" className="mt-2 text-xs text-rose-600">{error}</p>}
    <div className="mt-3 flex flex-wrap gap-2">{['I haven’t measured it','I don’t know','Skip'].map(t=><Button key={t} variant="ghost" className="min-h-9 py-1 text-xs" disabled={disabled} onClick={()=>onSay(t.replace('’',"'"))}>{t}</Button>)}</div>
    <p className="mt-2 text-[11px] text-slate-500">CuraLink records only the number you enter and doesn’t interpret it.</p>
  </div>
}

/** Inline optional-photo offer (structured action OFFER_PHOTO_UPLOAD); uploading uses the consent-gated drawer. */
export function PhotoOfferCard({ onAdd, onSay, disabled }: { onAdd: () => void; onSay: (text: string) => void; disabled?: boolean }) {
  return <div className="mt-2 rounded-2xl border border-teal-200 bg-white p-4" role="group" aria-label="Optional photo">
    <p className="text-sm font-semibold">Add a photo <span className="font-normal text-slate-500">(optional)</span></p>
    <p className="mt-1 text-xs leading-5 text-slate-600">JPG, PNG, WebP or iPhone HEIC/HEIF. You’ll be asked for consent before any analysis; any description is not a diagnosis, and you decide whether your clinician sees it.</p>
    <div className="mt-3 flex flex-wrap gap-2"><Button className="min-h-9 py-1 text-xs" disabled={disabled} onClick={onAdd}>Add a photo</Button><Button variant="ghost" className="min-h-9 py-1 text-xs" disabled={disabled} onClick={()=>onSay('No thanks, no photo')}>No thanks</Button></div>
  </div>
}

const ABSENCE_LABEL = { REQUESTED: 'Requested — not medically approved', NOT_REQUESTED: 'Not requested', NOT_SHARED: 'Not shared' } as const

/** Student-reviewed, versioned pre-visit summary of THIS conversation. Nothing unconfirmed can be selected. */
export function HandoffDialog({ snap, onClose }: { snap: IntakeSnapshot; onClose: () => void }) {
  const qc = useQueryClient()
  const encounters = useQuery({ queryKey: ['my-encounters'], queryFn: () => api.get<StudentEncounter[]>('/students/me/encounters') })
  const photos = usePhotos()
  const [keys, setKeys] = useState<string[]>(snap.fields.filter(f => f.confirmed_by_student).map(f => f.key))
  const [photoIds, setPhotoIds] = useState<string[]>([]) // default: photos are NOT shared
  const [purpose, setPurpose] = useState(!!snap.purpose)
  const [absence, setAbsence] = useState(!!snap.absence_requested)
  const prior = snap.summary?.status === 'SHARED' ? snap.summary.encounter_id : null
  const [target, setTarget] = useState<string>(prior ?? snap.linked_encounter_id ?? '')
  const [authorized, setAuthorized] = useState(false)
  const [done, setDone] = useState<Handoff | null>(null)
  const upcoming = (encounters.data ?? []).filter(e => e.status !== 'CANCELLED')
  const chosenEnc = upcoming.find(e => e.id === target)
  const confirm = (key: string) => api.post<IntakeSnapshot>(`/intake/sessions/${snap.session_id}/fields/${key}/confirm`, { confirmed: true }).then(s => { qc.setQueryData(['intake'], s); setKeys(k => [...k, key]) })
  const share = useMutation({
    mutationFn: () => api.post<Handoff>(`/intake/sessions/${snap.session_id}/summary`, { student_authorized: true, field_keys: keys, attachment_ids: photoIds, include_purpose: purpose, include_absence_request: absence, encounter_id: target || null }),
    onSuccess: h => { setDone(h); for (const k of ['intake', 'my-encounters', 'student-dashboard']) qc.invalidateQueries({ queryKey: [k] }) },
  })
  const withdraw = useMutation({ mutationFn: (id: string) => api.post<Handoff>(`/handoffs/${id}/withdraw`), onSuccess: h => { setDone(h); qc.invalidateQueries({ queryKey: ['intake'] }); qc.invalidateQueries({ queryKey: ['my-encounters'] }) } })
  const f = (k: string) => snap.fields.find(x => x.key === k)
  const temp = f('temperature')
  const notProvided = (key: string) => (snap.unknown ?? []).includes(key) ? 'Not measured / not known' : (snap.declined ?? []).includes(key) || snap.skipped_fields.includes(key) ? 'Declined' : 'Not provided'
  const nothing = keys.length === 0 && photoIds.length === 0 && !(purpose && snap.purpose) && !(absence && snap.absence_requested)
  const pick = (key: string, on: boolean) => setKeys(k => on ? [...k, key] : k.filter(x => x !== key))
  const row = (key: string, label: string) => { const x = f(key); if (!x) return null
    return <li key={key}><label className={`flex items-start gap-3 rounded-xl border p-3 text-sm ${x.confirmed_by_student?'border-slate-200':'border-dashed border-amber-300 bg-amber-50/40'}`}><input type="checkbox" disabled={!x.confirmed_by_student} checked={keys.includes(key)} onChange={e=>pick(key,e.target.checked)} className="mt-0.5 size-5 accent-teal-700" aria-label={`Share ${label}`}/><span className="min-w-0 flex-1"><span className="block text-xs font-semibold text-slate-500">{label} · {PROVENANCE[x.provenance]}</span>{x.display}{!x.confirmed_by_student&&<span className="mt-1 flex items-center gap-2 text-xs text-amber-800">Not confirmed yet <button type="button" onClick={()=>confirm(key)} className="font-semibold underline">Confirm this is correct</button></span>}</span></label></li> }
  return <div role="dialog" aria-modal="true" aria-labelledby="handoff-title" className="fixed inset-0 z-50 grid place-items-center overflow-y-auto bg-slate-950/40 p-5"><Card className="my-6 w-full max-w-lg p-6">
    {done?<><Badge tone={done.status==='WITHDRAWN'?'slate':'teal'}>{done.status==='WITHDRAWN'?'WITHDRAWN':'SUBMITTED'}</Badge><h2 id="handoff-title" className="mt-4 text-xl font-semibold">{done.status==='WITHDRAWN'?'Sharing withdrawn':done.clinician_name?`Pre-visit summary submitted to ${done.clinician_name}`:'Pre-visit summary submitted'}</h2><p className="mt-3 text-sm leading-6 text-slate-600" role="status">{done.status==='WITHDRAWN'?'Your clinician can no longer open this summary. Anything they already viewed can’t be un-seen.':`Version ${done.version} of this conversation’s summary is saved${done.clinician_name?` and shared with ${done.clinician_name}`:'. It will be shared with the clinician you book your next appointment with'}. You can withdraw it at any time.`}</p><div className="mt-6 flex justify-end gap-2">{done.status==='SHARED'&&<Button variant="danger" disabled={withdraw.isPending} onClick={()=>withdraw.mutate(done.packet_id)}>Withdraw</Button>}<Button onClick={onClose}>Done</Button></div></>
    :<><Badge tone="blue">PRE-VISIT SUMMARY</Badge><h2 id="handoff-title" className="mt-3 text-xl font-semibold">Review your pre-visit summary</h2><p className="mt-1 text-sm text-slate-500">From this conversation{snap.started_at?` (started ${fmtDay(snap.started_at)} ${fmtTime(snap.started_at)})`:''}. Correct anything that’s wrong, then choose what to share. It is not a diagnosis.</p>
      {snap.summary&&snap.summary.status==='SHARED'&&<p className="mt-3 rounded-lg bg-teal-50 p-2 text-xs text-teal-900">Version {snap.summary.version} already submitted{snap.summary.clinician_name?` to ${snap.summary.clinician_name}`:''}. Submitting again saves version {snap.summary.version+1}; earlier versions are kept.</p>}
      <fieldset className="mt-4"><legend className="text-sm font-semibold">What you reported</legend><ul className="mt-2 space-y-2">
        {row('symptoms_free_text','Symptoms (your words)')}{row('onset_text','When it started')}{row('onset_date','Onset date')}
        {temp?row('temperature','Temperature'):<li className="rounded-xl border border-slate-100 p-3 text-sm text-slate-500"><span className="block text-xs font-semibold">Temperature</span>{notProvided('temperature')}</li>}
        {['appointment_preference','accessibility_needs','requests','photo_observations'].map(k=>row(k, LABEL_FOR[k] ?? k))}
      </ul></fieldset>
      {(photos.data?.length ?? 0)>0?<fieldset className="mt-4"><legend className="text-sm font-semibold">Photos from this conversation (off unless you choose)</legend><ul className="mt-2 space-y-2">{photos.data!.map(p=><li key={p.id}><label className="flex items-center gap-3 rounded-xl border border-slate-200 p-2 text-sm"><input type="checkbox" checked={photoIds.includes(p.id)} onChange={e=>setPhotoIds(x=>e.target.checked?[...x,p.id]:x.filter(y=>y!==p.id))} className="size-5 accent-teal-700"/><img src={p.image_url} alt="Photo you may share" className="size-12 rounded-lg object-cover"/><span>Share this photo and its AI-generated, non-diagnostic description</span></label></li>)}</ul></fieldset>:<p className="mt-4 text-sm text-slate-500"><b className="text-slate-700">Photos:</b> none provided.</p>}
      <fieldset className="mt-4"><legend className="text-sm font-semibold">About the visit</legend><ul className="mt-2 space-y-2">
        {snap.purpose?<li><label className="flex items-start gap-3 rounded-xl border border-slate-200 p-3 text-sm"><input type="checkbox" checked={purpose} onChange={e=>setPurpose(e.target.checked)} className="mt-0.5 size-5 accent-teal-700"/><span><span className="block text-xs font-semibold text-slate-500">Reason for visit (your words)</span>{snap.purpose}</span></label></li>:<li className="text-sm text-slate-500">Reason for visit: not stated.</li>}
        <li><label className="flex items-start gap-3 rounded-xl border border-slate-200 p-3 text-sm"><input type="checkbox" checked={absence} onChange={e=>setAbsence(e.target.checked)} className="mt-0.5 size-5 accent-teal-700"/><span><span className="block text-xs font-semibold text-slate-500">Absence documentation</span>{snap.absence_requested?'I’d like to discuss absence documentation (a request — only your clinician decides).':'Not requested. Tick to let your clinician know you haven’t asked for one.'}</span></label></li>
      </ul></fieldset>
      {((snap.unknown?.length ?? 0)>0||(snap.declined?.length ?? 0)>0)&&<p className="mt-3 text-xs text-slate-600"><b>Shown to your clinician as not provided:</b> {[...(snap.unknown ?? []).map(k=>`${LABEL_FOR[k] ?? k} (not known)`),...(snap.declined ?? []).map(k=>`${LABEL_FOR[k] ?? k} (declined)`)].join(' · ')}</p>}
      <label className="mt-4 block text-sm font-semibold">Share with<select className="input mt-2" value={target} onChange={e=>setTarget(e.target.value)}><option value="">The next appointment I book</option>{upcoming.map(e=><option key={e.id} value={e.id}>{e.clinician_name} · {e.visit_type} · {fmtDay(e.starts_at)} {fmtTime(e.starts_at)}</option>)}</select></label>
      <div className="mt-4 rounded-xl bg-slate-50 p-3 text-xs leading-5 text-slate-600"><b>Never shared:</b> raw audio, your conversation transcript, other conversations, and any photo you don’t tick. <b>Professors</b> never receive any of these details.</div>
      <label className="mt-4 flex items-start gap-3 text-sm"><input type="checkbox" checked={authorized} onChange={e=>setAuthorized(e.target.checked)} className="mt-0.5 size-5 accent-teal-700"/><span>I authorize sharing the selected details with {chosenEnc?chosenEnc.clinician_name:'the clinician for this appointment (or the one I book next)'}.</span></label>
      {share.error&&<p role="alert" className="mt-3 text-sm text-rose-600">{(share.error as Error).message}</p>}
      <div className="mt-6 flex justify-end gap-2"><Button variant="ghost" onClick={onClose}>Cancel</Button><Button disabled={!authorized||nothing||share.isPending} onClick={()=>share.mutate()}>Submit pre-visit summary</Button></div></>}
  </Card></div>
}

const LABEL_FOR: Record<string, string> = { symptoms_free_text: 'Symptoms', onset_text: 'When it started', temperature: 'Temperature', photo: 'Photo', appointment_preference: 'Appointment preference', accessibility_needs: 'Accessibility needs', requests: 'Requests', photo_observations: 'AI photo observations (non-diagnostic)' }
export { ABSENCE_LABEL }
