# CURALINK | PRODUCT REQUIREMENTS DOCUMENT (PRD)
Version 1.0 • Hackathon MVP • October 23, 2026

## 1. Product vision
CuraLink is a student-first healthcare coordination platform. A student describes a health-related scheduling problem, receives non-diagnostic support and safe signposting, imports their UniTime calendar, compares clinic-provided eligible appointment slots, and automates the administrative preparation of absence notices and provider-verification requests. The student remains in control of booking and disclosure; clinicians and university officials retain their respective authority.

**Tagline:** Where care meets coordination.
**Positioning:** Healthcare and academic workflow automation, NOT an AI doctor, clinical triage service, medical excuse issuer, or clinic booking provider.

## 2. Problem, users, and jobs to be done
Primary user: Purdue student balancing classes, treatment, and academic obligations. Secondary actors: authorized clinic provider (demo actor), professor/contact recipient (demo email), university office (information and process, not automated approval). Hackathon prototype audience: judges using synthetic personas.

- JTBD-01: When I feel unwell and need care, help me locate appropriate resources without falsely diagnosing me.
- JTBD-02: When I need an appointment, show only real or clearly labeled demo availability that fits my schedule.
- JTBD-03: When I may miss class, determine which meetings overlap the reported absence period.
- JTBD-04: Prepare accurate professor messages and unsigned clinician-verification requests so I do not retype information.
- JTBD-05: When approval is pending, keep track of status and resume eligible automated actions after approval.
- JTBD-06 (stretch): Help me plan catch-up tasks using voluntarily exported Notability notes.

## 3. Goals and metrics
G1: End-to-end synthetic demo from chat to appointment recommendation to absence draft in under 3 minutes, excluding human review.
G2: 100% of generated absence drafts reference the correct classes/dates in a 20-case synthetic test suite.
G3: 0 emails sent without authenticated user consent; 0 provider signatures applied by the system.
G4: 100% of simulated appointment recommendations sourced from an explicitly identified slot inventory, not model-generated slots.
G5: 100% of high-risk test prompts follow clinician-reviewed escalation pathways in the limited test catalog; do not market as clinical validation.
G6: Demonstrate one successful event-driven continuation and one failure/retry scenario.
Metrics to display in demo: time and clicks compared to a manually measured baseline, overlap accuracy, scheduling runtime, correct destination resolution, workflow outcomes. Do not claim measured gains until measured.

## 4. Scope and release tiers
### P0 | Required hackathon MVP
- Responsive standalone web application, desktop-first/mobile-capable.
- Guest/demo persona and seeded synthetic data; no real patient information required.
- Safe chat UI for general health navigation, with scope disclaimer and crisis/emergency stop state.
- File upload for UniTime ICS; parse timezone, recurring events and all-day entries using tested library functionality.
- Weekly class calendar; overlap detection, personal blocked periods.
- Mock clinic catalog, with synthetic slots labeled DEMO; provider sets appointment types and eligibility outside LLM.
- Deterministic ranking with explanation and conflict filtering; booking means DEMO CONFIRMED only.
- Absence period selection (student-reported; not automatically inferred as medically justified).
- Identify potentially affected meetings, including multiple days/courses.
- Course/contact resolver: source, confidence/status, manual correction; never invent contact emails.
- Generate professor-specific editable messages and unsigned provider-verification PDF.
- Student approval gate and simulated clinician review/sign-off event; deliver to controlled test recipient only.
- Persist workflow events, expose status and explainable action log.
- Clear demo vs live badges for every external integration.

### P1 | If P0 is stable
- Claude structured tool calling through a stateful orchestrator (LangGraph optional).
- Authorized Microsoft Graph email integration with explicit consent, preview, and destination allowlist.
- Live read-only UniTime subscription for consented student using SSRF-safe fetching, or user-managed ICS upload refresh.
- Notability exported PDF academic-recovery feature and development notebook.
- Accessibility improvements, measured study-session planning.

### P2 | Stretch; NOT required to claim MVP
- Cartesia realtime voice; Moss agent SDK; Factory Droid SDK if genuinely executing runtime work.
- Approved real-world clinic scheduling partnerships; authenticated provider e-signature service; verified institutional workflows.
- Real student/provider accounts with appropriate organizational approvals and compliance program.

### Explicitly out of scope
- AI diagnosis; autonomous assessment or prioritization of medical urgency; prescriptions or treatment plans.
- Booking into a live clinic without approved endpoint/credentials and user authorization.
- Forging, preapplying or generating physician signatures or official excused-absence approval.
- Circumventing Purdue SSO, scraping private student/provider data, or automated submission to ODOS without approved workflow.
- Emailing a professor clinical diagnoses or sensitive history by default.

## 5. User stories + acceptance criteria
### US-01 Student starts safe intake (P0)
As a student, I describe my situation and receive appropriate administrative support.
AC: Chat identifies product boundaries; does not claim diagnosis; links to emergency guidance when screening flags supported warning signs; no automated medical urgency score. Test with curated unsafe prompts.

### US-02 Import timetable (P0)
As a student, I import my UniTime calendar.
AC: Upload .ics and see parsed courses, start/end, timezone and recurring occurrences; malformed calendars return a recoverable error; calendar privacy explained.

### US-03 View slot options (P0)
As a student, I see clinic-supplied slots that fit my calendar.
AC: All slots have source=mock in MVP; hard constraints remove impossible options; top 3 ranked with reasons; no synthetic availability presented as real.

### US-04 Confirm slot (P0)
As a student, I choose a candidate appointment.
AC: Explicit confirmation; demo booking does not claim third-party reservation; double-click does not create duplicate records; confirmation has source status.

### US-05 Prepare absence packet (P0)
As a student, I select potential absence dates and see affected classes.
AC: Uses event occurrence dates, student-selected period and overlap rule; missing professor contact displayed as "needs review"; produces class-specific drafts with no diagnosis.

### US-06 Approve packet (P0)
As a student, I review what would be sent.
AC: Exact recipients, dates, attachments and body visible; consent separately recorded; test delivery only; consent can be withheld.

### US-07 Provider verification (P0 demo)
As a simulated provider, I approve or reject an unsigned request.
AC: Separate actor interface; no auto-filled provider signature; rejected packet cannot advance; provider's decision logged with timestamp and actor.

### US-08 Resume workflow (P0)
As a student, I see progression from pending to delivered.
AC: Approval event triggers exactly-once-or-effectively-once delivery via idempotency key; failure indicates RETRYABLE/FAILED; logs show actions without sensitive contents.

### US-09 Academic recovery (P1)
As a student, I add notes voluntarily exported from Notability.
AC: PDF associated with course/date via student selection; extracted topics marked model-generated; study tasks displayed; no undocumented Notability API assumed.

## 6. End-to-end happy path
Student opens demo persona → describes problem → system shows administrative scope + support options → ICS import → calendar rendered → selects "Find an appointment" → service returns clinic-eligible synthetic slots → optimizer ranks nonconflicting options → student confirms DEMO slot → selects absence window → app derives impacted classes → user checks instructor contacts → app drafts emails and unsigned provider request → user approves disclosure → demo provider reviews request and approves → event processor delivers to test inbox → dashboard shows DELIVERED, not "excused".

## 7. Edge and failure cases
- ICS is missing course names/timezones, contains recurrence exceptions, or duplicate UID: graceful import + review.
- No clinic slots match: offer different days or manual clinic link, never fabricate.
- Clinic slot disappears before confirmation: reconfirm availability; recompute alternatives.
- Class overlaps partially: show overlap duration and allow manual class inclusion/exclusion.
- Unknown professor: require manual confirmation; do not guess addresses.
- Disagreement between schedule and course metadata: source provenance + correction UI.
- No provider approval: packet remains pending; never auto-approve.
- Student revokes email consent: stop unsent actions; record revocation.
- Invalid recipient or failed delivery: hold packet, show error, retry only after validation.
- Possible emergency indicators: interrupt ordinary scheduling and display emergency-care instructions; tests with clinician-reviewed criteria.

## 8. Safety, privacy and trust
Use synthetic health narratives and fake users in public demos. Keep medical text out of professor messages. Health records, if ever processed beyond demo, require legal/compliance review (HIPAA applicability depends on deployment context; other privacy obligations may apply). Never send sensitive data to analytics or telemetry. Consent should be scoped to every integration and disclosure. Encrypt secrets and sensitive fields, minimize retention, and permit deletion. Label generated drafts; do not present clinician approval as a legal medical excuse. Accessibility: keyboard interaction, accessible validation, contrast and screen-reader labels.

## 9. Dependencies and assumptions
Assume browser supports .ics upload. UniTime ICS fields and instructor coverage must be inspected using test exports. Purdue.io data currency and professor email coverage are unverified until tested. Clinic API integration is NOT assumed; use a separate mock adapter. Microsoft Graph/OAuth, provider verification, Notability API, and sponsor SDKs are optional and subject to available access and documentation.

## 10. Definition of done
P0 is complete only if demo runs locally from clean setup; uploaded ICS renders; optimizer ranks only seeded slots; doc drafts use correct synthetic course details; actor approvals work; send goes solely to test inbox; all high-risk paths fail safe; README and demo walkthrough are reproducible.

## 11. Addendum — Photo-Based Visual Observations (Non-Diagnostic)

Priority: P1 after the calendar, scheduling and absence workflow is functioning; a limited demo can be P0 only if it does not displace safety and core functionality.

Purpose: Allow a student to optionally upload a skin or body-area photo to help describe visible features and prepare questions for an appropriate health professional. This is NOT disease identification, medical triage, medical urgency scoring, or diagnostic decision support.

Supported visual observations: potential apparent swelling or asymmetry, reddish areas that could represent visible blood (never verify the substance is blood), dry or flaky-looking skin, and visible discoloration potentially consistent with bruising. Images alone cannot reliably establish swelling without a comparison image or clinical context, determine whether red material is blood, identify the cause of discoloration, or distinguish benign from serious conditions.

User story CV-01: As a student, I may optionally upload a photo and receive neutral, uncertainty-aware descriptions of visible features, general low-risk comfort information, and guidance on how to contact a healthcare professional, so I can explain what I see without being diagnosed.

User story CV-02: As a student, I can correct the observations, delete the photo, and decide whether an observation summary is used when preparing an appointment request. Photo sharing is never automatic.

User story CV-03: As a student, I receive safety guidance if I report concerning symptoms; the app must not downgrade or dismiss user-reported red flags based on a reassuring photograph.

UX acceptance: (1) upfront consent and purpose notice before upload; (2) default no retention, remove EXIF and location metadata; (3) only JPEG/PNG/WebP, size/format validation; (4) generated output labels each item 'possible visual observation,' notes image-quality limitations and never states a diagnosis; (5) no numerical severity/urgency score, no claims about infection/bleeding severity; (6) a user can delete images and summaries; (7) the result provides general options such as observing changes, avoiding irritation, and seeking professional evaluation as appropriate—not prescriptions or definitive treatment.

Safety: obvious severe symptoms reported by the student (e.g., difficulty breathing, uncontrolled bleeding, sudden major swelling) trigger preapproved urgent/emergency messaging regardless of image analysis. Do not attempt to assess severity from the photo. Clinician-reviewed escalation messaging and testing are required before public release.

Success measures: percentage of images correctly rejected for invalid format, no unsupported diagnostic claims in red-team tests, structured-output validity, user comprehension, and percentage of students who find observations useful when describing a concern. Do not measure 'diagnostic accuracy' as an MVP claim.

Non-goals: identifying a disease, deciding if a wound is infected, identifying actual blood, quantifying edema or bruise age, issuing clearance/absence certification, or using photos to prioritize patients.

## 12. Amendment v1.2 — Voice-First Student Experience and Clinician-Owned Absence Workflow (AUTHORITATIVE)
This amendment supersedes earlier descriptions of a student-controlled provider-verification process where inconsistent. CuraLink has two protected interfaces: STUDENT and CLINICIAN (doctor). A professor is an authorized recipient, NOT a portal user or reviewer. The student must opt in to transmit intake information; the clinician alone determines medically supported absence dates and whether to sign. Hackathon flows use fictional accounts and explicitly simulated bookings/signatures/delivery.

### Sign-in and role selection
- Landing screen: “I am a student” / “I am a healthcare professional.” Display a disclaimer that selecting the latter does not prove clinician status.
- Student signs in with student account; clinician signs in through verified role binding managed server-side. Demo offers clearly marked demo role accounts, isolated from production data.
- A student cannot access clinician screens or sign an absence form. A clinician sees only assigned, authorized patient encounters. Professor accounts are not needed for MVP.

### US-10 Voice-first natural conversation (P0)
- Student speaks with a Cartesia-powered assistant; spoken input is streamed to transcription, structured into intake fields, and responded to aloud. Students can interrupt at any time (barge-in): playback stops immediately, stale audio/LLM output is canceled, and the new utterance is captured.
- Optional transcript with accessibility controls, mute, replay and text fallback; never make microphones mandatory. Audio/recording requires clear consent and visible state. Speaker may correct previous facts, with updates highlighted.
- Assistant does not diagnose, medically triage autonomously, or prescribe. A clinically reviewed escalation flow responds to emergency warning signs. Non-diagnostic image descriptions and reported temperature may be added as contextual evidence only.

### US-11 Contextual data-collection drawer (P0)
- When structured information is missing, the same conversation opens a focused form/chat drawer for photo upload, manually reported temperature and units, onset date, symptoms in user's own words, appointment preferences, and optional accessibility needs.
- Voice never auto-confirms a medically sensitive field; student verifies a structured summary. Photo and audio data are separately consented and can be withheld. Detect missing fields rather than inventing them.

### US-12 Consentful clinician handoff (P0)
- After selecting an appointment, the student previews an intake packet with reported symptoms, timestamps, student-entered temperature, optional photo and neutral vision observations, relevant student-provided history, communication preferences, and provenance for every field.
- Student authorizes transfer to the assigned clinician; securely hand over structured intake and a clinician-readable summary. Provide no inference that photos establish diagnosis, severity, or fitness for class. Clinician may correct and annotate the record; preserve original student statements.

### US-13 Clinician dashboard and encounter (P0)
- Doctor dashboard lists assigned upcoming appointments, intake completeness, consent state and unsigned/pending absence cases. Clinician selects an encounter; views intake timeline, images where explicitly permitted, calendar conflicts, and missing details. Only the clinician sets medically supported absence start/end dates (including multi-day ranges), medical verification wording, and whether to certify at all.
- Calendar identifies each impacted class occurrence across the clinician-specified range, handles weekends/recurrences/time zones, and never presumes the full interval automatically qualifies for a university excuse.

### US-14 Clinician-controlled signature and delivery (P0 DEMO)
- Clinician can enroll an optional reusable signature asset after authenticated identity verification. Encrypt it, restrict retrieval, and treat it as a visual representation only—not as proof of legal authorization. In demo mode it is a clearly watermarked sample signature. Do not store real signatures or live patient data for the hackathon.
- For EACH document version the clinician must open final preview, confirm specific absence dates and recipients, and click “Approve & sign.” A backend-bound signature authorization records clinician identity, UTC timestamp, document hash, version and approved destinations. A stored signature NEVER auto-pastes or auto-sends without fresh authenticated approval.
- Student authorizes permitted disclosures beforehand; clinician controls final certification and delivery. The delivery worker sends minimal verification to approved instructor addresses or appropriate university channel only after these gates. Prefer “attendance verification” over specific diagnosis, never include raw chat/photos/temperature in professor messages. School decides whether absence is officially excused.
- Allow revoke/cancel before send, corrected/reissued documents with new version and fresh approval, and delivery receipts/errors. Multi-day certificate supports explicit inclusive start and end dates as determined by the clinician.

### US-15 Technical differentiators and sponsor-fit (P1/P2)
- Voice interruption-aware finite-state conversation manager; partial-stream cancellation and transcript-to-schema extraction with evidence provenance.
- Event-sourced clinician approval pipeline; policy-as-code RBAC/ABAC; per-patient encrypted artifacts and data minimization.
- Deterministic absence impact engine and slot optimizer with explainable tradeoffs; asynchronous outbox/idempotency and real-time student/provider status sync.
- Anthropic: substantive Claude reasoning over structured admin tools with human oversight; Cartesia: truly central real-time duplex voice; Microsoft: end-to-end usefulness, reliability and responsible design; Factory Droid/Moss: optional genuine task execution only if SDK and time allow; Notability: authentic development process and optional exported-note academic recovery.

### Revised MVP acceptance gates
- Separate student and clinician personas; unauthorized cross-role access always 403.
- Voice interrupts playback and prevents stale assistant speech from reappearing; text-only fallback works.
- Assistant requests missing fields in-context; no unsupported diagnoses or invented temperature.
- Clinician sees only authorized encounter packet with per-field sources and consent state.
- Clinician alone chooses 1–N certified dates and issues per-document approval; all impacted course meetings are accurate.
- Stored signature does not trigger signing or delivery by itself. New document version invalidates prior approval.
- No faculty email sends without verified instructor destination, student disclosure consent and explicit clinician authorization; demo sends only to test allowlist.
