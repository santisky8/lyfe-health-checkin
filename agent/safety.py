"""Danger-sign filter. Runs before any model call; a match skips advice entirely."""
import re

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
    r"overdose|took too many",
    r"severe allergic|throat (swelling|closing)|anaphyla",
    r"sudden(ly)? (numb|weak|can'?t move|lost (my )?(vision|sight))",
    r"(stiff neck|rash).{0,40}fever|fever.{0,40}(stiff neck|rash)",
    r"severe (stomach|abdominal|belly) pain",
    r"(red|hot|swollen).{0,30}(spreading|streak)",
    r"(sudden|can'?t) (see|speak)|lost (my )?(vision|speech)",
]
_DANGER = re.compile("|".join(DANGER), re.IGNORECASE)
_SELF_HARM = re.compile(
    r"suicid|kill myself|end my life|self[- ]harm|hurt myself|overdose|took too many", re.IGNORECASE)
# "No chest pain, just tired": a sign the person rules out in the same clause doesn't count.
_NEGATED = re.compile(r"\b(no|not|without|never|don'?t have|isn'?t|wasn'?t)\b[^.,;!?]{0,25}$",
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
