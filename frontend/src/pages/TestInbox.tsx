import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { Badge, Card, ErrorBanner, LoadingBlock } from '../components/ui'
import { useAuth } from '../lib/auth'
import { api } from '../lib/api'
import { fmtRelative } from '../lib/format'
import type { InboxMessage } from '../lib/types'

/** Demo transport destination: what instructors would have received. Nothing leaves the server. */
export default function TestInbox() {
  const { me } = useAuth()
  const { data, error, isLoading, refetch } = useQuery({ queryKey: ['test-inbox'], queryFn: () => api.get<InboxMessage[]>('/demo/test-inbox') })
  return <main className="min-h-screen bg-[#f6f8f8] p-5 text-slate-900 md:p-9"><div className="mx-auto max-w-4xl"><Link to={me?.role==='clinician'?'/clinician/dashboard':'/student/cases'} className="text-sm font-semibold text-teal-700">← Back</Link><div className="mt-4 flex flex-wrap items-center gap-3"><h1 className="text-3xl font-semibold">Test inbox</h1><Badge tone="amber">DEMO TRANSPORT</Badge></div><p className="mt-2 text-slate-500">Messages “delivered” by CuraLink in demo mode land here, never in a real mailbox. Addresses are fictional (example.com).</p>
    {error&&<div className="mt-5"><ErrorBanner error={error} onRetry={()=>refetch()}/></div>}<div className="mt-7 space-y-4">{isLoading&&<LoadingBlock className="h-32"/>}{data?.length===0&&<Card className="p-6 text-sm text-slate-500">No messages yet.</Card>}{data?.map(m=><Card key={m.id} className="p-5"><div className="flex flex-wrap items-center justify-between gap-2"><b className="text-sm">To: {m.to}</b><span className="text-xs text-slate-500">{fmtRelative(m.received_at)}</span></div><p className="mt-1 text-sm font-semibold">{m.subject}</p><pre className="mt-3 whitespace-pre-wrap font-sans text-sm leading-6 text-slate-700">{m.body}</pre><p className="mt-3 break-all text-xs text-slate-500">📎 {m.attachment_name} · sha256 {m.attachment_sha256.slice(0,24)}…</p></Card>)}</div></div></main>
}
