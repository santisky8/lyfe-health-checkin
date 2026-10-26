"""Clarifying questions, asked before any answer is written.

Some answers depend on details people leave out. "How long should I take arnica?" is a safety
question that changes with the form: arnica taken by mouth as an herbal supplement is toxic,
while homeopathic pellets and gels on unbroken skin are usually safe. So when the answer
depends on such a detail, the agent asks first (up to three short questions, each with tap
options) and answers once it knows.
"""
import json
import os
import re

import llm

SYSTEM = ("You decide what a careful health guide must know before answering. You do not "
          "answer the question. Reply with JSON only.")
ASK = """Message: {question}

Should the guide ask before answering? Ask only when the answer or its safety really changes
with a detail the message leaves out. Never ask for something the message already says.
- A remedy, herb or supplement: the form (taken by mouth as a supplement or tea, homeopathic
  pellets, cream or gel on the skin), what it is for, and how much and how often, when these
  are missing. The form options must always include "By mouth as a supplement, capsule or
  tea", because that is often the form with the most safety concerns.
- A symptom: when it started, how bad it is, and the one detail that tells the likely causes
  apart (an injury, fever, one side or both), when these are missing.
- Pregnancy, other medicines or conditions only when they change the safety.
- Nothing to ask when the message is clear enough, or is a general "why" question about
  the person's own week (sleep, energy, activity).

Reply with {{"questions": []}} or up to 3 questions, each with 2 to 5 short answer options:
{{"questions": [{{"q": "How are you taking it?", "options": ["By mouth as a supplement",
"Homeopathic pellets", "Gel or cream on the skin"]}}]}}"""

ANSWERED = ("my answers:", "ingredients on the label")
ORAL = "By mouth as a supplement, capsule or tea"


def questions(question):
    """Up to three questions with answer options, or [] when the guide can answer now. Uses the
    main model (CLARIFY_MODEL overrides it): the small one asks about the wrong things, such as
    what arnica is for, but not whether it is taken by mouth."""
    if any(mark in question.lower() for mark in ANSWERED):
        return []
    try:
        text = llm.chat([{"role": "system", "content": SYSTEM},
                         {"role": "user", "content": ASK.format(question=question)}],
                        max_tokens=2000, temperature=0, model=os.environ.get("CLARIFY_MODEL"))
        found = json.loads(re.search(r"\{.*\}", text, re.S).group(0)).get("questions", [])
    except Exception:  # an unreadable reply never blocks the answer
        return []
    out = []
    for item in found[:3]:
        q = str(item.get("q", "")).strip()
        options = [str(o).strip() for o in item.get("options", []) if str(o).strip()][:5]
        # The riskiest form must be one tap away even when the model leaves it out (it offered
        # pellets, gel and tincture for arnica, but not a supplement taken by mouth).
        if re.search(r"\bform\b|how are you (taking|using)|what kind", q.lower()) and not any(
                re.search(r"mouth|capsule|supplement|tablet|swallow", o.lower()) for o in options):
            options = [ORAL] + options[:4]
        if q and len(options) >= 2:
            out.append({"q": q, "options": options})
    return out


def with_answers(question, answers):
    """The question plus the person's answers, in the form the other steps understand."""
    lines = "\n".join(f"- {a['q']} {a['a']}" for a in answers if a.get("a"))
    return f"{question}\n\nMy answers:\n{lines}" if lines else question


if __name__ == "__main__":
    import sys
    print(json.dumps(questions(" ".join(sys.argv[1:])), indent=1))
