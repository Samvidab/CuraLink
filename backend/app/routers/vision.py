import hashlib
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, Response, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.errors import ApiError
from app.models import Attachment, User
from app.security import require_student
from app.services import audit, intake_service, llm_gateway, vision

router = APIRouter(prefix="/api/v1", tags=["vision"])
DEMO_IMAGES = {"red_area": "synthetic_red_area.png", "discoloration": "synthetic_discoloration.png"}


def _enabled() -> None:
    if not get_settings().enable_photo_observations:
        raise ApiError(404, "FEATURE_DISABLED", "Photo observations are turned off.")


def attachment_out(a: Attachment) -> dict:
    return {
        "id": a.id, "observations": a.observations, "limitations": a.limitations, "quality": a.quality, "observer": a.observer,
        "synthetic_demo": a.synthetic_demo, "created_at": a.created_at, "image_url": f"/api/v1/vision/observations/{a.id}/image",
        "labels": {o["category"]: vision.LABELS[o["category"]] for o in a.observations}, "disclaimer": vision.DISCLAIMER, "next_steps": vision.NEXT_STEPS,
    }


async def _store(db: Session, user: User, data: bytes, synthetic: bool) -> dict:
    sess = intake_service.current_session(db, user)
    result = vision.analyze(data)  # validates, strips metadata, quality + heuristic observations
    if llm_gateway.available() and result.quality["usable"]:
        try:
            raw = await llm_gateway.describe_image(result.image_png)
            obs = [vision.Observation(o["category"], o["description"], o["uncertainty"]) for o in raw]
            result.observations, result.observer = vision.guard(obs), "claude"
        except llm_gateway.LlmUnavailable:
            pass  # keep the deterministic heuristic result
    a = Attachment(
        id=f"att_{uuid4().hex[:10]}", session_id=sess.id, student_id=user.id, data=result.image_png, sha256=hashlib.sha256(result.image_png).hexdigest(),
        quality=result.quality, observations=[o.__dict__ for o in result.observations], limitations=result.limitations, observer=result.observer, synthetic_demo=synthetic,
    )
    db.add(a)
    sess.photo_consent = True
    summary = "; ".join(f"{vision.LABELS[o.category]}: {o.description}" for o in result.observations) or "Nothing clear enough to describe."
    intake_service.upsert(db, sess, "photo_observations", {"text": summary[:1000]}, "photo_observation", confirmed=False)
    audit.record(db, actor_role="student", actor_id=user.id, subject_student_id=user.id, action="PHOTO_ANALYZED", object_type="attachment", object_id=a.id, detail=f"{result.observer}, {len(result.observations)} observations")
    db.commit()
    return attachment_out(a)


@router.post("/vision/observations", dependencies=[Depends(_enabled)])
async def upload(file: UploadFile = File(...), consent: bool = Form(False), user: User = Depends(require_student), db: Session = Depends(get_db)) -> dict:
    if not consent:
        raise ApiError(400, "PHOTO_CONSENT_REQUIRED", "Confirm photo consent first, or continue without a photo.")
    data = await file.read(vision.MAX_BYTES + 1)
    return await _store(db, user, data, synthetic=False)


@router.post("/vision/demo-images/{name}", dependencies=[Depends(_enabled)])
async def use_demo_image(name: str, consent: bool = False, user: User = Depends(require_student), db: Session = Depends(get_db)) -> dict:
    if name not in DEMO_IMAGES:
        raise ApiError(404, "NOT_FOUND", "Unknown demo image.")
    if not consent:
        raise ApiError(400, "PHOTO_CONSENT_REQUIRED", "Confirm photo consent first.")
    return await _store(db, user, (get_settings().sample_data_dir / "demo_images" / DEMO_IMAGES[name]).read_bytes(), synthetic=True)


@router.get("/vision/observations")
def list_mine(user: User = Depends(require_student), db: Session = Depends(get_db)) -> list[dict]:
    sess = intake_service.current_session(db, user)
    return [attachment_out(a) for a in db.scalars(select(Attachment).where(Attachment.session_id == sess.id).order_by(Attachment.created_at)).all()]


def _own(db: Session, user: User, aid: str) -> Attachment:
    a = db.get(Attachment, aid)
    if a is None or a.student_id != user.id:
        raise ApiError(404, "NOT_FOUND", "Photo not found.")
    return a


@router.get("/vision/observations/{aid}/image")
def image(aid: str, user: User = Depends(require_student), db: Session = Depends(get_db)) -> Response:
    return Response(_own(db, user, aid).data, media_type="image/png", headers={"Cache-Control": "no-store"})


@router.delete("/vision/observations/{aid}", status_code=204)
def delete(aid: str, user: User = Depends(require_student), db: Session = Depends(get_db)) -> None:
    a = _own(db, user, aid)
    sess_id = a.session_id
    db.delete(a)
    db.flush()
    if not db.scalar(select(Attachment.id).where(Attachment.session_id == sess_id)):
        from app.models import IntakeField

        f = db.scalar(select(IntakeField).where(IntakeField.session_id == sess_id, IntakeField.key == "photo_observations"))
        if f:
            db.delete(f)
    audit.record(db, actor_role="student", actor_id=user.id, subject_student_id=user.id, action="PHOTO_DELETED", object_type="attachment", object_id=aid)
    db.commit()
