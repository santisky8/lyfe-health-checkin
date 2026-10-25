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
    r"seizure|fit(ting)?\b",
    r"suicid|kill myself|end my life|self[- ]harm|hurt myself",
    r"overdose|took too many",
    r"severe allergic|throat (swelling|closing)|anaphyla",
]
_DANGER = re.compile("|".join(DANGER), re.IGNORECASE)


def check(text):
    """Return the emergency message if the text shows a danger sign, else None."""
    return EMERGENCY if _DANGER.search(text) else None


DISCLAIMER = (
    "This is general health information, not medical advice. It does not diagnose or "
    "replace a doctor."
)
