import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import { Badge, Button, Card, SourceBadge } from '../../components/ui'
import { useStudentDashboard } from '../../components/StudentShell'
import { useAuth } from '../../lib/auth'
import { api, ApiError } from '../../lib/api'
import type { Me } from '../../lib/types'

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
  return <><h1 className="text-3xl font-semibold">Settings & privacy</h1><p className="mt-2 text-slate-500">Control your profile and simulated data connections.</p>{error&&<p role="alert" className="mt-4 text-sm text-rose-600">{error}</p>}<div className="mt-7 grid gap-5 lg:grid-cols-2"><Card className="p-6"><h2 className="text-lg font-semibold">Student profile</h2><label className="mt-5 block text-sm font-semibold">Name<input value={name ?? me?.display_name ?? ''} onChange={e=>setName(e.target.value)} className="input mt-2"/></label><label className="mt-4 block text-sm font-semibold">University email<input value={me?.email ?? ''} readOnly className="input mt-2 bg-slate-50 text-slate-500"/></label><Button className="mt-5" onClick={saveProfile}>Save profile</Button>{saved&&<p role="status" className="mt-3 text-sm font-semibold text-teal-700">{saved}</p>}</Card><Card className="p-6"><div className="flex items-center justify-between"><h2 className="text-lg font-semibold">UniTime calendar</h2><div className="flex gap-2">{data?.calendar&&<SourceBadge mode={data.calendar.source_mode}/>}<Badge tone={connected?'teal':'slate'}>{connected?'Connected':'Disconnected'}</Badge></div></div><p className="mt-4 text-sm leading-6 text-slate-500">Schedule data is used only to show conflicts and identify classes for absence drafts. This prototype accepts .ics uploads and never requests your password.</p>{data?.calendar&&<p className="mt-2 text-xs text-slate-500">{data.calendar.filename} · {data.calendar.events_imported} meetings · {data.calendar.timezone}</p>}{connected?<Button variant="danger" className="mt-5" onClick={()=>setConfirm(true)}>Disconnect calendar</Button>:<Button variant="secondary" className="mt-5" onClick={()=>go('/student/import')}>Import calendar</Button>}</Card><Card className="p-6 lg:col-span-2"><h2 className="text-lg font-semibold">Your privacy</h2><p className="mt-2 text-sm leading-6 text-slate-500">CuraLink minimizes sensitive data. You never need to disclose a diagnosis, and demo appointments, clinic availability, and email delivery are simulated.</p><Button variant="danger" className="mt-5" disabled={!connected} onClick={()=>setConfirm(true)}>Delete stored schedule data</Button>{deleted&&<p role="status" className="mt-3 text-sm font-semibold text-teal-700">Schedule data deleted from the demo server.</p>}</Card></div>{confirm&&<div role="dialog" aria-modal="true" aria-labelledby="rm-title" className="fixed inset-0 z-50 grid place-items-center bg-slate-950/40 p-5"><Card className="max-w-md p-6"><h2 id="rm-title" className="text-xl font-semibold">Remove calendar data?</h2><p className="mt-3 text-sm leading-6 text-slate-500">This disconnects the calendar and deletes its imported classes and meetings from the demo server.</p><div className="mt-6 flex justify-end gap-2"><Button variant="ghost" onClick={()=>setConfirm(false)}>Cancel</Button><Button variant="danger" onClick={removeCalendar}>Remove data</Button></div></Card></div>}</>
}
