import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import { Button } from './ui'
import { useAuth } from '../lib/auth'
import { initials } from '../lib/format'

export const clinicianNav = [
  { label: 'Appointments', to: '/clinician/dashboard' },
  { label: 'Intake Queue', to: '/clinician/intake' },
  { label: 'Absence Cases', to: '/clinician/absence-cases' },
  { label: 'Document Review', to: '/clinician/documents' },
  { label: 'Signature Settings', to: '/clinician/signatures' },
  { label: 'Activity', to: '/clinician/activity' },
] as const

export default function ClinicianShell() {
  const { me, logout } = useAuth()
  const navigate = useNavigate()
  const signOut = () => logout() // the route guard then sends the visitor to the welcome page
  return <div className="min-h-screen bg-[#f6f8f8] text-slate-900"><aside className="fixed inset-y-0 left-0 hidden w-72 bg-[#0c2f3b] p-5 text-white lg:block"><div className="flex items-center gap-3 px-2"><div className="grid size-10 place-items-center rounded-xl bg-sky-300 font-black text-[#0c2f3b]">C</div><div><b>CuraLink</b><p className="text-xs text-sky-200">CLINICIAN DEMO</p></div></div><nav className="mt-9 space-y-1" aria-label="Clinician navigation">{clinicianNav.map(n=><NavLink key={n.to} to={n.to} className={({isActive})=>`block w-full rounded-xl px-4 py-3 text-left text-sm ${isActive?'bg-white/12 text-white':'text-slate-300 hover:bg-white/8'}`}>{n.label}</NavLink>)}</nav><Button variant="ghost" className="absolute bottom-5 left-5 text-slate-300" onClick={signOut}>Sign out</Button></aside><div className="lg:pl-72"><header className="flex h-20 items-center justify-between border-b border-slate-200 bg-white px-6 md:px-9"><div><b>Clinician workspace</b><p className="text-xs text-slate-500">Fictional data · No clinical actions</p></div><div className="flex items-center gap-3"><Button variant="ghost" className="lg:hidden" onClick={signOut}>Sign out</Button><div className="grid size-10 place-items-center rounded-full bg-sky-100 text-sm font-bold text-sky-800" title={me?.display_name}>{initials(me?.display_name ?? '')}</div></div></header><nav className="flex gap-2 overflow-x-auto border-b border-slate-200 bg-white px-5 py-2 lg:hidden" aria-label="Clinician sections">{clinicianNav.map(n=><NavLink key={n.to} to={n.to} className={({isActive})=>`shrink-0 rounded-lg px-3 py-2 text-sm ${isActive?'bg-teal-50 font-semibold text-teal-800':'text-slate-600'}`}>{n.label}</NavLink>)}</nav><main className="mx-auto max-w-7xl p-5 md:p-9"><Outlet/></main></div></div>
}
