# CuraLink

**Where care meets coordination.** A student-first healthcare *administrative* coordination prototype for Cal Hacks 13.0.

A student describes their situation in their own words (text or voice), imports their UniTime calendar, books a clinic slot that fits around classes, and shares a consented intake packet with their assigned clinician. The clinician — and only the clinician — decides whether to document an absence, for which dates, signs a specific document version, and authorizes minimal-disclosure notices to instructors.

> CuraLink is **not** an AI doctor. It never diagnoses, never ranks medical urgency, never signs anything on its own, and never claims an absence is excused. Every person, course, clinic, address and appointment in this repository is **fictional**.

## Quick start

Requirements: [uv](https://docs.astral.sh/uv/) (Python 3.11), Node.js 22+.

```bash
cp .env.example .env      # optional: add ANTHROPIC_API_KEY / CARTESIA_API_KEY
./run_demo.sh             # start, or reuse already-running healthy servers
./run_demo.sh status      # what's running
./run_demo.sh stop        # stops only what run_demo.sh started
./run_demo.sh reset       # wipe fictional demo data (asks first)
```

Open **http://localhost:8443**. Ports are configurable (`API_PORT=8001 WEB_PORT=8444 ./run_demo.sh`). The launcher never kills processes it didn't start and never resets data unless you run `reset` and confirm. Logs: `.run/api.log`, `.run/web.log`.

| Persona | How to sign in |
|---|---|
| Student — Sam Lee | “I'm a student” → **Use demo student account** (`sam.lee@students.example.com` / `curalink-demo`) |
| Clinician — Dr. Avery Rivera | “I'm a healthcare professional” → **Use demo clinician account** (`dr.rivera@clinic.example.com` / `curalink-demo`) |
| Second clinician — Dr. Morgan Hale | `dr.hale@clinic.example.com` / `curalink-demo` (to show assignment scoping) |
| New student | “I'm a student” → **Create a student account**. You're asked for your first, last and optional preferred name once, then greeted by that name. |
| Unverified clinician | `pending.clinician@clinic.example.com` (is refused) |

Nobody is signed in automatically. `/` is always the welcome page; if this browser still has a valid session, it offers **Continue as …** or **Sign out**. Session cookies end when the browser closes, and every sign-in replaces the browser's previous session on the server.

Clinician sign-up (**Request a clinician account**) only creates an *unverified* account. Access requires a server-side step: `cd backend && uv run python -m app.admin verify-clinician <email>`.

Reset all demo data any time: `curl -X POST -H 'X-CuraLink-Client: web' http://127.0.0.1:8000/api/v1/demo/reset`.

## What is real vs. simulated

| Capability | Status |
|---|---|
| Role-based access (student / clinician), server-side sessions, cross-role 403, per-encounter assignment scoping | **Functional** |
| UniTime `.ics` **file import** (no live sync) with **semester selection** (terms inferred from each class's meeting dates; other terms kept but hidden), positioned week grid, *Review imported schedule* page; recurrence expansion, EXDATE, moved meetings (RECURRENCE-ID), cancelled meetings, DST, timezone detection, validation; instructor name/email read from UniTime's ATTENDEE/ORGANIZER fields; course titles from SUMMARY/DESCRIPTION; editable instructors in Settings | **Functional**, tested against a fixture that follows UniTime's export code (`sample_data/unitime_format_sample.ics`) — **not yet tested with a real Purdue export** |
| Slot ranking: hard constraints (class overlap, travel buffer, personal blocks), deterministic scoring with reason codes, stale-slot 409 + replan, idempotent confirm | **Functional** over a **synthetic** clinic inventory (`DEMO` badge everywhere) |
| Clinician-aware scheduling: choose a clinician and time (All clinicians / Specific clinician / Earliest available). Times come from fictional weekly hours, exceptions and bookings, minus selected-semester classes. Re-checked at confirmation, no double booking. The assistant answers “Which doctors are available?” and “Can I see Dr. Rivera?” using the same lookups. | **Functional** on fictional availability data |
| Appointment booking | **Simulated** — “Demo appointment — not booked with a real clinic.” The booked clinician (only) sees it in their portal |
| Safety screen (emergency / crisis language → 911 / 988 guidance, routine flow paused) | **Functional**, deterministic, **not clinically validated** |
| Assistant | **Claude** (`claude-opus-5-5`, server-side, narrow read-only tools) when `ANTHROPIC_API_KEY` is set; otherwise a **scripted** rule-based fallback. Both share the same safety screen, output guard and never-invent field rules |
| Voice | **Cartesia** streaming STT/TTS through the backend (key never reaches the browser) with barge-in and stale-audio rejection when `CARTESIA_API_KEY` is set; otherwise the browser's built-in speech APIs; otherwise text |
| Structured intake with provenance, student confirmation, consented handoff, withdrawal | **Functional** |
| Clinician **Medical Evaluation & Absence Determination**: clinician-only exam findings; *no certificate* / *approve period (dates chosen manually, 1+ days)* / *defer*; class schedule used only after the decision | **Functional**; CuraLink never suggests a duration |
| Medical certificate (all required fields, configurable wording/branding, demo verification ID), immutable PDF versions (SHA-256), per-version sign with re-authentication + single-use nonce | **Functional**; signatures are hand-drawn (encrypted at rest) or a generated sample, printed as **“SIMULATED SIGNATURE — DEMO, NOT VALID”** |
| Instructor notices | **Functional** outbox with consent / signature / verified-recipient gates and idempotency; delivered **only to a local test inbox** (`/demo/inbox`), never by email |
| Photo observations: consent-gated upload (**JPG, PNG, WebP, iPhone HEIC/HEIF**, up to 12 MB; type checked from file bytes; HEIC converted server-side; orientation fixed; EXIF/GPS stripped), tentative allowlisted observations with uncertainty, opt-in sharing to the clinician only | **Functional**. Observer = Claude vision when a key is set, otherwise basic colour analysis (labelled “not a medical model”). Demo images are synthetic |
| Clinician accept / correct / reject of shared fields (original preserved) | **Functional** |
| Notability import, live UniTime subscription, real clinic/email integrations, Factory/Moss/Fetch.ai | **Not implemented** |

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

### Intake, appointments and pre-visit summaries

```
User (student) ─< IntakeSession (one per conversation; created_at = start, ended_at, chief concern, purpose, absence request)
                    ├─< IntakeField (student-confirmed values, provenance)      ├─< Attachment (photos stay with their session)
                    └─< HandoffPacket = pre-visit summary, versioned per session (SHARED / SUPERSEDED / WITHDRAWN)
                             └── encounter_id ──> Encounter (the case) ──> Appointment (clinician, type, time, purpose,
                                  (empty until booked)        │                absence_requested, intake_session_id)
                                                              └── clinician_id ─> User (clinician) — access follows this
```

- **Contextual intake:** the dialog manager (`services/dialog.py`) decides the next step once per turn, before Claude is called. It emits structured actions: `OFFER_TEMPERATURE_INPUT`, `OFFER_PHOTO_UPLOAD`, `ASK_FOLLOW_UP`, `REVIEW_INTAKE` and `FIND_CARE` (scheduling). Claude is told what is on screen. The frontend renders cards from these actions and never parses sentences, and the scripted fallback produces the same actions.
- **Summaries:** the student reviews and selects confirmed details and photos, then authorizes. The snapshot becomes version N of that conversation, and older versions are kept as SUPERSEDED. A summary approved before booking is attached when the student books; one approved after booking goes to the appointment booked from that conversation.
- **Clinician view:** clinicians see summaries only through encounters assigned to them. The patient page shows the latest approved summary, plus *AI-Assisted Pre-Visit History* grouped by each conversation's local start date, newest first, never merged. Withdrawal hides the content on the next access and is audited.
- **Database upgrade:** existing demo databases are upgraded in place on startup and nothing is reset.
  - New columns are added as nullable.
  - `handoff_packets.encounter_id` becomes nullable through a one-time table rebuild. The database file is backed up first as `backend/curalink_demo.backup-<timestamp>.db`.
  - Missing demo clinician hours are added (also available as `uv run python -m app.admin seed-availability`).

## Manual configuration

Everything the team must supply by hand is in **[docs/MANUAL_SETUP_CHECKLIST.md](docs/MANUAL_SETUP_CHECKLIST.md)**; every `CURALINK_CONFIG` / `TODO(CURALINK-MANUAL)` marker is indexed in **[docs/DEVELOPER_CONFIGURATION.md](docs/DEVELOPER_CONFIGURATION.md)**.

## Integration status (be precise when presenting)

- **Assistant without Claude:** a stateful dialog manager (`backend/app/services/dialog.py`) — contextual questions asked once, declines remembered, next steps offered. With Claude it supplies state/context and anti-repeat guards. If Anthropic rejects the key, `/health` reports `"llm":"error"` and the UI says “Claude key rejected · scripted fallback”.
- **Claude:** code path uses the official `anthropic` SDK (server-only key, `claude-opus-5-5`, strict tools, `fallbacks: "default"`). A contract test runs the real SDK against a local fake API to check the request shape and tool loop. **No live API call has been made from this repo yet** — add a key and run the check below before claiming it live.
- **Cartesia:** raw WebSocket contract verified against docs.cartesia.ai (STT `ink-whisper`, TTS `sonic-3.6`, `cartesia_version=2026-08-14`, `X-API-Key` header). Barge-in, stale-chunk dropping, history carry-over and latency reporting are tested with simulated streams. **No live Cartesia session has been run yet.** Without a key the UI says “Browser speech · fallback” — that is the browser's own speech engine, never Cartesia.

### Live check: Claude
1. Put `ANTHROPIC_API_KEY=...` in `.env`, then `./run_demo.sh stop && ./run_demo.sh` (keys are read at API start).
2. `curl -s localhost:8000/api/v1/health` → `"llm":"live"`.
3. In **Talk to CuraLink** the badge reads “Claude · live”. Say “I've had a sore throat since Monday and want an appointment”. Expect tool chips (“Comparing eligible slots”, “Opening on your screen”), a **Find appointment options** card, and fields in “What CuraLink knows” marked unconfirmed. If the badge says “Scripted assistant” or activity shows “Assistant used scripted fallback”, the live call failed — check `.run/api.log`.

### Live check: Cartesia voice
1. Put `CARTESIA_API_KEY=...` (optional `CARTESIA_VOICE_ID`) in `.env`; restart. `/api/v1/health` → `"voice":"live"`; the voice card reads “Cartesia · live”.
2. Use Chrome on `http://localhost:8443` (localhost is a secure context, so the mic works). Allow the microphone when asked; if blocked, click the lock icon → Microphone → Allow, then reload.
3. **Latency:** after each reply the card shows “first audio N ms after you stopped”. Under ~1.5 s feels conversational.
4. **Interruption:** while CuraLink is speaking, start talking. Playback should stop immediately (“interrupt stopped playback in N ms”) and the old answer must not resume.
5. **Turn-taking:** pause mid-sentence for under ~1.3 s — the turn should not end. Use headphones to avoid the assistant hearing itself.
6. **Context:** type a message, then switch to voice and refer back to it (“what I said about my throat”) — history carries over both ways.

## Tests

```bash
cd backend && uv run pytest              # 113 tests: ICS/UniTime, ranking, RBAC, safety, Claude SDK contract, voice, vision, clinician workflow, signing/outbox gates, config markers
cd frontend && npx tsc --noEmit -p .     # typecheck
./run_demo.sh e2e                        # 15 Playwright flows on an ISOLATED stack (:8011/:8454, own DB) — never touches your demo data
```

Acceptance tests from the Implementation Plan covered in code: AT-01–AT-14, AT-21 (simulated delayed TTS), AT-22–AT-29.

## Demo script (~3 min)

1. **Student** → “I'm a student” → *Use demo student account* → Sign in (Sam's profile is complete, so this opens the dashboard) → *Settings → Import calendar* → *Use fictional sample calendar* (note the timezone, the moved STAT 350 meeting, and the course with no instructor contact).
2. **Talk to CuraLink** → *Start new conversation*.
   - Say “I have a rash on my arm”: an optional photo card appears. Add the synthetic HEIC from `sample_data/demo_images/`, confirm the details, then *Review your pre-visit summary* → tick the photo → authorize → submit.
   - *Start new conversation* again and say “I've had a fever and headache since yesterday. I missed class and want to discuss an absence note.” A temperature card appears; enter 100.8 °F. Confirm, review, submit.
   - Try “I have chest pain” to see the safety stop.
3. Ask “Which doctors are available?”, then “Can I see Dr. Rivera?”, pick a time and confirm. The *Appointments* page offers the same clinician cards.
4. As **Dr. Rivera**, open Sam Lee. The latest summary shows the temperature and the absence request (*requested, not medically approved*), and *AI-Assisted Pre-Visit History* lists Session 1 and Session 2 separately. As Dr. Hale, Sam isn't visible.
5. **My Cases** → request review for Wed–Fri → fix the missing PHIL 208 contact → consent → submit.
6. **Clinician** (second browser) → Signature Settings → **draw a signature** → Save → Absence Cases → Sam Lee → review the shared intake (accept/correct) → enter examination findings → *Approve an absence period* → type the dates → *Save absence period* (affected classes appear only now) → *Generate document* → *Approve & sign this version* (re-enter password) → *Send authorized copies*.
7. Open the **test inbox**: minimal-disclosure notices, no symptoms. Student's **My Cases** shows “Delivered to test inbox … your university decides”.

## Known limitations

- SQLite single-process demo; not for real patient data. No HIPAA compliance or legally valid e-signature is claimed.
- Real Claude / Cartesia calls are exercised only when keys are configured; automated tests stub them. Cartesia endpoints were verified against docs.cartesia.ai on 2026-10-24 and are configurable in `.env`.
- The safety screen is keyword-based and deliberately over-triggers; clinician-reviewed criteria are required before any real use.
- Notability import is not implemented; nothing here assumes access to Notability accounts.
- Time-savings figures shown in My Cases are measured per case from the audit log; no comparative baseline has been measured yet.
- Headless Chrome doesn't render the embedded PDF preview; regular browsers do (mobile shows an “Open preview” link).
