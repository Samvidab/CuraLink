from tests.conftest import RIVERA_MON_1030
import io

import pytest
from PIL import Image

from app.config import get_settings
from app.services import llm_gateway, vision

DEMO = get_settings().sample_data_dir / "demo_images"


def _png_with_exif() -> bytes:
    img = Image.new("RGB", (400, 300), (225, 180, 150))
    for x in range(150, 250):
        for y in range(100, 200):
            img.putpixel((x, y), (200, 30, 35))
    exif = Image.Exif()
    exif[0x8825] = {2: (40, 25, 0)}  # GPSInfo
    exif[0x010F] = "SecretCam"
    buf = io.BytesIO()
    img.save(buf, format="JPEG", exif=exif)
    return buf.getvalue()


def test_metadata_is_stripped_and_observations_are_tentative():
    data = _png_with_exif()
    assert b"SecretCam" in data
    r = vision.analyze(data)
    assert b"SecretCam" not in r.image_png and not Image.open(io.BytesIO(r.image_png)).getexif()
    assert [o.category for o in r.observations] == ["red_area_possible_blood"]
    o = r.observations[0]
    assert "red-appearing" in o.description and "can't show whether this is blood" in o.uncertainty
    assert any("Swelling can't be judged" in l for l in r.limitations)


@pytest.mark.parametrize("data,code", [(b"%PDF-1.4 not an image", "UNSUPPORTED_IMAGE"), (b"\x89PNG\r\n\x1a\n" + b"x" * 50, "CORRUPT_IMAGE"), (b"\xff\xd8\xff" + b"0" * (12 * 1024 * 1024 + 1), "IMAGE_TOO_LARGE")])
def test_invalid_images_fail_safely(data, code):
    with pytest.raises(Exception) as exc:
        vision.analyze(data)
    assert getattr(exc.value, "code", None) == code


def test_dark_image_is_not_described():
    buf = io.BytesIO()
    Image.new("RGB", (300, 300), (5, 5, 5)).save(buf, format="PNG")
    r = vision.analyze(buf.getvalue())
    assert r.observations == [] and "too dark" in r.limitations[0]


def test_guard_blocks_diagnosis_and_unknown_categories():
    kept = vision.guard([
        vision.Observation("red_area_possible_blood", "It sounds like you have an infection.", "x"),
        vision.Observation("tumor", "A mass", "y"),
        vision.Observation("dry_or_flaky_skin", "Some texture may look dry.", "Hard to judge in photos."),
    ])
    assert [o.category for o in kept] == ["dry_or_flaky_skin"]


def test_upload_requires_consent_and_feeds_intake(student):
    data = (DEMO / "synthetic_red_area.png").read_bytes()
    assert student.post("/api/v1/vision/observations", files={"file": ("p.png", data, "image/png")}, data={"consent": "false"}).status_code == 400
    r = student.post("/api/v1/vision/observations", files={"file": ("p.png", data, "image/png")}, data={"consent": "true"}).json()
    assert r["observer"] == "heuristic" and r["observations"][0]["category"] == "red_area_possible_blood"
    assert student.get(r["image_url"]).headers["content-type"] == "image/png"
    f = {x["key"]: x for x in student.get("/api/v1/intake/sessions/current").json()["fields"]}["photo_observations"]
    assert f["provenance"] == "photo_observation" and not f["confirmed_by_student"]
    assert student.delete(f"/api/v1/vision/observations/{r['id']}").status_code == 204
    assert "photo_observations" not in {x["key"] for x in student.get("/api/v1/intake/sessions/current").json()["fields"]}


def test_photo_reaches_only_the_assigned_clinician_when_selected(student, clinician, login):
    student.post("/api/v1/calendars/import-sample")
    student.post("/api/v1/appointments/confirm", json={"slot_id": RIVERA_MON_1030, "student_approved": True, "idempotency_key": "vision-key-01"})
    enc = student.get("/api/v1/students/me/encounters").json()[0]
    att = student.post("/api/v1/vision/demo-images/discoloration?consent=true").json()
    assert att["synthetic_demo"] and att["observations"][0]["category"] == "discoloration_possible_bruise"
    sid = student.get("/api/v1/intake/sessions/current").json()["session_id"]
    student.post(f"/api/v1/intake/sessions/{sid}/fields/photo_observations/confirm", json={"confirmed": True})
    # Shared WITHOUT the photo: clinician gets the text observation only.
    student.post(f"/api/v1/encounters/{enc['id']}/handoff", json={"student_authorized": True, "field_keys": ["photo_observations"]})
    view = clinician.get(f"/api/v1/clinician/encounters/{enc['id']}/intake").json()
    assert view["attachments"] == [] and view["consent"]["photo_shared"] is False
    assert clinician.get(f"/api/v1/clinician/encounters/{enc['id']}/attachments/{att['id']}").status_code == 403
    # Student explicitly shares the photo in a new session-less re-share is not possible; new packet for new session:
    # (photo belonged to the now-closed session) -> rejected
    r = student.post(f"/api/v1/encounters/{enc['id']}/handoff", json={"student_authorized": True, "field_keys": ["photo_observations"], "attachment_ids": [att["id"]]})
    assert r.status_code in (409, 422)


def test_photo_sharing_and_clinician_review(student, clinician, login):
    student.post("/api/v1/calendars/import-sample")
    student.post("/api/v1/appointments/confirm", json={"slot_id": RIVERA_MON_1030, "student_approved": True, "idempotency_key": "vision-key-02"})
    enc = student.get("/api/v1/students/me/encounters").json()[0]
    att = student.post("/api/v1/vision/demo-images/red_area?consent=true").json()
    sid = student.get("/api/v1/intake/sessions/current").json()["session_id"]
    student.post(f"/api/v1/intake/sessions/{sid}/fields/photo_observations/confirm", json={"confirmed": True})
    pkt = student.post(f"/api/v1/encounters/{enc['id']}/handoff", json={"student_authorized": True, "field_keys": ["photo_observations"], "attachment_ids": [att["id"]]}).json()
    assert pkt["attachment_ids"] == [att["id"]]
    view = clinician.get(f"/api/v1/clinician/encounters/{enc['id']}/intake").json()
    assert view["consent"]["photo_shared"] and view["attachments"][0]["id"] == att["id"]
    assert clinician.get(view["attachments"][0]["image_url"]).headers["content-type"] == "image/png"
    hale, _ = login("dr.hale@clinic.example.com")
    assert hale.get(view["attachments"][0]["image_url"]).status_code == 403
    # Clinician corrects an AI-generated observation; the student's original is preserved.
    assert clinician.post(f"/api/v1/clinician/encounters/{enc['id']}/intake/annotations", json={"field_key": "photo_observations", "decision": "corrected", "corrected_value": "Erythematous patch noted on exam"}).status_code == 200
    view = clinician.get(f"/api/v1/clinician/encounters/{enc['id']}/intake").json()
    assert view["annotations"]["photo_observations"]["decision"] == "corrected"
    assert "red-appearing" in view["fields"][0]["display"]
    assert student.post(f"/api/v1/clinician/encounters/{enc['id']}/intake/annotations", json={"field_key": "photo_observations", "decision": "rejected"}).status_code == 403


def test_claude_vision_path_is_guarded(student, monkeypatch):
    async def fake(png):
        return [{"category": "red_area_possible_blood", "description": "This is definitely an infected wound; you probably have cellulitis.", "uncertainty": "none"},
                {"category": "dry_or_flaky_skin", "description": "Some texture may look dry.", "uncertainty": "Hard to judge in photos."}]

    monkeypatch.setattr(llm_gateway, "available", lambda: True)
    monkeypatch.setattr(llm_gateway, "describe_image", fake)
    r = student.post("/api/v1/vision/demo-images/red_area?consent=true").json()
    assert r["observer"] == "claude" and [o["category"] for o in r["observations"]] == ["dry_or_flaky_skin"]


def _heic(color=(200, 30, 35), size=(400, 300)) -> bytes:
    import pillow_heif  # noqa: F401  (registers the HEIF encoder)

    img = Image.new("RGB", size, (225, 180, 150))
    for x in range(size[0] // 3, 2 * size[0] // 3):
        for y in range(size[1] // 3, 2 * size[1] // 3):
            img.putpixel((x, y), color)
    buf = io.BytesIO()
    img.save(buf, format="HEIF", quality=90)
    return buf.getvalue()


def test_heic_is_detected_by_content_and_converted_to_png():
    data = _heic()
    assert data[4:12] == b"ftypheic" and vision.sniff(data) == "image/heic"
    r = vision.analyze(data)
    assert r.image_png.startswith(b"\x89PNG") and (r.width, r.height) == (400, 300)
    assert [o.category for o in r.observations] == ["red_area_possible_blood"]


def test_upload_heic_named_like_an_iphone_file(student):
    r = student.post("/api/v1/vision/observations", files={"file": ("IMG_0042.HEIC", _heic(), "image/heic")}, data={"consent": "true"})
    assert r.status_code == 200, r.text
    assert student.get(r.json()["image_url"]).content.startswith(b"\x89PNG")  # converted for preview/clinician


def test_type_comes_from_bytes_not_extension(student):
    png = io.BytesIO()
    Image.new("RGB", (120, 90), (230, 190, 160)).save(png, format="PNG")
    ok = student.post("/api/v1/vision/observations", files={"file": ("photo.jpg", png.getvalue(), "image/jpeg")}, data={"consent": "true"})
    assert ok.status_code == 200  # real PNG with a .jpg name is fine
    bad = student.post("/api/v1/vision/observations", files={"file": ("photo.heic", b"%PDF-1.7 fake", "image/heic")}, data={"consent": "true"})
    assert bad.status_code == 422 and bad.json()["code"] == "UNSUPPORTED_IMAGE" and "HEIC" in bad.json()["message"]


@pytest.mark.filterwarnings("ignore::PIL.Image.DecompressionBombWarning")
def test_corrupt_heic_and_oversized_dimensions_fail_safely():
    with pytest.raises(Exception) as exc:
        vision.analyze(b"\x00\x00\x00\x18ftypheic" + b"\x00" * 200)
    assert getattr(exc.value, "code", None) == "CORRUPT_IMAGE"
    huge = io.BytesIO()
    Image.new("L", (9000, 6000)).save(huge, format="PNG")
    with pytest.raises(Exception) as exc:
        vision.analyze(huge.getvalue())
    assert getattr(exc.value, "code", None) == "IMAGE_DIMENSIONS"


def test_exif_orientation_is_applied_and_gps_removed():
    img = Image.new("RGB", (300, 100), (225, 180, 150))
    exif = Image.Exif()
    exif[0x0112] = 6  # rotate 90° CW on display
    exif[0x8825] = {2: (40, 25, 0)}
    buf = io.BytesIO()
    img.save(buf, format="JPEG", exif=exif)
    r = vision.analyze(buf.getvalue())
    out = Image.open(io.BytesIO(r.image_png))
    assert out.size == (100, 300) and not out.getexif()
