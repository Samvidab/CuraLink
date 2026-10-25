import { Badge } from './ui'
import type { DeliveryReadiness } from '../lib/types'

const BLOCKER_TITLE: Record<string, string> = {
  STUDENT_CONSENT_MISSING: 'Student consent missing',
  NOT_SIGNED: 'Not signed yet',
  DOCUMENT_CHANGED_AFTER_SIGNING: 'Document version changed after signing',
  RECIPIENTS_CHANGED_AFTER_SIGNING: 'Recipients changed after signing',
  STUDENT_CONFIRMATION_MISSING: 'Student confirmation missing',
  RECIPIENT_EMAIL_UNVERIFIED: 'Recipient email unverified',
  RECIPIENT_NOT_PERMITTED_FOR_DEMO: 'Recipient not permitted for demo delivery',
  DELIVERY_FAILED: 'Delivery failed',
}

function Step({ ok, label, detail }: { ok: boolean | null; label: string; detail?: string }) {
  return <li className="flex items-start gap-2"><span aria-hidden="true" className={`mt-0.5 grid size-5 shrink-0 place-items-center rounded-full text-[11px] font-bold ${ok?'bg-teal-100 text-teal-800':ok===null?'bg-slate-100 text-slate-500':'bg-amber-100 text-amber-800'}`}>{ok?'✓':ok===null?'–':'!'}</span><span><b className="font-semibold">{label}</b>{detail&&<span className="block text-xs text-slate-600">{detail}</span>}</span></li>
}

/** The same persisted status, as the clinician and the student see it. Nothing here is inferred on the client. */
export function DeliveryStatus({ d, audience }: { d: DeliveryReadiness; audience: 'clinician' | 'student' }) {
  const blockedDemo = d.blockers.some(b => b.code === 'RECIPIENT_NOT_PERMITTED_FOR_DEMO')
  return <section aria-label="Delivery status" className="rounded-xl border border-slate-200 p-4 text-sm">
    <ul className="space-y-2">
      <Step ok={d.clinician_signed} label={d.clinician_signed?`Clinician approved and signed (version ${d.signed_version})`:'Clinician approval and signature pending'}/>
      <Step ok={d.student_consent} label={d.student_consent?'Student consent confirmed':'Student consent missing'}/>
      {d.recipients.length>0&&<Step ok={d.contacts_confirmed} label={d.contacts_confirmed?'Instructor contacts confirmed':'Instructor contacts need attention'}/>}
      <Step ok={d.delivered?true:d.ready?true:blockedDemo?false:d.clinician_signed&&d.student_consent&&d.contacts_confirmed?false:null} label={d.delivered?'Simulated delivery completed':d.ready?`Demo delivery ready${d.uses_isolated_test_inbox?' — to the isolated test inbox':''}`:'Demo delivery blocked'}/>
    </ul>
    {d.recipients.length>0&&<ul className="mt-3 divide-y divide-slate-100 rounded-lg border border-slate-100" aria-label="Instructor recipients">{d.recipients.map(r=><li key={r.course_code} className="flex flex-wrap items-center justify-between gap-2 p-2 text-xs"><span><b>{r.course_code}</b>{r.instructor_name?` · ${r.instructor_name}`:''} · {r.email ?? 'no email'}</span><span className="flex flex-wrap gap-1.5"><Badge tone={['VERIFIED','CONFIRMED_BY_STUDENT'].includes(r.contact_state)?'teal':'amber'}>{r.contact_label}</Badge><Badge tone={r.demo_route==='NOT_PERMITTED_FOR_DEMO'?'amber':'slate'}>{r.demo_route==='ISOLATED_TEST_INBOX'?'Simulated — real address not contacted':r.route_label}</Badge></span></li>)}</ul>}
    {d.blockers.length>0&&<ul className="mt-3 space-y-1.5" aria-label="Why delivery is blocked">{d.blockers.map(b=><li key={b.code} role="status" className="rounded-lg bg-amber-50 p-2 text-xs text-amber-900"><b>{BLOCKER_TITLE[b.code] ?? b.code}:</b> {b.message}{audience==='student'&&b.code==='STUDENT_CONFIRMATION_MISSING'?' Use “Confirm instructor contacts” below.':''}</li>)}</ul>}
    {d.uses_isolated_test_inbox&&<p className="mt-3 text-xs text-slate-500">Demo safety: real-looking instructor addresses (for example from UniTime) are never contacted. Approved copies go to CuraLink’s isolated test inbox instead; the signed document is not changed.</p>}
  </section>
}
