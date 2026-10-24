import type { PropsWithChildren } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'
import { useAuth } from './lib/auth'
import type { Role } from './lib/types'
import StudentShell from './components/StudentShell'
import ClinicianShell from './components/ClinicianShell'
import Onboarding from './pages/Onboarding'
import { Forbidden, NotFound } from './pages/Status'
import Dashboard from './pages/student/Dashboard'
import FindCare from './pages/student/FindCare'
import Assistant from './pages/student/Assistant'
import Schedule from './pages/student/Schedule'
import AbsenceCenter from './pages/student/AbsenceCenter'
import Settings from './pages/student/Settings'
import ClinicianDashboard from './pages/clinician/ClinicianDashboard'
import EncounterCase from './pages/clinician/EncounterCase'
import ClinicianActivity from './pages/clinician/ClinicianActivity'
import { AbsenceCases, DocumentReview, IntakeQueue, SignatureSettings } from './pages/clinician/ClinicianLists'
import TestInbox from './pages/TestInbox'

function Splash() {
  return <main className="grid min-h-screen place-items-center bg-[#f5faf9]" role="status" aria-live="polite"><div className="grid size-12 animate-pulse place-items-center rounded-xl bg-teal-400 font-black text-[#0c2f3b]">C</div><span className="sr-only">Loading CuraLink…</span></main>
}

/** UX-only guard. The server enforces the same rule on every API call (403). */
function RequireRole({ role, children }: PropsWithChildren<{ role: Role }>) {
  const { me, loading } = useAuth()
  if (loading) return <Splash/>
  if (!me) return <Navigate to={role === 'clinician' ? '/clinician/sign-in' : '/select-role'} replace/>
  if (me.role !== role) return <Forbidden/>
  return <>{children}</>
}

function RequireAuth({ children }: PropsWithChildren) {
  const { me, loading } = useAuth()
  if (loading) return <Splash/>
  return me ? <>{children}</> : <Navigate to="/select-role" replace/>
}

function Home() {
  const { me, loading } = useAuth()
  if (loading) return <Splash/>
  return <Navigate to={me ? `/${me.role}/dashboard` : '/select-role'} replace/>
}

export default function App() {
  return <Routes>
    <Route path="/" element={<Home/>}/>
    <Route path="/select-role" element={<Onboarding initialStep={0}/>}/>
    <Route path="/clinician/sign-in" element={<Onboarding initialStep={4}/>}/>
    <Route path="/student/onboarding" element={<RequireRole role="student"><Onboarding initialStep={1}/></RequireRole>}/>
    <Route path="/student/import" element={<RequireRole role="student"><Onboarding initialStep={2}/></RequireRole>}/>
    <Route path="/student" element={<RequireRole role="student"><StudentShell/></RequireRole>}>
      <Route index element={<Navigate to="dashboard" replace/>}/>
      <Route path="dashboard" element={<Dashboard/>}/>
      <Route path="voice" element={<Assistant/>}/>
      <Route path="calendar" element={<Schedule/>}/>
      <Route path="appointments" element={<FindCare/>}/>
      <Route path="cases" element={<AbsenceCenter/>}/>
      <Route path="settings" element={<Settings/>}/>
    </Route>
    <Route path="/clinician/encounters/:id" element={<RequireRole role="clinician"><EncounterCase/></RequireRole>}/>
    <Route path="/clinician" element={<RequireRole role="clinician"><ClinicianShell/></RequireRole>}>
      <Route index element={<Navigate to="dashboard" replace/>}/>
      <Route path="dashboard" element={<ClinicianDashboard/>}/>
      <Route path="intake" element={<IntakeQueue/>}/>
      <Route path="absence-cases" element={<AbsenceCases/>}/>
      <Route path="documents" element={<DocumentReview/>}/>
      <Route path="signatures" element={<SignatureSettings/>}/>
      <Route path="activity" element={<ClinicianActivity/>}/>
    </Route>
    <Route path="/demo/inbox" element={<RequireAuth><TestInbox/></RequireAuth>}/>
    <Route path="/403" element={<Forbidden/>}/>
    <Route path="*" element={<NotFound/>}/>
  </Routes>
}
