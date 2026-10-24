// Tailwind only generates classes it can see literally in source, so course
// accent colors (sent by the API as "bg-sky-500" etc.) map to full class strings here.
const COLORS: Record<string, { bg: string; border: string }> = {
  'bg-sky-500': { bg: 'bg-sky-500', border: 'border-sky-500' },
  'bg-teal-500': { bg: 'bg-teal-500', border: 'border-teal-500' },
  'bg-violet-500': { bg: 'bg-violet-500', border: 'border-violet-500' },
  'bg-amber-500': { bg: 'bg-amber-500', border: 'border-amber-500' },
  'bg-rose-500': { bg: 'bg-rose-500', border: 'border-rose-500' },
  'bg-indigo-500': { bg: 'bg-indigo-500', border: 'border-indigo-500' },
}
const FALLBACK = { bg: 'bg-slate-400', border: 'border-slate-400' }

export const courseColor = (token: string | null | undefined) => (token && COLORS[token]) || FALLBACK
