import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { Badge, Card, ErrorBanner, LoadingBlock, SourceBadge } from '../../components/ui'
import TermSelector from '../../components/TermSelector'
import { api } from '../../lib/api'
import { fmtYmd } from '../../lib/format'
import type { CalendarSummary, Course, TermInfo } from '../../lib/types'

type ReviewCourse = Course & { meetings: number; first_meeting: string | null; last_meeting: string | null; pattern: [string, number][]; locations: string[]; moved_meetings: number }
type Review = { courses: ReviewCourse[]; calendar: CalendarSummary | null; timezone: string; terms: TermInfo[]; selected: string | null }
const SOURCE: Record<string, string> = { unitime_ics: 'UniTime file', demo_catalog: 'Fictional demo catalog', university_directory: 'University directory', manual: 'Entered by you', ics: 'Not in calendar data' }
const short = (d: string | null) => (d ? fmtYmd(d, { month: 'short', day: 'numeric', year: 'numeric' }) : '—')

/** Everything detected in the imported file, grouped by semester. Nothing is hidden or deleted here. */
export default function ScheduleReview() {
  const { data, error, isLoading, refetch } = useQuery({ queryKey: ['schedule-review'], queryFn: () => api.get<Review>('/calendar/review') })
  const byTerm: Record<string, ReviewCourse[]> = {}
  for (const c of data?.courses ?? []) (byTerm[c.term ?? 'No term'] ??= []).push(c)
  return <><Link to="/student/calendar" className="text-sm font-semibold text-teal-700">← Back to calendar</Link><h1 className="mt-3 text-3xl font-semibold">Review imported schedule</h1>
    <p className="mt-2 max-w-3xl text-slate-500">Every course CuraLink found in your calendar file, by semester. Semesters are inferred from each class's meeting dates (not from course codes). Classes from other semesters are kept here but don’t appear in your current calendar.</p>
    {data?.calendar&&<p className="mt-3 flex flex-wrap items-center gap-2 text-sm text-slate-600"><SourceBadge mode={data.calendar.source_mode}/>{data.calendar.filename} · {data.calendar.events_imported} meetings · {data.timezone}</p>}
    <div className="mt-5"><TermSelector/></div>
    {error&&<div className="mt-5"><ErrorBanner error={error} onRetry={()=>refetch()}/></div>}{isLoading&&<LoadingBlock className="mt-5 h-40"/>}
    {data&&data.courses.length===0&&<Card className="mt-6 p-6 text-sm text-slate-500">No courses were detected. <Link to="/student/import" className="font-semibold text-teal-700 underline">Import a calendar</Link></Card>}
    {Object.entries(byTerm).map(([term, list])=><section key={term} className="mt-7" aria-labelledby={`t-${term}`}><div className="flex items-center gap-2"><h2 id={`t-${term}`} className="text-xl font-semibold">{term}</h2>{term===data?.selected&&<Badge>Shown in calendar</Badge>}</div>
      <div className="mt-3 grid gap-3 lg:grid-cols-2">{list.map(c=><Card key={c.id} className="p-5 text-sm"><div className="flex flex-wrap items-start justify-between gap-2"><div><b>{c.code}{c.section?` · section ${c.section}`:''}</b><p className="text-slate-500">{c.title ?? 'Untitled course'}</p></div><Badge tone={c.contact_status==='VERIFIED'||c.contact_status==='STUDENT_CONFIRMED'?'teal':'amber'}>{c.instructor_name ?? 'Instructor not listed'}</Badge></div>
        <dl className="mt-3 grid grid-cols-2 gap-2"><div><dt className="text-xs font-semibold text-slate-500">Meetings</dt><dd>{c.meetings} · {short(c.first_meeting)} – {short(c.last_meeting)}</dd></div><div><dt className="text-xs font-semibold text-slate-500">Instructor source</dt><dd>{SOURCE[c.provenance] ?? c.provenance}</dd></div><div className="col-span-2"><dt className="text-xs font-semibold text-slate-500">Usual times</dt><dd>{c.pattern.map(([p,n])=>`${p} (${n})`).join(' · ') || '—'}</dd></div>{c.locations.length>0&&<div className="col-span-2"><dt className="text-xs font-semibold text-slate-500">Locations</dt><dd>{c.locations.join(', ')}</dd></div>}</dl>
        {c.moved_meetings>0&&<p className="mt-2 text-xs text-amber-700">{c.moved_meetings} meeting{c.moved_meetings>1?'s':''} moved from the usual time.</p>}</Card>)}</div></section>)}
    {data?.calendar?.warnings.length?<p className="mt-6 rounded-xl bg-amber-50 p-3 text-sm text-amber-900"><b>Import notes:</b> {data.calendar.warnings.join(' ')}</p>:null}
    <p className="mt-6 text-sm text-slate-500">Instructor wrong or missing? Fix it in <Link to="/student/settings" className="font-semibold text-teal-700 underline">Settings → Courses & instructors</Link>.</p></>
}
