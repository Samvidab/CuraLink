"""Clinic inventory adapter (TRD §3 clinic_adapter).

`ClinicAdapter` is the stable interface; `DemoClinicAdapter` serves the seeded
synthetic inventory. A future live adapter must implement the same methods and
report source_mode="real" only for availability confirmed by the clinic.
"""

import json
from datetime import datetime
from functools import lru_cache
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.errors import ApiError
from app.models import ClinicSlot


class ClinicAdapter(Protocol):
    source_mode: str

    def appointment_types(self) -> list[dict]: ...
    def list_slots(self, start: datetime, end: datetime, appointment_type: str | None = None) -> list[ClinicSlot]: ...
    def reserve(self, slot_id: str) -> ClinicSlot: ...
    def release(self, slot_id: str) -> None: ...
    def inventory_updated_at(self) -> str: ...


@lru_cache
def _inventory_meta() -> dict:
    return json.loads((get_settings().sample_data_dir / "demo_slots.json").read_text())


class DemoClinicAdapter:
    source_mode = "demo"

    def __init__(self, db: Session):
        self.db = db

    def appointment_types(self) -> list[dict]:
        return _inventory_meta()["appointment_types"]

    def inventory_updated_at(self) -> str:
        return _inventory_meta()["inventory_updated_at"]

    def list_slots(self, start: datetime, end: datetime, appointment_type: str | None = None) -> list[ClinicSlot]:
        q = select(ClinicSlot).where(ClinicSlot.starts_at < end, ClinicSlot.ends_at > start)
        if appointment_type:
            q = q.where(ClinicSlot.appointment_type == appointment_type)
        return list(self.db.scalars(q.order_by(ClinicSlot.starts_at, ClinicSlot.id)))

    def get(self, slot_id: str) -> ClinicSlot:
        slot = self.db.get(ClinicSlot, slot_id)
        if slot is None:
            raise ApiError(404, "SLOT_NOT_FOUND", "That appointment time doesn't exist.")
        return slot

    def reserve(self, slot_id: str) -> ClinicSlot:
        """Re-check mutable availability at confirmation time (TRD §7)."""
        slot = self.get(slot_id)
        if slot.status != "AVAILABLE" or not slot.permitted:
            raise ApiError(409, "SLOT_UNAVAILABLE", "That time was just taken. Here are updated options — nothing was booked.", details={"slot_id": slot_id})
        slot.status = "BOOKED"
        return slot

    def release(self, slot_id: str) -> None:
        slot = self.get(slot_id)
        if slot.status == "BOOKED":
            slot.status = "AVAILABLE"


def get_adapter(db: Session) -> DemoClinicAdapter:
    return DemoClinicAdapter(db)
