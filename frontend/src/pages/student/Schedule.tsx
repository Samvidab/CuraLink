import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { Badge, Button, Card, ErrorBanner, LoadingBlock, SourceBadge } from '../../components/ui'
import { useStudentDashboard } from '../../components/StudentShell'
import { api } from '../../lib/api'
import { fmtDay, fmtRange, fmtTime, fmtYmd, ymdIn } from '../../lib/format'
import { courseColor } from '../../lib/courseColors'
import type { CalendarEvent, CalendarEvents } from '../../lib/types'

const addDays = (ymd: string, n: number) => { const d = new Date(`${ymd}T12:00:00Z`); d.setUTCDate(d.getUTCDate() + n); return d.toISOString().slice(0, 10) }
const mondayOf = (ymd: string) => { const d = new Date(`${ymd}T12:00:00Z`); return addDays(ymd, -((d.getUTCDay() + 6) % 7)) }
const dayLabel = (ymd: string) => fmtYmd(ymd, { weekday: 'long', month: 'short', day: 'numeric' }).toUpperCase()

export default function Schedule() {
  const go = useNavigate()
  const { data: dash } = useStudentDashboard()
  const today = dash?.today ?? '2026-10-26'
  const [view, setView] = useState<'day' | 'week'>('day')
  const [day, setDay] = useState<string | null>(null)
  const [selected, setSelected] = useState<CalendarEvent | null>(null)
  const current = day ?? today
  const weekStart = mondayOf(current)
  const { data, error, isLoading, refetch } = useQuery({
    queryKey: ['calendar-events', weekStart],
    queryFn: () => api.get<CalendarEvents>(`/calendar/events?start=${weekStart}&end=${addDays(weekStart, 7)}`),
  })
  const tz = data?.timezone ?? 'America/Indiana/Indianapolis'
  const courses = Object.fromEntries((dash?.courses ?? []).map(c => [c.code, c]))
  const byDay = useMemo(() => {
    const m: Record<string, CalendarEvent[]> = {}
    for (const e of data?.events ?? []) (m[ymdIn(e.start_at, tz)] ??= []).push(e)
    return m
  }, [data, tz])
  const step = (n: number) => { setDay(addDays(current, view === 'week' ? n * 7 : n)); setSelected(null) }
  const color = (e: CalendarEvent) => courseColor(courses[e.course_code ?? '']?.color)

  if (error) return <ErrorBanner error={error} onRetry={() => refetch()} />
  const eventCard = (e: CalendarEvent, compact = false) => <button key={e.id} onClick={()=>setSelected(e)} className={`w-full rounded-xl border-l-4 ${color(e).border} bg-slate-50 text-left transition hover:bg-teal-50 focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-teal-200 ${compact?'p-2.5':'p-4'} ${selected?.id===e.id?'ring-2 ring-teal-300':''}`}><b className={compact?'text-sm':''}>{e.course_code ?? e.title}</b>{e.rescheduled&&<span className="ml-2"><Badge tone="amber">Moved</Badge></span>}<p className={`text-slate-500 ${compact?'text-xs':'text-sm'}`}>{compact?fmtRange(e.start_at,e.end_at,tz):`${courses[e.course_code ?? '']?.title ?? e.title}${courses[e.course_code ?? '']?.instructor_name?` · ${courses[e.course_code ?? '']!.instructor_name}`:''}`}</p></button>

  return <><div className="flex flex-wrap items-end justify-between gap-4"><div><h1 className="text-3xl font-semibold">My schedule</h1><p className="mt-2 text-slate-500">{data?.calendar?`Classes imported from ${data.calendar.source_mode==='uploaded'?'your UniTime .ics file':'the fictional sample calendar'}.`:'No calendar imported yet.'}</p></div><div className="flex flex-wrap items-center gap-2">{data?.calendar&&<SourceBadge mode={data.calendar.source_mode}/>}<Badge tone="slate">Times in {tz.replace(/_/g,' ')}</Badge></div></div>
    {data?.calendar?.warnings.length?<div className="mt-5 rounded-xl border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900" role="note"><b>Import notes:</b> {data.calendar.warnings.join(' ')}</div>:null}
    {!isLoading&&!data?.calendar?<Card className="mt-7 p-8 text-center"><h2 className="text-lg font-semibold">Import your UniTime calendar</h2><p className="mt-2 text-sm text-slate-500">Upload an .ics export or use the fictional sample calendar.</p><Button className="mt-5" onClick={()=>go('/student/import')}>Import calendar</Button></Card>:<>
    <div className="mt-7 flex flex-wrap items-center justify-between gap-3"><div className="flex items-center gap-2"><Button variant="secondary" onClick={()=>step(-1)} aria-label={`Previous ${view}`}>←</Button><Button variant="secondary" onClick={()=>{setDay(null);setSelected(null)}}>Today</Button><Button variant="secondary" onClick={()=>step(1)} aria-label={`Next ${view}`}>→</Button></div><div role="tablist" aria-label="Calendar view" className="flex rounded-xl border border-slate-200 bg-white p-1">{(['day','week'] as const).map(v=><button key={v} role="tab" aria-selected={view===v} onClick={()=>setView(v)} className={`min-h-9 rounded-lg px-4 text-sm font-semibold capitalize ${view===v?'bg-teal-700 text-white':'text-slate-600'}`}>{v}</button>)}</div></div>
    <div className={`mt-5 grid gap-5 ${selected?'xl:grid-cols-[1fr_320px]':''}`}>
      {isLoading?<LoadingBlock className="h-80"/>:view==='day'?<Card className="overflow-hidden"><div className="grid grid-cols-[110px_1fr] border-b border-slate-100 bg-slate-50 p-4 text-xs font-semibold text-slate-500"><span>TIME</span><span>{dayLabel(current)}</span></div>{(byDay[current]??[]).length===0&&<p className="p-6 text-sm text-slate-500">No classes on this day.</p>}{(byDay[current]??[]).map(e=><div key={e.id} className="grid grid-cols-[110px_1fr] border-b border-slate-100 p-4 last:border-0"><span className="text-sm text-slate-500">{e.all_day?'All day':fmtTime(e.start_at,tz)}</span>{eventCard(e)}</div>)}</Card>
      :<div className="overflow-x-auto"><div className="grid min-w-[760px] grid-cols-5 gap-3">{[0,1,2,3,4].map(i=>{const d=addDays(weekStart,i);return <Card key={d} className={`p-3 ${d===today?'ring-2 ring-teal-200':''}`}><button onClick={()=>{setDay(d);setView('day')}} className="w-full text-left text-xs font-semibold text-slate-500 hover:text-teal-700">{dayLabel(d).split(',')[0]}<span className="block text-sm text-slate-800">{dayLabel(d).split(', ')[1]}</span></button><div className="mt-3 space-y-2">{(byDay[d]??[]).length===0&&<p className="text-xs text-slate-400">No classes</p>}{(byDay[d]??[]).map(e=>eventCard(e,true))}</div></Card>})}</div><p className="mt-3 text-xs text-slate-500">Weekends hidden. {Object.keys(byDay).some(d=>[5,6].includes((new Date(`${d}T12:00:00Z`).getUTCDay()+6)%7))?'Some weekend events exist — switch to day view to see them.':'No weekend classes this week.'}</p></div>}
      {selected&&<Card className="h-fit p-5" ><div className="flex items-start justify-between gap-3"><div><Badge tone="slate">Class meeting</Badge><h2 className="mt-3 text-lg font-semibold">{selected.course_code ?? selected.title}</h2></div><button onClick={()=>setSelected(null)} aria-label="Close details" className="text-slate-400 hover:text-slate-700">×</button></div><dl className="mt-4 space-y-3 text-sm">{[['Course',courses[selected.course_code ?? '']?.title ?? selected.title],['When',`${fmtDay(selected.start_at,tz)} · ${fmtRange(selected.start_at,selected.end_at,tz)}`],['Where',selected.location ?? 'Not listed'],['Instructor',courses[selected.course_code ?? '']?.instructor_name ?? 'Not listed'],['Instructor contact',courses[selected.course_code ?? '']?.contact_status==='VERIFIED'?'Verified (demo catalog)':courses[selected.course_code ?? '']?.contact_status==='STUDENT_CONFIRMED'?'Confirmed by you':courses[selected.course_code ?? '']?.contact_status==='NEEDS_REVIEW'?'Needs review':'Contact needed']].map(([k,v])=><div key={k}><dt className="text-xs font-semibold text-slate-500">{k}</dt><dd className="mt-0.5">{v}</dd></div>)}</dl>{selected.rescheduled&&<p className="mt-4 rounded-lg bg-amber-50 p-3 text-xs text-amber-800">This meeting was moved from its usual time in your calendar export.</p>}<div className="mt-4 flex items-center gap-2 text-xs text-slate-500">Source <SourceBadge mode={selected.source}/></div></Card>}
    </div></>}
  </>
}
