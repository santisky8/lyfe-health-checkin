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
import os
import re
import sys
import urllib.parse
import urllib.request

import memory
import safety
import store


def load_env():
    """Read .env.local (gitignored). Accepts KEY=value lines or a Meterless Quick Connect link
    (http://<host>:<port>/connect#k=<key>&m=<model>)."""
    path = os.path.join(os.path.dirname(__file__), "..", ".env.local")
    if not os.path.exists(path):
        return
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if "/connect#" in line:
            base, frag = line.split("/connect#", 1)
            params = dict(p.split("=", 1) for p in frag.split("&") if "=" in p)
            os.environ.setdefault("LLM_BASE_URL", base.rstrip("/") + "/v1")
            if "k" in params:
                os.environ.setdefault("LLM_API_KEY", params["k"])
            if "m" in params:
                os.environ.setdefault("LLM_MODEL", urllib.parse.unquote(params["m"]))
        elif "=" in line and not line.startswith("#"):
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())


load_env()

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

SYSTEM = """You are a warm, honest health check-in coach. You never diagnose, never treat, and
never replace a doctor. Answer the user's "why" question using ONLY the evidence given.

Rules:
- Start with the most likely everyday causes that the user's OWN numbers show, with the numbers.
- The "checks" field already says whether each number meets its guideline. Never contradict it.
- Cite the user's own numbers as [log]. Cite every guideline or study claim with its [n]
  number, and only with a source whose text says it.
- If a claim has no source in the evidence, do not make it.
- Give ONE specific thing to try this week (amount, timing, how long).
- Safe, basic amounts only. Never suggest high doses of any supplement.
- If past check-ins are given, say what changed since then (better, worse, same) and whether
  the last suggestion was tried. Cite them as [m1], [m2]...
- End with "See a doctor if": when to go, and what to tell them (what they tried, for how
  long, what changed).
- Plain words, short sentences, under 220 words."""


def topics_for(question):
    q = question.lower()
    found = [t for key, ts in ROUTES.items() if key in q for t in ts]
    return list(dict.fromkeys(found)) or ["fatigue", "sleep", "physical activity"]


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


def _model_request(question, summary, sources, past, stream):
    base = os.environ.get("LLM_BASE_URL", "http://localhost:8088/v1")
    evidence = "\n\n".join(f"[{i}] {s['source']}: {s['title']}\n{s['text']}"
                           for i, s in enumerate(sources, 1))
    history = "\n".join(f"[m{i}] {m['learnedAt'][:10]} ({m['source']}): {m['content']}"
                        for i, m in enumerate(past, 1)) or "None yet."
    user = (f"Question: {question}\n\nUser's own data (last {summary['days']} days):\n"
            f"{json.dumps(summary, indent=1)}\n\nPast check-ins:\n{history}\n\n"
            f"Evidence:\n{evidence}")
    model = os.environ.get("LLM_MODEL", "default")
    if model.startswith("qwen3"):
        user += "\n/no_think"  # skip qwen3's long hidden reasoning on slow local hardware
    body = json.dumps({
        "model": model,
        "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}],
        "temperature": 0.2,
        "stream": stream,
    }).encode()
    req = urllib.request.Request(f"{base}/chat/completions", data=body, headers={
        "Content-Type": "application/json",
        "Authorization": f"Bearer {os.environ.get('LLM_API_KEY', 'rt-local')}",
    })
    return urllib.request.urlopen(req, timeout=int(os.environ.get("LLM_TIMEOUT", "600")))


def _clean(text):
    return re.sub(r"<think>.*?</think>\s*", "", text, flags=re.S).strip()


def ask_model(question, summary, sources, past):
    with _model_request(question, summary, sources, past, stream=False) as r:
        return _clean(json.load(r)["choices"][0]["message"]["content"])


def stream_model(question, summary, sources, past):
    """Yield the answer in pieces as the model writes it (OpenAI-style server-sent events)."""
    with _model_request(question, summary, sources, past, stream=True) as r:
        for raw in r:
            line = raw.decode("utf-8").strip()
            if not line.startswith("data:") or line == "data: [DONE]":
                continue
            delta = json.loads(line[5:])["choices"][0].get("delta", {}).get("content")
            if delta:
                yield delta


def suggestion_in(text):
    """The "try this week" line from the model's answer, kept so the next check-in can follow up."""
    for line in text.splitlines():
        if "try" in line.lower()[:30]:
            return line.strip(" *-#").replace("**", "")[:300]
    return ""


def remember_checkin(user_id, question, summary, topics, text):
    facts = (f"avg sleep {summary['avg_sleep_hours']} h, {summary['nights_under_7h']} of "
             f"{summary['nights_logged']} nights under 7 h, avg {summary['avg_steps']} steps, "
             f"{summary['moderate_or_vigorous_minutes_per_week']} active min/week "
             f"(log {summary['from']} to {summary['to']})")
    tip = suggestion_in(text)
    content = f"Check-in: asked \"{question}\". Data: {facts}." + (f" Suggested: {tip}" if tip else "")
    return memory.remember(user_id, content, source="checkin", tags=topics, confidence=0.9,
                           refs=[f"{store.table('user_log')}:{summary['from']}..{summary['to']}"])


def prepare(question, user_id, as_of=None):
    """Everything the answer is built from, gathered before the model runs: the safety check,
    the user's numbers and source passages from Zetaris, and past check-ins from H-MEM."""
    store.executed.clear()
    urgent = safety.check(question)
    if urgent:
        memory.remember(user_id, f"Danger sign reported: \"{question}\". Sent to emergency help.",
                        source="safety_filter", tags=["danger"], confidence=1.0)
        return {"question": question, "user": user_id, "urgent": urgent}
    summary = user_summary(user_id, as_of=as_of)
    if summary is None:
        return {"question": question, "user": user_id, "error": f"No log found for user {user_id}."}
    topics = topics_for(question)
    return {
        "question": question, "user": user_id, "urgent": None, "summary": summary,
        "topics": topics, "sources": sources_for(topics),
        "past": memory.recall(user_id, f"{question} {' '.join(topics)}", top_n=3),
        "sql": list(store.executed), "backend": store.backend(),
    }


def respond(prep):
    """Model answer for a prepared check-in, then save the check-in to memory."""
    text = ask_model(prep["question"], prep["summary"], prep["sources"], prep["past"])
    return finish(prep, text)


def finish(prep, text):
    text = _clean(text)
    saved = remember_checkin(prep["user"], prep["question"], prep["summary"], prep["topics"], text)
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
