import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import { Badge, Button, Card, SourceBadge } from '../../components/ui'
import { useStudentDashboard } from '../../components/StudentShell'
import { useAuth } from '../../lib/auth'
import { api, ApiError } from '../../lib/api'
import type { Course, Me } from '../../lib/types'

const SOURCE: Record<string, string> = { unitime_ics: 'From your UniTime file', demo_catalog: 'Fictional demo catalog', manual: 'Entered by you', ics: 'Not in your calendar file' }
const STATUS: Record<string, string> = { VERIFIED: 'Verified', STUDENT_CONFIRMED: 'Confirmed by you', NEEDS_REVIEW: 'Needs review', MISSING: 'Contact needed' }

function CourseRow({ c }: { c: Course }) {
  const qc = useQueryClient()
  const [open, setOpen] = useState(false)
  const [name, setName] = useState(c.instructor_name ?? '')
  const [email, setEmail] = useState(c.instructor_email ?? '')
  const [ok, setOk] = useState(false)
  const [error, setError] = useState('')
  const save = async () => {
    setError('')
    try { await api.patch(`/courses/${c.id}/contact`, { instructor_name: name || null, instructor_email: email, confirm: ok }); setOpen(false); qc.invalidateQueries({ queryKey: ['student-dashboard'] }) }
    catch (e) { setError(e instanceof ApiError ? e.message : 'Could not save.') }
  }
  return <li className="py-3"><div className="flex flex-wrap items-center justify-between gap-2"><div><b>{c.code}</b> <span className="text-slate-500">· {c.title ?? 'Untitled course'}</span><p className="text-xs text-slate-500">{c.instructor_name ?? 'Instructor not listed'}{c.instructor_email?` · ${c.instructor_email}`:''} · {SOURCE[c.provenance] ?? c.provenance}</p></div><div className="flex items-center gap-2"><Badge tone={c.contact_status==='VERIFIED'||c.contact_status==='STUDENT_CONFIRMED'?'teal':'amber'}>{STATUS[c.contact_status] ?? c.contact_status}</Badge><Button variant="ghost" className="min-h-9 py-1" onClick={()=>setOpen(!open)} aria-expanded={open}>Edit</Button></div></div>
    {open&&<div className="mt-3 grid gap-2 rounded-xl bg-slate-50 p-3 sm:grid-cols-2"><label className="text-xs font-semibold">Instructor name<input value={name} onChange={e=>setName(e.target.value)} className="input mt-1"/></label><label className="text-xs font-semibold">Instructor email<input type="email" value={email} onChange={e=>setEmail(e.target.value)} className="input mt-1" placeholder="name@example.com"/></label><label className="flex items-center gap-2 text-xs sm:col-span-2"><input type="checkbox" checked={ok} onChange={e=>setOk(e.target.checked)} className="size-4 accent-teal-700"/>I copied this from the official course page or syllabus</label>{error&&<p role="alert" className="text-xs text-rose-600 sm:col-span-2">{error}</p>}<div className="sm:col-span-2"><Button disabled={!ok||!email.includes('@')} onClick={save}>Save instructor</Button></div></div>}</li>
}

export default function Settings() {
  const { me } = useAuth()
  const qc = useQueryClient()
  const go = useNavigate()
  const { data } = useStudentDashboard()
  const connected = !!data?.calendar
  const [name, setName] = useState<string | null>(null)
  const [saved, setSaved] = useState('')
  const [confirm, setConfirm] = useState(false)
  const [deleted, setDeleted] = useState(false)
  const [error, setError] = useState('')
  const saveProfile = async () => {
    setError(''); setSaved('')
    try { qc.setQueryData(['me'], await api.patch<Me>('/students/me/profile', { display_name: (name ?? me?.display_name ?? '').trim() })); qc.invalidateQueries({ queryKey: ['student-dashboard'] }); setSaved('Profile saved.') }
    catch (e) { setError(e instanceof ApiError ? e.message : 'Could not save.') }
  }
  const removeCalendar = async () => {
    setError('')
    try { await api.del('/calendars/me'); setDeleted(true); qc.invalidateQueries({ queryKey: ['student-dashboard'] }) }
    catch (e) { setError(e instanceof ApiError ? e.message : 'Could not remove calendar data.') }
    finally { setConfirm(false) }
  }
  return <><h1 className="text-3xl font-semibold">Settings & privacy</h1><p className="mt-2 text-slate-500">Control your profile and simulated data connections.</p>{error&&<p role="alert" className="mt-4 text-sm text-rose-600">{error}</p>}<div className="mt-7 grid gap-5 lg:grid-cols-2"><Card className="p-6"><h2 className="text-lg font-semibold">Student profile</h2><label className="mt-5 block text-sm font-semibold">Name<input value={name ?? me?.display_name ?? ''} onChange={e=>setName(e.target.value)} className="input mt-2"/></label><label className="mt-4 block text-sm font-semibold">University email<input value={me?.email ?? ''} readOnly className="input mt-2 bg-slate-50 text-slate-500"/></label><Button className="mt-5" onClick={saveProfile}>Save profile</Button>{saved&&<p role="status" className="mt-3 text-sm font-semibold text-teal-700">{saved}</p>}</Card><Card className="p-6"><div className="flex items-center justify-between"><h2 className="text-lg font-semibold">UniTime calendar</h2><div className="flex gap-2">{data?.calendar&&<SourceBadge mode={data.calendar.source_mode}/>}<Badge tone={connected?'teal':'slate'}>{connected?'Imported':'Not imported'}</Badge></div></div><p className="mt-4 text-sm leading-6 text-slate-500">Schedule data is used only to show conflicts and identify classes for absence drafts. This prototype imports a UniTime .ics file once (no automatic sync) and never requests your password.</p>{data?.calendar&&<p className="mt-2 text-xs text-slate-500">{data.calendar.filename} · {data.calendar.events_imported} meetings · {data.calendar.timezone}</p>}{connected?<Button variant="danger" className="mt-5" onClick={()=>setConfirm(true)}>Remove calendar</Button>:<Button variant="secondary" className="mt-5" onClick={()=>go('/student/import')}>Import calendar</Button>}</Card>{data&&data.courses.length>0&&<Card className="p-6 lg:col-span-2"><h2 className="text-lg font-semibold">Courses & instructors</h2><p className="mt-2 text-sm text-slate-500">Instructor contacts are used only for clinician-approved attendance notices. CuraLink never guesses an address; fix missing ones here. Demo delivery only reaches example.com test inboxes.</p><ul className="mt-3 divide-y divide-slate-100 text-sm">{data.courses.map(c=><CourseRow key={c.id} c={c}/>)}</ul></Card>}<Card className="p-6 lg:col-span-2"><h2 className="text-lg font-semibold">Your privacy</h2><p className="mt-2 text-sm leading-6 text-slate-500">CuraLink minimizes sensitive data. You never need to disclose a diagnosis, and demo appointments, clinic availability, and email delivery are simulated.</p><Button variant="danger" className="mt-5" disabled={!connected} onClick={()=>setConfirm(true)}>Delete stored schedule data</Button>{deleted&&<p role="status" className="mt-3 text-sm font-semibold text-teal-700">Schedule data deleted from the demo server.</p>}</Card></div>{confirm&&<div role="dialog" aria-modal="true" aria-labelledby="rm-title" className="fixed inset-0 z-50 grid place-items-center bg-slate-950/40 p-5"><Card className="max-w-md p-6"><h2 id="rm-title" className="text-xl font-semibold">Remove calendar data?</h2><p className="mt-3 text-sm leading-6 text-slate-500">This removes the imported calendar and deletes its classes and meetings from the demo server.</p><div className="mt-6 flex justify-end gap-2"><Button variant="ghost" onClick={()=>setConfirm(false)}>Cancel</Button><Button variant="danger" onClick={removeCalendar}>Remove data</Button></div></Card></div>}</>
}
