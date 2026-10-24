import { useState } from 'react'
import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { Icon } from './ui'
import { useAuth } from '../lib/auth'
import { api } from '../lib/api'
import { initials } from '../lib/format'
import type { StudentDashboard } from '../lib/types'

// Icon keys keep the original Figma page names; labels follow the v1.2 student tabs.
export const studentNav = [
  { icon: 'Overview', label: 'Home', to: '/student/dashboard' },
  { icon: 'AI Health Assistant', label: 'Talk to CuraLink', to: '/student/voice' },
  { icon: 'My Schedule', label: 'Calendar', to: '/student/calendar' },
  { icon: 'Find Care', label: 'Appointments', to: '/student/appointments' },
  { icon: 'Absence Center', label: 'My Cases', to: '/student/cases' },
  { icon: 'Settings', label: 'Settings', to: '/student/settings' },
] as const

export function useStudentDashboard() {
  return useQuery({ queryKey: ['student-dashboard'], queryFn: () => api.get<StudentDashboard>('/students/me/dashboard') })
}

export default function StudentShell() {
  const { me, logout } = useAuth()
  const navigate = useNavigate()
  const [mobile, setMobile] = useState(false)
  const { data } = useStudentDashboard()
  const cal = data?.calendar
  const canGoBack = (window.history.state?.idx ?? 0) > 0
  const signOut = async () => { await logout(); navigate('/select-role', { replace: true }) }

  return <div className="min-h-screen bg-[#f6f8f8] text-slate-900"><aside className={`fixed inset-y-0 left-0 z-40 w-72 bg-[#0c2f3b] p-5 text-white transition-transform lg:translate-x-0 ${mobile?'translate-x-0':'-translate-x-full'}`}><div className="flex items-center justify-between px-2"><div className="flex items-center gap-3"><div className="grid size-10 place-items-center rounded-xl bg-teal-400 font-black text-[#0c2f3b]">C</div><span className="text-xl font-bold">CuraLink</span></div><button className="lg:hidden" onClick={()=>setMobile(false)} aria-label="Close navigation">×</button></div><nav className="mt-9 space-y-1" aria-label="Student navigation">{studentNav.map(n=><NavLink key={n.to} to={n.to} onClick={()=>setMobile(false)} className={({isActive})=>`flex w-full items-center gap-3 rounded-xl px-4 py-3 text-left text-sm font-medium transition ${isActive?'bg-white/12 text-white':'text-slate-300 hover:bg-white/8 hover:text-white'}`}><Icon name={n.icon}/>{n.label}</NavLink>)}</nav><div className="absolute bottom-5 left-5 right-5 rounded-2xl bg-white/8 p-4"><p className="text-xs font-semibold text-teal-300">SAMPLE DATA MODE</p><p className="mt-2 text-sm leading-5 text-slate-300">All integrations and delivery actions are simulated.</p></div></aside>{mobile&&<button className="fixed inset-0 z-30 bg-slate-950/30 lg:hidden" onClick={()=>setMobile(false)} aria-label="Close menu overlay"/>}<div className="lg:pl-72"><header className="sticky top-0 z-20 flex h-20 items-center justify-between border-b border-slate-200/80 bg-[#f6f8f8]/90 px-5 backdrop-blur md:px-9"><div className="flex items-center gap-2"><button onClick={()=>setMobile(true)} className="grid size-11 place-items-center rounded-xl border border-slate-200 bg-white lg:hidden" aria-label="Open navigation">☰</button><button onClick={()=>navigate(-1)} disabled={!canGoBack} className="inline-flex min-h-11 items-center gap-2 rounded-xl border border-slate-200 bg-white px-4 text-sm font-semibold text-slate-700 shadow-sm transition hover:border-teal-300 hover:text-teal-800 focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-teal-200 disabled:cursor-not-allowed disabled:opacity-40" aria-label="Return to previous page"><span aria-hidden="true">←</span> Back</button></div><div className="hidden items-center gap-2 text-sm text-slate-500 sm:flex"><span className={`size-2 rounded-full ${cal?'bg-teal-500':'bg-slate-300'}`}/><span>{cal?(cal.source_mode==='uploaded'?'UniTime file imported · not live-synced':'Sample calendar · fictional'):'No calendar imported'}</span></div><div className="flex items-center gap-3"><button onClick={()=>navigate('/student/voice')} className="hidden min-h-10 items-center gap-2 rounded-xl border border-slate-200 bg-white px-3 text-sm font-semibold text-teal-700 sm:flex"><Icon name="mic" size={18}/>Talk to CuraLink</button><button onClick={signOut} className="grid size-10 place-items-center rounded-full bg-[#d9b56d] text-sm font-bold text-slate-900" aria-label="Sign out and switch role" title="Sign out">{initials(me?.display_name ?? '')}</button></div></header><main className="mx-auto max-w-7xl p-5 md:p-9"><Outlet/></main></div></div>
}
