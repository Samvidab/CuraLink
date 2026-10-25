"""Photo observations: NON-DIAGNOSTIC, uncertainty-first descriptions (PRD §11, TRD §15).

Pipeline: explicit consent -> magic-byte/size validation -> decode + re-encode (drops
EXIF/GPS) -> image-quality checks -> candidate observations from an allowlisted set
-> guardrail filter -> shown to the student, who decides whether to share.

Two observers share one output contract:
  * "claude"    – Claude vision via llm_gateway (only when ANTHROPIC_API_KEY is set)
  * "heuristic" – deterministic colour/texture measurements; not a medical model
Neither ever diagnoses, judges severity/urgency, or confirms blood or bruising.
"""

import io
from dataclasses import dataclass, field

import pillow_heif
from PIL import Image, ImageFilter, ImageOps, ImageStat, UnidentifiedImageError

from app.errors import ApiError
from app.services import safety

MAX_SIDE = 1600
MAX_PIXELS = 50_000_000  # decoded-size guard (decompression bombs)


def max_bytes() -> int:
    """MAX_UPLOAD_MB (12 by default; 4 on Vercel, whose functions accept request bodies up to 4.5 MB)."""
    from app.config import get_settings

    return int(get_settings().max_upload_mb * 1024 * 1024)


def supported_label() -> str:
    return f"JPG, PNG, WebP or iPhone HEIC/HEIF, up to {max_bytes() // (1024 * 1024)} MB"
Image.MAX_IMAGE_PIXELS = MAX_PIXELS
pillow_heif.register_heif_opener()  # decode HEIC/HEIF in-process (no temp files, no shelling out)
_HEIF_BRANDS = {b"heic", b"heix", b"hevc", b"hevx", b"heim", b"heis", b"mif1", b"msf1", b"avif"}
CATEGORIES = ("apparent_swelling", "red_area_possible_blood", "dry_or_flaky_skin", "discoloration_possible_bruise", "other")
LABELS = {
    "apparent_swelling": "Apparent puffiness or asymmetry",
    "red_area_possible_blood": "Red-appearing area (not verified as blood)",
    "dry_or_flaky_skin": "Dry or flaky-looking texture",
    "discoloration_possible_bruise": "Discoloration (cannot confirm bruising)",
    "other": "Other visible feature",
}
DISCLAIMER = "Possible visual observations only. A photo can't show what is causing something, and this is not a diagnosis or a measure of severity or urgency."
NEXT_STEPS = [
    "Notice whether it changes over the next day or two (a dated photo can help you describe it).",
    "Avoid irritating the area while you wait to be seen.",
    "Contact a qualified healthcare professional if you're concerned. If you have severe symptoms, call 911.",
]
_SIGNATURES = {b"\xff\xd8\xff": "image/jpeg", b"\x89PNG\r\n\x1a\n": "image/png"}


@dataclass
class Observation:
    category: str
    description: str
    uncertainty: str  # always present; never a numeric confidence


@dataclass
class Result:
    image_png: bytes
    width: int
    height: int
    quality: dict
    observations: list[Observation] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    observer: str = "heuristic"


def sniff(data: bytes) -> str:
    """Detect the real type from the file's bytes (never trusts the filename or browser MIME)."""
    for sig, mime in _SIGNATURES.items():
        if data.startswith(sig):
            return mime
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data[4:8] == b"ftyp" and data[8:12] in _HEIF_BRANDS:
        return "image/heic"
    raise ApiError(422, "UNSUPPORTED_IMAGE", f"That file isn't a supported photo. Use {supported_label()}.")


def clean(data: bytes) -> Image.Image:
    """Validate and re-encode. Re-encoding from raw pixels discards EXIF/GPS and any other metadata."""
    if len(data) > max_bytes():
        raise ApiError(422, "IMAGE_TOO_LARGE", f"That photo is too large. Use {supported_label()}.")
    if not data:
        raise ApiError(422, "CORRUPT_IMAGE", "The file was empty. Try another photo or continue without one.")
    mime = sniff(data)
    try:
        img = Image.open(io.BytesIO(data))
        if img.width * img.height > MAX_PIXELS or min(img.size) < 16:
            raise ApiError(422, "IMAGE_DIMENSIONS", "That image's dimensions aren't supported. Try a normal phone photo.")
        if mime != "image/heic":
            img.verify()
            img = Image.open(io.BytesIO(data))
        img = ImageOps.exif_transpose(img)  # honour the camera's orientation before metadata is dropped
        img = img.convert("RGB")
    except ApiError:
        raise
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError, Image.DecompressionBombError) as exc:
        raise ApiError(422, "CORRUPT_IMAGE", "We couldn't read that image (it may be damaged). Try another photo or continue without one.") from exc
    img.thumbnail((MAX_SIDE, MAX_SIDE), Image.Resampling.LANCZOS)
    return Image.frombytes("RGB", img.size, img.tobytes())  # brand-new image: no metadata carried over


def quality(img: Image.Image) -> dict:
    gray = img.convert("L")
    brightness = ImageStat.Stat(gray).mean[0]
    sharpness = ImageStat.Stat(gray.filter(ImageFilter.FIND_EDGES)).var[0]
    notes = []
    if min(img.size) < 200:
        notes.append("Low resolution; details may be missed.")
    if brightness < 55:
        notes.append("The photo is dark; colours may look different than in person.")
    elif brightness > 225:
        notes.append("The photo is very bright or washed out.")
    if sharpness < 40:
        notes.append("The photo looks blurry.")
    return {
        "lighting": "low" if brightness < 55 else "very bright" if brightness > 225 else "ok",
        "clarity": "blurry" if sharpness < 40 else "ok",
        "notes": notes,
        "usable": not (brightness < 25 or min(img.size) < 64),
    }


def _fractions(img: Image.Image) -> dict:
    small = img.copy()
    small.thumbnail((200, 200))
    hsv = small.convert("HSV")
    px = list(hsv.get_flattened_data()) if hasattr(hsv, "get_flattened_data") else list(hsv.getdata())
    n = len(px) or 1
    red = sum(1 for h, s, v in px if (h < 10 or h > 245) and s > 120 and v > 60) / n
    purple_blue = sum(1 for h, s, v in px if 160 <= h <= 220 and s > 60 and 40 < v < 200) / n
    yellow_green = sum(1 for h, s, v in px if 35 <= h <= 70 and s > 90 and v > 80) / n
    flakes = small.convert("L").filter(ImageFilter.FIND_EDGES)
    texture = ImageStat.Stat(flakes).mean[0]
    pale = sum(1 for h, s, v in px if s < 35 and v > 200) / n
    return {"red": red, "purple_blue": purple_blue, "yellow_green": yellow_green, "texture": texture, "pale": pale}


def heuristic_observations(img: Image.Image) -> list[Observation]:
    f = _fractions(img)
    out: list[Observation] = []
    if f["red"] > 0.04:
        out.append(Observation("red_area_possible_blood", "A red-appearing area is visible.", "Colour alone can't show whether this is blood, irritation, makeup, fabric or lighting."))
    if f["purple_blue"] > 0.03 or f["yellow_green"] > 0.05:
        out.append(Observation("discoloration_possible_bruise", "An area of purplish, bluish or yellow-green discoloration may be visible.", "This can't confirm bruising; shadows, veins, ink and camera tint can look similar."))
    if f["texture"] > 28 and f["pale"] > 0.05:
        out.append(Observation("dry_or_flaky_skin", "Some texture may look dry or flaky.", "Fine texture is hard to judge in photos; it may be hair, lint or image noise."))
    return out


def guard(obs: list[Observation]) -> list[Observation]:
    """Drop anything outside the allowlist or that drifts into diagnosis/severity."""
    kept = []
    for o in obs:
        if o.category not in CATEGORIES:
            continue
        if safety.guard_output(o.description)[1] or safety.guard_output(o.uncertainty)[1]:
            continue
        kept.append(o)
    return kept


LIMITATIONS = [
    "Swelling can't be judged reliably from one photo without a comparison.",
    "A photo can't show whether a red area is blood or what caused any discoloration.",
    "These observations do not change appointment priority and are never sent to professors.",
]


def analyze(data: bytes, observer=None) -> Result:
    img = clean(data)
    q = quality(img)
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    result = Result(image_png=buf.getvalue(), width=img.width, height=img.height, quality=q, limitations=list(LIMITATIONS))
    if not q["usable"]:
        result.limitations.insert(0, "The photo is too dark or small to describe. You can retake it or continue without a photo.")
        return result
    if observer is not None:
        obs, name = observer(result.image_png)
        result.observations, result.observer = guard(obs), name
    else:
        result.observations = guard(heuristic_observations(img))
    return result
