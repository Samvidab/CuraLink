from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.errors import ApiError
from app.models import User
from app.schemas import DemoLoginIn, LoginIn, MeOut
from app.security import current_user, end_session, permissions_for, start_session, verify_password
from app.services import audit

router = APIRouter(prefix="/api/v1", tags=["auth"])

DEFAULT_PERSONA = {"student": "demo-student-1", "clinician": "demo-clinician-1"}


def me_out(user: User) -> MeOut:
    return MeOut(
        id=user.id, role=user.role, display_name=user.display_name, email=user.email, timezone=user.timezone,
        demo=user.demo, credentials=user.credentials, permissions=permissions_for(user),
    )


@router.post("/auth/demo/login", response_model=MeOut)
def demo_login(body: DemoLoginIn, response: Response, db: Session = Depends(get_db)) -> MeOut:
    """Demo-only shortcut. The persona picks a *fixture account*; the role still
    comes from the database row, never from the request."""
    if not get_settings().demo_mode:
        raise ApiError(404, "NOT_FOUND", "Not available.", recoverable=False)
    user = db.get(User, DEFAULT_PERSONA[body.persona])
    if user is None:
        raise ApiError(503, "DEMO_NOT_SEEDED", "Demo data is missing. Run the demo reset.")
    start_session(db, response, user)
    audit.record(db, actor_role=user.role, actor_id=user.id, action="SIGNED_IN", detail="demo persona")
    db.commit()
    return me_out(user)


@router.post("/auth/login", response_model=MeOut)
def login(body: LoginIn, response: Response, db: Session = Depends(get_db)) -> MeOut:
    user = db.scalar(select(User).where(func.lower(User.email) == body.email.strip().lower()))
    if user is None or not verify_password(body.password, user.password_hash):
        raise ApiError(401, "INVALID_CREDENTIALS", "Email or password is incorrect.")
    if body.expected_role and user.role != body.expected_role:
        # Signing in through the wrong portal never switches roles.
        raise ApiError(403, "WRONG_PORTAL", f"This account can't use the {body.expected_role} portal.", recoverable=False)
    if user.role == "clinician" and not user.clinician_verified:
        raise ApiError(403, "CLINICIAN_NOT_VERIFIED", "This clinician account hasn't been verified, so it can't access patient information.", recoverable=False)
    start_session(db, response, user)
    audit.record(db, actor_role=user.role, actor_id=user.id, action="SIGNED_IN")
    db.commit()
    return me_out(user)


@router.post("/auth/logout", status_code=204)
def logout(request: Request, response: Response, db: Session = Depends(get_db)) -> Response:
    end_session(db, request, response)
    response.status_code = 204
    return response


@router.get("/me", response_model=MeOut)
def me(user: User = Depends(current_user)) -> MeOut:
    return me_out(user)
