"""Demo course catalog: stands in for a verified instructor-contact source.
Emails are never synthesized; unknown courses get contact_status=MISSING."""

import json
from functools import lru_cache

from app.config import get_settings


@lru_cache
def _catalog() -> dict[str, dict]:
    path = get_settings().sample_data_dir / "demo_courses.json"
    data = json.loads(path.read_text())
    return {c["code"]: c for c in data["courses"]}


def lookup(code: str) -> dict | None:
    return _catalog().get(code)
