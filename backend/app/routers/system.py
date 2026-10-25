import hmac

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.errors import ApiError
from app.models import User
from app.security import current_user
from app.schemas import DemoPersona, DemoResetOut, Health, IntegrationStatus
from app.seed import DEMO_PASSWORD, reset_demo
from app.services import llm_gateway

router = APIRouter(prefix="/api/v1", tags=["system"])


@router.get("/health", response_model=Health)
def health() -> Health:
    s = get_settings()
    return Health(
        demo_mode=s.demo_mode,
        demo_today=s.demo_today.isoformat(),
        integrations=IntegrationStatus(
            llm=llm_gateway.status(),
            voice="live" if s.cartesia_api_key else "fallback",
        ),
        llm_detail=llm_gateway.detail(),
        convex=_convex_status(),
        limits={"photo_mb": get_settings().max_upload_mb},
    )


def _convex_status() -> dict:
    from app.services import convex_bridge

    if not convex_bridge.enabled():
        return {"enabled": False}
    st = convex_bridge.STATUS
    return {"enabled": True, "last_ok": st["last_ok"], "last_error": st["last_error"], "records_pushed": st["pushed"]}


@router.get("/convex/token")
def convex_token(user: User = Depends(current_user)) -> dict:
    """Short-lived token so the browser can read ITS authorized records from Convex (real-time views)."""
    from app.services import convex_bridge

    return {"token": convex_bridge.mint(user), "expires_in": convex_bridge.TOKEN_TTL}


def _demo_only() -> None:
    if not get_settings().demo_mode:
        raise ApiError(404, "NOT_FOUND", "Not available.", recoverable=False)


def demo_admin(request: Request) -> None:
    """Destructive demo controls (reset, simulated other bookings, forced failures). Open only on a laptop;
    a public deployment uses DEMO_CONTROLS=token (header X-CuraLink-Admin) or off. Same 404 either way."""
    s = get_settings()
    _demo_only()
    if s.demo_controls == "open":
        return
    supplied = request.headers.get("X-CuraLink-Admin", "")
    if s.demo_controls == "token" and s.demo_admin_token and hmac.compare_digest(supplied, s.demo_admin_token):
        return
    raise ApiError(404, "NOT_FOUND", "Not available.", recoverable=False)


@router.post("/demo/reset", response_model=DemoResetOut, dependencies=[Depends(demo_admin)])
def demo_reset(db: Session = Depends(get_db)) -> DemoResetOut:
    reset_demo(db)
    from app.services import convex_bridge

    if convex_bridge.enabled():
        convex_bridge.full_sync(reset_all=True)  # Convex mirrors the fresh fictional data, nothing stale
    return DemoResetOut(student_id="demo-student-1")


@router.post("/demo/convex-resync", dependencies=[Depends(demo_admin)])
def convex_resync() -> dict:
    """Admin repair: push every current record to Convex (e.g. after an outage)."""
    from app.services import convex_bridge

    if not convex_bridge.enabled():
        raise ApiError(409, "CONVEX_DISABLED", "Convex sync isn't configured.")
    return {"pushed": convex_bridge.full_sync()}


@router.get("/demo/personas", response_model=list[DemoPersona], dependencies=[Depends(_demo_only)])
def demo_personas(db: Session = Depends(get_db)) -> list[DemoPersona]:
    users = db.scalars(select(User).where(User.demo.is_(True)).order_by(User.role.desc(), User.id)).all()
    return [
        DemoPersona(
            role=u.role,
            display_name=u.display_name,
            email=u.email,
            note=f"Fictional account · password '{DEMO_PASSWORD}'" + ("" if u.role == "student" or u.clinician_verified else " · NOT verified (access denied)"),
        )
        for u in users
    ]
