# CURALINK | TECHNICAL REQUIREMENTS DOCUMENT (TRD)
Version 1.0 • Hackathon MVP • October 23, 2026

## 1. System context
CuraLink is a React SPA with FastAPI backend. The backend has a deterministic rules + optimization layer, a narrowly scoped LLM orchestration layer, and adapters for calendars, clinic inventory, contact lookup, document generation and approved delivery. Human authorization is enforced in backend policy, never left to an LLM prompt.

## 2. Technology stack and choices
Frontend: React 18+, TypeScript, Vite, Tailwind, shadcn/ui, React Query, React Router. Backend: Python 3.11+, FastAPI, Pydantic v2. State: SQLite for zero-setup demo or Supabase PostgreSQL if team already configured it. Calendar: icalendar + recurring_ical_events (or equivalent recurrence expansion). Time zones: zoneinfo. PDF: ReportLab. Scheduling: deterministic filters + ranking initially; OR-Tools optional when needed. LLM: Anthropic Claude via server-only API; LangGraph only if it adds state checkpointing. Email: test SMTP/Mailtrap or test inbox adapter; Graph OAuth P1. Background workflows: synchronous event dispatcher for demo with persisted state; production later uses durable queue/outbox. Tests: pytest, React Testing Library, Playwright smoke test. Structured logging with redaction.

## 3. Component boundaries
Frontend: /chat, /calendar, /appointments, /absences, /documents/:id, /activity, /settings, /demo/provider. Backend modules: api, schemas, auth_demo, ics_parser, course_resolver, clinic_adapter, scheduling_engine, absence_mapper, llm_gateway, pdf_builder, approval_service, outbox_worker, audit. No module except llm_gateway can call the model. No model output is directly executable or eligible as consent.

### Integration modes
MODE=demo (default): seeded fictitious students/classes, .ics upload, synthetic clinic availability, simulated provider, test-only email.
MODE=pilot (future): approved campus integrations; verified identity and scopes; disabled until reviewed.
All API payloads carry `source_mode: demo|real|uploaded` when relevant. Show this in UI.

## 4. Core domain models
Student {id, display_name, demo_mode, timezone, consent_version}; Course {id, code, section, term, title?, instructor_name?, instructor_email?, provenance, verified}; CalendarEvent {id, uid, course_id?, start_at, end_at, location?, recurrence_id?, source}; ClinicSlot {id, clinic_id, appointment_type, starts_at, ends_at, source_mode, status, travel_minutes?, permitted=true}; Appointment {id, student_id, slot_id, state, confirmation_mode, idempotency_key}; AbsenceCase {id, student_id, start_at, end_at, student_reported, status}; ImpactedClass {case_id, calendar_event_id, overlap_minutes, include}; Document {id, case_id, type, version, signed_status, pdf_storage_key, verified_by?}; DraftMessage {id, case_id, course_id, recipient_address?, body, status}; Approval {id, object_type, object_id, actor_role, scope, decision, timestamp}; OutboxAction {id, kind, payload_ref, idempotency_key, status, attempts, error_code}; AuditEvent {id, actor_role, action, object_id, from_state, to_state, at, source_mode}.

Use ISO 8601 with offsets on the wire; store UTC instants; retain original ICS TZID for display. Recurring calendar events MUST be expanded within requested date range before overlap calculation.

## 5. State machines
Appointment: OFFERED → PENDING_STUDENT_CONFIRMATION → DEMO_CONFIRMED (demo) OR SUBMITTED_TO_CLINIC → CONFIRMED/REJECTED (future approved live path). Not permitted: OFFERED → live CONFIRMED without clinic acknowledgment.
Absence packet: DRAFT → PENDING_STUDENT_APPROVAL → PENDING_PROVIDER_REVIEW → APPROVED_FOR_DELIVERY → QUEUED → DELIVERED; alternative: REJECTED / CANCELLED / FAILED. Provider review can approve a provider-verification document only; no automatic official university excusal. If student rejects disclosure, do not queue delivery.
Document: UNSIGNED → PROVIDER_REVIEWED → APPROVED (simulated only in demo). Never generate a signature blob. Delivery state separate from absence approval.

## 6. API contracts (stable v1)
### POST /api/v1/demo/reset
Response 200 {"student_id":"demo-student-1","source_mode":"demo"}. Clears demo-only records; never available in pilot.
### POST /api/v1/calendars/import
multipart/form-data `file` (.ics, max 2 MB); response 200 {"calendar_id":"cal_1","events_imported":12,"warnings":[],"source_mode":"uploaded"}. Reject invalid type/size with 422.
### GET /api/v1/calendar/events?start=...&end=...
200 {"events":[{"id":"ev_1","course_code":"CS 18000","start_at":"2026-10-26T09:30:00-04:00","end_at":"2026-10-26T10:20:00-04:00","location":"LILY"}],"timezone":"America/Indiana/Indianapolis"}.
### POST /api/v1/intake/messages
Request {"session_id":"s1","message":"I feel unwell and need to arrange care"}; response {"assistant_message":"...","safety_state":"GENERAL_SUPPORT|ESCALATE|EMERGENCY_GUIDANCE","next_actions":["IMPORT_CALENDAR","FIND_CARE"],"tool_events":[]}. The assistant must not diagnose or estimate urgency.
### GET /api/v1/clinic/slots?start=...&end=...&appointment_type=...
200 {"slots":[{"id":"slot_42","starts_at":"...","ends_at":"...","clinic_name":"Demo Student Clinic","source_mode":"demo","permitted":true}],"inventory_updated_at":"..."}.
### POST /api/v1/schedule/recommendations
Request {"student_id":"demo-student-1","slot_ids":["slot_42"],"preferences":{"avoid_class_conflicts":true,"max_travel_minutes":45}}; response {"options":[{"slot_id":"slot_42","score":16.0,"conflicts":[],"reason_codes":["NO_CLASS_CONFLICT","SHORT_TRAVEL"],"source_mode":"demo"}],"rejected":[{"slot_id":"slot_9","reason_code":"CLASS_CONFLICT"}]}.
### POST /api/v1/appointments/confirm
Request {"slot_id":"slot_42","student_approved":true,"idempotency_key":"uuid"}; response {"appointment_id":"apt_1","status":"DEMO_CONFIRMED","external_booking":false}. No live booking claim.
### POST /api/v1/absence-cases
Request {"student_id":"demo-student-1","start_at":"...","end_at":"...","student_reported":true}; response {"case_id":"case_1","status":"DRAFT","impacted_classes":[{"event_id":"ev_1","overlap_minutes":50,"contact_status":"NEEDS_REVIEW"}]}.
### POST /api/v1/absence-cases/{id}/drafts
Response {"messages":[{"id":"msg_1","course_code":"CS 18000","recipient_address":null,"body":"...","requires_review":true}],"provider_document_id":"doc_1","pdf_url":"/api/v1/documents/doc_1/download","signed":false}.
### POST /api/v1/approvals
Request {"object_type":"absence_packet","object_id":"case_1","actor_role":"student|demo_provider","decision":"approve|reject","scope":"delivery|provider_verification","consent_version":"v1"}; response {"state":"PENDING_PROVIDER_REVIEW|APPROVED_FOR_DELIVERY|REJECTED"}. Actor is determined by authenticated session/role, not trusted request text in production.
### POST /api/v1/delivery/queue
Request {"case_id":"case_1","idempotency_key":"uuid"}; response {"status":"QUEUED","destination_mode":"test_only"}; server rejects without verified approvals, valid address, test allowlist.
### GET /api/v1/workflows/{case_id}/events
Response {"events":[{"event_type":"DRAFT_CREATED","actor":"system","at":"...","status":"ok"}]} with medical text excluded.
Error model: {"code":"SLOT_UNAVAILABLE","message":"...","recoverable":true,"details":{}}; HTTP 400/401/403/409/422/500 as appropriate.

## 7. Scheduling engine: algorithm
Input = clinic-confirmed eligible slots, class intervals, blocked time, travel buffers, preference weights. Hard constraints: slot is offered and available, correct appointment type, clinic-provided eligibility, no mutually exclusive overlap unless student explicitly opts to allow conflict (still show conflict), sufficient travel/setup margin, time-zone valid. Ranking among feasible slots: normalized wait time + travel minutes + preference penalties. Medical severity is never computed by LLM. Sort deterministic (cost, start time, slot id). Output reason codes and excluded-slot explanations. Recheck mutable availability at confirmation; in demo update simulated inventory status.

Initial complexity: if N slots and M calendar events, O(N*M) overlap filtering; index sorted intervals if required. Use OR-Tools only if extended to combinatorial multi-appointment scheduling; avoid unjustified complexity.

## 8. Course matching and absence logic
Normalize course codes and sections; use student-imported ICS events as primary truth for timing. Resolve instructors via explicitly verified course catalog source or manual user confirmation; do not synthesize email addresses. An event is impacted when max(startA,startB) < min(endA,endB), after timezone normalization. Show overlap minutes. Do not infer medical justification from attendance overlap or appointment confirmation. Provider form contains identifying and scheduling details with neutral language; provider decides which factual statements can be verified.

## 9. LLM control contract and security
Permitted LLM tools: list_calendar_events(read), get_ranked_slots(read), create_draft(write draft), explain_reasons(read). Restricted actions: book_appointment, send_email, sign_document, approve_provider, grant_excuse, access_credentials: LLM cannot execute; backend requires separate authenticated authorization. Validate model output with typed schemas; reject unknown tools, unsafe arguments and PII leaks. Use deterministic prompt template: non-diagnostic support; no urgent medical ranking; emergency warning signs trigger approved safety handler; don't invent professor, doctor, clinic, slot, policy or document signature. Audit tool invocations with data minimization.

## 10. Privacy and security engineering
Demo fixtures only; no live PHI in hackathon demo. Calendar URL is a secret-like token: prefer ICS upload; if fetching later, permit only HTTPS with host allowlist, private-network/DNS-rebinding protection, strict size and redirects. Secrets server-side, .env ignored by Git. Test email destination allowlist and test accounts. Authenticated action roles and CSRF defense in future pilot. Rate limiting, content-length controls, uploaded file validation, safe document filenames, retention and deletion endpoints, secure download access. Never log symptom narratives or full documents.

## 11. Data seed and test fixtures
Seed students: demo-student-1, demo-student-2. Classes: 4 courses across weekdays, overlapping and nonoverlapping events, DST boundary, one recurring exception. Mock slots: 20 slots with different times/travel; one becomes unavailable during demo. Contacts: two verified demo emails, one missing contact. Absence cases: one overlapping 3 meetings, one no overlap. Provider: separate demo actor. All addresses end in example.com or point to a controlled test mailbox, never actual professor.

## 12. Verification and nonfunctional requirements
Unit tests: ICS recurrence/time zones, interval overlaps, stable ranking, contact uncertainty, approval-guard matrix, duplicate queue, LLM tool authorization. Integration tests: upload → plan → draft → approve → test deliver; reject/revoke → no deliver; stale slot → replan. E2E: keyboard-driven Playwright flow. Performance target: calendar import under 3s for 100 occurrences, slot ranking under 500ms for 100 slots/100 events on development machine (targets, verify). Accessibility WCAG 2.2 AA aspirational. MVP startup via documented commands and optional Docker Compose.

## 13. Development and deployment
Repository: frontend/, backend/, docs/, sample_data/, tests/. GitHub Actions: lint, typecheck, pytest. .env.example (ANTHROPIC_API_KEY, DATABASE_URL, DEMO_MODE=true, TEST_EMAIL_ALLOWLIST, CORS_ORIGINS). Deploy frontend Vercel or Netlify; backend Render/Railway or local demo; store no real health data in free-tier demos. Provide scripted `seed_demo.py` and `run_demo.sh`.

## 14. Open technical decisions
A) Real-time UniTime access? Default ICS upload until rights/format validated.
B) Instructor fields? Manual correction when absent.
C) Scheduling live inventory? Use mock; partnership required for real.
D) Provider signing? Demo approval with prominent simulation labels, not clinical e-signature.
E) LangGraph and OR-Tools? Add only if they materially improve real state handling/optimization.

## 15. Addendum — Computer Vision Module and Contracts

Module: backend/services/vision.py (image validation and model adapter), backend/services/vision_guardrails.py (schema validation and language checks), frontend/components/PhotoObservation.tsx. A vision-capable model may be used as a descriptive assistive tool, NOT a medically validated classifier. Name and version of the chosen model must be configured and logged for each test run.

Pipeline: user consent -> local format/size check -> server validates MIME and file signature, rejects oversized/unsafe data -> remove EXIF and GPS metadata -> minimize/crop image with user control -> vision model produces structured candidate observations -> rule-based output validator blocks forbidden diagnostic terms and unsupported confidence claims -> UI displays qualified observations, limitations, and general informational guidance -> optional user-approved sharing with appointment intake.

POST /api/v1/vision/observations: multipart file plus explicit consent flag and optional user-selected region. Respond with {observation_id, image_quality:{lighting,clarity,notes}, possible_features:[{category: apparent_swelling|red_area_possible_blood|dry_or_flaky_skin|discoloration_possible_bruise|other, description, uncertainty}], limitations:[...], general_next_steps:[...], disclaimer, needs_human_review:false}. Do not return disease predictions, confidence of diagnosis, clinical severity, or urgency ranking.

DELETE /api/v1/vision/observations/{id}: remove temporarily persisted image and associated observations when applicable. GET /api/v1/vision/observations/{id} only if authenticated and consented persistence exists. For MVP, prefer processing in memory and retaining only a session-scoped observation summary after explicit opt-in.

LLM contract: output must validate against a strict Pydantic schema with an allowlist of observation categories. The model must never assert that a pictured red area is confirmed blood, that swelling is present based on a single photo with certainty, or that a discolored mark is definitively a bruise. Prefer 'a red-appearing area is visible' and 'I cannot determine what caused it.' Never infer an absence duration, diagnosis, treatment regimen, or appointment urgency from the photo.

Security: do not log image bytes, URLs, EXIF, embeddings, or health narratives. Restrict uploads by size (e.g. 8 MB), image decoders, file signatures, per-user rate limits and authenticated access when available. Use private temporary storage with short expiry if required by infrastructure; never publicly accessible buckets. Do not use patient photos to train models without separate express consent.

Integration: photo summary is strictly optional context. It may assist student-authored description for clinical intake after review, but does not influence deterministic scheduling priority or medical eligibility. Never include photographs or sensitive observations in instructor emails or absence forms by default.

Test cases: unsupported or corrupted image; oversized upload; low light/blur; no relevant visible feature; makeup or red clothing mistaken for blood; camera tint; single-image apparent swelling without baseline; bruising-like discoloration caused by shadows; an image combined with student-reported emergency signs; prompt injection embedded in image text; deletion request; no-consent request; model outage; false reassurance and diagnostic hallucination red-team tests.

Implementation stages: V0 upload-preview and consent with sample neutral observations; V1 real vision model structured extraction and guardrail tests; V2 clinician-reviewed evaluation and privacy impact review before any real-world health deployment.

## 16. Amendment v1.2 — Voice, Multi-Role Architecture, and Clinician Signature Pipeline (AUTHORITATIVE)
This section overrides earlier student-centric provider approval state machine/API semantics where they conflict. Use STUDENT and CLINICIAN as authenticated roles (professor is not a portal role). Avoid claims of HIPAA compliance or legally binding e-signatures in the prototype; plan a formal legal/security review before deployment with real patients.

### Architecture extensions
Frontend routes: /select-role, /student/{dashboard,voice,intake,calendar,appointments,status}, /clinician/{dashboard,appointments/:id,intake/:id,absence-cases/:id,signatures,delivery}, /demo/reset. Backend modules add voice_gateway, realtime_session, intake_schema_extractor, encounter_assignment, consent_service, clinician_workbench, signature_vault, signed_artifact_service, notification_gateway.
- Identity: OAuth/OIDC subject -> DB-backed role and clinician verification; never trust a role string from request. Object-scoped access: encounter assignment + student consent + clinician active status. Audit access to every intake attachment.
- Socket: authenticated short-lived WebSocket or WebRTC tokens; avoid streaming sensitive audio through persistent third-party services without contract/security review. Implement scoped, expirying sessions and explicit retention settings.

### Cartesia voice stream and interruption contract
- Preferred implementation: verify the supported Cartesia Line agent SDK and/or streaming STT+TTS APIs at build time. Use Cartesia for material voice input/output, not merely button-based narration. Audio pipeline: microphone -> client audio frames -> speech activity/turn detection -> Cartesia transcription (where available) -> validated conversational state -> Claude administrative tool decisions -> Cartesia synthesized audio -> client speaker.
- Barge-in trigger: detect new user speech while assistant audio is active; on detection atomically (a) pause/clear current audio buffer, (b) increment server turn_version, (c) cancel active synthesis/LLM tasks when supported, (d) ignore late chunks bearing old turn_version, (e) capture new speech. If SDK exposes built-in interruption, test actual interruption and still guard stale messages in application state.
- Stream messages: session.started, mic.level, transcript.partial, transcript.final, assistant.text.delta, assistant.audio.chunk, assistant.cancelled, barge_in, intake.field_requested, intake.field_updated, audio.error, session.ended. Each has session_id, turn_id, turn_version and server timestamp; audio chunks also sequence index.
- Handle noise, silence, duplicate transcript, device permission denial, offline network, accent/acoustic variance and manual text fallback. Don't persist raw audio or full transcripts by default; obtain separate opt-in when required. Never treat transcript as medically verified.
- Do not hard-code unverified vendor endpoints, SDK methods or latency figures; confirm exact contracts using current docs: https://docs.cartesia.ai/line/sdk/tips and https://docs.cartesia.ai .

### Structured multimodal intake and handoff
IntakeSession {id, student_id, encounter_id?, status, voice_consent, transcription_consent, photo_consent, created_at}; IntakeField {id, session_id, key, typed_value, unit?, provenance:voice|form|photo_observation|clinician, confidence?, confirmed_by_student, observed_at}; Attachment {id, encounter_id, media_type, storage_key, consent_scope, deletion_at?, sha256}; HandoffPacket {id, encounter_id, field_snapshot_json, attachment_refs, student_approved_at, clinician_visible_at, version, source_mode}; Encounter {id, student_id, clinician_id, appointment_id, status}; ClinicianNote {id, encounter_id, text, clinician_id, authored_at}.
- Typed schema: symptoms_free_text, onset_date, temperature_value (number + C/F + measured_at + reported_by), optional image observations (explicitly non-diagnostic), requests, appointment preference; validation and distinct "not provided" state. Convert units deterministically without reinterpreting severity.
- Validate and summarize model extraction against transcript spans and submitted form values; display editable provenance badges and student confirmation before clinician transmission. Avoid automatically including unrelated historical audio or photos.

### Clinician-authored multi-day absences
ClinicianAbsenceDecision {id, encounter_id, clinician_id, inclusive_start_date, inclusive_end_date, documentation_type, approved_wording, rationale_private?, status, version}; affected course occurrences computed from clinician-assigned date range in student calendar timezone (inclusive local dates; no automatic expansion beyond chosen range). Only clinician can create or change certified range; students may REQUEST dates but never attest certification.
- Distinguish appointment date from absence dates; a clinic visit never automatically validates missed-class dates.
- Resolve professor identity + official email using trusted source or verified clinician/student confirmation. Block unknown or ambiguous recipients; never guess.

### Reusable signature asset, cryptographic approval, and safe document generation
SignatureAsset {id, clinician_id, encrypted_blob_ref, created_at, revoked_at, verification_state, mime_type}; DocumentVersion {id, case_id, version, unsigned_sha256, signed_sha256?, clinician_id, rendering_template_version, state}; SignAuthorization {id, clinician_id, document_version_id, document_sha256, approved_destinations_hash, consent_record_id, authenticated_at, approved_at, authorization_nonce}; Delivery {id, document_version_id, destination, state, provider_approved_at, student_consented_at, idempotency_key, transport_receipt}.
- Signature enrollment occurs ONLY in authenticated clinician portal; in MVP use a marked fictional sample asset. For production require verified clinician identity and suitable e-sign compliance assessment. Encrypt assets at rest with tightly scoped keys; no browser-local permanent signature caching, no signature URL in email, no generalized "paste signature" API.
- Document pipeline: create unsigned immutable PDF -> clinician preview full page + dates + recipients -> reauthenticate/confirm sign -> verify content hash + permitted role -> compose signed PDF with signature image, clinician name/date plus tamper-evident audit reference -> store signed hash -> delivery by authorized outbox. Approval is tied to exact version and recipients. Any edit resets approved state and requires approval again. Server applies asset, not the AI/client.
- Student consent to disclosure and explicit clinician signing are separate requirements. Sending to faculty must not disclose detailed symptom descriptions, image uploads or temperatures. Do not promise legal validity or university acceptance in the prototype.

### Event state machines
VoiceTurn: IDLE -> LISTENING -> THINKING -> SPEAKING; SPEAKING -> INTERRUPTED -> LISTENING; any -> ERROR -> TEXT_FALLBACK. Late audio chunks ignored after cancellation.
Encounter: UPCOMING -> INTAKE_SHARED -> CLINICIAN_REVIEW -> COMPLETED / CANCELLED.
AbsenceCase: STUDENT_REQUESTED -> CLINICIAN_REVIEW -> DATES_SET -> DRAFT_GENERATED -> PENDING_CLINICIAN_SIGNATURE -> SIGNED -> DELIVERY_QUEUED -> SENT / FAILED, with REJECTED/REVOKED branches. Gate SEND on student disclosure consent + verified actor + signed immutable doc version + vetted recipients. University excusal status remains independent/unknown.

### Additional API contracts (under /api/v1)
- POST /auth/demo/login {persona:"student|clinician"} -> demo-scoped session; disabled outside demo. GET /me -> authenticated role/permissions. Never let the client set its own role.
- POST /voice/sessions {voice_consent:true} -> {session_id, transport_token, expires_at}; WS /voice/stream with event schema above. POST /voice/sessions/{id}/interrupt -> {turn_version, state:"LISTENING"} (fallback when signaling not handled directly).
- PATCH /intake/sessions/{id}/fields {fields:[{key,value,unit,source}]} -> validated snapshot. POST /intake/sessions/{id}/attachments (multipart, explicit consent).
- POST /encounters/{id}/handoff {student_authorized:true, included_field_ids:[...], attachment_ids:[...]} -> {packet_id,version,status:"SHARED"}. GET /clinician/encounters -> assigned appointments only. GET /clinician/encounters/{id}/intake -> consent-filtered record.
- POST /clinician/encounters/{id}/absence-decision {start_date,end_date,wording} -> decision + impacted_class_occurrences; clinician-only. POST /clinician/absence-cases/{id}/render -> immutable unsigned doc version.
- POST /clinician/signature-assets -> restricted upload/enrollment (demo asset only for hackathon); DELETE /clinician/signature-assets/{id} revokes asset.
- POST /clinician/documents/{version_id}/approve-sign {nonce, document_sha256, recipient_ids, step_up_proof} -> {state:"SIGNED",signed_sha256,...}; clinician-only, single-use nonce. POST /clinician/documents/{version_id}/deliver {idempotency_key} -> test-only queued, gated on consent and signature. GET /clinician/documents/{version_id}/preview -> authenticated short-lived URL.
- GET /students/me/cases -> student-visible status stripped of clinician private notes. All unauthorized access -> 403; stale version/hash -> 409.

### Additional engineered features and evals
- Real-time appointment/intake status sync via SSE/WebSocket with role filtered events; resumable idempotent processing via transactional outbox and retry/dead-letter behavior.
- Constraint graph connecting clinician-declared date ranges, calendar occurrences, sections and verified recipients; deterministic recomputation on changed dates.
- Evidence provenance, conflict detection, missing-field requests, typed model tool schemas, zero-trust server permission checks, consent revocation and deletion workflows.
- Test voice interruption in <1 assistant turn with simulated delayed TTS chunks; enforce zero late-chunk playback. Test multi-day crossing weekend + recurring class exceptions; doctor role scoping; signer access; signature revocation; modified PDF hash; stale version; wrong recipient; student declined photo disclosure; double delivery.
- Engineering metric candidates: interruption-to-playback-stop latency (measured locally), intake field confirmation accuracy, class overlap accuracy, signed version integrity, duplicate-send prevention, least-privilege access tests. Never invent benchmarks.
