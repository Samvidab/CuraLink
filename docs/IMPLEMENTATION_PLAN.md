# CURALINK | IMPLEMENTATION PLAN & AGENT HANDOFF
Version 1.0 • Build sequence and acceptance gates • October 23, 2026

## 1. Instructions to the coding agent
You are implementing CuraLink, a healthcare ADMINISTRATIVE coordination prototype for Cal Hacks. Read all four project documents before coding. Prioritize a completely working end-to-end MVP. Build functional code, not just mockups. Use fictional student/clinic data in demo. Never claim a live clinic appointment, valid doctor's signature, or officially excused absence. Do not implement autonomous clinical diagnosis or severity ranking. Before proceeding to the next milestone, run tests and demonstrate the acceptance criteria. If an external API is unavailable, implement a clearly marked mock adapter behind a stable interface; do not invent endpoint access.

## 2. Repository deliverables
- frontend/ React + TypeScript + Vite app with stated routes and accessible components.
- backend/ FastAPI service with documented /api/v1 routes, Pydantic schemas, safe LLM integration and deterministic service layer.
- sample_data/ sample.ics (fictional), demo_courses.json, demo_slots.json, contacts.json.
- tests/ unit, integration and smoke E2E tests.
- README.md: architecture, run commands, demo credentials/personas, setup, assumptions, known limitations, sponsor usage.
- .env.example, .gitignore, CI workflow, curl/API examples, demo reset command.
- docs/ references to these four documents; architecture diagram optional.

## 3. Team-parallel workstreams
A | Frontend & UX: app shell, dashboard, chat, calendar, appointments, documents, activity, error/success states.
B | Integration & optimization: ICS parsing/recurrence, course matching, synthetic slots, deterministic ranking, timezone tests.
C | Agent & orchestration: Anthropic interface, Pydantic tool schemas, state machine, message routing, safe handling.
D | Administration & QA: absence mapping, professor drafts, ReportLab PDF, provider approval, outbox, test delivery, end-to-end tests and README.
Workstreams agree on API contracts and fixture IDs before parallel coding. Avoid competing edits to shared contracts.

## 4. Timeboxed milestones (relative to project start)
### M0 (0–2h): skeleton and interface contract
Create monorepo; establish Python and Node tooling; lint/typecheck; baseline Figma sketches; define schema files; seed example fixtures; CORS and health route. Gate: frontend renders and GET /api/v1/health returns 200; both lint/test workflows run.
### M1 (2–6h): reliable calendar core
Implement multipart ICS import with size/type controls; expand recurrences into events; classify course meetings; calculate overlaps; display weekly calendar. Gate: fixture import returns expected event count; timezone/DST and recurrence tests pass; errors understandable.
### M2 (5–10h): eligible appointment ranking
Implement clinic adapter interface and demo inventory; conflict filtering and normalized scoring; rankings with reason codes; explicit demo confirmation and stale slot handling. Gate: ranking has deterministic ordering, 0 fabricated slots, demo status unambiguous.
### M3 (8–14h): document assembly
Implement absence dates + event overlaps; contact resolution with manual verification; per-course message drafts; unsigned PDF generation and content validation. Gate: correct classes/dates/contacts in 20 fixtures; unknown contact blocked from delivery.
### M4 (12–19h): consent and automation
Implement student review, provider demo persona, transition guards, audit log, outbox queue, idempotent delivery to test allowlist. Gate: no delivery without both required approvals; rejection/revocation blocks delivery; double submit sends once.
### M5 (17–23h): AI agent as interface
Connect Claude to safe tools (calendar read, ranked slots read, create draft). Add stateful progress/action cards and safety routing. Gate: demo works with and without model API (fallback scripted demo); no AI writes provider approvals or sends directly.
### M6 (23–29h): polish + edge cases
Responsive UI, accessibility, loading/error states; event traces; stale slot recomputation; Notability development notebook or optional PDF import. Gate: full E2E Playwright smoke, all target browsers, demo dataset reset.
### M7 (29–36h): measurement, pitch and submit
Measure baseline time/clicks, collect test results, record demo, prepare 3-minute pitch, README, sponsor details and submission. Freeze features when recording starts. Gate: fresh checkout boot and offline backup demo succeed; submission fields complete before deadline.

## 5. Dependency order and hard gates
Schemas and fixtures → ICS normalization → calendar UI → clinic adapter and scheduler → absence mapper → contact validation and PDF → review/approval state machine → delivery → LLM orchestration → polish and sponsor extras. Never implement send before authorization guards. Do not make first working demo depend on external clinic permissions.

## 6. Detailed agent ticket backlog
T-001 [P0][B] Generate sample ICS with multi-course weekly recurrences, timezone and exclusion; tests for expected occurrences.
T-002 [P0][B] Implement POST /calendars/import and GET /calendar/events; reject malicious/oversize files.
T-003 [P0][A] CalendarGrid with imported events, timezone label, detail drawer, upload retry.
T-004 [P0][B] Implement get_slots clinic adapter returning seeded synthetic slots and provenance.
T-005 [P0][B] Implement deterministic filter/score, reason codes and no-options state.
T-006 [P0][A] Appointment screen with slot compare and demo confirmation dialog.
T-007 [P0][D] Absence mapper for affected event occurrences and overlap minutes.
T-008 [P0][D] Course/contact resolver; manual verification; never fabricate email.
T-009 [P0][D] Editable per-class email draft generation and ReportLab unsigned PDF.
T-010 [P0][D] Student consent gate, demo provider approval, state machine and transition audit.
T-011 [P0][D] Test-only sender, idempotency key, destination allowlist and failure path.
T-012 [P0][C] Model gateway with server-side key, safe prompts, typed output and allowed tool list.
T-013 [P0][C] Prompt-scope guard: no diagnosis, no medical urgency ranking, support escalation.
T-014 [P0][A] Activity trace and role-specific pending-state UI.
T-015 [P0][All] E2E smoke and final demo story; fresh install reproducibility.
T-016 [P1][D] Notability-exported PDF course-note import and review checklist.
T-017 [P1][A] Voice UI hook with Cartesia using supported API only.
T-018 [P1][C] Moss runtime SDK integration if accessible and truly agentic.
T-019 [P1][C] Factory Droid runtime execution and visible task trace if SDK available.
T-020 [P1][B] Real UniTime read-only subscription only with secure host allowlist and explicit consent.

## 7. Acceptance tests: runnable scenarios
AT-01 ICS recurring course expands into Monday/Wednesday/Friday meetings with correct local hours for selected week.
AT-02 ICS EXDATE is excluded, invalid TZID handled predictably, duplicate UID not repeated.
AT-03 Existing class overlapping 13:30–14:20 excludes 14:00 clinic slot; later free slot ranks.
AT-04 Travel buffer creates conflict even if the literal appointment times don't overlap.
AT-05 Deleted/claimed mock clinic slot yields 409 and triggers replan.
AT-06 Student marks two calendar sessions missed; exactly two corresponding drafts appear.
AT-07 Unknown instructor email yields NEEDS_REVIEW and disables delivery.
AT-08 Provider approval absent/rejected → no email; approvals cannot be forged by client-specified actor_role.
AT-09 Student consent revoked before delivery → no email.
AT-10 Two identical queue requests send at most one message per destination/document version.
AT-11 Professor email contains no symptom details by default; verification form unsigned.
AT-12 High-risk symptom test halts routine booking guidance and points to appropriate emergency services.
AT-13 Source_mode=demo appears beside every synthetic slot/confirmation and activity event.
AT-14 Failure in email adapter produces recoverable pending/failed state, not false "delivered".
AT-15 Fresh checkout can run locally using README and seed script; test suite green.

## 8. Sample demo script and event choreography
Scene 1: Student demo persona opens assistant; asks for help after feeling unwell. Agent explains it's administrative support, not a medical diagnostician.
Scene 2: Click import sample ICS; show four courses in calendar.
Scene 3: Request care coordination; system reads 20 DEMO clinic slots, filters class overlaps and travel, ranks top three; visibly reject a conflicting slot.
Scene 4: Click confirm 14:30 DEMO slot; source badge and fake booking status shown.
Scene 5: Choose next-day absence period; preview impacted courses; one professor contact verified and another manually corrected.
Scene 6: Generate per-course email drafts and unsigned PDF; show minimal disclosed information.
Scene 7: Student approves; simulated provider separately approves; event listener queues test email and updates trace; no real excused status claimed.
Scene 8: Invalidate another slot, demonstrate replanning/failure recovery; end with measured test metrics.

## 9. Risk register and mitigations
R1 API access blocked (high likelihood): mock adapter + transparent source badges.
R2 ICS recurrence and timezone mistakes (high impact): tested expansion, UTC normalized storage and sample fixtures.
R3 Instructor details missing (likely): manual review; never guess emails.
R4 AI inaccurate medical framing (high impact): strict scope, safety handler and QA with curated cases; not clinically validated.
R5 Leakage of health info (high impact): fictional demo data, minimized message content, redacted logs, allowlisted destinations.
R6 Provider approval fiction mistaken as valid signature (high impact): DEMO provider label and no signature images.
R7 Agent complexity delays MVP (medium): deterministic service core, model as narrow UX layer, fallback demo.
R8 Team merge conflicts (medium): contract freeze, feature branches, PR owner, CI and twice-daily integration.
R9 Site/Internet failure on demo day (medium): prerecorded walkthrough, local mock data and preloaded scenarios.

## 10. Sponsor submission strategy
Anthropic: demonstrate Claude's permitted structured tool calls, safe constraints and real workflow utility. Microsoft: measurable customer time saved, production architecture and responsible controls. Notability: real handwritten planning, diagrams, meeting notes, PDF markups and Smart Notes used during development; optional note import. Cartesia/Moss/Factory only if actual working in-app integration can be shown. Do not misrepresent a development-only tool as runtime functionality.

## 11. Definition of done / release checklist
[ ] Imported ICS schedule with recurrence and local time correctness.
[ ] Real working deterministic mock-clinic slot ranking with reasons.
[ ] Student explicitly confirms simulated appointment.
[ ] Correct class-date-to-draft pipeline with manual instructor review.
[ ] Unsigned PDF and editable professor-specific emails.
[ ] Approval state machine blocks unauthorized delivery.
[ ] Test-only one-time delivery and full status trace.
[ ] Safe non-diagnostic messaging and scope notice.
[ ] Clean install, seed, unit/integration/E2E tests, README and demo video.
[ ] All sponsor claims verifiable; no real data or approvals misrepresented.

## 12. Copy/paste kickoff prompt for coding agent
"Implement CuraLink as specified in the four attached documents. Start by inspecting the repository and reporting missing scaffolding, then create the MVP according to the dependency order in Implementation Plan §5. First define Pydantic models and API contracts, generate fictional fixture data, then build calendar import, mocked clinic scheduling, absence drafts, permissioned provider-review workflow and UI. Use real working code and tests; run lint/typecheck/pytest and a full E2E path. Do not diagnose, assign medical urgency, forge provider approval/signatures, invent professor contact data, or claim live third-party booking. Label mock clinic data and provider workflows DEMO. Do not create external emails except through a controlled test allowlist after student consent and simulated provider approval. Complete P0 fully before optional sponsor SDKs; provide run instructions, tests, and known limitations."

## 13. Addendum — Computer Vision Implementation Tickets

Scope and priority: Add photo observations as P1; do not jeopardize the core end-to-end scheduling and absence-demo workflow. Use synthetic or appropriately licensed demo images; do not put real patient photos in the repository.

CV-01 (Frontend, 1–2h): Optional photo-upload UI with consent, drag/drop or picker, preview, remove/retake and image-quality hints. Acceptance: user can proceed without uploading; no photo is analyzed without explicit opt-in.

CV-02 (Backend, 1–2h): POST /api/v1/vision/observations and validation of file signature/type/size; metadata stripping; short-lived private processing. Acceptance: invalid/oversized inputs fail safely without logging photo contents.

CV-03 (AI, 2–3h): Vision-model adapter returning Pydantic structured candidate observations for apparent swelling/asymmetry, red-appearing area (not confirmed blood), dry/flaky appearance, and possible bruise-like discoloration. Acceptance: no diagnosis, cause, severity, urgency or inferred provider authorization is output.

CV-04 (Safety, 1–2h): Deterministic output constraints, disclaimers, red-flag handling driven by student report and clinician-reviewed guidance. Acceptance: emergency signals cannot be overruled by a photo; false assurance and fabricated diagnoses are blocked in predefined tests.

CV-05 (Integration, 1h): Optional student-reviewed observation summary for appointment intake only. Acceptance: no image or sensitive observation is sent to professors, stored in absence drafts, or used to rank clinic urgency.

CV-06 (QA, 1–2h): Automated tests for invalid images, lighting ambiguity, red fabric vs blood, bruising-like shadows, misleading single-image swelling, user deletion, consent denial, photo-embedded prompt injection and vision-model outage. Acceptance: safe fallback to existing text-based intake.

CV-07 (Demo, 30m): Demonstrate image analysis using a synthetic or licensed image, then continue with scheduling and documentation. In presentation label observations as descriptive and non-diagnostic; explicitly call out limitations.

Build instructions for coding agent: Read PRD §11, TRD §15 and UI/UX §16 before implementing these tickets. Add API schemas and tests first; do not rewrite existing agent permission boundaries. Use feature flag ENABLE_PHOTO_OBSERVATIONS, default false until validation passes. Add 'Photo-based observations are not medical diagnosis' in the README and demo slide. Do not claim clinical efficacy.

Definition of done: one complete photo-to-structured-observation demonstration; optional consented carry-forward to clinical appointment intake; zero photo data in academic communications; all safety and privacy test cases pass.

## 14. Amendment v1.2 — Voice, Clinician Portal, Signing Automation (AUTHORITATIVE)
This revised order overrides previous single-portal assumptions. Produce two independent authenticated interfaces and a true voice-first intake, but protect a reliable non-voice demo fallback. Do not ship automated clinician medical judgments, real signatures, unapproved professor emails, or claims of live clinic connectivity.

### First deliverable / architecture freeze (new P0)
- T-021 [P0][A/D] Role-selection entry, separate student and clinician route shells, server-authorized demo personas, cross-role 403 tests.
- T-022 [P0][C] Cartesia technical spike: validate current Line SDK/streaming API, browser transport and full duplex streaming; choose documented approach and record SDK versions (https://docs.cartesia.ai/line/sdk/tips).
- T-023 [P0][A/C] Audio streaming UI + turn state machine, captions, mic permissions, manual text fallback and barge-in with cancellation/late-chunk rejection.
- T-024 [P0][C] Structured intake extraction from finalized transcript to typed fields with provenance; student corrections and confirmation.
- T-025 [P0][A/D] Contextual intake panel with temperature value/units/time, optional consent-gated photo upload, symptoms and onset; synchronized with voice context.
- T-026 [P0][D] Consentful encrypted handoff snapshot tied to booked/demo appointment and assigned clinician; doctor-side intake display restricted to assigned cases.
- T-027 [P0][A/D] Doctor dashboard with upcoming appointment list, completeness indicators, encounter review and missing-data request.
- T-028 [P0][D] Doctor-only multi-day absence-range composer and deterministic impacted-classes recomputation (weekends, exceptions, time zones).
- T-029 [P0][D] Controlled sample signature vault, immutable PDF document versions, clinician final preview and per-version approve-and-sign gate. Hackathon uses fictional signatures only.
- T-030 [P0][D] Authorized document delivery outbox with verified recipients, separate student disclosure consent, clinician sign authorization, idempotency and test-inbox delivery.
- T-031 [P0][All] End-to-end test student voice -> form -> handoff -> clinician -> multiday PDF -> per-version sign -> mock delivery; demonstrate no-send without clinician approval.

### Recommended revised implementation order and parallel assignments
A — Student UX: sign-in, voice UI, contextual form, calendar, booking review, case tracking.
B — Scheduling/data: ICS parsing, course mapping, clinician-date class impact, mock clinic inventory, optimization.
C — Voice/AI: Cartesia integration, barge-in, transcript/field extraction, Claude admin tools, safe routing, synthetic tests.
D — Clinician/admin/security: RBAC, encounter assignment, consent, clinician portal, document versioning, signature authorization, email outbox, audit.
Order: role/auth schema and fictional fixtures -> two UI shells -> intake structured models -> streaming voice and robust fallback -> UniTime/scheduling -> consentful handoff -> clinician multiday decision -> immutable preview -> signature/approval -> test delivery -> polish.

### Time budget for a ~36-hour hackathon (parallel)
0–3h: Freeze schemas, seed mock doctor/student cases, set up role shells and tests.
3–9h: UniTime + calendar and clinician dashboard prototype; independently validate Cartesia streaming and interruption on a minimal page.
9–16h: Full voice-to-structured-data workflow, contextual photo/temperature drawer, clinic slot recommender and encounter handoff.
16–24h: Clinician multi-day date decision, class impact matching, unsigned PDFs, signature vault + per-version signing and test outbox.
24–30h: E2E integration, event trace, privacy gates, fallback workflows, usability tests.
30–36h: Fixed demo, measured evaluations, docs/README, sponsor writeup and submission; freeze new features for recording. Drop extra sponsor SDKs before dropping testing.

### Additional acceptance tests
AT-21 Real microphone speech interrupts agent during streaming TTS; old audio is canceled and no stale audio is played after interruption.
AT-22 Missing temperature triggers a field drawer; student can skip; system never invents a value or unit.
AT-23 A phone photo may be included in doctor packet only after explicit share consent; professor packet excludes photo and symptoms.
AT-24 Clinician assigned to case A cannot access case B; student never accesses sign/send endpoints.
AT-25 Doctor can certify a multi-day interval; matching collects only meetings within inclusive clinician-entered local dates, not nonexistent weekend classes.
AT-26 Saved sample signature does not create a signed document until clinician reviews and confirms immutable version; stale document hash fails with 409.
AT-27 Any edit after signature creates new unsigned version, requiring explicit new approval. Revoked signature cannot be used subsequently.
AT-28 No email without student disclosure consent, verified professor address, final clinician signature approval and delivery authorization; send is idempotent.
AT-29 Provider can decline to document absence; app never infers or automatically prescribes duration from symptoms/photo.
AT-30 Doctor dashboard accurately labels student-reported vs clinician-verified fields; an offline/unsupported Cartesia integration falls back to text while preserving workflow.

### High-value advanced technical extensions, only if stable
P1: Turn-level audio latency dashboard, interruptions/event trace, confidence-gated transcript corrections; clinician-requested additional fields with live student notification; SSE status updates; backend temporal event model; auditable policy engine.
P2: Cartesia low-latency multimodal voice, optional Notability PDF academic recovery, Factory Droid execution of a bounded administrative task (with trace), Moss agent context sync, OR-Tools multi-constraint rescheduling, simulation/evaluation harness with 25 patient encounters and 100 timetable combinations.
Never use external SDKs merely for a prize; demonstrate substantive SDK execution. Potential track alignment: Cartesia core voice and interruption; Anthropic structured orchestration; Microsoft measurable reliable clinician workflow; Factory meaningful SDK agent action with permission boundary; Notability authentic design/dev record.

### Replacement coding-agent kickoff instruction
Implement CuraLink from all four documents, applying the v1.2 AUTHORITATIVE amendments when older sections conflict. There are TWO portals: Student (Cartesia-powered interruptible voice and contextual forms) and Clinician (assigned intake/appointments, clinician-authored multi-day absence decisions, review-and-sign immutable PDFs and test-only authorized delivery). A professor is the recipient, not a third portal. No AI may set absence duration, medically rank cases, diagnose, sign documents or send without server-approved authorization. Build robust mock adapters where live integrations cannot be verified. Start by implementing role boundaries and contracts; then voice, UniTime, scheduling, clinician handoff, absence range, PDF signature versioning, test outbox and E2E tests. Show measured interruption handling and no unauthorized sends. Do not claim real HIPAA compliance, legal e-signature validity, live clinic availability or official university excusal.
