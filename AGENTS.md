# figma-make-app

React + Vite + Tailwind CSS project running inside Figma Make.

## Development Server

Inside Figma Make, a Vite development server is **already running** on `$PORT` (default 8443). Locally, run `./run_demo.sh` from the repo root: it starts the FastAPI backend on 8000 and Vite on 8443 (Vite proxies `/api`, including the voice WebSocket, to the backend).

- Preview URL: The user can access the running app through the preview panel
- Hot reload: Changes to source files are reflected immediately

## Project Structure

This is the canonical project structure. Start with task-relevant files below. Only follow imports or inspect other files when required, when a documented path is missing, or when the repository contradicts this guide. The frontend lives in `frontend/`; paths below are relative to it unless prefixed.

- `src/main.tsx` - React entrypoint; providers (React Query, Router, Auth) and `src/index.css`
- `src/App.tsx` - Route table and role guards (student / clinician portals)
- `src/components/` - `ui.tsx` design primitives (Icon, Button, Badge, Card, SourceBadge…), portal shells, intake panel
- `src/pages/` - `Onboarding.tsx`, `student/*`, `clinician/*`, `TestInbox.tsx`
- `src/lib/` - `api.ts` client, `types.ts` (mirrors `backend/app/schemas.py`), `auth.tsx`, `voice.ts`, `format.ts`
- `src/index.css` - Global CSS entrypoint and Tailwind CSS v4 import
- `index.html` - Vite HTML shell containing the `#root` element and loading `src/main.tsx`
- `package.json` - Project dependencies and the Vite build, development, preview, and formatting scripts
- `vite.config.ts` - Vite configuration with React, Tailwind CSS v4, and Figma Make plugins, the `@` alias for `src`, and the `/api` proxy
- `.mise.toml` - Toolchain versions for Node.js and pnpm
- `e2e/` - Playwright end-to-end tests (`npx playwright test`; both servers must be running)
- `../backend/` - FastAPI service (`uv run pytest`); see the root `README.md`
- `../docs/` - PRD, TRD, App Flow, Implementation Plan (v1.2 amendments are authoritative)

## Dependencies

- Runtime: React 19 and React DOM 19
- Styling: Tailwind CSS v4 with the `@tailwindcss/vite` plugin
- Build tooling: Vite 8, TypeScript 5.7, and `@vitejs/plugin-react`
- Formatting: oxfmt

## Styling

This project uses **Tailwind CSS v4** through the `@tailwindcss/vite` plugin configured in `vite.config.ts`. `src/index.css` imports Tailwind with `@import 'tailwindcss';`. Use Tailwind utility classes directly in JSX and put global CSS or Tailwind v4 theme customization in `src/index.css`. This scaffold does not need a Tailwind config file or PostCSS config.

`src/main.tsx` imports `src/index.css`, so global font wiring belongs in `src/index.css`. Keep CSS `@import` statements first, then add any `@font-face` rules and font-family defaults there.

Tailwind emits utility classes in `@layer utilities`, and CSS outside any cascade layer overrides every layer regardless of specificity. Put global element styles, such as resets and defaults for `body`, headings, `button`, or `input`, inside `@layer base { ... }` so utility classes on those elements still apply. Tailwind's Preflight already applies `box-sizing: border-box`, removes default margins, and sets `font: inherit` on form controls, so do not repeat those rules.
