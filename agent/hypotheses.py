"""Hypothesis step: turn an everyday description into candidate condition names.

"Stinging needles in the soles of my feet" -> peripheral neuropathy, plantar fasciitis, ...
These are search terms for the library and PubMed, not a diagnosis; the answer weighs them
against the evidence.
"""
import re

import llm

SYSTEM = ("You generate search terms for a medical reference library. You do not give advice. "
          "Follow the output format exactly.")
ASK = ("For this message, give two lines.\n"
       "CONDITIONS: up to 4 standard medical names of conditions or everyday causes the library "
       "should look up, most likely first, separated by semicolons.\n"
       "REMEDIES: every remedy, supplement, product, food, medicine or practice the person "
       "names (for example ginger; honey; arnica; homeopathy), separated by semicolons, or "
       "none.\n"
       "BRANDS: any brand or product names among them (a commercial product, not a generic "
       "herb, food or ingredient), separated by semicolons, or none.\n\nMessage: {question}")


def _names(line):
    """Clean names: drop notes such as "Gut FX (product)" -> "Gut FX", and anything that reads
    like a sentence ("Since no specific condition is mentioned") rather than a name."""
    names = [re.sub(r"\s*\(.*?\)\s*|\s*\(.*$", " ", n) for n in re.split(r"[;,]", line)]
    names = [re.sub(r"^[\s\d.\-*]+|[\s.]+$", "", n) for n in names]
    return [n for n in names if 2 < len(n) < 60 and len(n.split()) <= 5
            and not n.lower().startswith(("none", "no ", "since ", "not "))]


def _model():
    """The fast model for search terms when one is set (Nemotron Bolt on Nightshift): big
    reasoning models spend the token budget thinking and may return no list at all."""
    import os
    return os.environ.get("HYPO_MODEL") or None


def analyse(question):
    """Candidate conditions and the remedies or products the person asks about."""
    text = llm.chat([{"role": "system", "content": SYSTEM},
                     {"role": "user", "content": ASK.format(question=question)}],
                    max_tokens=400, temperature=0, model=_model())
    found = {"conditions": [], "remedies": [], "brands": []}
    for line in text.splitlines():
        key, _, rest = line.partition(":")
        key = key.strip().lower()
        if key.startswith("condition"):
            found["conditions"] = _names(rest)[:4]
        elif key.startswith("remed"):
            found["remedies"] = _names(rest)[:3]
        elif key.startswith("brand"):
            found["brands"] = _names(rest)[:2]
    return found


def candidates(question):
    return analyse(question)["conditions"]


if __name__ == "__main__":
    import sys
    print(analyse(" ".join(sys.argv[1:])))
