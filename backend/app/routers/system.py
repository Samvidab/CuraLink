from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.errors import ApiError
from app.models import User
from app.schemas import DemoPersona, DemoResetOut, Health, IntegrationStatus
from app.seed import DEMO_PASSWORD, reset_demo

router = APIRouter(prefix="/api/v1", tags=["system"])


@router.get("/health", response_model=Health)
def health() -> Health:
    s = get_settings()
    return Health(
        demo_mode=s.demo_mode,
        demo_today=s.demo_today.isoformat(),
        integrations=IntegrationStatus(
            llm="live" if s.anthropic_api_key else "fallback",
            voice="live" if s.cartesia_api_key else "fallback",
        ),
    )


def _demo_only() -> None:
    if not get_settings().demo_mode:
        raise ApiError(404, "NOT_FOUND", "Not available.", recoverable=False)


@router.post("/demo/reset", response_model=DemoResetOut, dependencies=[Depends(_demo_only)])
def demo_reset(db: Session = Depends(get_db)) -> DemoResetOut:
    reset_demo(db)
    return DemoResetOut(student_id="demo-student-1")


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
