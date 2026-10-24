"""Structured intake fields: allowed keys, validation, and a deterministic
extractor used when no model is configured. Values are only ever taken from
what the student literally said or typed; nothing is inferred or invented."""

import re
from dataclasses import dataclass
from datetime import date

FIELD_KEYS = (
    "symptoms_free_text",
    "onset_text",
    "onset_date",
    "temperature",
    "appointment_preference",
    "accessibility_needs",
    "requests",
    "photo_observations",
)
LABELS = {
    "symptoms_free_text": "What you're experiencing (your words)",
    "onset_text": "When it started (your words)",
    "onset_date": "Onset date",
    "temperature": "Temperature you measured",
    "appointment_preference": "Appointment preference",
    "accessibility_needs": "Accessibility needs",
    "requests": "Other requests",
    "photo_observations": "Photo observations (non-diagnostic)",
}
# Fields a clinician handoff should usually have; temperature is requested but skippable.
REQUESTED_FOR_HANDOFF = ("symptoms_free_text", "onset_text", "temperature")

TEMP_RANGES = {"C": (30.0, 45.0), "F": (86.0, 113.0)}


class FieldError(ValueError):
    pass


def validate(key: str, value: dict) -> dict:
    """Return a normalised payload or raise FieldError. Never coerces a missing unit."""
    if key not in FIELD_KEYS:
        raise FieldError(f"Unknown field '{key}'.")
    if key == "temperature":
        try:
            v = float(value.get("value"))
        except (TypeError, ValueError):
            raise FieldError("Temperature needs a number.") from None
        unit = str(value.get("unit") or "").upper()[:1]
        if unit not in TEMP_RANGES:
            raise FieldError("Temperature needs a unit (°C or °F).")
        lo, hi = TEMP_RANGES[unit]
        if not lo <= v <= hi:
            raise FieldError(f"{v}°{unit} is outside the range a thermometer reading would show. Please re-check it.")
        out = {"value": round(v, 1), "unit": unit}
        if value.get("measured_at"):
            out["measured_at"] = str(value["measured_at"])[:40]
        return out
    if key == "onset_date":
        try:
            d = date.fromisoformat(str(value.get("date")))
        except ValueError:
            raise FieldError("Onset date must be YYYY-MM-DD.") from None
        return {"date": d.isoformat()}
    text = str(value.get("text") or "").strip()
    if not text:
        raise FieldError("This field can't be empty.")
    return {"text": text[:1000]}


@dataclass
class Extracted:
    key: str
    value: dict


_TEMP = re.compile(r"(\d{2,3}(?:\.\d)?)\s*(?:°|degrees?)?\s*(f|c|fahrenheit|celsius)\b", re.I)
_TEMP_NO_UNIT = re.compile(r"\b(?:temp(?:erature)?|fever)\D{0,20}(\d{2,3}(?:\.\d)?)\b", re.I)
_ONSET = re.compile(
    r"\b(since (yesterday|last night|this morning|(last )?(monday|tuesday|wednesday|thursday|friday|saturday|sunday)|the weekend)|"
    r"(for|about|around) (a|one|two|three|four|five|\d+) (hours?|days?|weeks?)|started (yesterday|today|this morning|last night|on \w+ \d+))\b",
    re.I,
)
_SYMPTOM_WORDS = re.compile(
    r"\b(feel\w*|sick|ill|unwell|pain|ache|aching|hurt\w*|fever|cough\w*|sore|nause\w*|vomit\w*|dizzy|tired|fatigue\w*|rash|itch\w*|"
    r"swell\w*|headache|migraine|cold|flu|congest\w*|throat|stomach|diarrh\w*|anxious|anxiety|stress\w*|depress\w*|can'?t sleep|insomnia)\b",
    re.I,
)


def extract(text: str) -> tuple[list[Extracted], list[str]]:
    """Returns (fields, notes). Notes flag things to ask about instead of guessing."""
    fields: list[Extracted] = []
    notes: list[str] = []
    m = _TEMP.search(text)
    if m:
        unit = m.group(2)[0].upper()
        try:
            fields.append(Extracted("temperature", validate("temperature", {"value": m.group(1), "unit": unit})))
        except FieldError:
            notes.append("temperature_out_of_range")
    elif _TEMP_NO_UNIT.search(text):
        notes.append("temperature_unit_missing")
    o = _ONSET.search(text)
    if o:
        fields.append(Extracted("onset_text", {"text": o.group(0)}))
    if _SYMPTOM_WORDS.search(text):
        fields.append(Extracted("symptoms_free_text", {"text": text.strip()[:1000]}))
    return fields, notes


def display(key: str, value: dict) -> str:
    if key == "temperature":
        return f"{value['value']}°{value['unit']}" + (f" (measured {value['measured_at']})" if value.get("measured_at") else "")
    if key == "onset_date":
        return value["date"]
    return value.get("text", "")
