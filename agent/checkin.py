"""Health check-in agent: answers "why" questions from the user's own log plus trusted sources.

Flow: danger-sign filter -> pick topics -> SQL through Zetaris for the user's numbers and source
passages -> past check-ins from Meterless H-MEM memory -> model -> cited answer -> the check-in
is saved back to memory with its source and confidence.

Usage:
  python3 agent/checkin.py --user 1503960366 "Why am I tired every afternoon?"
  python3 agent/checkin.py --dry-run ...   # print the evidence pack, no model call
  python3 agent/checkin.py --user 1503960366 --note "Went to bed 30 min earlier, less tired"
"""
import argparse
import json
import re
import sys
import time

import hypotheses
import library
import llm
import memory
import research
import safety
import store



# Question words -> topics used by the loaders.
ROUTES = {
    "sleep": ["sleep", "fatigue"], "tired": ["fatigue", "sleep"], "energy": ["fatigue", "sleep"],
    "exhaust": ["fatigue", "sleep"], "insomnia": ["sleep"], "walk": ["physical activity"],
    "exercise": ["physical activity"], "active": ["physical activity"], "steps": ["physical activity"],
    "eat": ["nutrition"], "food": ["nutrition"], "diet": ["nutrition"], "vitamin": ["nutrition"],
    "water": ["hydration"], "thirst": ["hydration"], "stress": ["stress"], "anxious": ["stress"],
    "headache": ["headache", "hydration"], "weight": ["weight", "physical activity"],
    "back": ["back pain", "physical activity"], "alcohol": ["alcohol"], "drink": ["alcohol", "hydration"],
}

SYSTEM = """You are Check-In, a warm, honest health guide. You never diagnose, never treat, and
never replace a doctor: you explain what something could be and what the person can do.
Use ONLY the evidence given.

Write it like this, with each bold heading exactly as shown:
One or two sentences on what they describe. If their own numbers are given and relevant,
start from them and cite [log]; the "checks" field says whether each meets its guideline,
never contradict it.
**Possible causes**
2 to 4 causes, most likely first, taken from the candidates or the evidence. For each, what
usually fits it (where, when, what it feels like) and how to tell it apart from the others.
Say "could be", never "you have". If the description is too vague to tell them apart, end
this part with one question that would help.
**What you can do now**
Specific, safe steps for the everyday causes: how, how often, for how long. Basic safe
amounts only; never high doses of any supplement. Never recommend a medicine, injection or
procedure; at most say it is something a doctor may discuss.
**What the research says**
One to three short facts from the PubMed reviews or the library, each cited. Treatments
that need a doctor are named only as options to ask a doctor about.
**See a doctor if**
Warning signs and timing, then what to tell the doctor: what they tried, for how long, what
changed.

Rules: cite every claim with [n] for a source, [log] for their numbers, [m1], [m2] for past
check-ins. If past check-ins are given, say what changed since then. No claim without a
source. Plain words, short sentences, under 300 words."""

PERSONAL = ("sleep", "tired", "energy", "exhaust", "insomnia", "fatigue", "walk", "exercise",
            "active", "steps", "weight")
MIN_MATCH = 0.68  # below this a library topic is more likely noise than help


def topics_for(question):
    q = question.lower()
    found = [t for key, ts in ROUTES.items() if key in q for t in ts]
    return list(dict.fromkeys(found))


def is_personal(question):
    """Does the question touch what the user's log measures (sleep, activity, weight)?"""
    return any(word in question.lower() for word in PERSONAL)


def user_summary(user_id, days=7, as_of=None):
    """The user's last `days` days up to `as_of` (ISO date; default: latest in the log), with
    guideline checks computed here so the model never has to judge numbers itself."""
    rows = store.query(
        f"SELECT * FROM {store.table('user_log')} WHERE user_id = ? AND day <= ? "
        f"ORDER BY day DESC LIMIT ?", (user_id, as_of or "9999-12-31", days))
    if not rows:
        return None
    sleep = [int(r["minutes_asleep"]) for r in rows if r["minutes_asleep"]]
    steps = [int(r["steps"]) for r in rows]
    active = sum(int(r["active_minutes"]) for r in rows)
    return {
        "days": len(rows),
        "from": rows[-1]["day"], "to": rows[0]["day"],
        "avg_sleep_hours": round(sum(sleep) / len(sleep) / 60, 1) if sleep else None,
        "nights_logged": len(sleep),
        "nights_under_7h": sum(1 for m in sleep if m < 420),
        "avg_steps": round(sum(steps) / len(steps)),
        "moderate_or_vigorous_minutes_per_week": round(active / len(rows) * 7),
        "avg_sedentary_hours": round(
            sum(int(r["sedentary_minutes"]) for r in rows) / len(rows) / 60, 1),
    } | {"checks": guideline_checks(sleep, active / len(rows) * 7)}


def guideline_checks(sleep_minutes, active_per_week):
    # Adults 18-64: 7+ hours of sleep (CDC/MyHealthfinder); 150+ minutes a week of moderate or
    # vigorous activity (WHO 2020).
    avg_sleep = sum(sleep_minutes) / len(sleep_minutes) / 60 if sleep_minutes else None
    return {
        "sleep_meets_7h_guideline": None if avg_sleep is None else avg_sleep >= 7,
        "activity_meets_150_min_guideline": active_per_week >= 150,
    }


def sources_for(topics, per_table=2):
    found = []
    marks = ",".join("?" * len(topics))
    for table, cols in [("myhealthfinder", "title || ' - ' || section"),
                        ("medlineplus", "title"),
                        ("pubmed", "title || ' (' || journal || ', ' || year || ')'")]:
        found += store.query(
            f"SELECT {cols} AS title, substr(text, 1, 900) AS text, url, source "
            f"FROM {store.table(table)} WHERE topic IN ({marks}) AND text != '' LIMIT ?",
            (*topics, per_table * len(topics)))
    seen, unique = set(), []
    for s in found:
        if s["url"] + s["title"] not in seen:
            seen.add(s["url"] + s["title"])
            unique.append(s)
    return unique[:10]


def messages(prep):
    evidence = "\n\n".join(f"[{i}] {s['source']}: {s['title']}\n{s['text']}"
                           for i, s in enumerate(prep["sources"], 1))
    history = "\n".join(f"[m{i}] {m['learnedAt'][:10]} ({m['source']}): {m['content']}"
                        for i, m in enumerate(prep["past"], 1)) or "None yet."
    summary = prep["summary"]
    numbers = (f"User's own data (last {summary['days']} days):\n{json.dumps(summary, indent=1)}"
               if summary else "User's own data: not relevant to this question.")
    user = (f"Question: {prep['question']}\n\nCandidate causes to weigh: "
            f"{', '.join(prep['hypotheses']) or 'none'}\n\n{numbers}\n\n"
            f"Past check-ins:\n{history}\n\nEvidence:\n{evidence}")
    return [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}]


def ask_model(prep):
    return llm.chat(messages(prep))


def stream_model(prep):
    """Yield the answer in pieces as the model writes it."""
    return llm.chat(messages(prep), stream=True)


def suggestion_in(text):
    """The first step under "What you can do now", kept so the next check-in can follow up."""
    part = re.split(r"\*\*What you can do now\*\*:?", text, flags=re.I)
    if len(part) < 2:
        return ""
    body = re.split(r"\*\*", part[1])[0]
    first = next((ln.strip(" *-•\t") for ln in body.splitlines() if ln.strip(" *-•\t")), "")
    return re.sub(r"\[(\d+|log|m\d+)\]", "", first)[:300].strip()


def remember_checkin(prep, text):
    summary, parts, refs = prep["summary"], [f"asked \"{prep['question']}\""], []
    if prep["hypotheses"]:
        parts.append("considered " + ", ".join(prep["hypotheses"]))
    if summary:
        parts.append(f"data: avg sleep {summary['avg_sleep_hours']} h, "
                     f"{summary['nights_under_7h']} of {summary['nights_logged']} nights under 7 h, "
                     f"avg {summary['avg_steps']} steps, "
                     f"{summary['moderate_or_vigorous_minutes_per_week']} active min/week "
                     f"(log {summary['from']} to {summary['to']})")
        refs.append(f"{store.table('user_log')}:{summary['from']}..{summary['to']}")
    tip = suggestion_in(text)
    if tip:
        parts.append(f"suggested: {tip}")
    refs += [s["url"] for s in prep["sources"][:5]]
    return memory.remember(prep["user"], "Check-in: " + "; ".join(parts) + ".", source="checkin",
                           tags=prep["topics"], confidence=0.9, refs=refs)


def prepare(question, user_id, as_of=None):
    """Everything the answer is built from, gathered before it is written: the safety check,
    candidate causes, library topics and the user's numbers through Zetaris, live PubMed
    reviews, and past check-ins from H-MEM."""
    store.executed.clear()
    urgent = safety.check(question)
    if urgent:
        memory.remember(user_id, f"Danger sign reported: \"{question}\". Sent to emergency help.",
                        source="safety_filter", tags=["danger"], confidence=1.0)
        return {"question": question, "user": user_id, "urgent": urgent}
    timings = {}
    t0 = time.time()
    hyps = hypotheses.candidates(question)
    timings["hypotheses"] = round(time.time() - t0, 1)
    topics = topics_for(question)
    summary = user_summary(user_id, as_of=as_of) if is_personal(question) else None
    t0 = time.time()
    found = [r for r in library.search(f"{question}. Possibly: {', '.join(hyps)}")
             if r["match"] >= MIN_MATCH][:3]
    library_rows = [{"title": r["title"], "text": r["text"], "url": r["url"],
                     "source": r["source"], "kind": "library", "match": r["match"]} for r in found]
    guide_rows = [dict(s, kind="guide") for s in sources_for(topics, per_table=1)] if topics else []
    timings["zetaris"] = round(time.time() - t0, 1)
    t0 = time.time()
    try:
        papers, seen = [], set()
        for h in hyps[:3]:  # one review per candidate, so each cause has its own evidence
            for p in research.reviews([h], top_n=2):
                if p["url"] not in seen:
                    seen.add(p["url"])
                    papers.append(dict(p, kind="research", about=h))
                    break
    except Exception:  # PubMed down or slow: answer from the library alone
        papers = []
    timings["pubmed"] = round(time.time() - t0, 1)
    past = memory.relevant(user_id, question)
    return {
        "question": question, "user": user_id, "urgent": None, "summary": summary,
        "hypotheses": hyps, "topics": topics or [h.lower() for h in hyps[:2]],
        "sources": library_rows + guide_rows[:2] + papers, "past": past,
        "sql": list(store.executed), "backend": store.backend(), "timings": timings,
    }


def respond(prep):
    """Model answer for a prepared check-in, then save the check-in to memory."""
    return finish(prep, ask_model(prep))


def finish(prep, text):
    text = llm.clean(text)
    saved = remember_checkin(prep, text)
    return {"text": text, "saved": saved, "disclaimer": safety.DISCLAIMER}


def answer(question, user_id, dry_run=False, as_of=None):
    prep = prepare(question, user_id, as_of)
    if prep.get("urgent") or prep.get("error"):
        return prep.get("urgent") or prep["error"]
    if dry_run:
        return json.dumps(prep, indent=1)
    out = respond(prep)
    refs = "\n".join(f"[{i}] {s['source']}: {s['title']} - {s['url']}"
                     for i, s in enumerate(prep["sources"], 1))
    mems = "\n".join(f"[m{i}] {m['learnedAt'][:10]}, {m['source']}, confidence {m['confidence']:.2f}"
                     f" ({m['id']})" for i, m in enumerate(prep["past"], 1))
    return (f"{out['text']}\n\nSources:\n{refs}"
            + (f"\n\nRemembered from past check-ins (Meterless H-MEM):\n{mems}" if mems else "")
            + f"\n\nSaved this check-in to memory as {out['saved']['id']}.\n\n{out['disclaimer']}")


def note(user_id, text):
    return memory.remember(user_id, f"User reported: {text}", source="user_report",
                           tags=topics_for(text), confidence=0.7, origin="user_correction")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("question", nargs="?")
    p.add_argument("--user", default="1503960366")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--note", help="what the user tried and how it went, saved to memory")
    p.add_argument("--as-of", help="check in as of this date (YYYY-MM-DD), for demos on the log")
    a = p.parse_args()
    if a.note:
        m = note(a.user, a.note)
        print(f"Saved to memory as {m['id']}.")
    elif a.question:
        print(answer(a.question, a.user, a.dry_run, a.as_of))
    else:
        p.error("give a question or --note")


if __name__ == "__main__":
    sys.exit(main())
