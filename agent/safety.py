"""Danger-sign filter. Runs before any model call; a match skips advice entirely.

Two layers: plain rules for medical danger signs (chest pain, stroke signs, self-harm), then
NVIDIA's Nemotron Safety Guard model for harmful requests the rules can't phrase, such as asking
how many pills would be fatal. The rules never depend on the model: if it is unreachable, the
rules still run and the trace says the model was skipped."""
import json
import os
import re
import time
import unicodedata
import urllib.request

import llm

EMERGENCY = (
    "This could be serious. Please get help now: call your local emergency number "
    "(911 in North America, 112 in Europe, 999 in the UK). "
    "If you're thinking about harming yourself, find a free, confidential line at "
    "https://findahelpline.com (in Canada and the US, call or text 988)."
)

# Patterns based on the "call 999 / go to A&E" lists on NHS and MedlinePlus pages, matched on
# normalised text (see _normal): lower case, no accents, look-alike letters and l33t digits
# mapped back, hyphens and runs of spaces collapsed. English, Spanish and French.
DANGER = [
    r"chest (pain|tightness|pressure|hurts?)|(pain|pressure|tightness) in (my )?chest|"
    r"my chest (hurts|is (tight|hurting))",
    r"(having|had|think i'?m having|might be having|is having) a (heart attack|stroke)",
    r"(can'?t|cannot|unable to|hard to|trouble|difficulty) (catch (my|a) )?breath|"
    r"short(ness)? of breath|gasping|lips (are |is )?(turning |turned |going )?(blue|purple)",
    r"(face|mouth|smile) (is )?droop|one side of (my |his |her )?face|slurred speech|"
    r"speech is slurred|arm (is |feels |went |goes )?(weak|numb)",
    r"(worst|sudden|thunderclap) headache",
    r"faint(ed|ing)|passed out|blacked out|unconscious",
    r"cough(ing)? (up )?blood|vomit(ing)? blood|blood in (my )?(stool|poo)|"
    r"(won'?t|can'?t|doesn'?t|will not) stop bleeding|bleeding (that )?(won'?t|will not) stop",
    r"seizure|convuls|\b(having|had) (a )?fits?\b|\bfitting\b",
    # "took too many Tylenol" counts; "took too many steps / breaks / naps" doesn't.
    r"overdos|took (way )?too (many|much)\b(?! (steps|hours|time|naps?|days|breaks|sun|photos))|"
    r"took \d{2,} (pills|tablets|capsules|tylenol|advil|aspirin|paracetamol|acetaminophen|ibuprofen|"
    r"sleeping pills)",
    r"severe allergic|throat (is )?(swelling|closing)|anaphyla",
    r"sudden(ly)? (numb|weak|can'?t move|lost (my )?(vision|sight))",
    r"(stiff neck|rash).{0,40}fever|fever.{0,40}(stiff neck|rash)",
    r"severe (stomach|abdominal|belly) pain",
    r"(red|hot|swollen).{0,30}(spreading|streak)",
    r"(sudden|can'?t) (see|speak)|lost (my )?(vision|speech)",
    # Spanish and French emergencies
    r"dolor (en el|de) pecho|no puedo respirar|me desmaye|desmayo|sobredosis|"
    r"douleur (thoracique|dans la poitrine)|mal a la poitrine|(je )?(ne peux pas|n'?arrive pas a) "
    r"respirer|surdose|evanoui",
]
# Self-harm and lethal-dose wording. Never cancelled by a denial nearby: "I'm not ok and want to
# end my life" is not a denial.
SELF_HARM = (
    r"suicid|kill (my ?self|me)\b|end (my life|it all)|self harm|hurt myself|cut myself|"
    r"(want|wanna|going|ready) to die\b(?! (my|your|her|his|the|it|them)\b)|don'?t want to (be alive|live|wake up)|better off dead|"
    r"unalive|take all (of )?(my|the) (pills|meds|medicine)|"
    r"swallowed (a|the|my) (whole )?(bottle|pack|box)|"
    r"(lethal|fatal|deadly) (dose|amount)|"
    r"how (many|much) .{0,40}(kill|be fatal|be lethal|to die|not wake up|is too (many|much))|"
    r"quiero morir|matarme|quitarme la vida|no quiero vivir|"
    r"je veux mourir|me tuer|en finir|me suicider"
)
_DANGER = re.compile("|".join(DANGER + [SELF_HARM]), re.IGNORECASE)
_SELF_HARM = re.compile(SELF_HARM, re.IGNORECASE)
# "No chest pain, just tired": a sign the person rules out in the same clause doesn't count.
# "not sure" or "not a normal" deny nothing, "no matter" isn't a denial, and a new clause
# ("no fever but chest pain") ends a denial. "never" is not a denial either: "I've never felt
# chest pain like this" is a reason to get help.
_NEGATED = re.compile(r"\b(no(?! matter)|not(?! sure| certain| a normal| normal| like)|without|"
                      r"don'?t have|isn'?t|wasn'?t)\b"
                      r"(?:(?!\b(?:but|and|though|although|however)\b)[^.,;!?]){0,25}$",
                      re.IGNORECASE)
# Look-alike letters (Cyrillic, Greek) and l33t digits inside words, mapped back to Latin.
_LOOKALIKE = str.maketrans("аеорсухіјѕԁԛԝаеоїі" "αεορτυνικ", "aeopcyxijsdqwaeoii" "aeoptuvik")
_LEET = {"1": "i", "3": "e", "0": "o", "4": "a", "5": "s", "7": "t", "@": "a", "$": "s"}


def _normal(text):
    """Lower case, no accents, look-alikes and l33t mapped back, one space between words."""
    t = unicodedata.normalize("NFKD", unicodedata.normalize("NFKC", text).lower())
    t = "".join(c for c in t if not unicodedata.combining(c)).translate(_LOOKALIKE)
    t = t.replace("’", "'").replace("‘", "'")
    t = re.sub(r"(?<=[a-z])[134057@$]|[134057@$](?=[a-z])",
               lambda m: _LEET.get(m.group(), m.group()), t)
    return re.sub(r"[\s_\-]+", " ", t)


def check(text):
    """Return the emergency message if the person's own words show a danger sign, else None.
    Only the person's words: the agent's questions mention danger signs on purpose."""
    text = _normal(text)
    for m in _DANGER.finditer(text):
        before = text[max(0, m.start() - 40):m.start()]
        if _SELF_HARM.match(m.group()) or not _NEGATED.search(before):
            return EMERGENCY
    return None


DISCLAIMER = (
    "This is general health information, not medical advice. It does not diagnose or "
    "replace a doctor."
)


GUARD_MODEL = "nvidia/llama-3.1-nemotron-safety-guard-8b-v3"
GUARD_URL = llm.NVIDIA_CLOUD + "/chat/completions"


def guard(text):
    """Nemotron Safety Guard's verdict on the person's words: {"safe", "categories", "seconds"},
    or None when there is no NVIDIA key or the call fails (the rules above still ran)."""
    key = os.environ.get("NVIDIA_API_KEY")
    if not key:
        return None
    body = {"model": GUARD_MODEL, "messages": [{"role": "user", "content": text}], "max_tokens": 60}
    req = urllib.request.Request(GUARD_URL, data=json.dumps(body).encode(), headers={
        "Content-Type": "application/json", "Authorization": f"Bearer {key}"})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=8) as r:
            reply = json.load(r)["choices"][0]["message"]["content"]
        verdict = json.loads(reply[reply.index("{"):reply.rindex("}") + 1])
    except Exception:
        return None
    cats = [c.strip() for c in verdict.get("Safety Categories", "").split(",") if c.strip()]
    return {"safe": verdict.get("User Safety", "safe").lower() == "safe", "categories": cats,
            "seconds": round(time.time() - t0, 1)}
