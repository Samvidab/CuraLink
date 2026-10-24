import { useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../lib/api'
import type { TermsResponse } from '../lib/types'

export function useTerms() {
  return useQuery({ queryKey: ['calendar-terms'], queryFn: () => api.get<TermsResponse>('/calendar/terms') })
}

/** Semester tabs. Changing term refreshes every dependent view (calendar, courses, conflicts, absence matching). */
export default function TermSelector() {
  const qc = useQueryClient()
  const { data } = useTerms()
  if (!data || data.terms.length === 0) return null
  const select = async (term: string) => {
    qc.setQueryData(['calendar-terms'], await api.put<TermsResponse>('/calendar/selected-term', { term }))
    for (const key of ['calendar-events', 'student-dashboard', 'recommendations', 'impact-preview', 'schedule-review']) qc.invalidateQueries({ queryKey: [key] })
  }
  const recent = data.terms.slice(-3)
  const older = data.terms.slice(0, -3)
  return <div className="flex flex-wrap items-center gap-2" role="group" aria-label="Semester">
    <span className="text-xs font-semibold text-slate-500">Semester</span>
    <div role="tablist" className="flex flex-wrap rounded-xl border border-slate-200 bg-white p-1">{recent.map(t=><button key={t.term} role="tab" aria-selected={data.selected===t.term} onClick={()=>select(t.term)} className={`min-h-9 rounded-lg px-3 text-sm font-semibold ${data.selected===t.term?'bg-teal-700 text-white':'text-slate-600 hover:text-teal-800'}`}>{t.term}{t.term===data.default&&<span className="sr-only"> (current)</span>}</button>)}</div>
    {older.length>0&&<select aria-label="Other terms" className="input max-w-44" value={older.some(t=>t.term===data.selected)?data.selected!:''} onChange={e=>e.target.value&&select(e.target.value)}><option value="">Other terms</option>{older.map(t=><option key={t.term} value={t.term}>{t.term}</option>)}</select>}
  </div>
}
