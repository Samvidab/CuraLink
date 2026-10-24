import { useQuery } from '@tanstack/react-query'
import { Card, ErrorBanner, LoadingBlock, SourceBadge } from '../../components/ui'
import { api } from '../../lib/api'
import { eventLabel, fmtRelative } from '../../lib/format'
import type { Activity } from '../../lib/types'

export default function ClinicianActivity() {
  const { data, error, isLoading, refetch } = useQuery({ queryKey: ['clinician-activity'], queryFn: () => api.get<Activity[]>('/clinician/activity') })
  return <><h1 className="text-3xl font-semibold">Activity</h1><p className="mt-2 text-slate-500">Actions you have taken. Logs never include patient narratives or document contents.</p>{error&&<div className="mt-5"><ErrorBanner error={error} onRetry={()=>refetch()}/></div>}<Card className="mt-7 divide-y divide-slate-100">{isLoading&&<LoadingBlock/>}{data?.length===0&&<p className="p-5 text-sm text-slate-500">No activity yet.</p>}{data?.map(a=><div key={a.id} className="flex flex-wrap items-center justify-between gap-3 p-4 text-sm"><div><b>{eventLabel(a.event_type)}</b>{a.to_state&&<span className="ml-2 text-slate-500">→ {a.to_state}</span>}<p className="text-slate-500">{fmtRelative(a.at)}{a.detail?` · ${a.detail}`:''}</p></div><SourceBadge mode={a.source_mode}/></div>)}</Card></>
}
