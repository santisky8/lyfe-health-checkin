"""Hypothesis step: turn an everyday description into candidate condition names.

"Stinging needles in the soles of my feet" -> peripheral neuropathy, plantar fasciitis, ...
These are search terms for the library and PubMed, not a diagnosis; the answer weighs them
against the evidence.
"""
import re

import llm

SYSTEM = ("You generate search terms for a medical reference library. You do not give advice. "
          "Output only condition names separated by semicolons.")
ASK = ("Which conditions or everyday causes should the library look up for this description? "
       "Up to 4 standard medical names, most likely first.\n\nDescription: {question}")


def candidates(question):
    text = llm.chat([{"role": "system", "content": SYSTEM},
                     {"role": "user", "content": ASK.format(question=question)}],
                    max_tokens=60, temperature=0)
    names = [re.sub(r"^[\s\d.\-*]+|[\s.]+$", "", n) for n in re.split(r"[;\n]", text)]
    return [n for n in names if 2 < len(n) < 60][:4]


if __name__ == "__main__":
    import sys
    print(candidates(" ".join(sys.argv[1:])))
