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


# ---- scheduling intents (clinician + time) ----------------------------------------------------------------
WHO_AVAILABLE = re.compile(r"\b(which|what|who|any)\b.{0,20}\b(doctors?|clinicians?|providers?|nurses?)\b|\bwho('?s| is) (available|free)\b|\bavailable (doctors?|clinicians?)\b", re.I)
EARLIEST = re.compile(r"\b(earliest|soonest|first available|as soon as possible|asap)\b", re.I)
NO_PREF = re.compile(r"\b(no preference|don'?t (have a )?preference|anyone is fine|any (doctor|clinician) is fine|doesn'?t matter)\b", re.I)
SAME_AS_LAST = re.compile(r"\b(same (doctor|clinician|provider)|(saw|seen|see) last time|my (usual|regular) doctor)\b", re.I)
GENDER = re.compile(r"\b(female|woman|women|lady)\b|\b(male|man|men)\b(?= (doctor|clinician|provider))", re.I)
PART = re.compile(r"\b(morning|afternoon|evening)\b", re.I)
WEEKDAY_NAMES = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
TYPE_WORDS = [("vaccination", re.compile(r"\b(vaccin\w*|shot|flu shot|booster)\b", re.I)), ("mental_health", re.compile(r"\b(counsel\w*|therap\w*|mental health|anxiety|depress\w*)\b", re.I)),
              ("routine_checkup", re.compile(r"\b(check-?up|physical|routine)\b", re.I))]


def match_clinician(text: str, clinicians: list[tuple[str, str]]) -> str | None:
    """Match 'Dr. Rivera' / 'Avery Rivera' / 'Nair' against REAL clinician names only."""
    low = text.lower()
    for cid, name in clinicians:
        parts = [w for w in re.sub(r"^dr\.?\s+|,.*$", "", name, flags=re.I).lower().split() if len(w) > 2]
        if parts and (parts[-1] in re.findall(r"[a-z]+", low) or " ".join(parts) in low):
            return cid
    return None


def scheduling_intent(conv: dict, text: str, clinicians: list[tuple[str, str]], today, last_clinician: str | None) -> dict | None:
    """Update conv['sched'] from the message. Returns the preferences if this turn is about scheduling."""
    from datetime import timedelta

    sched = dict(conv.get("sched") or {})
    touched = False
    cid = match_clinician(text, clinicians)
    if cid:
        sched["clinician_id"], touched = cid, True
    if SAME_AS_LAST.search(text):
        sched["clinician_id"], sched["same_as_last"], touched = last_clinician, True, True
        sched.pop("attribute", None)
    if NO_PREF.search(text) or WHO_AVAILABLE.search(text):
        if not cid:
            sched.pop("clinician_id", None)
            sched.pop("attribute", None)
            sched.pop("same_as_last", None)
        touched = True
    g = GENDER.search(text)
    if g and re.search(r"\b(doctor|clinician|provider|nurse|someone)\b", text, re.I):
        sched["attribute"], touched = {"gender": "woman" if g.group(1) else "man"}, True
        if not cid:  # a new preference replaces an earlier clinician choice
            sched.pop("clinician_id", None)
            sched.pop("same_as_last", None)
    if EARLIEST.search(text):
        sched["sort"], touched = "earliest", True
    # Day / time-of-day words only mean scheduling inside a scheduling context ("since Monday" is an onset).
    in_context = touched or bool(APPOINTMENT.search(text)) or conv.get("state") == "COORDINATING_APPOINTMENT"
    if not in_context:
        return None
    low = re.sub(r"\b(since|started|starting|began|from)\s+(last\s+)?\w+", " ", text.lower())
    if "tomorrow" in low:
        sched["start"], sched["days"], touched = (today + timedelta(days=1)).isoformat(), 1, True
    elif re.search(r"\btoday\b", low):
        sched["start"], sched["days"], touched = today.isoformat(), 1, True
    else:
        for i, wd in enumerate(WEEKDAY_NAMES):
            if re.search(rf"\b{wd}\b", low):
                delta = (i - today.weekday()) % 7
                sched["start"], sched["days"], touched = (today + timedelta(days=delta)).isoformat(), 1, True
                break
        if re.search(r"\b(this|next) week\b|\bany ?day\b", low):
            sched["start"], sched["days"], touched = today.isoformat(), 5, True
    p = PART.search(low)
    if p:
        sched["part_of_day"], touched = p.group(1).lower(), True
    for t, rx in TYPE_WORDS:
        if rx.search(text):
            sched["appointment_type"] = t
    if APPOINTMENT.search(text) or touched:
        conv["sched"] = sched
        return sched
    return None


def describe_schedule(result: dict, sched: dict) -> str:
    """Short spoken-friendly summary of REAL search results (times come from the scheduling backend)."""
    from datetime import datetime

    def when(s: dict) -> str:
        d = datetime.fromisoformat(s["starts_at"])
        return f"{d:%a} {d:%-I:%M %p}"

    if sched.get("same_as_last") and not sched.get("clinician_id"):
        return "I couldn't find a previous appointment for you, so here's who is available instead."
    with_slots = [c for c in result["clinicians"] if c["slots"]]
    if result.get("notice"):
        alt = result["alternatives"]
        bits = [result["notice"]]
        if alt["same_clinician"]:
            bits.append(f"Their next openings are {', '.join(when(s) for s in alt['same_clinician'][:2])}.")
        if alt["other_clinicians"]:
            bits.append(f"Other clinicians have time, for example {alt['other_clinicians'][0]['clinician_name']} on {when(alt['other_clinicians'][0])}.")
        return " ".join(bits) + " Pick one on screen, or tell me another day."
    if not with_slots:
        return "No eligible appointments matched your calendar. Try another day, or contact the clinic."
    if sched.get("clinician_id") and len(with_slots) == 1:
        c = with_slots[0]
        return f"Here are {c['name']}'s openings that don't clash with your classes — the first is {when(c['slots'][0])}. Choose one on screen to confirm."
    if sched.get("sort") == "earliest":
        s = result["options"][0]
        return f"The earliest opening that fits your classes is {when(s)} with {s['clinician_name']}. Other options are on screen."
    names = ", ".join(f"{c['name']} (first {when(c['slots'][0])})" for c in with_slots[:3])
    return f"Available clinicians: {names}. Tap a time to confirm, or tell me who you'd like to see."
