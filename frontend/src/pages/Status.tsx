import { Link } from 'react-router-dom'
import { Badge, Card } from '../components/ui'
import { useAuth } from '../lib/auth'

const home = (role?: string) => (role === 'clinician' ? '/clinician/dashboard' : role === 'student' ? '/student/dashboard' : '/select-role')

/** 403: deliberately reveals nothing about the requested resource. */
export function Forbidden() {
  const { me } = useAuth()
  return <main className="grid min-h-screen place-items-center bg-[#f6f8f8] p-5"><Card className="max-w-md p-8 text-center"><Badge tone="rose">403 · ACCESS DENIED</Badge><h1 className="mt-4 text-2xl font-semibold">You don’t have access to this page</h1><p className="mt-3 text-sm leading-6 text-slate-500">Each CuraLink portal only shows information its role is authorized to see. Sign out to switch roles.</p><Link to={home(me?.role)} className="mt-6 inline-flex min-h-11 items-center rounded-xl bg-teal-700 px-4 text-sm font-semibold text-white">Go to my dashboard</Link></Card></main>
}

export function NotFound() {
  const { me } = useAuth()
  return <main className="grid min-h-screen place-items-center bg-[#f6f8f8] p-5"><Card className="max-w-md p-8 text-center"><h1 className="text-2xl font-semibold">Page not found</h1><Link to={home(me?.role)} className="mt-6 inline-flex min-h-11 items-center rounded-xl bg-teal-700 px-4 text-sm font-semibold text-white">Go home</Link></Card></main>
}

/** Section that exists in the IA but isn't connected yet. Says so plainly. */
export function ComingSoon({ title, detail }: { title: string; detail: string }) {
  return <><h1 className="text-3xl font-semibold">{title}</h1><Card className="mt-7 p-6"><Badge tone="slate">Not yet available</Badge><p className="mt-3 text-sm leading-6 text-slate-500">{detail}</p></Card></>
}
