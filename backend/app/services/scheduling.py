"""Deterministic slot filtering and ranking (TRD §7).

Pure functions over plain data. No LLM, no medical severity: ranking uses
only wait time, travel and student preferences.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta

# Score weights (lower score = better). Documented so reasons stay explainable.
WAIT_POINTS_PER_DAY = 4.0
TRAVEL_POINTS_PER_10_MIN = 1.0
OUTSIDE_PREFERRED_WINDOW = 3.0
TIGHT_GAP_PENALTY = 1.5  # less than 15 min spare around classes
TIGHT_GAP = timedelta(minutes=15)


@dataclass(frozen=True)
class Interval:
    start: datetime
    end: datetime
    label: str
    ref_id: str | None = None


@dataclass(frozen=True)
class Slot:
    id: str
    starts_at: datetime
    ends_at: datetime
    appointment_type: str
    travel_minutes: int
    available: bool = True
    permitted: bool = True


@dataclass(frozen=True)
class Preferences:
    appointment_type: str | None = None
    avoid_class_conflicts: bool = True
    max_travel_minutes: int | None = None
    earliest_hour: int | None = None  # local hour, inclusive
    latest_hour: int | None = None  # local hour, exclusive (slot must end by then)
    allow_conflicts: bool = False  # student explicitly opts in; conflicts still shown


@dataclass
class Conflict:
    label: str
    ref_id: str | None
    kind: str  # CLASS_OVERLAP | TRAVEL_BUFFER | PERSONAL_BLOCK
    overlap_minutes: int


@dataclass
class Ranked:
    slot: Slot
    score: float
    reason_codes: list[str]
    conflicts: list[Conflict] = field(default_factory=list)


@dataclass
class Rejected:
    slot: Slot
    reason_code: str
    conflicts: list[Conflict] = field(default_factory=list)


def overlap_minutes(a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime) -> int:
    """TRD §8 overlap rule: max(startA, startB) < min(endA, endB)."""
    start, end = max(a_start, b_start), min(a_end, b_end)
    return int((end - start).total_seconds() // 60) if start < end else 0


def find_conflicts(slot: Slot, busy: list[Interval]) -> list[Conflict]:
    """Direct overlaps, plus travel buffers on both sides of the visit."""
    buffer = timedelta(minutes=slot.travel_minutes)
    out: list[Conflict] = []
    for b in busy:
        direct = overlap_minutes(slot.starts_at, slot.ends_at, b.start, b.end)
        kind = "PERSONAL_BLOCK" if b.label.startswith("Personal") else "CLASS_OVERLAP"
        if direct:
            out.append(Conflict(b.label, b.ref_id, kind, direct))
            continue
        with_travel = overlap_minutes(slot.starts_at - buffer, slot.ends_at + buffer, b.start, b.end)
        if with_travel:
            out.append(Conflict(b.label, b.ref_id, "TRAVEL_BUFFER", with_travel))
    return out


def _local_hour_ok(slot: Slot, prefs: Preferences, tz) -> bool:
    start, end = slot.starts_at.astimezone(tz), slot.ends_at.astimezone(tz)
    if prefs.earliest_hour is not None and start.hour < prefs.earliest_hour:
        return False
    if prefs.latest_hour is not None and (end.hour, end.minute) > (prefs.latest_hour, 0):
        return False
    return True


def rank_slots(slots: list[Slot], busy: list[Interval], prefs: Preferences, now: datetime, tz) -> tuple[list[Ranked], list[Rejected]]:
    ranked: list[Ranked] = []
    rejected: list[Rejected] = []
    for slot in slots:
        # Hard constraints.
        if not slot.available:
            rejected.append(Rejected(slot, "SLOT_UNAVAILABLE"))
            continue
        if not slot.permitted:
            rejected.append(Rejected(slot, "NOT_ELIGIBLE"))
            continue
        if slot.starts_at <= now:
            rejected.append(Rejected(slot, "IN_THE_PAST"))
            continue
        if prefs.appointment_type and slot.appointment_type != prefs.appointment_type:
            rejected.append(Rejected(slot, "WRONG_APPOINTMENT_TYPE"))
            continue
        if prefs.max_travel_minutes is not None and slot.travel_minutes > prefs.max_travel_minutes:
            rejected.append(Rejected(slot, "TRAVEL_TOO_LONG"))
            continue
        conflicts = find_conflicts(slot, busy)
        if conflicts and prefs.avoid_class_conflicts and not prefs.allow_conflicts:
            code = "CLASS_CONFLICT" if any(c.kind == "CLASS_OVERLAP" for c in conflicts) else (
                "PERSONAL_BLOCK_CONFLICT" if any(c.kind == "PERSONAL_BLOCK" for c in conflicts) else "TRAVEL_BUFFER_CONFLICT")
            rejected.append(Rejected(slot, code, conflicts))
            continue

        # Soft scoring.
        reasons: list[str] = []
        wait_days = max(0.0, (slot.starts_at - now).total_seconds() / 86400)
        score = wait_days * WAIT_POINTS_PER_DAY + (slot.travel_minutes / 10) * TRAVEL_POINTS_PER_10_MIN
        reasons.append("NO_CLASS_CONFLICT" if not conflicts else "HAS_CONFLICT_ALLOWED_BY_STUDENT")
        if wait_days < 1:
            reasons.append("SOONEST_AVAILABLE")
        reasons.append("SHORT_TRAVEL" if slot.travel_minutes <= 10 else "LONGER_TRAVEL")
        if not _local_hour_ok(slot, prefs, tz):
            score += OUTSIDE_PREFERRED_WINDOW
            reasons.append("OUTSIDE_PREFERRED_HOURS")
        if not conflicts:
            buffer = timedelta(minutes=slot.travel_minutes)
            tight = any(
                overlap_minutes(slot.starts_at - buffer - TIGHT_GAP, slot.ends_at + buffer + TIGHT_GAP, b.start, b.end)
                for b in busy
            )
            if tight:
                score += TIGHT_GAP_PENALTY
                reasons.append("TIGHT_BETWEEN_CLASSES")
            else:
                reasons.append("COMFORTABLE_GAP")
        if conflicts:
            score += 100  # conflicts allowed only by explicit opt-in always sink to the bottom
        ranked.append(Ranked(slot, round(score, 2), reasons, conflicts))

    # Deterministic: (cost, start time, slot id).
    ranked.sort(key=lambda r: (r.score, r.slot.starts_at, r.slot.id))
    rejected.sort(key=lambda r: (r.slot.starts_at, r.slot.id))
    return ranked, rejected
