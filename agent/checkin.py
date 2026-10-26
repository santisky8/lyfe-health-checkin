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

import clarify
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
If the person asks about a remedy, supplement, product, dose or how long to use something,
start with **Your question** and answer it directly first: what the evidence says, a safe
amount and duration if the evidence gives one, who should avoid it, and interactions with
the conditions or medicines they mention. Never guess what is in a branded product: if its
ingredients are not in the evidence, say you can't confirm them and ask for the ingredient
list on the label, then cover the general cautions that apply. Be calibrated: if something
is a common food or a widely used remedy that is safe for most adults in normal amounts,
say so plainly, then say who should be careful (for example babies, pregnancy, diabetes,
reflux, blood thinners). Do not discourage safe self-care, and do not claim interactions
the evidence does not show.
Then one or two sentences on what they describe. If their own numbers are given and relevant,
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
procedure; at most say it is something a doctor may discuss. If they ask about a medicine
they already take, say what the evidence says about its safety or interactions and to follow
the label or their pharmacist; never give it a dose or suggest it as treatment.
**What the research says**
One to three short facts from the PubMed reviews, NCCIH or the library, each cited. Treatments
that need a doctor are named only as options to ask a doctor about.
**See a doctor if**
Warning signs and timing, then what to tell the doctor: what they tried, for how long, what
changed. Say how long it usually takes to settle when the evidence gives it.

Rules: a source counts only if its text supports the claim; skip sources that are off-topic.
If the question asks why something seemed to work, explain honestly and kindly what the
evidence says, including placebo, natural ups and downs, and other changes made at the same
time. Cite every claim with [n] for a source, [log] for their numbers, [m1], [m2] for past
check-ins. If past check-ins are given, say what changed since then. Past check-ins only
say what was asked, tried and suggested before: never use them as evidence for a medical
fact. No claim without a source. If there is no evidence for a point, say so instead of
citing. Plain words, short sentences, under 300 words."""

# Words that make the user's log (sleep, activity, weight) relevant. Not "walk": "pain when
# walking" is about the ankle, not the step count.
PERSONAL = ("sleep", "tired", "energy", "exhaust", "insomnia", "fatigue", "how active",
            "steps", "weight", "exercise enough")
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
                           for i, s in enumerate(prep["sources"], 1)) or "None found."
    history = "\n".join(f"[m{i}] {m['learnedAt'][:10]} ({m['source']}): {m['content']}"
                        for i, m in enumerate(prep["past"], 1)) or "None yet."
    summary = prep["summary"]
    numbers = (f"User's own data (last {summary['days']} days):\n{json.dumps(summary, indent=1)}"
               if summary else "User's own data: not relevant to this question.")
    convo = prep.get("conversation") or []
    follow = ("This is a follow-up in an ongoing conversation:\n"
              f"{clarify.transcript(convo, answer_chars=1500)}\n\n"
              "Answer the person's latest message directly. Don't repeat what the earlier "
              "answer already said; refer back to it in a phrase. Use only the headings that "
              "matter for this follow-up, but keep **See a doctor if** whenever there is any "
              "risk. Under 220 words.\n\n"
              if any(t.get("kind") == "answer" for t in convo) else "")
    user = (follow + f"Question: {prep['question']}\n\nCandidate causes to weigh: "
            f"{', '.join(prep['hypotheses']) or 'none'}\nRemedies or products asked about: "
            f"{', '.join(prep.get('remedies', [])) or 'none'}\n"
            + (f"Branded products whose ingredients you do NOT know: {', '.join(prep['brands'])}. "
               f"Do not say what they contain or what kind of product they are; ask for the "
               f"ingredient list on the label.\n" if prep.get("brands") else "")
            + f"\n{numbers}\n\n"
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


REMEDY_SECTIONS = ("bottom line", "what have we learned", "safety", "how much do we know",
                   "effectiveness", "what the science says")


def remedy_facts(name, limit=3):
    """NCCIH sections about a named herb, supplement or practice, read through Zetaris:
    the bottom line, what the research shows and the safety notes."""
    words = [w for w in re.findall(r"[a-z]+", name.lower()) if len(w) > 3
             and w not in ("homeopathic", "remedy", "remedies", "supplement", "extract")]
    if "homeopathic" in name.lower() or "homeopathy" in name.lower():
        words = ["homeopathy"]
    rows = []
    for w in words[:2]:
        rows = store.query(
            f"SELECT title, section, substr(text, 1, 1400) AS text, url, source "
            f"FROM {store.table('nccih')} WHERE lower(title) LIKE ?", (f"%{w}%",))
        if rows:
            break
    keep = [r for r in rows if any(k in r["section"].lower() for k in REMEDY_SECTIONS)]
    return [{"title": f"{r['title']}: {r['section']}", "text": r["text"], "url": r["url"],
             "source": r["source"]} for r in keep[:limit]]


def prepare(question, user_id, as_of=None, clarified=False):
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
    if not clarified:
        asks = clarify.questions(question)
        if asks:  # ask first; the page sends the answers back with clarified=True
            return {"question": question, "user": user_id, "urgent": None, "clarify": asks,
                    "timings": {"clarify": round(time.time() - t0, 1)}}
    timings["clarify"] = round(time.time() - t0, 1)
    t0 = time.time()
    found_terms = hypotheses.analyse(question)
    hyps = found_terms["conditions"]
    # Only remedies the person actually named: a word of it must be in the question, so an
    # ankle question doesn't turn into one about rest, ice and physical therapy.
    words = set(re.findall(r"[a-z]+", question.lower()))
    remedies = [r for r in found_terms["remedies"]
                if words & {w for w in re.findall(r"[a-z]+", r.lower()) if len(w) > 2}]
    brands = [] if "ingredients on the label" in question.lower() else found_terms.get("brands", [])
    timings["hypotheses"] = round(time.time() - t0, 1)
    topics = topics_for(question)
    summary = user_summary(user_id, as_of=as_of) if is_personal(question) else None
    t0 = time.time()
    # Exact condition names first; meaning-based search only fills the gaps, because on its
    # own it can rank Diphtheria above Eczema for "red, dry skin in the folds of my arms".
    found = library.by_name(hyps)[:3]
    ids = {r["doc_id"] for r in found}
    found += [r for r in library.search(f"{question}. Possibly: {', '.join(hyps)}")
              if r["match"] >= MIN_MATCH and r["doc_id"] not in ids][:3 - len(found)]
    library_rows = [{"title": r["title"], "text": r["text"], "url": r["url"],
                     "source": r["source"], "kind": "library", "match": r["match"]} for r in found]
    guide_rows = ([dict(s, kind="guide") for s in sources_for(topics, per_table=1)]
                  if topics and summary else [])
    remedy_rows = []
    for name in remedies:
        rows = remedy_facts(name)
        if not rows and name not in brands:  # no NCCIH page: NIH LactMed and LiverTox instead
            try:
                rows = research.nih_safety(name)
            except Exception:
                rows = []
        remedy_rows += [dict(r, kind="remedy", about=name) for r in rows]
    timings["zetaris"] = round(time.time() - t0, 1)
    t0 = time.time()
    papers, seen = [], set()

    def add_review(terms, about, context=None):
        """First new review for these terms; PubMed hiccups skip one term, not all of them."""
        for attempt in range(2):
            try:
                found = research.reviews(terms, top_n=2, context=context)
                break
            except Exception:  # PubMed slow or rate-limited: wait once, then give up on it
                time.sleep(1.5)
        else:
            return False
        for p in found:
            if p["url"] not in seen:
                seen.add(p["url"])
                papers.append(dict(p, kind="research", about=about))
                return True
        return False

    generic = [r for r in remedies if r not in brands]  # PubMed knows ginger, not Gut FX
    for name in generic[:2]:
        # The remedy for these conditions only: on its own, "honey" finds honey for diabetic
        # foot ulcers, which says nothing about a sore throat.
        if hyps:
            add_review([name], name, context=hyps)
        else:
            add_review([name], name)
    if generic and hyps:
        # A remedy question: the person's own conditions matter as they meet the remedy
        # ("antidepressants" with diabetes), not on their own ("heart failure in diabetes").
        add_review([hyps[0]], hyps[0], context=generic[0])
    else:
        for h in hyps[:3]:  # one review per candidate cause
            add_review([h], h)
    timings["pubmed"] = round(time.time() - t0, 1)
    past = latest_per_question(memory.relevant(user_id, question, top_n=8))[:3]
    return {
        "question": question, "user": user_id, "urgent": None, "summary": summary,
        "hypotheses": hyps, "remedies": remedies, "brands": brands,
        "topics": topics or [h.lower() for h in hyps[:2]],
        "sources": remedy_rows + library_rows + guide_rows[:2] + papers, "past": past,
        "sql": list(store.executed), "backend": store.backend(), "timings": timings,
    }


def turn(turns, user_id, as_of=None):
    """One step of a conversation. `turns` is the whole conversation so far, newest last:
    {"role": "user" | "assistant", "content": ..., "kind": "ask" | "answer"}. Returns a
    follow-up question ({"ask": {...}}), the emergency message, or the prepared evidence for
    an answer (the page then streams it with /api/stream)."""
    latest = turns[-1]["content"]
    urgent = safety.check(latest)
    if urgent:
        memory.remember(user_id, f"Danger sign reported: \"{latest}\". Sent to emergency help.",
                        source="safety_filter", tags=["danger"], confidence=1.0)
        return {"urgent": urgent}
    t0 = time.time()
    ask = clarify.next_step(turns)
    if ask:
        return {"ask": ask, "timings": {"clarify": round(time.time() - t0, 1)}}
    prep = prepare(clarify.case_text(turns), user_id, as_of, clarified=True)
    prep["conversation"] = turns
    prep.setdefault("timings", {})["clarify"] = round(time.time() - t0, 1)
    return prep


def latest_per_question(past):
    """Keep only the newest check-in for each question asked, so asking the same thing three
    times does not fill the memory slots with copies of one old answer."""
    seen, keep = set(), []
    for m in sorted(past, key=lambda m: m["learnedAt"], reverse=True):
        asked = re.search(r'asked "([^"]+)"', m["content"])
        key = asked.group(1).lower() if asked else m["id"]
        if key not in seen:
            seen.add(key)
            keep.append(m)
    return sorted(keep, key=lambda m: -m.get("similarity", 0))


def check_citations(text, n_sources, n_past):
    """Drop citation marks that point at nothing, such as [3] when only two sources were
    given, so every remaining mark opens a real source."""
    def keep(m):
        refs = [r.strip() for r in m.group(1).split(",")]
        ok = [r for r in refs if r == "log"
              or (r.isdigit() and 1 <= int(r) <= n_sources)
              or (re.fullmatch(r"m\d+", r) and 1 <= int(r[1:]) <= n_past)]
        return "".join(f"[{r}]" for r in ok)  # [m3][5], never "[m3, 5]"
    if not n_sources:  # a model-made reference list with no sources behind it
        text = re.sub(r"\n\s*\[\d+\][^\n]*", "", text)
    text = re.sub(r"\[((?:\d+|log|m\d+)(?:\s*,\s*(?:\d+|log|m\d+))*)\]", keep, text)
    return re.sub(r" +([.,;])", r"\1", re.sub(r"(\S)  +(\S)", r"\1 \2", text))


def respond(prep):
    """Model answer for a prepared check-in, then save the check-in to memory."""
    return finish(prep, ask_model(prep))


def finish(prep, text):
    text = check_citations(llm.clean(text), len(prep["sources"]), len(prep["past"]))
    saved = remember_checkin(prep, text)
    return {"text": text, "saved": saved, "disclaimer": safety.DISCLAIMER}


def answer(question, user_id, dry_run=False, as_of=None, clarified=False):
    prep = prepare(question, user_id, as_of, clarified)
    if prep.get("urgent") or prep.get("error"):
        return prep.get("urgent") or prep["error"]
    if prep.get("clarify"):
        return "Before answering, Check-In needs to know:\n" + "\n".join(
            f"- {c['q']} ({' / '.join(c['options'])})" for c in prep["clarify"]) + \
            '\n\nRun again with --answers "..."'
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
    p.add_argument("--answers", help="answers to the clarifying questions, as one line")
    a = p.parse_args()
    if a.note:
        m = note(a.user, a.note)
        print(f"Saved to memory as {m['id']}.")
    elif a.question:
        q = f"{a.question}\n\nMy answers:\n{a.answers}" if a.answers else a.question
        print(answer(q, a.user, a.dry_run, a.as_of, clarified=bool(a.answers)))
    else:
        p.error("give a question or --note")


if __name__ == "__main__":
    sys.exit(main())
