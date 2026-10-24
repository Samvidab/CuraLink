"""CuraLink API entrypoint. Run: `uv run uvicorn app.main:app --reload --port 8000`."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import select

from app import db as dbmod
from app.config import get_settings
from app.errors import install as install_errors
from app.models import User
from app.routers import absence, auth, clinician, intake, scheduling, student, system, voice
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
    finally:
        gen.close()


@asynccontextmanager
async def lifespan(_: FastAPI):
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
    for r in (system.router, auth.router, student.router, scheduling.router, intake.router, voice.router, absence.router, clinician.router):
        app.include_router(r)
    return app


app = create_app()
