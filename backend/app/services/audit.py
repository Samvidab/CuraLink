"""Append-only workflow trace (TRD AuditEvent). Callers must pass only
non-sensitive, compact details: never symptoms, document bodies or secrets."""

from sqlalchemy.orm import Session

from app.models import AuditEvent


def record(
    db: Session,
    *,
    actor_role: str,
    actor_id: str | None,
    action: str,
    subject_student_id: str | None = None,
    object_type: str | None = None,
    object_id: str | None = None,
    from_state: str | None = None,
    to_state: str | None = None,
    status: str = "ok",
    detail: str | None = None,
    source_mode: str = "demo",
) -> AuditEvent:
    ev = AuditEvent(
        actor_role=actor_role,
        actor_id=actor_id,
        subject_student_id=subject_student_id,
        action=action,
        object_type=object_type,
        object_id=object_id,
        from_state=from_state,
        to_state=to_state,
        status=status,
        detail=detail,
        source_mode=source_mode,
    )
    db.add(ev)
    return ev
