@AGENTS.md
# CuraLink Project Instructions

@AGENTS.md

Before writing code, read:
- docs/PRD.md
- docs/TRD.md
- docs/APP_FLOW.md
- docs/IMPLEMENTATION_PLAN.md

Preserve the existing Figma-generated frontend. Do not rebuild the UI from scratch.

Build two separate role-based interfaces:
- Student: Cartesia voice assistant with interruption support, contextual data forms, computer vision observations, UniTime integration, and appointment coordination.
- Doctor: assigned patient appointments, consented intake data, doctor-selected multi-day absences, document generation, securely stored signatures, mandatory final review, and authorized delivery.

Use React/TypeScript for the frontend and Python/FastAPI for the backend.

Never let AI diagnose, prescribe, certify absences, or automatically sign documents. Use fictional patient data for demos.

Work in small, testable increments. Run tests and preserve the current frontend design.