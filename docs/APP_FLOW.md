# CURALINK | APPLICATION FLOW & UI/UX SPECIFICATION
Version 1.0 • Hackathon MVP • October 23, 2026

## 1. Experience principles
Warm and reassuring but not diagnostic; highly legible; honest about synthetic integrations; user always knows what will happen next. Core design promise: the app handles administrative steps, while each authority approves only the decision they own. Every generated medical/academic document is clearly tagged "Draft" until approved. No implicit email sending or clinic booking.

## 2. Information architecture
Routes:
- / = Landing/entry: "Health situations are hard. Coordination shouldn't be."
- /onboarding = connect/import calendar, timezone, consent, demo explanation
- /dashboard = classes today, pending cases, appointment state, primary action
- /assistant = chatbot conversation, action cards and safety notices
- /calendar = weekly calendar and editable personal blocks
- /appointments = appointment options with scoring rationales
- /absences = impacted classes and date-range selector
- /absences/:id/review = email/PDF review and student approval
- /activity = event history, status, error/retry
- /demo/provider = fictional provider review portal clearly marked DEMO
- /settings = integrations, calendar removal, delete demo data

## 3. Design system and components
Brand: CuraLink. Palette: deep teal #0F766E, sea-glass #CCFBF1, neutral ink #18303A, slate #64748B, off-white #F8FAFC; errors #B91C1C. Type: Inter or system UI. 8-point spacing system. Radius 12–16 px. Responsive desktop sidebar (240 px), mobile bottom navigation. Keyboard-accessible focus rings, descriptive buttons, accessible labels, status live regions. Never use color alone to distinguish clinical/demo states.
Shared components: AppShell, Sidebar, StatusPill, SourceBadge(DEMO/UPLOADED/REAL), SessionHeader, ChatBubble, SafetyNotice, CalendarGrid, SlotCard, RankingExplanation, AffectedClassRow, EmailDraftEditor, PDFPreview, ApprovalTimeline, ConsentDialog, ActivityEvent, EmptyState, ErrorBanner, Toast, LoadingSkeleton.

## 4. Flow A — onboarding and calendar import
Entry → Welcome → Select "Try with fictional student" or "Import my UniTime .ics" → privacy explainer → ICS dropzone → parser progress → detected timezone and courses → review/resolve unknown names → calendar ready → dashboard. Show clear consent that imported academic schedule stays in demo session; do not ask for UniTime password.
States: empty, dragging, uploading, parsing, success, partial_success, error, calendar_review_required. If broken import, offer sample calendar instantly.

## 5. Flow B — conversation and support
Dashboard CTA "Help me coordinate care" → assistant shows notice "I can organize care, not diagnose" → user enters situation → optional follow-up for administrative needs; a limited safety handler routes possible emergencies to prominent appropriate-care guidance → if routine coordination requested, action card "Find appointment options" → /appointments. Do not present condition rankings, self-treatment advice, or a definitive medical urgency score. Include "Contact a clinician" and "Emergency help" guidance routes; safety notice should interrupt the flow when indicated.
Chat content layouts: left assistant, right user, chronological. Assistant tool-calling progress cards: "Reading class calendar", "Comparing eligible slots", "Preparing drafts". Stream status only, not sensitive intermediate reasoning. Chat retains edit/cancel.

## 6. Flow C — scheduling
Appointments page includes: weekly calendar left; right column: source status, appointment type (selected from clinic catalog), ranked cards. Each card displays start-end, clinic location (mock), travel, conflicts, and reasons. Reject pane shows infeasible options and reasons. CTA "Confirm demo appointment" only after explicit explanation of simulated booking. If clinic slot expires during confirmation, show updated alternatives without silent rescheduling. On success, show confirmation card and next action "Prepare absence support".
Sort default: feasible then lower score; filter accessible transport, dates and conflict allowances; never claim urgency inferred by AI. No results: adjust timeframe or visit clinic manually.

## 7. Flow D — absence case and academic matching
Start from appointment success or dashboard → date range picker (user decides dates) → map to ICS meeting occurrences → list affected courses with overlap duration and contact confidence. Editable toggles for each course; no extrapolating that a medical visit automatically excuses an entire day. If professor unknown, chip "Contact needed" with manual field; no guessed email. CTA "Create drafts".

## 8. Flow E — document review and approval
Review is 3 columns on desktop or stacked on mobile: selected classes, editable professor emails, unsigned provider request PDF preview. Confirmations: (1) I reviewed class dates and recipients; (2) I consent to send these limited details after required approvals. If a draft contains sensitive medical details, show redaction warning and remove by default. On approval, mark status PENDING_PROVIDER_REVIEW; show "Nothing has been sent yet".
Demo provider screen requires explicit action Approve/Reject using separate persona toggle, records timestamp, never inserts handwritten signature. If approved, an event creates a test-only delivery action after consent recheck. Student sees QUEUED → DELIVERED with recipient test inbox and timestamp; explicit "Not an official excused absence" copy.

## 9. Flow F — optional Notability catch-up
Student clicks "Catch up" → selects affected class → uploads Notability-exported PDF notes or slides with right to use → sees topics extracted with low-confidence markers → manually edits checklist → adds review blocks to local planner. No claim of direct Notability account sync.

## 10. Screen-by-screen field and validation checklist
### Dashboard
Display: upcoming class events, next demo appointment, absence case state, activity history, chat CTA. Empty: import schedule. Error: retry data load.
### Assistant
Display: conversation and typed tool status, disclaimer link, visible emergency escalation. Disable submit while safety overlay active; preserve input after recoverable errors.
### Calendar
Display: week/day toggle, events with course/section/location/source, timezone. Tap event for details; partial imported record shows warning.
### Appointments
Display: source badge, ranked slots, conflict explanation, explicit confirm modal. Confirm button disabled for stale/unavailable slots.
### Absences
Display: date range, course occurrences, overlap, contact verification status. Generate disabled if no date or all classes excluded.
### Document Review
Display: editable draft, exact recipients, unsigned provider form, version. Delivery disabled until consent, provider approval and verified destination.
### Activity
Display: timestamps, event types, actor roles, compact reasons. Do NOT show full patient narrative or secrets in logs.

## 11. Detailed microcopy
- Medical scope: "CuraLink helps coordinate care and academic paperwork. It doesn't diagnose conditions or decide medical urgency."
- Demo slot: "Demo appointment — not booked with a real clinic."
- Pending provider: "Waiting for provider review. No medical verification has been issued."
- Provider rejected: "Verification was not approved. Your drafts are saved, but cannot be delivered as approved documentation."
- Sent: "Delivered to a test inbox. Your university decides whether any absence is excused."
- Missing instructor: "We couldn't verify this instructor's contact information. Please check it before sending."
- No slot: "No eligible appointments matched your calendar. Try another date or contact the clinic."

## 12. Navigation diagram (text)
Landing → Onboarding → Dashboard → Assistant → Appointment Options → Demo Confirmation → Absence Selection → Draft Review → Student Approval → Demo Provider Review → Test Delivery → Activity.
Dashboard ↔ Calendar; Dashboard ↔ Absence Center; Dashboard ↔ Activity. Every flow supports back and save draft. Alternate branches: Emergency Guidance (stops routine flow); Invalid Calendar (sample fallback); Slot Unavailable (re-ranking); Provider Reject (review state); Consent Revoke (cancel queued delivery).

## 13. Interaction spec: example tasks
Task 1: Import sample ICS; expectation: class cards appear within 3s target and show timezone.
Task 2: Ask "I feel sick and need a doctor's appointment"; expectation: non-diagnostic intake + care coordination CTA.
Task 3: Choose first eligible slot; expectation: conflict-free option with explainable tradeoffs, explicit demo booking.
Task 4: Choose date with CS and MA classes; expectation: both show with correct overlap and drafts.
Task 5: Leave professor email blank; expectation: approval/delivery blocked.
Task 6: Approve as demo provider; expectation: event history updates, one test email sent if prior consent exists.

## 14. Accessibility, responsiveness and privacy
At 375px wide, cards stack and PDF has "Open preview" instead of embedded multi-column view. Minimum touch target 44px. Focus management for dialogs. Screen reader announcement on changed workflow status. Do not use symptom text in URL/search params; no logging to client analytics. User can delete session/calendar data; permanent real-world retention policy is future work.

## 15. Design handoff acceptance
Each screen has states for loading, empty, error, success; consistent status vocabulary; no hidden approval actions; a user can recover from every nonfatal failure; source_mode always visible for clinic listings; no fake signature imagery.

## 16. Addendum — Photo Observation User Flow

Entry points: assistant offers 'Add a photo (optional)' and a 'Photo observations' tab in the consultation flow. The app must work without a photo.

Step 1: Consent sheet explains: 'CuraLink can describe some visible features, but a photo cannot tell us what is causing them. This is not a diagnosis, and photos will not be shared with your professor.' Separate unchecked consent to photo analysis; explicit notice of any temporary upload.

Step 2: Image picker/camera with user-controlled crop, preview, retake, remove, and image-quality tips (good lighting, in focus; avoid including face or identifying objects unless necessary). Do not pressure students to photograph sensitive areas.

Step 3: Analyzing state shows upload and analysis progress without claims of clinical review; processing failure preserves ability to continue without photo.

Step 4: Results screen titled 'Possible visual observations' with neutral cards: 'Apparent puffiness/asymmetry', 'Red-appearing area (not verified as blood)', 'Dry/flaky appearance', 'Discoloration (cannot confirm bruising)'. Only show categories supported by the specific image and allow 'Nothing clear enough to describe'. Include image-quality limitations and 'This does not establish a diagnosis or severity.'

Step 5: Offer non-specific practical actions such as keeping track of changes and contacting a qualified healthcare professional when concerned; avoid tailored treatment, medication or dismissal of symptoms. User-reported red flags invoke clinician-reviewed urgent guidance independent of photo content.

Step 6: Student may edit/correct observation text and opt to add it to their appointment intake summary; default is not to share. The professor-facing absence workflow never inherits image data, symptom details, or medical observations.

Accessibility: descriptive upload controls, keyboard support, screen reader progress announcements, color-independent visual labels, alt text for user image preview and plain-language uncertainty.

Failure states: no consent, unsupported format, file too large, blurry image, unsafe image, model timeout, conflicting observations, deleted image. Each provides a clear retry or 'Continue without photo' action.

Demo sequence: select fictional/synthetic example image -> see limited observation with uncertainty -> approve inclusion in appointment intake -> scheduling continues with clinic-provided eligible slots; no clinical inference alters appointment priority.

## 17. Amendment v1.2 — Dual-Portal Voice-First Experience (AUTHORITATIVE)
This section supersedes earlier descriptions of student or demo-provider responsibilities where inconsistent. The only app personas are Student and Clinician (doctor); professor is an email recipient, not a portal role. Clearly label demo bookings and fictional documents.

### Landing and sign-in screen
Two prominent cards: “I'm a student” and “I'm a healthcare professional.” Student route -> student auth -> student dashboard. Clinician route -> clinician verification / clinician demo credentials -> clinician dashboard. Role selection is presentation only; backend authorization determines access. Show role switch only after logout.

### Student experience navigation
Student tabs: Home | Talk to CuraLink | Calendar | Appointments | My Cases | Settings. Default action is a prominent “Start voice conversation” with visible microphone permissions, voice consent, start/end state, live caption and text-mode toggle. At all times render a mic activity indicator, playback state and “Interrupt” control (speech barge-in should also work naturally). Never require voice for accessibility.
- Conversation canvas: waveform, captions, transcript segments with “correct this,” contextual intake progress, “What CuraLink knows” structured summary card.
- Whenever the agent needs a temperature, photo or unspoken required field, a collapsible right-side panel (mobile bottom sheet) opens with temperature numeric input + units + measured time, photo capture/upload + preview + consent, symptom onset date, free-text note. Return to voice automatically after submit or skip; keep transcript and form in one synchronized session.
- At end, show “Review what will be sent to your clinician” with each structured field and provenance (Spoken / Entered / Image observation). Checkboxes control photo sharing and voice transcript sharing independently; raw audio is not shared by default. Student confirms and submits; clear success and revoke-before-review affordance.
- Appointment page ranks clinic-authorized available times against UniTime; appointment selection requires explicit confirmation. While booking is unavailable, use “Open clinic booking page” rather than claiming confirmation.
- Student My Cases shows clinic handoff status, visit status, documentation progress, delivery receipts, and optional academic recovery. It must not show private clinician notes or stored signature.

### Clinician dashboard and encounter workspace
Left nav: Appointments | Intake Queue | Absence Cases | Document Review | Signature Settings | Activity. Main dashboard shows Today / Upcoming appointment rows (time, student, intake received, needs review, absence pending) with statuses but avoids sensitive symptom preview on list cards.
- Encounter detail: patient identity, appointment details, structured student-reported intake, optional shared images with privacy warning and neutral CV description, consent metadata and provenance, editable clinician notes. Distinguish patient reports from clinician findings. Missing-data request may be sent back to student through secure portal.
- Absence composer: clinician selects inclusive first/last excused/verified date via two date pickers; system previews impacted class occurrences grouped by instructor including term, class, local dates, verified recipient status. Clinician edits wording and may choose shorter range, decline certification or return for correction. No AI-generated or preselected clinical duration.
- Signature settings: upload/draw a reusable signature, name/credentials, revoke/delete, clear warning: asset NEVER automatically authorizes use. In demo only show fictional sample signature with DEMO watermark.
- Final review: show full PDF preview + exact date interval, affected classes, recipients and minimal disclosure; “Approve & sign this version” CTA requires reauthentication/explicit fresh confirmation. On sign, display immutable signed version, timestamp and verification metadata. “Send authorized copies” requires separately verified authorization and targets test inbox in demo. Editing anything returns to unsigned state.
- Activity: statuses DRAFT / NEEDS_REVIEW / AWAITING_SIGNATURE / SIGNED / QUEUED / SENT / FAILED; show delivery receipts and retry, never claim university approval.

### Role-specific screen states and dialogs
- Voice states: ready / requesting mic / listening / thinking / speaking / interrupted / reconnecting / text fallback; interrupted speech clears old assistant audio without removing committed intake.
- Medical safety state: present approved emergency help guidance and stop routine scheduling suggestions; never classify diagnosis or assign clinical time-to-care independently.
- Clinician absence range crossing weekend: show only actually occurring classes, group repeated occurrences, and show skipped/no-class days.
- Signed-document edit dialog: “Changes will invalidate the existing signature and require another review.”
- Recipient not verified: no Send button, show required correction.
- Student consent withdrawn: clinician sees packet unavailable/withdrawn, no new delivery; previously delivered documents cannot be recalled and this is clearly explained.
- Unauthorized access: 403 page, no leaked patient names or details. No doctor-selectable demo role switch allowed in real deployment.

### Responsive UI / interaction quality
Use semantic buttons, focus rings, captions, keyboard controls for voice, no auto-play before user initiation, upload alt/metadata, visible privacy states. On mobile voice view is single-column and structured intake panel slides upward; clinician full document/signing is optimized for desktop. Limit sensitive screen previews, do not surface patient details in notifications or URL query parameters.

### Showcase end-to-end sequence
Student signs in -> interrupts AI mid-response -> sends spoken symptoms -> intake form appears to add temperature/photo -> confirms handoff packet -> selects available demo clinic slot -> Clinician signs in -> opens appointment -> reads student-shared data -> chooses medically supported 3-day interval -> sees affected recurring classes -> previews PDF with stored sample signature available -> explicitly signs this exact version -> authorizes mock test-only sends -> student status updates. Never describe this demo as actual clinical care or university-certified absence.
