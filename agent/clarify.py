"""The conversation step: ask a follow-up question, or go ahead and answer.

Some answers depend on details people leave out. "How long should I take arnica?" is a safety
question that changes with the form: arnica taken by mouth as an herbal supplement is toxic,
while homeopathic pellets and gels on unbroken skin are usually safe. So after each message
the model reads the conversation and either asks one short question (with tap options; the
person can also reply in their own words) or says it has enough. It never asks more than
MAX_ASKS times in a row, and follow-ups after an answer keep the whole conversation.
"""
import json
import os
import re

import llm

MAX_ASKS = 3
ORAL = "By mouth as a supplement, capsule or tea"

SYSTEM = ("You are the intake step of a careful health guide. You do not answer the health "
          "question yourself. Reply with JSON only.")
ASK = """Conversation so far:
{transcript}

Does the guide need one more detail before it answers the person's latest message? Ask only
when the answer or its safety really changes with a detail nobody has given yet. Never ask
for something already said anywhere in the conversation, and never repeat a question.
- A remedy, herb or supplement: the form (taken by mouth as a supplement or tea, homeopathic
  pellets, cream or gel on the skin), what it is for, how much and how often. The form
  options must always include "By mouth as a supplement, capsule or tea".
- A symptom: when it started, how bad it is, and the one detail that tells the likely causes
  apart (an injury, fever, one side or both).
- Pregnancy, other medicines or conditions only when they change the safety.
- Nothing to ask when the message is clear enough, when it is a general "why" question about
  the person's own week (sleep, energy, activity), or when it is a follow-up the earlier
  answer already gives enough to handle.

Ask as few questions as possible. Stop as soon as the safe answer is clear: once a detail
already decides it (for example, an herb taken by mouth that should be avoided), answer
instead of asking about the dose. Otherwise ask ONE question, the most important one, in a
friendly, natural way, with 2 to 5 short answer options:
{{"ask": {{"q": "How are you taking the arnica?", "options": ["By mouth as a supplement,
capsule or tea", "Homeopathic pellets", "Gel or cream on the skin"]}}}}
or, when the guide can answer now: {{"ask": null}}"""

ANSWERED = ("my answers:", "ingredients on the label")


def transcript(turns, answer_chars=700):
    """The conversation as plain text. Earlier answers are shortened: the intake step needs to
    know what was covered, not every word."""
    lines = []
    for t in turns:
        if t["role"] == "user":
            lines.append(f"Person: {t['content']}")
        elif t.get("kind") == "answer":
            lines.append(f"Guide (answer): {t['content'][:answer_chars]}")
        else:
            lines.append(f"Guide (question): {t['content']}")
    return "\n".join(lines)


def asks_since_answer(turns):
    n = 0
    for t in reversed(turns):
        if t["role"] == "assistant":
            if t.get("kind") == "answer":
                break
            n += 1
    return n


def next_step(turns):
    """One follow-up question {"q", "options"}, or None when the guide can answer now."""
    if asks_since_answer(turns) >= MAX_ASKS:
        return None
    if len(turns) == 1 and any(m in turns[0]["content"].lower() for m in ANSWERED):
        return None
    try:
        text = llm.chat([{"role": "system", "content": SYSTEM},
                         {"role": "user", "content": ASK.format(transcript=transcript(turns))}],
                        max_tokens=2000, temperature=0, model=os.environ.get("CLARIFY_MODEL"))
        ask = json.loads(re.search(r"\{.*\}", text, re.S).group(0)).get("ask")
    except Exception:  # an unreadable reply never blocks the answer
        return None
    if not isinstance(ask, dict):
        return None
    q = str(ask.get("q", "")).strip()
    options = [str(o).strip() for o in ask.get("options", []) if str(o).strip()][:5]
    # The riskiest form must be one tap away even when the model leaves it out (it offered
    # pellets, gel and tincture for arnica, but not a supplement taken by mouth).
    if re.search(r"\bform\b|how are you (taking|using)|what kind", q.lower()) and not any(
            re.search(r"mouth|capsule|supplement|tablet|swallow", o.lower()) for o in options):
        options = [ORAL] + options[:4]
    asked = {t["content"].strip().lower() for t in turns if t["role"] == "assistant"}
    if not q or q.lower() in asked:
        return None
    return {"q": q, "options": options}


def questions(question):
    """Single-message form for the command line: [] or a list with one question."""
    step = next_step([{"role": "user", "content": question}])
    return [step] if step else []


def case_text(turns):
    """The conversation folded into one request for the search steps: the first message, the
    details the person gave, earlier answers in brief, and the latest message to answer."""
    first = next(t["content"] for t in turns if t["role"] == "user")
    parts, pending, details = [first], None, []
    answered_before = False
    for t in turns[1:]:
        if t["role"] == "assistant":
            if t.get("kind") == "answer":
                answered_before = True
                if details:
                    parts.append("My answers:\n" + "\n".join(details))
                    details = []
                parts.append(f"(Check-In answered: {t['content'][:400]}...)")
            else:
                pending = t["content"]
        elif pending:
            details.append(f"- {pending} {t['content']}")
            pending = None
        else:
            parts.append(("Follow-up question: " if answered_before else "") + t["content"])
    if details:
        parts.append("My answers:\n" + "\n".join(details))
    return "\n\n".join(parts)


if __name__ == "__main__":
    import sys
    print(json.dumps(questions(" ".join(sys.argv[1:])), indent=1))
