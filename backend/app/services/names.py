"""Names on the authenticated user's profile: validation, the name CuraLink addresses someone by, the greeting.

A name is profile data, never identity: it is saved only to the signed-in account and never used to look up,
create or switch to another person's records.
"""

import json
import re

from sqlalchemy.orm import Session

from app.config import get_settings
from app.errors import ApiError
from app.models import User

# Letters (incl. accented), spaces, apostrophes, hyphens, periods. Also keeps names inert in the LLM context.
_NAME = re.compile(r"^[^\W\d_](?:[^\W\d_]|[ '\-.’])*$")
MAX_LEN = 40


def clean(value: str | None, field: str, required: bool = True) -> str | None:
    v = " ".join((value or "").split())
    if not v:
        if required:
            raise ApiError(422, "NAME_REQUIRED", f"Enter your {field}.")
        return None
    if len(v) > MAX_LEN or not _NAME.match(v):
        raise ApiError(422, "INVALID_NAME", f"Use letters, spaces, apostrophes or hyphens for your {field} (up to {MAX_LEN} characters).")
    return v


def profile_complete(user: User) -> bool:
    return bool(user.first_name and user.last_name)


def address_name(user: User) -> str | None:
    """What CuraLink calls the student: preferred name, else first name."""
    return user.preferred_name or user.first_name


def greeting(user: User) -> str:
    """Single source for the assistant's opening line: shown as text AND spoken by voice."""
    name = address_name(user) if user.role == "student" else None
    hello = f"Hi {name}!" if name else "Hi!"
    return f"{hello} I'm CuraLink, your campus healthcare navigator. I can help organize care, not diagnose. How can I help you today?"


def backfill_demo_names(db: Session) -> int:
    """Give existing fictional demo accounts their first/last names without touching anything else.

    Only fills names that are missing, so a student's own edits and all records are preserved.
    """
    users = json.loads((get_settings().sample_data_dir / "demo_users.json").read_text())
    changed = 0
    for row in users["students"] + users["clinicians"]:
        u = db.get(User, row["id"])
        if u is not None and not u.first_name and row.get("first_name"):
            u.first_name, u.last_name = row["first_name"], row["last_name"]
            changed += 1
    if changed:
        db.commit()
    return changed
