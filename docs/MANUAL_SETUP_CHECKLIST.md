# CuraLink — Manual Setup Checklist

What the team has to supply by hand, and how to check it works. Everything else runs out of the box with **fictional** demo data.

- Put secrets in the repo-root **`.env`** (copy `.env.example`; `.env` is git-ignored). Restart the API after editing: `./run_demo.sh stop && ./run_demo.sh`.
- Search the code for `CURALINK_CONFIG:` (where a setting lives) and `TODO(CURALINK-MANUAL):` (what is still missing). Full index: [DEVELOPER_CONFIGURATION.md](DEVELOPER_CONFIGURATION.md).
- No setting can switch off clinician approval, student consent, signature authorization or recipient verification. Those checks are in code, not configuration.

Legend — **Needed for:** 🟢 hackathon live demo · 🔵 production only.

---

## A. Required for the live hackathon demo

### A1. Anthropic API key — `ANTHROPIC_API_KEY` 🟢
1. **Why:** powers Claude for conversational intake (structured, never-invent fields), appointment-option requests and, optionally, photo observations.
2. **Where to get it:** https://console.anthropic.com/ → Settings → API Keys → Create key.
3. **Where it goes:** `.env` → `ANTHROPIC_API_KEY=...` (read in `backend/app/config.py`, marker `CURALINK_CONFIG: ANTHROPIC_API_KEY`). Optional: `ANTHROPIC_MODEL` (default `claude-opus-5-5`), `ANTHROPIC_EFFORT` (default `low`).
4. **Steps:** create key → paste into `.env` → restart API.
5. **Fallback if missing:** a scripted, rule-based assistant. The UI badge says **“Scripted assistant (demo)”**.
6. **How to test:** `curl -s localhost:8000/api/v1/health` shows `"llm":"live"`. In *Talk to CuraLink* the badge reads **“Claude · live”**, and the message “sore throat since Monday, I need an appointment” shows tool chips and a *Find appointment options* card. If activity shows “Assistant used scripted fallback”, check `.run/8000/api.log`.

### A2. Cartesia API key — `CARTESIA_API_KEY` 🟢
1. **Why:** real-time, interruptible voice (speech-to-text + text-to-speech) through the backend.
2. **Where to get it:** Cartesia dashboard (https://play.cartesia.ai/) → API Keys.
3. **Where it goes:** `.env` → `CARTESIA_API_KEY=...` (marker `CURALINK_CONFIG: CARTESIA_API_KEY` in `backend/app/config.py`; used only by `backend/app/services/cartesia.py`).
4. **Steps:** paste key → restart API → open http://localhost:8443 in Chrome → allow the microphone.
5. **Fallback if missing:** the browser's own speech engine, labelled **“Browser speech · fallback”** (never called Cartesia); if the browser lacks it, text only.
6. **How to test:** `/api/v1/health` shows `"voice":"live"`; the voice card reads **“Cartesia · live”**. Then:
   - Speak, and watch “first audio N ms after you stopped”.
   - Talk over a reply: playback stops and the old reply doesn't resume.
   - Pause briefly mid-sentence: the turn shouldn't end.

### A3. Cartesia voice — `CARTESIA_VOICE_ID` 🟢
1. **Why:** chooses CuraLink's spoken voice.
2. **Where to get it:** Cartesia playground → Voices → pick a calm, clear voice → copy its ID.
3. **Where it goes:** `.env` → `CARTESIA_VOICE_ID=...` (marker `CURALINK_CONFIG: CARTESIA_VOICE_ID`).
4. **Steps:** set it → restart → start a voice conversation.
5. **Fallback if missing:** the voice ID from Cartesia's documentation example.
6. **How to test:** listen; if TTS fails, the UI shows “Voice playback failed; the reply is shown as text.”

### A4. Vision model — `VISION_MODEL` (optional) 🟢
1. **Why:** non-diagnostic photo observations with Claude vision.
2. **Where it goes:** `.env` → `VISION_MODEL=...` (defaults to `ANTHROPIC_MODEL`; marker `CURALINK_CONFIG: VISION_MODEL`). It needs A1.
3. **Fallback if missing:** deterministic colour/quality analysis, labelled “basic colour analysis (not a medical model)”.
4. **How to test:** upload the synthetic demo image in *Add details → Add a photo*. The observer label reads “Claude vision”.

No other credentials are needed for the hackathon. Clinic availability, email delivery and signatures are simulated and labelled.

---

## B. University information

### B1. Academic term — `ACADEMIC_TERM_ID`, `ACADEMIC_TERM_START`, `ACADEMIC_TERM_END` 🟢/🔵
- **Why:** identifies the term for instructor lookups. Calendar expansion already uses the dates in the uploaded `.ics`.
- **Where:** `.env`; marker `CURALINK_CONFIG: ACADEMIC_TERM` in `backend/app/config.py`. Time zone: `DEMO_TIMEZONE` (default `America/Indiana/Indianapolis`).
- **Fallback:** `FALL-2026-DEMO`, with no fixed term dates. `TODO(CURALINK-MANUAL)`: official term dates for production.
- **Test:** upload a UniTime export; the course list shows the right term's meetings.

### B2. Authorized instructor directory — `UNIVERSITY_DIRECTORY_URL` 🔵
- **Why:** fills in instructor contacts that the student's UniTime export doesn't include.
- **Where to get it:** only from the university, as a written authorization plus API details (e.g. a registrar or IT data connector). Don't scrape pages behind a login.
- **Where:** `.env`; connector contract in `backend/app/services/instructor_directory.py` (marker `CURALINK_CONFIG: UNIVERSITY_DIRECTORY`).
- **Fallback:** disabled. Contacts come from the `.ics` file, the catalog, or manual confirmation.
- **Test:** `uv run pytest -k directory` (runs a stub connector). With a real connector, import a calendar and check that contacts show “Verified” only when the connector says `authoritative: true`.

### B3. Course catalog lookup — `COURSE_CATALOG_SOURCE` 🟢/🔵
- **Why:** course titles and instructor contacts keyed by course code (and section/term in production).
- **Where:** `.env`; `backend/app/services/instructor_directory.py::from_catalog` (marker `CURALINK_CONFIG: COURSE_CATALOG_SOURCE`). Demo data: `sample_data/demo_courses.json` (fictional).
- **Fallback:** `demo_catalog`. `TODO(CURALINK-MANUAL)`: an authorized Purdue catalog export/API.
- **Test:** import the sample calendar; CS 240 shows “Fictional demo catalog · Verified”.

### B4. Manual confirmation of missing instructor contacts 🟢
- **Why:** CuraLink never guesses an address; missing ones need a person to confirm them.
- **Where:** marker `CURALINK_CONFIG: INSTRUCTOR_EMAIL_FALLBACK` (`backend/app/routers/absence.py`, `PATCH /api/v1/courses/{id}/contact`). UI: **Settings → Courses & instructors** and **My Cases → Contact needed**.
- **Fallback:** the course is marked “Contact needed” and is never sent to.
- **Test:** fix PHIL 208 in Settings; it becomes “Confirmed by you”. Delivery still only goes to `TEST_EMAIL_ALLOWLIST` domains.

---

## C. Demo clinic information (fictional)

### C1. Clinic name and address — `CLINIC_NAME`, `CLINIC_ADDRESS`, `CLINIC_PHONE`, `CLINIC_EMAIL` 🟢
- **Where:** `.env` (optional; fictional defaults built in); marker `CURALINK_CONFIG: CLINIC_PROFILE` in `backend/app/config.py` and `backend/app/curalink_config.py`.
- **Test:** generate a certificate; the header and footer show these values.

### C2. Clinician profiles 🟢
- **Where:** `sample_data/demo_users.json` (names, credentials, verified flag), loaded by `backend/app/seed.py`; marker `CURALINK_CONFIG: CLINICIAN_CREDENTIALS`. The demo password (`curalink-demo`) is stored only as a scrypt hash.
- **Test:** `pending.clinician@clinic.example.com` is refused; Dr. Hale can't open Dr. Rivera's patients.

### C3. Certificate template, wording and branding 🟢
- **Where:**
  - Template: `backend/app/services/pdf_builder.py::render` (`CLINIC_CERTIFICATE_TEMPLATE`)
  - Wording: `CERTIFICATE_LANGUAGE`
  - Branding: `CERTIFICATE_BRANDING`
  - Required fields: `ABSENCE_CERTIFICATION_FIELDS`
  - Verification IDs: `DOCUMENT_VERIFICATION`, in `absence_service.py`
  - Professor emails: `NOTIFICATION_TEMPLATES`

  Everything except the template and verification IDs lives in `backend/app/curalink_config.py`.
- **Fallback:** fictional wording with a DEMO banner. `TODO(CURALINK-MANUAL)`: provider-approved wording and logo.
- **Test:** generate → preview. Every required field is filled in, or rendering stops with `CERTIFICATE_INCOMPLETE`.

### C4. Simulated signature 🟢
- **What happens:** clinicians draw a signature in **Signature Settings**. It is stored AES-GCM encrypted (`SIGNATURE_STORAGE`, `SIGNATURE_ENCRYPTION`), placed per `SIGNATURE_PLACEMENT`, and printed with **“SIMULATED SIGNATURE — DEMO, NOT VALID”**.
- **Key:** `SIGNATURE_ENCRYPTION_KEY` in `.env`, or in demo mode an auto-generated `backend/.secrets/signature.key` (git-ignored).
- **Test:** draw → Save → *Approve & sign this version* (re-enter password) → the signed PDF shows the drawing.

---

## D. Production-only information 🔵 (do not fake these)

| Item | Where | Status |
|---|---|---|
| Verified clinic identity | `CLINIC_PROFILE` | `TODO(CURALINK-MANUAL)` — real clinic agreement + details |
| Verified clinician credentials (SSO/OIDC, license checks) | `CLINICIAN_CREDENTIALS` | `TODO(CURALINK-MANUAL)` — replace demo login |
| Secure signature storage + key management (KMS, rotation) | `SIGNATURE_STORAGE`, `SIGNATURE_ENCRYPTION` | `TODO(CURALINK-MANUAL)` |
| Authorized document delivery provider | `EMAIL_PROVIDER`, `EMAIL_DELIVERY_MODE`, `EMAIL_SENDER` | `TODO(CURALINK-MANUAL)` — only `test_inbox` exists; other modes refuse to send |
| Document authenticity service | `DOCUMENT_VERIFICATION` | `TODO(CURALINK-MANUAL)` — demo IDs are not proof of authenticity |
| Data protection & retention (HIPAA/FERPA review, deletion schedules, audit retention) | — | `TODO(CURALINK-MANUAL)` — legal/compliance review before any real patient data |
| Institution-approved workflows (university absence policy, instructor contact rules) | `DOCUMENT_RECIPIENT_RULES` | `TODO(CURALINK-MANUAL)` — written approval from the university |

The system must stay in `DEMO_MODE=true` with fictional data until every row above is done.
