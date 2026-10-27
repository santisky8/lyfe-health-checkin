"""Danger-sign filter. Runs before any model call; a match skips advice entirely.

Two layers: plain rules for medical danger signs (chest pain, stroke signs, self-harm), then
NVIDIA's Nemotron Safety Guard model for harmful requests the rules can't phrase, such as asking
how many pills would be fatal. The rules never depend on the model: if it is unreachable, the
rules still run and the trace says the model was skipped."""
import json
import os
import re
import time
import urllib.request

import llm

EMERGENCY = (
    "This could be serious. Please get help now: call your local emergency number "
    "(911 in North America, 112 in Europe, 999 in the UK). "
    "If you're thinking about harming yourself, find a free, confidential line at "
    "https://findahelpline.com (in Canada and the US, call or text 988)."
)

# Patterns based on the "call 999 / go to A&E" lists on NHS and MedlinePlus pages.
DANGER = [
    r"chest (pain|tightness|pressure)",
    r"(can'?t|cannot|hard to|trouble|difficulty) breath",
    r"short(ness)? of breath",
    r"face (drooping|droop)|slurred speech|arm (weak|numb)",
    r"(worst|sudden|thunderclap) headache",
    r"faint(ed|ing)|passed out|unconscious",
    r"cough(ing)? (up )?blood|vomit(ing)? blood|blood in (my )?(stool|poo)",
    r"seizure|convuls|\b(having|had) (a )?fits?\b|\bfitting\b",
    r"suicid|kill myself|end my life|self[- ]harm|hurt myself",
    # "took too many Tylenol" counts; "took too many steps / breaks / naps" doesn't.
    r"overdos|took (way )?too (many|much)\b(?! (steps|hours|time|naps?|days|breaks|sun|photos))",
    r"(lethal|fatal|deadly) (dose|amount)|how (many|much) .{0,30}(kill|be fatal|be lethal|to die)",
    r"severe allergic|throat (swelling|closing)|anaphyla",
    r"sudden(ly)? (numb|weak|can'?t move|lost (my )?(vision|sight))",
    r"(stiff neck|rash).{0,40}fever|fever.{0,40}(stiff neck|rash)",
    r"severe (stomach|abdominal|belly) pain",
    r"(red|hot|swollen).{0,30}(spreading|streak)",
    r"(sudden|can'?t) (see|speak)|lost (my )?(vision|speech)",
]
_DANGER = re.compile("|".join(DANGER), re.IGNORECASE)
# Never cancelled by a denial nearby: "I'm not ok and want to end my life". An overdose can
# be denied ("I didn't overdose"), so it is left to the usual negation check.
_SELF_HARM = re.compile(
    r"suicid|kill myself|end my life|self[- ]harm|hurt myself|"
    r"(lethal|fatal|deadly) (dose|amount)|how (many|much) .{0,30}(kill|be fatal|be lethal|to die)",
    re.IGNORECASE)
# "No chest pain, just tired": a sign the person rules out in the same clause doesn't count.
# "not sure" doesn't deny anything, and a new clause ("no fever but chest pain") ends a denial.
_NEGATED = re.compile(r"\b(no|not(?! sure| certain)|without|never|don'?t have|isn'?t|wasn'?t)\b"
                      r"(?:(?!\b(?:but|and|though|although|however)\b)[^.,;!?]){0,25}$",
                      re.IGNORECASE)


def check(text):
    """Return the emergency message if the person's own words show a danger sign, else None.
    Only the person's words: the agent's questions mention danger signs on purpose."""
    for m in _DANGER.finditer(text):
        # Self-harm always counts: "I'm not ok and want to end my life" is not a denial.
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
