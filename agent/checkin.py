"""Health check-in agent: answers "why" questions from the user's own log plus trusted sources.

Flow: danger-sign filter -> pick topics -> SQL for the user's numbers and source passages ->
model (OpenAI-compatible endpoint served by Meterless) -> cited answer.

Usage:
  python3 agent/checkin.py --user 1503960366 "Why am I tired every afternoon?"
  python3 agent/checkin.py --dry-run ...   # print the evidence pack, no model call
"""
import argparse
import json
import os
import sys
import urllib.parse
import urllib.request

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
- Cite the user's own numbers as [log]. Cite every guideline or study claim with its [n]
  number, and only with a source whose text says it.
- If a claim has no source in the evidence, do not make it.
- Give ONE specific thing to try this week (amount, timing, how long).
- Safe, basic amounts only. Never suggest high doses of any supplement.
- End with "See a doctor if": when to go, and what to tell them (what they tried, for how
  long, what changed).
- Plain words, short sentences, under 220 words."""


def topics_for(question):
    q = question.lower()
    found = [t for key, ts in ROUTES.items() if key in q for t in ts]
    return list(dict.fromkeys(found)) or ["fatigue", "sleep", "physical activity"]


def user_summary(user_id, days=14):
    rows = store.query(
        "SELECT * FROM user_log WHERE user_id = ? ORDER BY day DESC LIMIT ?", (user_id, days))
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
    }


def sources_for(topics, per_table=2):
    found = []
    marks = ",".join("?" * len(topics))
    for table, cols in [("myhealthfinder", "title || ' - ' || section"),
                        ("medlineplus", "title"),
                        ("pubmed", "title || ' (' || journal || ', ' || year || ')'")]:
        found += store.query(
            f"SELECT {cols} AS title, substr(text, 1, 900) AS text, url, source "
            f"FROM {table} WHERE topic IN ({marks}) AND text != '' LIMIT ?",
            (*topics, per_table * len(topics)))
    seen, unique = set(), []
    for s in found:
        if s["url"] + s["title"] not in seen:
            seen.add(s["url"] + s["title"])
            unique.append(s)
    return unique[:10]


def ask_model(question, summary, sources):
    base = os.environ.get("LLM_BASE_URL", "http://localhost:8088/v1")
    evidence = "\n\n".join(f"[{i}] {s['source']}: {s['title']}\n{s['text']}"
                           for i, s in enumerate(sources, 1))
    user = (f"Question: {question}\n\nUser's own data (last {summary['days']} days):\n"
            f"{json.dumps(summary, indent=1)}\n\nEvidence:\n{evidence}")
    body = json.dumps({
        "model": os.environ.get("LLM_MODEL", "default"),
        "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}],
        "temperature": 0.2,
    }).encode()
    req = urllib.request.Request(f"{base}/chat/completions", data=body, headers={
        "Content-Type": "application/json",
        "Authorization": f"Bearer {os.environ.get('LLM_API_KEY', 'rt-local')}",
    })
    with urllib.request.urlopen(req, timeout=180) as r:
        return json.load(r)["choices"][0]["message"]["content"]


def answer(question, user_id, dry_run=False):
    urgent = safety.check(question)
    if urgent:
        return urgent
    summary = user_summary(user_id)
    if summary is None:
        return f"No log found for user {user_id}."
    sources = sources_for(topics_for(question))
    if dry_run:
        return json.dumps({"summary": summary, "sources": sources}, indent=1)
    text = ask_model(question, summary, sources)
    refs = "\n".join(f"[{i}] {s['source']}: {s['title']} - {s['url']}"
                     for i, s in enumerate(sources, 1))
    return f"{text}\n\nSources:\n{refs}\n\n{safety.DISCLAIMER}"


def main():
    p = argparse.ArgumentParser()
    p.add_argument("question")
    p.add_argument("--user", default="1503960366")
    p.add_argument("--dry-run", action="store_true")
    a = p.parse_args()
    print(answer(a.question, a.user, a.dry_run))


if __name__ == "__main__":
    sys.exit(main())
