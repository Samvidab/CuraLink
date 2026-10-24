"""Deterministic safety screen. Runs on every student message BEFORE any model
call and is never overridden by model output or photos.

PROTOTYPE ONLY: these patterns and messages are not clinically validated.
Clinician review of the escalation criteria is required before real use (PRD §8).
It deliberately over-triggers: a false alarm costs a click, a miss costs more.
"""

import re
from dataclasses import dataclass

CRISIS = re.compile(
    r"\b(suicid\w*|kill(ing)? myself|end (my|it all)|take my (own )?life|self[- ]?harm|hurt(ing)? myself|don'?t want to (live|be alive))\b",
    re.I,
)
EMERGENCY = re.compile(
    r"\b(chest (pain|pressure|tightness)|can'?t breathe|cannot breathe|(trouble|difficulty|hard) breathing|short(ness)? of breath|choking|"
    r"unconscious|passed out|won'?t wake|seizure|convuls\w*|stroke|face (is )?droop\w*|slurred speech|"
    r"(severe|heavy|uncontrolled|won'?t stop) bleeding|bleeding (a lot|heavily|won'?t stop|that won'?t stop)|"
    r"overdos\w*|poison\w*|anaphyla\w*|throat (is )?(swelling|closing)|tongue (is )?swelling|sudden (major |severe )?swelling|"
    r"emergency|911)\b",
    re.I,
)

EMERGENCY_MESSAGE = (
    "This could need urgent help. If you're in danger or this feels like an emergency, call 911 now or go to the nearest "
    "emergency department. Don't wait for this app. CuraLink can't assess medical urgency."
)
CRISIS_MESSAGE = (
    "I'm really glad you told me. If you might hurt yourself, call or text 988 (Suicide & Crisis Lifeline) right now, or call 911 "
    "if you're in immediate danger. You don't have to handle this alone."
)


@dataclass(frozen=True)
class SafetyResult:
    state: str  # GENERAL_SUPPORT | EMERGENCY_GUIDANCE
    category: str | None  # crisis | emergency
    message: str | None


def screen(text: str) -> SafetyResult:
    if CRISIS.search(text or ""):
        return SafetyResult("EMERGENCY_GUIDANCE", "crisis", CRISIS_MESSAGE)
    if EMERGENCY.search(text or ""):
        return SafetyResult("EMERGENCY_GUIDANCE", "emergency", EMERGENCY_MESSAGE)
    return SafetyResult("GENERAL_SUPPORT", None, None)


_DIAGNOSTIC = re.compile(
    r"\b(you (likely|probably|might|may|must) have|it (sounds|looks) like (you have|you've got)|diagnos(e|is|ed|ing)\b(?! or)|"
    r"you('re| are) (suffering from|infected)|(take|try) \d+\s?mg|nothing to worry about|(it'?s|this is) (probably |likely )?not serious)\b",
    re.I,
)

SAFE_REPLACEMENT = (
    "I can't assess what's causing this or how urgent it is, but I can help you organize details for a clinician and find an "
    "appointment that fits your classes."
)


def guard_output(text: str) -> tuple[str, bool]:
    """Replace model output that drifts into diagnosis, dosing or reassurance."""
    if _DIAGNOSTIC.search(text or ""):
        return SAFE_REPLACEMENT, True
    return text, False
