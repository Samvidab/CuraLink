"""Stateful intake dialog manager (used directly in scripted mode; feeds context + guards in Claude mode).

Fixes the repetition bug: the previous fallback was stateless keyword matching, so any message
without a keyword ("hi", "I don't know", "what now?") got the same canned paragraph, and declined
questions were asked again on every turn.

States: GREETING -> COLLECTING_INITIAL_CONCERN -> CLARIFYING_INFORMATION -> OPTIONAL_CONTEXTUAL_INPUT
        -> OFFERING_NEXT_STEPS -> REVIEWING_INTAKE / COORDINATING_APPOINTMENT -> COMPLETED
State lives in IntakeSession.conversation (JSON), so it survives text<->voice switches and reloads.
Nothing here diagnoses, ranks urgency or sets absence dates.
"""

import hashlib
import re
from dataclasses import dataclass, field

FEVER = re.compile(r"\b(fever\w*|temperature|temp\b|chills|feel(ing)? hot|sweats|burning up)\b", re.I)
VISIBLE = re.compile(r"\b(rash\w*|dry|flak\w*|itch\w*|bruis\w*|swell\w*|swollen|red(ness)?|bump\w*|cut|scrape\w*|burn(ed|t)?\b|spot\w*|hives|blister\w*|skin|lump\w*|bite\w*|wound)\b", re.I)
DECLINE = re.compile(r"^\s*(no|nope|nah|skip|pass)\b|(i\s*)?(don'?t|do not) know|not sure|no idea|didn'?t (measure|check|take)|haven'?t (measured|checked|taken)|rather not|prefer not|no thanks|can'?t remember|unsure", re.I)
APPOINTMENT = re.compile(r"\b(appointment|book|schedule|slot|see (someone|a doctor|a nurse|the doctor)|get seen|find (a )?time|visit)\b", re.I)
REVIEW = re.compile(r"\b(review|summary|summari[sz]e|what do you know|what have you got|show (me )?my (info|information|details))\b", re.I)
END = re.compile(r"\b(that'?s (all|it)|that is all|bye|goodbye|end (this|the) (chat|conversation)|i'?m done|we'?re done|nothing else|no,? that'?s it|stop (the )?(chat|conversation))\b", re.I)
WHAT_NOW = re.compile(r"\b(what now|what next|what should i do|next steps?|what can you do|help me|how does this work)\b", re.I)
GREETING = re.compile(r"^\s*(hi|hello|hey|good (morning|afternoon|evening)|yo)\b[\s!.,]*$", re.I)
THANKS = re.compile(r"^\s*(thanks|thank you|thx|ok(ay)?|cool|great|got it)\b[\s!.,]*$", re.I)
PHOTO = re.compile(r"\b(photo|picture|pic|image|upload)\b", re.I)
SYMPTOM = re.compile(r"\b(feel\w*|sick|ill|unwell|pain|ache|aching|hurt\w*|sore|nause\w*|vomit\w*|dizzy|tired|fatigue\w*|cough\w*|headache|migraine|cold|flu|congest\w*|throat|stomach|diarrh\w*|anxious|anxiety|stress\w*|depress\w*|insomnia)\b", re.I)

QUESTIONS = {
    "onset_text": ["When did this start?", "Roughly when did it begin?"],
    "temperature": ["Do you know your temperature? If you measured it, tell me the number and °F or °C — or say you don't know.",
                    "Did you take your temperature? A number with °F or °C helps, but it's fine if you didn't."],
    "photo": ["If it would help to show what it looks like, you can add a photo — totally optional.",
              "You can optionally add a photo of the area; it's never shared unless you choose to."],
}
LABEL = {"onset_text": "when it started", "temperature": "your temperature", "photo": "a photo"}


@dataclass
class Turn:
    text: str
    state: str
    actions: list[str] = field(default_factory=list)
    form: dict | None = None
    pending: str | None = None


def blank() -> dict:
    return {"state": "GREETING", "turn": 0, "pending": None, "asked": {}, "declined": [], "concerns": [], "last": [], "guidance_given": False, "photo_offered": False}


def _h(text: str) -> str:
    return hashlib.sha1(text.lower().encode()).hexdigest()[:12]


def update_concerns(conv: dict, text: str) -> None:
    c = set(conv.get("concerns", []))
    if FEVER.search(text):
        c.add("fever")
    if VISIBLE.search(text):
        c.add("visible")
    if SYMPTOM.search(text) or FEVER.search(text) or VISIBLE.search(text):
        c.add("symptom")
    conv["concerns"] = sorted(c)


def record_decline(conv: dict, text: str) -> str | None:
    """If the student declines the pending question, remember it so it's never asked again."""
    pending = conv.get("pending")
    if pending and DECLINE.search(text):
        conv["declined"] = sorted(set(conv.get("declined", [])) | {pending})
        conv["pending"] = None
        return pending
    if re.search(r"\b(no|don'?t want|without)\b.*\b(photo|picture|image)\b", text, re.I):
        conv["declined"] = sorted(set(conv.get("declined", [])) | {"photo"})
        if conv.get("pending") == "photo":
            conv["pending"] = None
        return "photo"
    return None


def next_question(conv: dict, have: set[str], has_photo: bool) -> str | None:
    """Only relevant, unanswered, un-declined questions; each asked at most once."""
    concerns = set(conv.get("concerns", []))
    done = set(conv.get("declined", [])) | {k for k, n in conv.get("asked", {}).items() if n >= 1}
    candidates = []
    if "symptom" in concerns and not ({"onset_text", "onset_date"} & have):
        candidates.append("onset_text")
    if "fever" in concerns and "temperature" not in have:
        candidates.append("temperature")
    if "visible" in concerns and not has_photo:
        candidates.append("photo")
    return next((k for k in candidates if k not in done), None)


def _ack(updated: list[str], fields: dict[str, str]) -> str:
    if "temperature" in updated:
        return f"Noted your temperature: {fields.get('temperature', '')}."
    if "onset_text" in updated or "onset_date" in updated:
        return f"Got it — noted when it started (“{fields.get('onset_text') or fields.get('onset_date', '')}”)."
    if "symptoms_free_text" in updated:
        return "Thanks, I've noted that in your own words."
    return ""


def plan(conv: dict, text: str, updated: list[str], fields: dict[str, str], has_photo: bool, has_calendar: bool, notes: list[str]) -> Turn:
    """Decide the next scripted reply and state. Mutates conv (pending/asked/state/last)."""
    conv.setdefault("asked", {})
    conv["turn"] = conv.get("turn", 0) + 1
    update_concerns(conv, text)
    declined = record_decline(conv, text)
    if conv.get("pending") and conv["pending"] in updated:
        conv["pending"] = None
    have = set(fields)
    parts: list[str] = []
    if declined:
        parts.append(f"No problem — we'll leave out {LABEL.get(declined, 'that')}.")
    ack = _ack(updated, fields)
    if ack:
        parts.append(ack)
    if "temperature_unit_missing" in notes:
        conv["pending"] = "temperature"
        return Turn(" ".join(parts + ["Was that in °F or °C? I won't guess the unit."]), "CLARIFYING_INFORMATION", ["OPEN_INTAKE_FORM"], {"fields": ["temperature"]}, "temperature")
    if "temperature_out_of_range" in notes:
        return Turn(" ".join(parts + ["That reading looks unusual — could you re-check it? You can also enter it in the form."]), "CLARIFYING_INFORMATION", ["OPEN_INTAKE_FORM"], {"fields": ["temperature"]})

    calendar_actions = [] if has_calendar else ["IMPORT_CALENDAR"]
    if END.search(text):
        conv["pending"] = None
        msg = "Okay — I'll stop here. " + ("Your notes are saved; review them before sharing with your clinician." if have else "You can come back any time.")
        return Turn(" ".join(parts + [msg]), "COMPLETED", ["REVIEW_INTAKE", "FIND_CARE"] if have else ["FIND_CARE"])
    if APPOINTMENT.search(text):
        conv["pending"] = None
        msg = "Let's find a time. I'll show demo clinic slots that fit around your classes — you confirm on the next screen." if has_calendar else "Let's find a time. Import your UniTime calendar first so I only suggest slots that don't clash with classes."
        return Turn(" ".join(parts + [msg]), "COORDINATING_APPOINTMENT", ["FIND_CARE", *calendar_actions])
    if REVIEW.search(text):
        return Turn(" ".join(parts + ["Here's what I have so far — check each item before anything is shared."]), "REVIEWING_INTAKE", ["REVIEW_INTAKE"])
    if PHOTO.search(text) and "photo" not in conv.get("declined", []) and not declined:
        conv["photo_offered"] = True
        return Turn(" ".join(parts + ["Sure — add a photo in the form. It's optional, I'll only describe visible features (never a diagnosis), and you choose whether your clinician sees it."]), "OPTIONAL_CONTEXTUAL_INPUT", ["OFFER_PHOTO"], {"fields": ["photo"]})

    q = next_question(conv, have, has_photo)
    if q:
        conv["pending"] = q
        conv["asked"][q] = conv["asked"].get(q, 0) + 1
        variants = QUESTIONS[q]
        question = variants[conv["turn"] % len(variants)]
        if q == "photo":
            conv["photo_offered"] = True
            return Turn(" ".join(parts + [question]), "OPTIONAL_CONTEXTUAL_INPUT", ["OFFER_PHOTO", "FIND_CARE"], {"fields": ["photo"]}, q)
        form = {"fields": ["temperature"]} if q == "temperature" else None
        actions = ["OPEN_INTAKE_FORM"] if form else []
        return Turn(" ".join(parts + [question]), "CLARIFYING_INFORMATION", actions, form, q)

    if "symptom" in conv.get("concerns", []) or have:
        conv["pending"] = None
        if WHAT_NOW.search(text) or THANKS.search(text):
            return Turn(" ".join(parts + ["From here you can: review what I've noted, find an appointment that fits your classes, add something else, or end the conversation. What would you like?"]), "OFFERING_NEXT_STEPS", ["REVIEW_INTAKE", "FIND_CARE", "ADD_MORE", "END_CONVERSATION", *calendar_actions])
        if not conv.get("guidance_given"):
            conv["guidance_given"] = True
            guidance = "Thanks — that gives your clinician a clear picture. In the meantime, keep an eye on how it changes; if it gets worse or something new and severe appears, contact a clinician sooner, or call 911 in an emergency."
        else:
            guidance = "Anything else you'd like to add, or shall we move on?"
        return Turn(" ".join(parts + [guidance, "You can review your information, find an appointment, add more, or end here."]), "OFFERING_NEXT_STEPS", ["REVIEW_INTAKE", "FIND_CARE", "ADD_MORE", "END_CONVERSATION", *calendar_actions])

    # No concern described yet.
    if WHAT_NOW.search(text):
        msg = "I can help you describe what's going on for your clinician, find a demo appointment that fits your classes, and prepare absence paperwork your clinician reviews. What would you like to do?"
        return Turn(msg, "COLLECTING_INITIAL_CONCERN", ["FIND_CARE"])
    if THANKS.search(text):
        return Turn("You're welcome. Tell me what's going on whenever you're ready, or I can help you find an appointment.", "COLLECTING_INITIAL_CONCERN", ["FIND_CARE"])
    if conv["turn"] <= 1 or GREETING.search(text):
        return Turn("Hi! What's going on today? Describe it in your own words — or if you just need an appointment, say so.", "COLLECTING_INITIAL_CONCERN", ["FIND_CARE"])
    return Turn("I'm not sure I followed. Could you describe what you're experiencing, or would you rather go straight to finding an appointment?", "COLLECTING_INITIAL_CONCERN", ["FIND_CARE"])


def avoid_repeat(conv: dict, text: str, fallback: str) -> str:
    """Never send the same reply twice in a row (also guards Claude output)."""
    h = _h(text)
    if h in conv.get("last", [])[-2:]:
        text = fallback if _h(fallback) not in conv.get("last", [])[-2:] else "Would you like to review your information, find an appointment, or add something else?"
    conv["last"] = (conv.get("last", []) + [_h(text)])[-4:]
    return text


def context_for_model(conv: dict, fields: dict[str, str]) -> str:
    known = "; ".join(f"{k}={v}" for k, v in fields.items()) or "nothing yet"
    return (f"conversation state {conv.get('state')}; already known: {known}; student declined: {', '.join(conv.get('declined', [])) or 'nothing'}; "
            f"already asked: {', '.join(conv.get('asked', {})) or 'nothing'}. Do NOT ask about anything declined, known or already asked. "
            "Only ask about temperature if they mention fever; only offer a photo for something visible. If they want an appointment, go straight to it.")
