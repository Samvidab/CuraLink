import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { Badge, Button, Card, ErrorBanner, LoadingBlock, SourceBadge } from '../../components/ui'
import { useStudentDashboard } from '../../components/StudentShell'
import TermSelector, { useTerms } from '../../components/TermSelector'
import { api } from '../../lib/api'
import { courseColor } from '../../lib/courseColors'
import { fmtDay, fmtRange, fmtTime, fmtYmd, minutesIn, ymdIn } from '../../lib/format'
import type { CalendarEvent, CalendarEvents } from '../../lib/types'

const addDays = (ymd: string, n: number) => { const d = new Date(`${ymd}T12:00:00Z`); d.setUTCDate(d.getUTCDate() + n); return d.toISOString().slice(0, 10) }
const mondayOf = (ymd: string) => { const d = new Date(`${ymd}T12:00:00Z`); return addDays(ymd, -((d.getUTCDay() + 6) % 7)) }
const dayLabel = (ymd: string) => fmtYmd(ymd, { weekday: 'long', month: 'short', day: 'numeric' }).toUpperCase()
const HOUR_PX = 52

/** Side-by-side columns for overlapping meetings within one day. */
function layout(events: CalendarEvent[], tz: string) {
  const items = events.filter(e => !e.all_day).map(e => ({ e, start: minutesIn(e.start_at, tz), end: Math.max(minutesIn(e.end_at, tz), minutesIn(e.start_at, tz) + 15), col: 0, cols: 1 }))
  items.sort((a, b) => a.start - b.start || a.end - b.end)
  let group: typeof items = []
  let groupEnd = -1
  const flush = () => { const n = Math.max(...group.map(g => g.col)) + 1; group.forEach(g => (g.cols = n)); group = [] }
  for (const it of items) {
    if (it.start >= groupEnd && group.length) flush()
    const used = new Set(group.filter(g => g.end > it.start).map(g => g.col))
    while (used.has(it.col)) it.col++
    group.push(it)
    groupEnd = Math.max(groupEnd, it.end)
  }
  if (group.length) flush()
  return items
}

export default function Schedule() {
  const go = useNavigate()
  const { data: dash } = useStudentDashboard()
  const { data: termData } = useTerms()
  const today = termData?.today ?? dash?.today ?? '2026-10-26'
  const term = termData?.terms.find(t => t.term === termData.selected)
  // Start in the selected term: today's week if today is inside it, otherwise the term's first week.
  const anchor = term && (today < term.first_meeting || today > term.last_meeting) ? term.first_meeting : today
  const [view, setView] = useState<'day' | 'week'>('week')
  const [day, setDay] = useState<string | null>(null)
  const [selected, setSelected] = useState<CalendarEvent | null>(null)
  useEffect(() => { setDay(null); setSelected(null) }, [termData?.selected])
  const current = day ?? anchor
  const weekStart = mondayOf(current)
  const { data, error, isLoading, refetch } = useQuery({
    queryKey: ['calendar-events', weekStart, termData?.selected],
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

  // Grid bounds from the real events (default 8 AM–6 PM).
  const timed = (data?.events ?? []).filter(e => !e.all_day)
  const startHour = Math.min(8, ...timed.map(e => Math.floor(minutesIn(e.start_at, tz) / 60)))
  const endHour = Math.max(18, ...timed.map(e => Math.ceil(minutesIn(e.end_at, tz) / 60)))
  const weekend = [5, 6].some(i => (byDay[addDays(weekStart, i)] ?? []).length > 0)
  const days = Array.from({ length: weekend ? 7 : 5 }, (_, i) => addDays(weekStart, i))

  if (error) return <ErrorBanner error={error} onRetry={() => refetch()} />
  const eventCard = (e: CalendarEvent, compact = false) => <button key={e.id} onClick={()=>setSelected(e)} className={`w-full rounded-xl border-l-4 ${color(e).border} bg-slate-50 text-left transition hover:bg-teal-50 focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-teal-200 ${compact?'p-2.5':'p-4'} ${selected?.id===e.id?'ring-2 ring-teal-300':''}`}><b className={compact?'text-sm':''}>{e.course_code ?? e.title}</b>{e.rescheduled&&<span className="ml-2"><Badge tone="amber">Moved</Badge></span>}<p className={`text-slate-500 ${compact?'text-xs':'text-sm'}`}>{compact?fmtRange(e.start_at,e.end_at,tz):`${courses[e.course_code ?? '']?.title ?? e.title}${courses[e.course_code ?? '']?.instructor_name?` · ${courses[e.course_code ?? '']!.instructor_name}`:''}`}</p></button>

  return <><div className="flex flex-wrap items-end justify-between gap-4"><div><h1 className="text-3xl font-semibold">My schedule</h1><p className="mt-2 text-slate-500">{data?.calendar?`Classes imported from ${data.calendar.source_mode==='uploaded'?'your UniTime .ics file':'the fictional sample calendar'}.`:'No calendar imported yet.'}</p></div><div className="flex flex-wrap items-center gap-2">{data?.calendar&&<SourceBadge mode={data.calendar.source_mode}/>}<Badge tone="slate">Times in {tz.replace(/_/g,' ')}</Badge></div></div>
    {data?.calendar&&<div className="mt-5 flex flex-wrap items-center justify-between gap-3"><TermSelector/><Link to="/student/schedule-review" className="text-sm font-semibold text-teal-700 underline">Review imported schedule</Link></div>}
    {term&&<p className="mt-2 text-xs text-slate-500">{term.term}: {term.courses} course{term.courses===1?'':'s'}, classes {fmtYmd(term.first_meeting,{month:'short',day:'numeric'})} – {fmtYmd(term.last_meeting,{month:'short',day:'numeric',year:'numeric'})} · term {term.source}</p>}
    {data?.calendar?.warnings.length?<div className="mt-5 rounded-xl border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900" role="note"><b>Import notes:</b> {data.calendar.warnings.join(' ')}</div>:null}
    {!isLoading&&!data?.calendar?<Card className="mt-7 p-8 text-center"><h2 className="text-lg font-semibold">Import your UniTime calendar</h2><p className="mt-2 text-sm text-slate-500">Upload an .ics export or use the fictional sample calendar.</p><Button className="mt-5" onClick={()=>go('/student/import')}>Import calendar</Button></Card>:<>
    <div className="mt-6 flex flex-wrap items-center justify-between gap-3"><div className="flex items-center gap-2"><Button variant="secondary" onClick={()=>step(-1)} aria-label={`Previous ${view}`}>←</Button><Button variant="secondary" onClick={()=>{setDay(null);setSelected(null)}}>{anchor===today?'Today':'Term start'}</Button><Button variant="secondary" onClick={()=>step(1)} aria-label={`Next ${view}`}>→</Button><span className="ml-1 text-sm font-semibold text-slate-600">{view==='week'?`Week of ${fmtYmd(weekStart,{month:'short',day:'numeric',year:'numeric'})}`:fmtYmd(current,{weekday:'long',month:'short',day:'numeric'})}</span></div><div role="tablist" aria-label="Calendar view" className="flex rounded-xl border border-slate-200 bg-white p-1">{(['day','week'] as const).map(v=><button key={v} role="tab" aria-selected={view===v} onClick={()=>setView(v)} className={`min-h-9 rounded-lg px-4 text-sm font-semibold capitalize ${view===v?'bg-teal-700 text-white':'text-slate-600'}`}>{v}</button>)}</div></div>
    <div className={`mt-5 grid gap-5 ${selected?'xl:grid-cols-[1fr_320px]':''}`}>
      {isLoading?<LoadingBlock className="h-80"/>:view==='day'?<Card className="overflow-hidden"><div className="grid grid-cols-[110px_1fr] border-b border-slate-100 bg-slate-50 p-4 text-xs font-semibold text-slate-500"><span>TIME</span><span>{dayLabel(current)}</span></div>{(byDay[current]??[]).length===0&&<p className="p-6 text-sm text-slate-500">No classes on this day.</p>}{(byDay[current]??[]).map(e=><div key={e.id} className="grid grid-cols-[110px_1fr] border-b border-slate-100 p-4 last:border-0"><span className="text-sm text-slate-500">{e.all_day?'All day':fmtTime(e.start_at,tz)}</span>{eventCard(e)}</div>)}</Card>
      :<Card className="overflow-x-auto p-0"><div className="min-w-[720px]" role="grid" aria-label={`Week of ${weekStart}`}>
        <div className="grid border-b border-slate-100 bg-slate-50" style={{ gridTemplateColumns: `64px repeat(${days.length}, 1fr)` }}><span/>{days.map(d=><button key={d} onClick={()=>{setDay(d);setView('day')}} className={`p-3 text-left text-xs font-semibold hover:text-teal-700 ${d===today?'text-teal-700':'text-slate-500'}`}>{dayLabel(d).split(',')[0]}<span className="block text-sm text-slate-800">{dayLabel(d).split(', ')[1]}</span></button>)}</div>
        <div className="relative grid" style={{ gridTemplateColumns: `64px repeat(${days.length}, 1fr)`, height: (endHour - startHour) * HOUR_PX }}>
          <div className="relative">{Array.from({ length: endHour - startHour }, (_, i) => <span key={i} className="absolute right-2 -translate-y-1/2 text-[11px] text-slate-400" style={{ top: i * HOUR_PX }}>{i===0?'':`${((startHour+i+11)%12)+1} ${startHour+i<12?'AM':'PM'}`}</span>)}</div>
          {days.map(d=><div key={d} className={`relative border-l border-slate-100 ${d===today?'bg-teal-50/40':''}`} data-day={d}>
            {Array.from({ length: endHour - startHour }, (_, i) => <div key={i} className="absolute inset-x-0 border-t border-slate-100" style={{ top: i * HOUR_PX }}/>)}
            {layout(byDay[d] ?? [], tz).map(({ e, start, end, col, cols })=><button key={e.id} onClick={()=>setSelected(e)} data-testid="grid-event" data-start={fmtTime(e.start_at,tz)} className={`absolute overflow-hidden rounded-lg border-l-4 ${color(e).border} bg-white px-2 py-1 text-left shadow-sm ring-1 ring-slate-200 transition hover:bg-teal-50 focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-teal-200 ${selected?.id===e.id?'ring-2 ring-teal-300':''}`} style={{ top: (start - startHour * 60) * HOUR_PX / 60, height: (end - start) * HOUR_PX / 60 - 2, left: `calc(${(col / cols) * 100}% + 2px)`, width: `calc(${100 / cols}% - 4px)` }} aria-label={`${e.course_code ?? e.title}, ${fmtRange(e.start_at,e.end_at,tz)}${e.rescheduled?', moved':''}`}><b className="block truncate text-xs">{e.course_code ?? e.title}{e.rescheduled?' · moved':''}</b><span className="block truncate text-[11px] text-slate-500">{fmtRange(e.start_at,e.end_at,tz)}</span></button>)}
          </div>)}
        </div>
        {(data?.events ?? []).length===0&&<p className="border-t border-slate-100 p-4 text-sm text-slate-500">No {termData?.selected ?? ''} classes this week.</p>}
      </div></Card>}
      {selected&&<Card className="h-fit p-5" ><div className="flex items-start justify-between gap-3"><div><Badge tone="slate">Class meeting</Badge><h2 className="mt-3 text-lg font-semibold">{selected.course_code ?? selected.title}</h2></div><button onClick={()=>setSelected(null)} aria-label="Close details" className="text-slate-400 hover:text-slate-700">×</button></div><dl className="mt-4 space-y-3 text-sm">{[['Course',courses[selected.course_code ?? '']?.title ?? selected.title],['Section',courses[selected.course_code ?? '']?.section ?? '—'],['Term',selected.term ?? '—'],['When',`${fmtDay(selected.start_at,tz)} · ${fmtRange(selected.start_at,selected.end_at,tz)}`],['Where',selected.location ?? 'Not listed'],['Instructor',courses[selected.course_code ?? '']?.instructor_name ?? 'Not listed'],['Instructor contact',courses[selected.course_code ?? '']?.contact_status==='VERIFIED'?'Verified':courses[selected.course_code ?? '']?.contact_status==='STUDENT_CONFIRMED'?'Confirmed by you':courses[selected.course_code ?? '']?.contact_status==='NEEDS_REVIEW'?'Needs review':'Contact needed']].map(([k,v])=><div key={k}><dt className="text-xs font-semibold text-slate-500">{k}</dt><dd className="mt-0.5">{v}</dd></div>)}</dl>{selected.rescheduled&&<p className="mt-4 rounded-lg bg-amber-50 p-3 text-xs text-amber-800">This meeting was moved from its usual time in your calendar export.</p>}<div className="mt-4 flex items-center gap-2 text-xs text-slate-500">Source <SourceBadge mode={selected.source}/></div></Card>}
    </div></>}
  </>
}
