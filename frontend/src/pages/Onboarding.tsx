import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import { Badge, Button, Icon } from '../components/ui'
import { useAuth } from '../lib/auth'
import { api, ApiError } from '../lib/api'
import type { CalendarImport, Me } from '../lib/types'
import { Logo } from '../components/Logo'

// Steps: 0 role selection · 1 profile · 2 calendar import · 3 done · 4 clinician sign-in · 5 student sign-in
type ImportState = 'idle' | 'dragging' | 'uploading' | 'success' | 'error'
const DEMO_CLINICIAN = { email: 'dr.rivera@clinic.example.com', password: 'curalink-demo' }
const DEMO_STUDENT = { email: 'sam.lee@students.example.com', password: 'curalink-demo' }
const contactLabel = { VERIFIED: 'Contact verified', STUDENT_CONFIRMED: 'Contact confirmed by you', NEEDS_REVIEW: 'Contact needs review', MISSING: 'Contact needed' } as const

export default function Onboarding({ initialStep = 0 }: { initialStep?: 0 | 1 | 2 | 4 | 5 }) {
  const navigate = useNavigate()
  const qc = useQueryClient()
  const { me, login, register, logout } = useAuth()
  const [step, setStep] = useState<number>(initialStep)
  const [first, setFirst] = useState('')
  const [last, setLast] = useState('')
  const [preferred, setPreferred] = useState('')
  const [signup, setSignup] = useState(false)
  const [docReq, setDocReq] = useState({ first_name: '', last_name: '', credentials: '', clinical_role: '' })
  const [requested, setRequested] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [importState, setImportState] = useState<ImportState>('idle')
  const [imported, setImported] = useState<CalendarImport | null>(null)
  const [skipped, setSkipped] = useState(false)
  const fileInput = useRef<HTMLInputElement>(null)

  useEffect(() => { setStep(initialStep); setError(''); setSignup(false); setRequested('') }, [initialStep])
  useEffect(() => {
    if (me?.role !== 'student' || step !== 1) return
    setFirst(v => v || me.first_name || ''); setLast(v => v || me.last_name || ''); setPreferred(v => v || me.preferred_name || '')
  }, [me, step])

  const run = async (fn: () => Promise<void>) => {
    setBusy(true); setError('')
    try { await fn() } catch (e) { setError(e instanceof ApiError ? e.message : 'Something went wrong.') } finally { setBusy(false) }
  }
  const signInStudent = () => {
    if (!email.includes('@') || password.length < 6) return setError('Enter a valid email and a password with at least 6 characters.')
    run(async () => { const m = await login(email, password, 'student'); navigate(m.profile_complete ? '/student/dashboard' : '/student/onboarding') })
  }
  const createStudent = () => {
    if (!email.includes('@') || password.length < 8) return setError('Enter a valid email and a password with at least 8 characters.')
    run(async () => { await register(email, password); navigate('/student/onboarding') })
  }
  const nextProfile = () => {
    if (!first.trim() || !last.trim()) return setError('Enter your first and last name.')
    run(async () => { qc.setQueryData(['me'], await api.patch<Me>('/students/me/profile', { first_name: first, last_name: last, preferred_name: preferred || null })); setStep(2) })
  }
  const requestClinician = () => {
    if (Object.values(docReq).some(v => !v.trim()) || !email.includes('@') || password.length < 8) return setError('Fill in every field; the password needs at least 8 characters.')
    run(async () => { setRequested((await api.post<{ message: string }>('/auth/register/clinician', { ...docReq, email, password })).message) })
  }
  const callName = me?.preferred_name || me?.first_name || ''
  const upload = async (file: File | undefined) => {
    if (!file) return
    setImportState('uploading'); setError('')
    const form = new FormData(); form.append('file', file)
    try { setImported(await api.post<CalendarImport>('/calendars/import', form)); setImportState('success') }
    catch (e) { setImportState('error'); setError(e instanceof ApiError ? e.message : 'Upload failed.') }
  }
  const useSample = async () => {
    setImportState('uploading'); setError('')
    try { setImported(await api.post<CalendarImport>('/calendars/import-sample')); setImportState('success') }
    catch (e) { setImportState('error'); setError(e instanceof ApiError ? e.message : 'Could not load the sample calendar.') }
  }
  const signInClinician = () => {
    if (!email.includes('@') || password.length < 6) return setError('Enter a valid email and a password with at least 6 characters.')
    run(async () => { await login(email, password, 'clinician'); navigate('/clinician/dashboard') })
  }
  const finish = () => { qc.invalidateQueries({ queryKey: ['student-dashboard'] }); navigate('/student/dashboard') }
  const ready = importState === 'success' || skipped

  return <main className="min-h-screen bg-[#f5faf9] p-5 text-slate-900">
    <div className="mx-auto flex min-h-[calc(100vh-2.5rem)] max-w-6xl overflow-hidden rounded-[2rem] border border-slate-200 bg-white shadow-xl">
      <aside className="hidden w-[38%] flex-col justify-between bg-[#0c2f3b] p-12 text-white md:flex">
        <div><div className="mb-16 flex items-center gap-3"><Logo size={48}/><span className="text-xl font-bold">CuraLink</span></div>
          <p className="text-sm font-semibold text-teal-300">BUILT FOR CAL HACKS 13.0</p>
          <h1 className="mt-4 text-4xl font-semibold leading-tight">Campus care, coordinated around your life.</h1>
          <p className="mt-5 max-w-sm leading-7 text-slate-300">Navigate student health resources, compare care with your classes, and communicate absences with confidence.</p>
        </div>
        <p className="text-sm text-slate-400">Private by design. No university password required.</p>
      </aside>
      <div className="flex flex-1 flex-col p-7 md:p-12">
        <div className="mb-6 flex items-center gap-3 md:hidden"><Logo size={44}/><span className="text-lg font-bold">CuraLink</span></div>
        <div className="mb-10 flex gap-2" aria-label={step===4?'Clinician sign in':step===5?'Student sign in':`Onboarding step ${step + 1} of 4`}>{[0,1,2,3].map(i=><div key={i} className={`h-1.5 flex-1 rounded-full ${step>=4||i<=step?'bg-teal-600':'bg-slate-200'}`}/>)}</div>
        <div className="my-auto mx-auto w-full max-w-lg">
          {step===0 && <><Badge>Choose your portal</Badge><h2 className="mt-5 text-4xl font-semibold tracking-tight">Welcome to CuraLink</h2>{me&&<div className="mt-5 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-teal-200 bg-teal-50 p-3 text-sm text-teal-900" role="status"><span>You’re still signed in as <b>{me.display_name}</b>.</span><span className="flex gap-2"><Button className="min-h-9 py-1" onClick={()=>navigate(me.role==='student'&&!me.profile_complete?'/student/onboarding':`/${me.role}/dashboard`)}>Continue as {me.preferred_name || me.first_name || me.display_name}</Button><Button variant="secondary" className="min-h-9 py-1" onClick={()=>void logout()}>Sign out</Button></span></div>}<p className="mt-4 text-lg leading-7 text-slate-600">Sign in to the workspace built for your role. This selection is for the fictional demo only.</p><div className="mt-8 grid gap-4 sm:grid-cols-2"><button onClick={()=>navigate('/student/sign-in')} className="rounded-2xl border-2 border-slate-200 p-5 text-left transition hover:border-teal-500 hover:bg-teal-50 focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-teal-200 disabled:opacity-60"><div className="grid size-11 place-items-center rounded-xl bg-teal-100 font-bold text-teal-800">S</div><h3 className="mt-4 font-semibold">I'm a student</h3><p className="mt-1 text-sm leading-5 text-slate-500">Coordinate care, classes, and cases.</p></button><button onClick={()=>navigate('/clinician/sign-in')} className="rounded-2xl border-2 border-slate-200 p-5 text-left transition hover:border-sky-500 hover:bg-sky-50 focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-sky-200"><div className="grid size-11 place-items-center rounded-xl bg-sky-100 font-bold text-sky-800">MD</div><h3 className="mt-4 font-semibold">I'm a healthcare professional</h3><p className="mt-1 text-sm leading-5 text-slate-500">Sign in to the clinician demo portal.</p></button></div>{error&&<p role="alert" className="mt-4 text-sm text-rose-600">{error}</p>}<p className="mt-5 text-center text-xs text-slate-400">Role selection is presentation only; the server decides what each account can access. Choosing “healthcare professional” does not prove clinician status.</p></>}
          {step===1 && <><p className="text-sm font-semibold text-teal-700">STEP 2 OF 4</p><h2 className="mt-2 text-3xl font-semibold">Welcome to CuraLink! Before we get started, what should we call you?</h2><p className="mt-2 text-slate-500">Signed in as <b>{me?.email}</b>. Your name is saved to your own profile and shown on appointments with clinicians you book.</p><form className="mt-8 space-y-5" onSubmit={e=>{e.preventDefault();nextProfile()}}><div className="grid gap-4 sm:grid-cols-2"><label className="block text-sm font-semibold">First name<span className="text-rose-600" aria-hidden="true"> *</span><input value={first} onChange={e=>setFirst(e.target.value)} aria-required="true" className="input mt-2" autoComplete="given-name"/></label><label className="block text-sm font-semibold">Last name<span className="text-rose-600" aria-hidden="true"> *</span><input value={last} onChange={e=>setLast(e.target.value)} aria-required="true" className="input mt-2" autoComplete="family-name"/></label></div><label className="block text-sm font-semibold">Preferred name <span className="font-normal text-slate-500">(optional)</span><input value={preferred} onChange={e=>setPreferred(e.target.value)} className="input mt-2" autoComplete="nickname" aria-describedby="pref-hint"/><span id="pref-hint" className="mt-1 block text-xs font-normal text-slate-500">What CuraLink calls you in greetings. You can change it later in Settings.</span></label><label className="block text-sm font-semibold">University<select className="input mt-2" defaultValue="Purdue University"><option>Purdue University</option></select></label>{error&&<p role="alert" className="text-sm text-rose-600">{error}</p>}<Button type="submit" className="w-full" disabled={busy}>Continue</Button></form></>}
          {step===2 && <><p className="text-sm font-semibold text-teal-700">STEP 3 OF 4</p><h2 className="mt-2 text-3xl font-semibold">Import your UniTime schedule</h2><p className="mt-3 leading-6 text-slate-600">Upload the .ics file exported from UniTime so CuraLink can compare classes with care times. This is a one-time file import (no live sync), and we never ask for your Purdue password.</p>
            <details className="mt-4 rounded-xl bg-slate-50 p-4 text-sm leading-6 text-slate-700"><summary className="cursor-pointer font-semibold">How do I get my schedule file?</summary><ol className="mt-2 list-decimal space-y-1 pl-5"><li>Sign in to UniTime yourself in another tab (CuraLink never sees your password).</li><li>Open your personal timetable for the current term.</li><li>Choose <b>Export → iCalendar</b> and save the <code>.ics</code> file.</li><li>Upload it here. Then check the list below: course codes, times, time zone, and instructor contacts.</li><li>Anything marked “Contact needed” or “needs review” can be fixed later in Settings → Courses & instructors.</li></ol><p className="mt-2 text-xs text-slate-500">Exact menu names can differ between UniTime versions. No file handy? Use the fictional sample calendar.</p></details>
            {importState!=='success'&&<label onDragOver={e=>{e.preventDefault();setImportState('dragging')}} onDragLeave={()=>setImportState('idle')} onDrop={e=>{e.preventDefault();upload(e.dataTransfer.files[0])}} className={`mt-7 flex cursor-pointer flex-col items-center rounded-2xl border-2 border-dashed p-6 text-center transition focus-within:ring-4 focus-within:ring-teal-200 ${importState==='dragging'?'border-teal-500 bg-teal-50':'border-slate-200 hover:border-teal-300'}`}><span className="grid size-11 place-items-center rounded-xl bg-teal-50 text-teal-700"><Icon name="upload"/></span><span className="mt-3 text-sm font-semibold">{importState==='uploading'?'Reading your calendar…':'Drop your UniTime .ics file here'}</span><span className="mt-1 text-xs text-slate-500">.ics only · up to 2 MB</span><input ref={fileInput} type="file" accept=".ics,text/calendar" className="sr-only" onChange={e=>upload(e.target.files?.[0])} aria-label="Upload UniTime .ics file"/></label>}
            {error&&<p role="alert" className="mt-3 text-sm text-rose-600">{error}{importState==='error'&&' You can try again or use the fictional sample calendar.'}</p>}
            {importState==='success'&&imported?<div className="mt-5 rounded-xl bg-teal-50 p-4 text-sm text-teal-900" role="status"><div className="flex items-center justify-between gap-2"><b>Calendar {imported.source_mode==='demo'?'loaded':'imported'}</b><Badge tone={imported.source_mode==='demo'?'amber':'blue'}>{imported.source_mode==='demo'?'DEMO SAMPLE':'UPLOADED'}</Badge></div><p className="mt-1 text-teal-800">{imported.events_imported} class meetings this term · {imported.timezone}</p><ul className="mt-3 space-y-1.5">{imported.courses.map(c=><li key={c.id} className="flex items-center justify-between gap-2"><span><b>{c.code}</b> <span className="text-teal-800">· {c.title}{c.term?` · ${c.term}`:''}</span></span><span className={`text-xs font-semibold ${c.contact_status==='VERIFIED'||c.contact_status==='STUDENT_CONFIRMED'?'text-teal-700':'text-amber-700'}`}>{contactLabel[c.contact_status]}</span></li>)}</ul>{imported.warnings.length>0&&<div className="mt-3 rounded-lg bg-amber-50 p-3 text-xs text-amber-800"><b>Please review:</b><ul className="mt-1 list-disc pl-4">{imported.warnings.map(w=><li key={w}>{w}</li>)}</ul></div>}</div>
            :<div className="mt-5 grid gap-3 sm:grid-cols-2"><Button disabled={importState==='uploading'} onClick={()=>fileInput.current?.click()}><Icon name="upload" size={18}/>Upload .ics file</Button><Button variant="secondary" disabled={importState==='uploading'} onClick={useSample}>Use fictional sample calendar</Button></div>}
            <div className="mt-5 flex items-center justify-between">{importState!=='success'?<button onClick={()=>{setSkipped(true);setStep(3)}} className="text-sm font-semibold text-slate-500 underline">Skip for now</button>:<button onClick={()=>{setImportState('idle');setImported(null)}} className="text-sm font-semibold text-slate-500 underline">Use a different file</button>}<Button disabled={!ready} onClick={()=>setStep(3)}>Continue</Button></div></>}
          {step===3 && <div className="text-center"><div className="mx-auto grid size-16 place-items-center rounded-full bg-teal-100 text-teal-700"><Icon name="check" size={30}/></div><h2 className="mt-6 text-3xl font-semibold">You’re ready{callName?`, ${callName}`:''}.</h2><p className="mt-3 leading-7 text-slate-600">{skipped&&importState!=='success'?'You can import your calendar any time from Settings. ':''}Find demo care, ask the campus navigator, and submit absence cases for clinician review.</p><Button className="mt-8 w-full" onClick={finish}>Go to dashboard <Icon name="arrow"/></Button></div>}
          {step===5 && signup && <><button onClick={()=>{setSignup(false);setError('')}} className="mb-6 text-sm font-semibold text-slate-500">← Back to sign in</button><Badge>Student portal</Badge><h2 className="mt-5 text-3xl font-semibold">Create a student account</h2><p className="mt-3 leading-6 text-slate-500">Fictional demo accounts only. Don’t use your real university password. We’ll ask for your name next.</p><form className="mt-8 space-y-5" onSubmit={e=>{e.preventDefault();createStudent()}}><label className="block text-sm font-semibold">Email<input type="email" value={email} onChange={e=>setEmail(e.target.value)} placeholder="you@students.example.com" className="input mt-2" autoComplete="email"/></label><label className="block text-sm font-semibold">Create a password<input type="password" value={password} onChange={e=>setPassword(e.target.value)} placeholder="At least 8 characters" className="input mt-2" autoComplete="new-password"/></label>{error&&<p role="alert" className="text-sm text-rose-600">{error}</p>}<Button type="submit" className="w-full" disabled={busy}>Create account <Icon name="arrow"/></Button></form></>}
          {step===5 && !signup && <><button onClick={()=>navigate('/select-role')} className="mb-6 text-sm font-semibold text-slate-500">← Back to role selection</button><Badge>Student portal</Badge><h2 className="mt-5 text-3xl font-semibold">Sign in as a student</h2><p className="mt-3 leading-6 text-slate-500">This is a fictional demo. Use the demo student account below — never your real Purdue credentials.</p><form className="mt-8 space-y-5" onSubmit={e=>{e.preventDefault();signInStudent()}}><label className="block text-sm font-semibold">Student email<input type="email" name="email" value={email} onChange={e=>setEmail(e.target.value)} placeholder="you@students.example.com" className="input mt-2" autoComplete="username"/></label><label className="block text-sm font-semibold">Password<input type="password" name="password" value={password} onChange={e=>setPassword(e.target.value)} placeholder="Enter your password" className="input mt-2" autoComplete="current-password"/></label>{error&&<p role="alert" className="text-sm text-rose-600">{error}</p>}<Button type="submit" className="w-full" disabled={busy}>Sign in to student portal <Icon name="arrow"/></Button><button type="button" onClick={()=>{setEmail(DEMO_STUDENT.email);setPassword(DEMO_STUDENT.password);setError('')}} className="w-full rounded-xl border border-dashed border-teal-200 bg-teal-50/60 p-3 text-left text-xs text-teal-900 hover:border-teal-400"><b>Use demo student account</b><br/>{DEMO_STUDENT.email} · password <code>{DEMO_STUDENT.password}</code></button></form><button type="button" onClick={()=>{setSignup(true);setError('');setEmail('');setPassword('')}} className="mt-5 w-full text-center text-sm font-semibold text-teal-700 underline">New to CuraLink? Create a student account</button></>}
          {step===4 && signup && <><button onClick={()=>{setSignup(false);setError('');setRequested('')}} className="mb-6 text-sm font-semibold text-slate-500">← Back to sign in</button><Badge tone="blue">Clinician portal</Badge><h2 className="mt-5 text-3xl font-semibold">Request a clinician account</h2><p className="mt-3 leading-6 text-slate-500">An administrator verifies credentials before any clinician access is granted. Submitting this form does not give you access to patient information.</p>{requested?<p role="status" className="mt-6 rounded-xl bg-sky-50 p-4 text-sm text-sky-900">{requested}</p>:<form className="mt-6 space-y-4" onSubmit={e=>{e.preventDefault();requestClinician()}}><div className="grid gap-4 sm:grid-cols-2"><label className="block text-sm font-semibold">First name<input value={docReq.first_name} onChange={e=>setDocReq({...docReq,first_name:e.target.value})} className="input mt-2" autoComplete="given-name"/></label><label className="block text-sm font-semibold">Last name<input value={docReq.last_name} onChange={e=>setDocReq({...docReq,last_name:e.target.value})} className="input mt-2" autoComplete="family-name"/></label><label className="block text-sm font-semibold">Professional credentials<input value={docReq.credentials} onChange={e=>setDocReq({...docReq,credentials:e.target.value})} placeholder="MD, DO, NP, RN…" className="input mt-2"/></label><label className="block text-sm font-semibold">Specialty or clinical role<input value={docReq.clinical_role} onChange={e=>setDocReq({...docReq,clinical_role:e.target.value})} placeholder="Primary Care" className="input mt-2"/></label></div><label className="block text-sm font-semibold">Professional email<input type="email" value={email} onChange={e=>setEmail(e.target.value)} className="input mt-2" autoComplete="email"/></label><label className="block text-sm font-semibold">Create a password<input type="password" value={password} onChange={e=>setPassword(e.target.value)} placeholder="At least 8 characters" className="input mt-2" autoComplete="new-password"/></label>{error&&<p role="alert" className="text-sm text-rose-600">{error}</p>}<Button type="submit" className="w-full" disabled={busy}>Submit for verification</Button></form>}</>}
          {step===4 && !signup && <><button onClick={()=>navigate('/select-role')} className="mb-6 text-sm font-semibold text-slate-500">← Back to role selection</button><Badge tone="blue">Clinician portal</Badge><h2 className="mt-5 text-3xl font-semibold">Sign in as a healthcare professional</h2><p className="mt-3 leading-6 text-slate-500">This is a fictional demo. Use the demo clinician account below; real clinician identity verification is out of scope.</p><form className="mt-8 space-y-5" onSubmit={e=>{e.preventDefault();signInClinician()}}><label className="block text-sm font-semibold">Professional email<input type="email" value={email} onChange={e=>setEmail(e.target.value)} placeholder="doctor@clinic.example.com" className="input mt-2" autoComplete="email"/></label><label className="block text-sm font-semibold">Password<input type="password" value={password} onChange={e=>setPassword(e.target.value)} placeholder="Enter your password" className="input mt-2" autoComplete="current-password"/></label>{error&&<p role="alert" className="text-sm text-rose-600">{error}</p>}<Button type="submit" className="w-full" disabled={busy}>Sign in to clinician portal <Icon name="arrow"/></Button><button type="button" onClick={()=>{setEmail(DEMO_CLINICIAN.email);setPassword(DEMO_CLINICIAN.password);setError('')}} className="w-full rounded-xl border border-dashed border-sky-200 bg-sky-50/60 p-3 text-left text-xs text-sky-900 hover:border-sky-400"><b>Use demo clinician account</b><br/>{DEMO_CLINICIAN.email} · password <code>{DEMO_CLINICIAN.password}</code></button><p className="text-center text-xs text-slate-400">Demo sign-in only. No real clinician identity is verified.</p></form><button type="button" onClick={()=>{setSignup(true);setError('');setEmail('');setPassword('')}} className="mt-5 w-full text-center text-sm font-semibold text-sky-700 underline">Request a clinician account</button></>}
        </div>
      </div>
    </div>
  </main>
}
