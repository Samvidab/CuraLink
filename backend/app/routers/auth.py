import re
from uuid import uuid4

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.errors import ApiError
from app.models import User
from app.schemas import ClinicianRegisterIn, DemoLoginIn, LoginIn, MeOut, RegisterIn
from app.security import current_user, end_session, hash_password, permissions_for, start_session, verify_password
from app.services import audit, names

router = APIRouter(prefix="/api/v1", tags=["auth"])

DEFAULT_PERSONA = {"student": "demo-student-1", "clinician": "demo-clinician-1"}
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")
_LABEL = re.compile(r"^[\w][\w .,'()&/\-]*$")


def me_out(user: User) -> MeOut:
    return MeOut(
        id=user.id, role=user.role, display_name=user.display_name, email=user.email, timezone=user.timezone,
        demo=user.demo, credentials=user.credentials, permissions=permissions_for(user),
        first_name=user.first_name, last_name=user.last_name, preferred_name=user.preferred_name,
        clinical_role=user.clinical_role, profile_complete=names.profile_complete(user),
    )


@router.post("/auth/demo/login", response_model=MeOut)
def demo_login(body: DemoLoginIn, request: Request, response: Response, db: Session = Depends(get_db)) -> MeOut:
    """Demo-only shortcut. The persona picks an existing *fixture account* (never creates one); the role
    still comes from the database row, never from the request."""
    if not get_settings().demo_mode:
        raise ApiError(404, "NOT_FOUND", "Not available.", recoverable=False)
    user = db.get(User, DEFAULT_PERSONA[body.persona])
    if user is None:
        raise ApiError(503, "DEMO_NOT_SEEDED", "Demo data is missing. Run the demo reset.")
    start_session(db, request, response, user)
    audit.record(db, actor_role=user.role, actor_id=user.id, action="SIGNED_IN", detail="demo persona")
    db.commit()
    return me_out(user)


@router.post("/auth/login", response_model=MeOut)
def login(body: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)) -> MeOut:
    user = db.scalar(select(User).where(func.lower(User.email) == body.email.strip().lower()))
    if user is None or not verify_password(body.password, user.password_hash):
        raise ApiError(401, "INVALID_CREDENTIALS", "Email or password is incorrect.")
    if body.expected_role and user.role != body.expected_role:
        # Signing in through the wrong portal never switches roles.
        raise ApiError(403, "WRONG_PORTAL", f"This account can't use the {body.expected_role} portal.", recoverable=False)
    if user.role == "clinician" and not user.clinician_verified:
        raise ApiError(403, "CLINICIAN_NOT_VERIFIED", "This clinician account hasn't been verified, so it can't access patient information.", recoverable=False)
    start_session(db, request, response, user)
    audit.record(db, actor_role=user.role, actor_id=user.id, action="SIGNED_IN")
    db.commit()
    return me_out(user)


def _new_account_email(db: Session, email: str) -> str:
    if not get_settings().demo_mode:
        # Real accounts need institutional sign-in (TODO(CURALINK-MANUAL): SSO); demo sign-up only.
        raise ApiError(404, "NOT_FOUND", "Not available.", recoverable=False)
    e = email.strip().lower()
    if not _EMAIL.match(e):
        raise ApiError(422, "INVALID_EMAIL", "Enter a valid email address.")
    if db.scalar(select(User.id).where(func.lower(User.email) == e)):
        raise ApiError(409, "EMAIL_IN_USE", "An account with this email already exists. Sign in instead.")
    return e


@router.post("/auth/register", response_model=MeOut, status_code=201)
def register_student(body: RegisterIn, request: Request, response: Response, db: Session = Depends(get_db)) -> MeOut:
    """Create a (fictional demo) STUDENT account. The role is fixed server-side; names are collected next."""
    email = _new_account_email(db, body.email)
    user = User(id=f"stu_{uuid4().hex[:12]}", role="student", display_name=email.split("@")[0], email=email,
                password_hash=hash_password(body.password), timezone=get_settings().demo_timezone, demo=True)
    db.add(user)
    db.flush()
    start_session(db, request, response, user)
    audit.record(db, actor_role="student", actor_id=user.id, subject_student_id=user.id, action="ACCOUNT_CREATED")
    db.commit()
    return me_out(user)


@router.post("/auth/register/clinician", status_code=201)
def register_clinician(body: ClinicianRegisterIn, db: Session = Depends(get_db)) -> dict:
    """Request a clinician account. It is created UNVERIFIED and gets no session: claiming a name or
    credentials never grants clinician access. Verification is a server-side step (python -m app.admin)."""
    email = _new_account_email(db, body.email)
    first, last = names.clean(body.first_name, "first name"), names.clean(body.last_name, "last name")
    creds, role = body.credentials.strip(), body.clinical_role.strip()
    if not _LABEL.match(creds) or not _LABEL.match(role):
        raise ApiError(422, "INVALID_PROFILE", "Use letters, numbers and basic punctuation for credentials and role.")
    user = User(id=f"cln_{uuid4().hex[:12]}", role="clinician", display_name=f"{first} {last}", first_name=first, last_name=last,
                credentials=creds, clinical_role=role, email=email, password_hash=hash_password(body.password),
                timezone=get_settings().demo_timezone, clinician_verified=False, demo=True)
    db.add(user)
    db.flush()
    audit.record(db, actor_role="clinician", actor_id=user.id, action="CLINICIAN_ACCOUNT_REQUESTED", detail="pending verification")
    db.commit()
    return {"status": "PENDING_VERIFICATION", "message": "Request received. A CuraLink administrator must verify your credentials before you can sign in."}


@router.post("/auth/logout", status_code=204)
def logout(request: Request, response: Response, db: Session = Depends(get_db)) -> Response:
    end_session(db, request, response)
    response.status_code = 204
    return response


@router.get("/me", response_model=MeOut)
def me(user: User = Depends(current_user)) -> MeOut:
    return me_out(user)
