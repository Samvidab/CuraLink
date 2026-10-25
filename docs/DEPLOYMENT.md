# CuraLink — Public Deployment Plan (and where Convex fits)

Status: **prepared, not deployed.** Nothing in this document has been published. Deploy only after the team approves it.

## 1. What CuraLink is today

| Part | Technology | Notes |
|---|---|---|
| Frontend | React 19 + Vite (static build in `frontend/dist`) | Talks only to `/api` on the same origin |
| API | Python 3.11 FastAPI (≈7,400 lines in `backend/app`) | Auth sessions, scheduling engine, intake dialog, Claude tool loop, PDF certificates, encrypted signatures |
| Voice | WebSocket `/api/v1/voice/stream` held open by FastAPI | Proxies audio to Cartesia STT/TTS with barge-in; keys never reach the browser |
| Data | SQLite through SQLAlchemy (one file) | Partial unique index + write lock prevent double booking |
| Python-only libraries | `reportlab` (PDF), `pillow-heif` (HEIC), `cryptography` (AES-GCM signatures), `icalendar`, `anthropic` | |

## 2. What Convex is (verified against docs.convex.dev, 2026-10-24)

- **Server code is JavaScript/TypeScript only.** Queries, mutations, actions and HTTP actions are TS/JS ([Functions](https://docs.convex.dev/functions)). Convex does **not** run our Python FastAPI service.
- **Database:** document database. Mutations are transactional. Queries and mutations have a 1-second user-code limit; actions run up to 10 minutes (Node runtime, 512 MiB) or 30 minutes (Convex runtime) ([Limits](https://docs.convex.dev/production/state/limits)).
- **Real-time:** clients subscribe to queries and receive updates automatically (the Python client also supports `subscribe`).
- **File storage:** yes (Free plan: 1 GB storage, 1 GB/month egress).
- **Auth:** integrates with identity providers (Convex Auth, Clerk, Auth0, custom JWT). Our current cookie sessions would have to be redesigned.
- **Frontend hosting:** Convex's docs direct you to **Vercel or Netlify** (or custom hosting) ([Hosting](https://docs.convex.dev/production/hosting/)). Convex doesn't host the React app for us.
- **Python access:** the official `convex` PyPI package (`ConvexClient(url).query(...)` / `.subscribe(...)`) lets Python call Convex functions ([Python quickstart](https://docs.convex.dev/quickstart/python)).
- **No arbitrary WebSocket server:** our browser ↔ server ↔ Cartesia voice proxy has to stay on a server we control.

## 3. Options

| Option | What changes | Effort / risk before the demo | Recommendation |
|---|---|---|---|
| **A. Ship the existing app as one container** (Dockerfile in repo root) on a container host with a persistent volume (Fly.io, Render or Railway) | Nothing functional. FastAPI serves the API, voice WebSocket and built frontend from one HTTPS origin | Low. Already smoke-tested locally in production mode | **Recommended for Cal Hacks** |
| B. Hybrid: Convex as system of record, FastAPI stays for AI/voice/PDF | Rewrite persistence (~25 tables) as Convex tables and mutations; FastAPI calls Convex via the Python client with a deploy key; re-implement transactional booking and authorization as Convex mutations; auth redesign | High (days). Two places to secure; adds a network hop to every request | After the hackathon, if real-time multi-device sync becomes a priority |
| C. Full Convex rewrite | Port all ~7,400 lines to TypeScript and find TS replacements for reportlab, pillow-heif and the Cartesia proxy (which still needs a separate server) | Very high | Not advised |

The $75 Convex credit isn't needed for Option A. Keep it for Option B if the team pursues real-time sync later. Redeem it yourselves through Convex's official process; **never** paste the code into chat, commit it, or put it in `.env`.

## 4. Option A — exact steps (example: Fly.io; Render and Railway are equivalent)

Prerequisites: Docker running locally (only needed to build locally); a Fly.io account; `flyctl` installed.

```bash
# from the repo root, on the reviewed commit of feature/mvp-finalization
fly launch --no-deploy --name curalink-demo --region ord --internal-port 8000   # writes fly.toml; review it
fly volumes create curalink_data --size 1 --region ord                           # persistent SQLite + backups
# add to fly.toml:   [mounts] source = "curalink_data"  destination = "/data"

fly secrets set \
  ANTHROPIC_API_KEY=... CARTESIA_API_KEY=... CARTESIA_VOICE_ID=... \
  SIGNATURE_ENCRYPTION_KEY="$(python3 -c 'import secrets,base64;print(base64.b64encode(secrets.token_bytes(32)).decode())')" \
  DEMO_CONTROLS=token DEMO_ADMIN_TOKEN="$(python3 -c 'import secrets;print(secrets.token_urlsafe(32))')" \
  CORS_ORIGINS=https://curalink-demo.fly.dev

fly deploy                      # builds the Dockerfile remotely
fly status && curl -s https://curalink-demo.fly.dev/api/v1/health
```

Run **one machine**. SQLite allows a single writer, and the double-booking protection relies on its write lock. Don't scale out without moving to Postgres plus a Postgres partial unique index.

### Environment variables

| Variable | Required in production | Purpose |
|---|---|---|
| `ENVIRONMENT=production` | set by Dockerfile | Turns on the startup self-check (`backend/app/deploy_checks.py`) |
| `COOKIE_SECURE=true` | set by Dockerfile | HTTPS-only session cookie (HttpOnly, SameSite=Lax) |
| `DATABASE_URL=sqlite:////data/curalink.db` | set by Dockerfile | Must point at the mounted volume |
| `FRONTEND_DIST=/app/frontend/dist` | set by Dockerfile | Serve the built SPA from the API origin |
| `CORS_ORIGINS` | yes | The public `https://` origin only |
| `SIGNATURE_ENCRYPTION_KEY` | yes | 32-byte base64 key for drawn-signature encryption |
| `DEMO_CONTROLS` / `DEMO_ADMIN_TOKEN` | yes (`token` + ≥24 chars, or `off`) | Protects `/demo/reset`, `/demo/book-as-other`, `/demo/transport/fail-next` |
| `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL` | optional | Claude; missing → labelled scripted fallback |
| `CARTESIA_API_KEY`, `CARTESIA_VOICE_ID` | optional | Voice; missing → labelled browser-speech fallback |
| `DEMO_MODE=true` | default | Fictional data only; there is no non-demo mode |

The service refuses to start if production settings are unsafe. It lists each problem by **name** and never prints a value.

### Security notes for the public demo

- **Secrets:** API keys exist only as platform secrets, read by FastAPI. The frontend bundle contains none: there are no `VITE_*` secrets.
- **Sessions:** HttpOnly + Secure cookies on the same origin. State-changing requests need the `X-CuraLink-Client` header. The voice WebSocket checks `Origin` and the session.
- **Authorization:** roles come from the database. Clinicians reach only encounters assigned to them, and a cancelled appointment ends access. Students reach only their own records. The test inbox shows only the viewer's own (or assigned) cases.
- **Photos:** metadata is stripped and the image is stored as a database blob, served only to the owner or an assigned clinician the student selected, with `Cache-Control: no-store`.
- **Demo admin endpoints:** 404 unless `DEMO_CONTROLS` allows them (token header or off).
- **Data:** fictional only. Account sign-up is open in demo mode, so tell testers to use fictional details.
- **Logging:** access paths and status only; no request bodies, symptoms, transcripts or secret values.
- **Health:** `GET /api/v1/health` reports which integrations are live or fallback, without values. The Docker `HEALTHCHECK` polls it.

### Local development is unchanged

`./run_demo.sh` (8000/8443) and `./run_demo.sh e2e` (isolated 8011/8454) keep `ENVIRONMENT=local` and `DEMO_CONTROLS=open`. The existing `backend/curalink_demo.db` is never migrated or deleted by deployment: a fresh deployment seeds its own fictional data on the volume.

## 5. Release gate (all must pass before publishing)

| Gate | How it's verified |
|---|---|
| Student and clinician login; no automatic sign-in | `e2e/accounts.spec.ts`, `tests/test_accounts.py` |
| Voice AI works | Live Cartesia check on the deployed URL (manual: section "Live check: Cartesia" in README) |
| Contextual temperature and photo inputs | `e2e/conversation-photo-semester.spec.ts`, `tests/test_previsit.py` |
| Clinician-aware scheduling, appointments persist | `e2e/scheduling.spec.ts`, `tests/test_scheduling.py` |
| Assigned clinician sees consented pre-visit notes grouped by session and date | `e2e/previsit-demo.spec.ts`, `tests/test_previsit.py` |
| Only clinicians set certified absence dates | `tests/test_absence.py`, `e2e/absence.spec.ts` |
| Document review and signing | `e2e/absence.spec.ts` |
| API keys protected; unsafe production config refused | `tests/test_deploy.py`, production smoke test (section 4) |
| Full suite green | `uv run pytest`, `./run_demo.sh e2e`, `npx tsc --noEmit -p .`, `pnpm build` |

## 6. If the team later chooses Option B (Convex as system of record)

1. Model each SQLAlchemy table as a Convex table; keep our string IDs in an indexed `legacyId` field, and store foreign keys as Convex `Id<>` references.
2. Port authorization into every Convex query and mutation (the student or assigned-clinician checks in `routers/*.py`). Never trust a client-supplied role.
3. Port booking as one Convex mutation: re-validate availability, check overlaps, insert. Mutations are serializable, which replaces the SQLite write lock.
4. Export with a one-off script: read SQLite, then write through an authenticated Convex mutation in dependency order (users → profiles/rules → calendars/events → sessions/fields/attachments → appointments/encounters → packets → cases/decisions/documents/deliveries).
5. Verify referential integrity: per-table row counts match, and every reference resolves. The script must fail on any orphan.
6. Run both in parallel on a copy of the demo data before switching; keep SQLite as a rollback.
