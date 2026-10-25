"""CuraLink API entrypoint. Run: `uv run uvicorn app.main:app --reload --port 8000`."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import select

from app import db as dbmod
from app.config import get_settings
from app.errors import ApiError
from app.errors import install as install_errors
from app.models import User
from app.routers import absence, auth, clinician, intake, scheduling, student, system, vision, voice
from app.security import CLIENT_HEADER

log = logging.getLogger("curalink")
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def _ensure_seeded() -> None:
    dbmod.create_all()
    gen = dbmod.get_db()
    db = next(gen)
    try:
        if get_settings().demo_mode and db.scalar(select(User).limit(1)) is None:
            from app.seed import reset_demo

            reset_demo(db)
            log.info("Seeded fictional demo data.")
        elif get_settings().demo_mode:
            from app.services.availability import ensure_demo_data
            from app.services.names import backfill_demo_names

            backfill_demo_names(db)  # older demo databases: add missing names, keep every record
            changes = ensure_demo_data(db)  # add missing demo clinician hours; never resets anything
            from app.services.intake_service import close_untranscribed_sessions

            changes["conversations_ended"] = close_untranscribed_sessions(db)
            if any(changes.values()):
                log.warning("Demo data upgrade: %s", changes)
    finally:
        gen.close()


@asynccontextmanager
async def lifespan(_: FastAPI):
    s = get_settings()
    if s.environment == "production":
        from app.deploy_checks import production_problems

        problems = production_problems(s)
        if problems:
            raise RuntimeError("Refusing to start a public deployment:\n- " + "\n- ".join(problems))
    log.info("CuraLink API starting (environment=%s, demo_mode=%s, demo_controls=%s, llm=%s, voice=%s)", s.environment, s.demo_mode, s.demo_controls,
             "configured" if s.anthropic_api_key else "fallback", "configured" if s.cartesia_api_key else "fallback")
    _ensure_seeded()
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="CuraLink API", version="0.1.0", lifespan=lifespan)
    install_errors(app)

    @app.middleware("http")
    async def require_client_header(request: Request, call_next):
        # CSRF defence: state-changing API calls must carry a custom header,
        # which browsers won't send cross-site without a CORS preflight.
        if request.url.path.startswith("/api/") and request.method not in SAFE_METHODS and request.headers.get(CLIENT_HEADER) != "web":
            return JSONResponse({"code": "MISSING_CLIENT_HEADER", "message": "Request rejected.", "recoverable": False, "details": {}}, status_code=403)
        return await call_next(request)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE"],
        allow_headers=["Content-Type", CLIENT_HEADER],
    )
    for r in (system.router, auth.router, student.router, scheduling.router, intake.router, voice.router, vision.router, absence.router, clinician.router):
        app.include_router(r)
    if settings.frontend_dist:
        _serve_frontend(app, settings.frontend_dist)
    return app


def _serve_frontend(app: FastAPI, dist) -> None:
    """Serve the built React app from the same origin as the API (single deployable)."""
    from pathlib import Path

    from fastapi.responses import FileResponse
    from fastapi.staticfiles import StaticFiles

    root = Path(dist).resolve()
    index = root / "index.html"
    if not index.is_file():
        raise RuntimeError(f"FRONTEND_DIST has no index.html: {root}")
    app.mount("/assets", StaticFiles(directory=root / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        if path.startswith("api/"):
            raise ApiError(404, "NOT_FOUND", "Not found.")
        f = (root / path).resolve()
        if path and f.is_file() and root in f.parents:  # public files such as the logo; no path traversal
            return FileResponse(f)
        return FileResponse(index, headers={"Cache-Control": "no-cache"})


app = create_app()
