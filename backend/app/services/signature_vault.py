"""Encrypted storage for clinician signature images.

# CURALINK_CONFIG: SIGNATURE_ENCRYPTION
Key source, in order: SIGNATURE_ENCRYPTION_KEY env var (base64url, 32 bytes) -> in demo mode only,
a locally generated key at backend/.secrets/signature.key (git-ignored, chmod 600).
TODO(CURALINK-MANUAL): production must use a managed KMS/secret store and key rotation.

A stored signature is never applied automatically: app/services/absence_service.sign() requires a
fresh, single-use, version- and hash-bound approval with re-authentication (SIGNING_POLICY).
"""

import base64
import io
import os
from functools import lru_cache
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from PIL import Image, UnidentifiedImageError

from app.config import REPO_ROOT, get_settings
from app.errors import ApiError

KEY_FILE = REPO_ROOT / "backend" / ".secrets" / "signature.key"
MAX_PNG_BYTES = 300 * 1024


@lru_cache
def _key() -> bytes:
    s = get_settings()
    if s.signature_encryption_key:
        key = base64.urlsafe_b64decode(s.signature_encryption_key + "==")
    elif s.demo_mode:
        if not KEY_FILE.exists():
            KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
            KEY_FILE.write_bytes(base64.urlsafe_b64encode(os.urandom(32)))
            KEY_FILE.chmod(0o600)
        key = base64.urlsafe_b64decode(KEY_FILE.read_bytes())
    else:
        raise ApiError(500, "SIGNATURE_KEY_MISSING", "Signature storage isn't configured.", recoverable=False)
    if len(key) != 32:
        raise ApiError(500, "SIGNATURE_KEY_INVALID", "Signature encryption key must be 32 bytes.", recoverable=False)
    return key


def encrypt(data: bytes, owner_id: str) -> bytes:
    nonce = os.urandom(12)
    return nonce + AESGCM(_key()).encrypt(nonce, data, owner_id.encode())  # owner bound as associated data


def decrypt(blob: bytes, owner_id: str) -> bytes:
    return AESGCM(_key()).decrypt(blob[:12], blob[12:], owner_id.encode())


def validate_png(data: bytes) -> bytes:
    """Accept a drawn signature PNG only; re-encode to drop metadata."""
    if len(data) > MAX_PNG_BYTES or not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ApiError(422, "INVALID_SIGNATURE_IMAGE", "Draw your signature again (PNG up to 300 KB).")
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except (UnidentifiedImageError, OSError) as exc:
        raise ApiError(422, "INVALID_SIGNATURE_IMAGE", "Draw your signature again.") from exc
    if not (50 <= img.width <= 1200 and 20 <= img.height <= 600):
        raise ApiError(422, "INVALID_SIGNATURE_IMAGE", "Signature image has an unexpected size.")
    img = img.convert("RGBA")
    alpha = img.getchannel("A")
    if alpha.getbbox() is None:
        raise ApiError(422, "EMPTY_SIGNATURE", "The signature pad is empty.")
    out = io.BytesIO()
    Image.frombytes("RGBA", img.size, img.tobytes()).save(out, format="PNG")
    return out.getvalue()


def key_file_path() -> Path:
    return KEY_FILE
