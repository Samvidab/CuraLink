# CuraLink

**Where care meets coordination.** A student-first healthcare *administrative* coordination prototype for Cal Hacks 13.0.

A student describes their situation in their own words (text or voice), imports their UniTime calendar, books a clinic slot that fits around classes, and shares a consented intake packet with their assigned clinician. The clinician — and only the clinician — decides whether to document an absence, for which dates, signs a specific document version, and authorizes minimal-disclosure notices to instructors.

> CuraLink is **not** an AI doctor. It never diagnoses, never ranks medical urgency, never signs anything on its own, and never claims an absence is excused. Every person, course, clinic, address and appointment in this repository is **fictional**.

## Quick start

Requirements: [uv](https://docs.astral.sh/uv/) (Python 3.11), Node.js 22+.

```bash
cp .env.example .env      # optional: add ANTHROPIC_API_KEY / CARTESIA_API_KEY
./run_demo.sh             # API on :8000, web app on :8443, demo data reset
```

Open http://localhost:8443.

| Persona | How to sign in |
|---|---|
| Student — Sam Lee | “I'm a student” (demo persona, no password) |
| Clinician — Dr. Avery Rivera | “I'm a healthcare professional” → **Use demo clinician account** (`dr.rivera@clinic.example.com` / `curalink-demo`) |
| Second clinician — Dr. Morgan Hale | `dr.hale@clinic.example.com` / `curalink-demo` (to show assignment scoping) |
| Unverified clinician | `pending.clinician@clinic.example.com` (is refused) |

Reset all demo data any time: `curl -X POST -H 'X-CuraLink-Client: web' http://127.0.0.1:8000/api/v1/demo/reset`.

## What is real vs. simulated

| Capability | Status |
|---|---|
| Role-based access (student / clinician), server-side sessions, cross-role 403, per-encounter assignment scoping | **Functional** |
| UniTime `.ics` upload: recurrence expansion, EXDATE, moved meetings (RECURRENCE-ID), DST, timezone detection, validation | **Functional** (sample calendar is fictional) |
| Slot ranking: hard constraints (class overlap, travel buffer, personal blocks), deterministic scoring with reason codes, stale-slot 409 + replan, idempotent confirm | **Functional** over a **synthetic** clinic inventory (`DEMO` badge everywhere) |
| Appointment booking | **Simulated** — “Demo appointment — not booked with a real clinic.” |
| Safety screen (emergency / crisis language → 911 / 988 guidance, routine flow paused) | **Functional**, deterministic, **not clinically validated** |
| Assistant | **Claude** (`claude-opus-5-5`, server-side, narrow read-only tools) when `ANTHROPIC_API_KEY` is set; otherwise a **scripted** rule-based fallback. Both share the same safety screen, output guard and never-invent field rules |
| Voice | **Cartesia** streaming STT/TTS through the backend (key never reaches the browser) with barge-in and stale-audio rejection when `CARTESIA_API_KEY` is set; otherwise the browser's built-in speech APIs; otherwise text |
| Structured intake with provenance, student confirmation, consented handoff, withdrawal | **Functional** |
| Clinician multi-day decision, class-impact engine, immutable PDF versions (ReportLab, SHA-256), per-version sign with re-authentication + single-use nonce | **Functional**; the signature image is a **generated, watermarked DEMO sample** |
| Instructor notices | **Functional** outbox with consent / signature / verified-recipient gates and idempotency; delivered **only to a local test inbox** (`/demo/inbox`), never by email |
| Photo observations, Notability import, live UniTime subscription, real clinic/email integrations | **Not implemented** (P1/P2) |

## Architecture

```
frontend/  React 19 + Vite 8 + Tailwind v4 (Figma Make design), React Router, React Query
backend/   FastAPI + Pydantic v2 + SQLAlchemy (SQLite), demo mode only
  app/routers/    auth, student, scheduling, intake, voice, absence, clinician, system
  app/services/   ics_import, scheduling, absence_mapper, safety, intake_fields,
                  intake_service, llm_gateway (only module that calls a model),
                  cartesia + voice_session, pdf_builder, absence_service (outbox), audit
sample_data/  fictional ICS, course catalog, personas, 20 synthetic clinic slots
docs/         PRD, TRD, App Flow, Implementation Plan (v1.2 amendments are authoritative)
```

Key rules enforced on the server, not in prompts:
- The client never sets its own role; every route resolves the actor from an HttpOnly session cookie. State-changing calls require an `X-CuraLink-Client` header (CSRF defence); the voice WebSocket checks `Origin`.
- The model can only read calendar/slots and *propose* unconfirmed intake fields. It has no booking, sending, signing or approval tools.
- Sending requires: student disclosure consent (re-checked at send time) + latest **signed** version + matching hash + unchanged approved recipients + verified, allowlisted addresses. Any edit creates a new unsigned version.
- Audit events never contain symptoms, transcripts or document bodies.

## Tests

```bash
cd backend && uv run pytest              # 83 tests: ICS, ranking, RBAC, safety, voice barge-in, signing/outbox gates
cd frontend && npx tsc --noEmit && npx playwright test   # 8 E2E flows (needs both servers running; uses local Chrome)
```

Acceptance tests from the Implementation Plan covered in code: AT-01–AT-14, AT-21 (simulated delayed TTS), AT-22–AT-29.

## Demo script (~3 min)

1. **Student** → “I'm a student” → Continue → *Use fictional sample calendar* (note the timezone, the moved STAT 350 meeting, and the course with no instructor contact).
2. **Talk to CuraLink** → type or speak “I've had a sore throat and a fever of 100.8 F since yesterday”. Watch “What CuraLink knows” fill in with provenance; confirm each item. Try “I have chest pain” to see the safety stop.
3. **Appointments** → ranked demo slots with reasons; open “Why some times aren't shown”. Confirm the 2:30 PM slot via the explicit demo-booking dialog.
4. Back in **Talk to CuraLink** → *Review what will be sent to your clinician* → share selected fields.
5. **My Cases** → request review for Wed–Fri → fix the missing PHIL 208 contact → consent → submit.
6. **Clinician** (second browser) → Signature Settings → enroll demo sample → Absence Cases → Sam Lee → read the shared intake → narrow the dates → *Approve date range* → *Generate document* → *Approve & sign this version* (re-enter password) → *Send authorized copies*.
7. Open the **test inbox**: minimal-disclosure notices, no symptoms. Student's **My Cases** shows “Delivered to test inbox … your university decides”.

## Known limitations

- SQLite single-process demo; not for real patient data. No HIPAA compliance or legally valid e-signature is claimed.
- Real Claude / Cartesia calls are exercised only when keys are configured; automated tests stub them. Cartesia endpoints were verified against docs.cartesia.ai on 2026-10-24 and are configurable in `.env`.
- The safety screen is keyword-based and deliberately over-triggers; clinician-reviewed criteria are required before any real use.
- Headless Chrome doesn't render the embedded PDF preview; regular browsers do (mobile shows an “Open preview” link).
