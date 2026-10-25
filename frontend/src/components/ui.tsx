import type React from 'react'

export function Icon({ name, size = 20 }: { name: string; size?: number }) {
  const paths: Record<string, React.ReactNode> = {
    Overview: <><rect x="3" y="3" width="7" height="7" rx="2"/><rect x="14" y="3" width="7" height="7" rx="2"/><rect x="3" y="14" width="7" height="7" rx="2"/><rect x="14" y="14" width="7" height="7" rx="2"/></>,
    'Find Care': <><path d="M12 21s7-4.4 7-11a7 7 0 0 0-14 0c0 6.6 7 11 7 11Z"/><path d="M12 7v6M9 10h6"/></>,
    'AI Health Assistant': <><path d="M21 15a4 4 0 0 1-4 4H8l-5 3V7a4 4 0 0 1 4-4h10a4 4 0 0 1 4 4Z"/><path d="M8 9h8M8 13h5"/></>,
    'My Schedule': <><rect x="3" y="5" width="18" height="16" rx="3"/><path d="M16 3v4M8 3v4M3 10h18"/></>,
    'Absence Center': <><path d="M6 2h9l5 5v15H6z"/><path d="M14 2v6h6M9 13h6M9 17h6"/></>,
    Settings: <><circle cx="12" cy="12" r="3"/><path d="M19.4 15a2 2 0 0 0 .4 2.2l.1.1-2.6 2.6-.1-.1a2 2 0 0 0-2.2-.4 2 2 0 0 0-1.2 1.8V21h-3.6v-.2A2 2 0 0 0 9 19a2 2 0 0 0-2.2.4l-.1.1-2.6-2.6.1-.1A2 2 0 0 0 4.6 15a2 2 0 0 0-1.8-1.2H3v-3.6h.2A2 2 0 0 0 5 9a2 2 0 0 0-.4-2.2l-.1-.1 2.6-2.6.1.1A2 2 0 0 0 9 4.6a2 2 0 0 0 1.2-1.8V3h3.6v.2A2 2 0 0 0 15 5a2 2 0 0 0 2.2-.4l.1-.1 2.6 2.6-.1.1a2 2 0 0 0-.4 2.2 2 2 0 0 0 1.8 1.2h.2v3.6h-.2A2 2 0 0 0 19.4 15Z"/></>,
    mic: <><rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v3M9 21h6"/></>,
    arrow: <path d="m9 18 6-6-6-6"/>,
    check: <path d="m5 12 4 4L19 6"/>,
    clock: <><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></>,
    plus: <path d="M12 5v14M5 12h14"/>,
    upload: <><path d="M12 16V4M7 9l5-5 5 5"/><path d="M4 16v3a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-3"/></>,
    alert: <><path d="M12 3 2 21h20Z"/><path d="M12 10v5M12 18h.01"/></>,
  }
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{paths[name]}</svg>
}

export function Button({ children, onClick, variant = 'primary', disabled = false, className = '', type = 'button', ...aria }: React.PropsWithChildren<{ onClick?: () => void; variant?: 'primary'|'secondary'|'ghost'|'danger'; disabled?: boolean; className?: string; type?: 'button'|'submit'; title?: string; 'aria-label'?: string; 'aria-expanded'?: boolean; 'aria-describedby'?: string }>) {
  const styles = { primary: 'bg-teal-700 text-white hover:bg-teal-800 shadow-sm', secondary: 'bg-white text-slate-700 border border-slate-200 hover:border-teal-300', ghost: 'text-slate-600 hover:bg-slate-100', danger: 'bg-rose-50 text-rose-700 border border-rose-200' }
  return <button type={type} disabled={disabled} onClick={onClick} {...aria} className={`inline-flex min-h-11 items-center justify-center gap-2 rounded-xl px-4 py-2 text-sm font-semibold transition focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-teal-200 disabled:cursor-not-allowed disabled:opacity-50 ${styles[variant]} ${className}`}>{children}</button>
}

export function Badge({ children, tone = 'teal' }: React.PropsWithChildren<{ tone?: 'teal'|'blue'|'amber'|'slate'|'rose' }>) {
  const style = { teal:'bg-teal-50 text-teal-700', blue:'bg-sky-50 text-sky-700', amber:'bg-amber-50 text-amber-700', slate:'bg-slate-100 text-slate-600', rose:'bg-rose-50 text-rose-700' }[tone]
  return <span className={`inline-flex rounded-full px-2.5 py-1 text-xs font-semibold ${style}`}>{children}</span>
}

export function Card({ children, className = '' }: React.PropsWithChildren<{ className?: string }>) {
  return <section className={`rounded-2xl border border-slate-200/80 bg-white shadow-[0_1px_2px_rgba(15,23,42,.03)] ${className}`}>{children}</section>
}

/** DEMO / UPLOADED / REAL marker. Text label, never color alone (App Flow §3). */
export function SourceBadge({ mode }: { mode: string }) {
  const label = mode === 'uploaded' ? 'UPLOADED' : mode === 'real' ? 'LIVE' : 'DEMO'
  return <Badge tone={mode === 'uploaded' ? 'blue' : mode === 'real' ? 'teal' : 'amber'}>{label}</Badge>
}

export function ErrorBanner({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const message = error instanceof Error ? error.message : 'Something went wrong.'
  return <div role="alert" className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-rose-200 bg-rose-50 p-4 text-sm text-rose-800"><span className="flex items-center gap-2"><Icon name="alert" size={18}/>{message}</span>{onRetry&&<Button variant="secondary" onClick={onRetry}>Try again</Button>}</div>
}

export function LoadingBlock({ label = 'Loading…', className = 'h-24' }: { label?: string; className?: string }) {
  return <div role="status" aria-live="polite" className={`animate-pulse rounded-2xl bg-slate-100 ${className}`}><span className="sr-only">{label}</span></div>
}
