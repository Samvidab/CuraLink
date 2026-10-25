"""Server-side administration (operators only; never exposed over HTTP).

    uv run python -m app.admin verify-clinician doctor@clinic.example.com
    uv run python -m app.admin seed-availability     # add MISSING demo clinician hours; resets nothing
    uv run python -m app.admin convex-sync           # push every current record to Convex (CONVEX_* settings required)
    uv run python -m app.admin convex-jwks           # print the PUBLIC key set (data: URI) for Convex's CURALINK_JWKS

Verification is the ONLY way a clinician account gains clinician access.
"""

# TODO(CURALINK-MANUAL): replace with a real credential/license check before production.

import sys

from sqlalchemy import func, select

from app import db as dbmod
from app.models import User
from app.services import audit


def main(argv: list[str]) -> int:
    if argv == ["convex-jwks"]:
        from app.services import convex_bridge

        print(convex_bridge.jwks_data_uri())
        return 0
    if argv == ["convex-sync"]:
        from app.services import convex_bridge

        if not convex_bridge.enabled():
            print("CONVEX_SITE_URL and CONVEX_SYNC_SECRET are not set.")
            return 1
        dbmod.create_all()
        print(f"Pushed {convex_bridge.full_sync()} records to Convex.")
        return 0
    if argv == ["seed-availability"]:
        from app.services.availability import ensure_demo_data

        dbmod.create_all()
        gen = dbmod.get_db()
        try:
            print(ensure_demo_data(next(gen)))
            return 0
        finally:
            gen.close()
    if len(argv) != 2 or argv[0] != "verify-clinician":
        print(__doc__)
        return 2
    gen = dbmod.get_db()
    db = next(gen)
    try:
        user = db.scalar(select(User).where(func.lower(User.email) == argv[1].strip().lower(), User.role == "clinician"))
        if user is None:
            print("No clinician account with that email.")
            return 1
        user.clinician_verified = True
        audit.record(db, actor_role="admin", actor_id="cli", action="CLINICIAN_VERIFIED", object_type="user", object_id=user.id)
        db.commit()
        print(f"Verified {user.display_name} ({user.email}).")
        return 0
    finally:
        gen.close()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
