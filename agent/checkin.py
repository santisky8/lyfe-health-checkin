"""Health check-in agent: answers "why" questions from the user's own log plus trusted sources.

Flow: danger-sign filter -> clarifying question if the safe answer depends on a missing detail
-> candidate causes (fast model) -> the user's numbers and library pages through Zetaris SQL,
plus live PubMed reviews -> off-topic sources dropped by meaning -> past check-ins from
Meterless H-MEM -> cited answer from the model -> citations checked -> the check-in is saved
back to H-MEM with its sources and confidence. Every choice along the way goes into
prep["decisions"], shown in the app under "Show your work" and saved as a trace file.

Usage:
  python3 agent/checkin.py --user 1503960366 "Why am I tired every afternoon?"
  python3 agent/checkin.py --dry-run ...   # print the evidence pack, no model call
  python3 agent/checkin.py --user 1503960366 --note "Went to bed 30 min earlier, less tired"
"""
import argparse
import contextvars
import json
import re
import sys
import time
from datetime import date, timedelta
from concurrent.futures import ThreadPoolExecutor

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
    "back": ["back pain", "physical activity"], "alcohol": ["alcohol"], "drink": ["hydration"],
    "beer": ["alcohol"], "wine": ["alcohol"],
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
Warning signs and timing, each cited to the source that lists it (a "See a Doctor" guide or
the library topic when given), then what to tell the doctor: what they tried, for how long, what
changed. Say how long it usually takes to settle when the evidence gives it.

Rules: a source counts only if its text supports the claim; skip sources that are off-topic.
If the question asks why something seemed to work, explain honestly and kindly what the
evidence says, including placebo, natural ups and downs, and other changes made at the same
time. Cite every claim with [n] for a source, [log] for their numbers, [m1], [m2] for past
check-ins. Every cause, step, warning sign and research fact needs at least one [n]; any line
without one is removed before the person sees it, so give only what a source supports: [log] and [m1] show
what applies to this person, never why something is true. If past check-ins are given, say what
changed since then. Past check-ins only
say what was asked, tried and suggested before: never use them as evidence for a medical
fact. No claim without a source. If there is no evidence for a point, say so instead of
citing. Plain words, short sentences, under 300 words."""

# Words that make the user's log (sleep, activity, weight) relevant. Not "walk": "pain when
# walking" is about the ankle, not the step count.
PERSONAL = ("sleep", "tired", "energy", "exhaust", "insomnia", "fatigue", "how active",
            "steps", "weight", "exercise enough")
MIN_MATCH = 0.68  # below this a library topic is more likely noise than help
MIN_RELEVANCE = 0.5  # below this a source is off-topic for the question (see on_topic)
RELEVANCE_GAP = 0.12  # and this far behind the best source, it is likely off-topic too
MAX_SOURCES = 8  # evidence sent to the model; more adds tokens, not better answers
TRACES = store.CLEAN.parent / "traces"  # one JSON decision trace per check-in (gitignored)


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


def suggestions(user_id, as_of=None, limit=3):
    """Questions worth asking, read from this person's own week, each with the facts behind it.
    Fixed rules on the Zetaris log and the person's notes, not the model: instant, can't invent
    anything, and every suggestion can say exactly why it is shown."""
    week = user_summary(user_id, as_of=as_of)
    if not week:
        return []
    before = user_summary(user_id, as_of=str(date.fromisoformat(week["from"]) - timedelta(days=1)))
    sleep, out = week["avg_sleep_hours"], []
    notes = [m for m in memory.all_memories(user_id) if m.get("source") == "user_report"]
    active = week["moderate_or_vigorous_minutes_per_week"]
    if notes:  # follow up on the latest thing they tried
        tried = notes[-1]["content"].removeprefix("User reported: ").rstrip(".")
        facts = [f"You noted: {tried}"]
        if before and before["avg_sleep_hours"] and sleep:
            facts.append(f"Sleep {before['avg_sleep_hours']} h → {sleep} h a night")
        out.append({"q": f"Did this help: {tried.lower()}?", "facts": facts})
    if sleep is not None and before and before["avg_sleep_hours"] \
            and before["avg_sleep_hours"] - sleep >= 0.5:
        out.append({"q": "Why has my sleep gotten worse this week, and what can I change?",
                    "facts": [f"{sleep} h a night this week",
                              f"{before['avg_sleep_hours']} h the week before"]})
    if sleep is not None and sleep < 7:
        out.append({"q": "I'm sleeping under 7 hours. Why am I tired in the afternoon, and what helps?",
                    "facts": [f"{sleep} h a night",
                              f"{week['nights_under_7h']} of {week['nights_logged']} nights under 7 h",
                              "Goal: 7 h or more"]})
    if week["avg_sedentary_hours"] >= 10:
        awake = max(24 - (sleep or 8), 1)  # a bad log row can claim 24 h of sleep
        out.append({"q": f"I sit about {round(week['avg_sedentary_hours'])} hours a day. "
                         "What does that do to my body, and what helps?",
                    "facts": [f"{week['avg_sedentary_hours']} h sitting a day",
                              f"{round(100 * min(week['avg_sedentary_hours'], awake) / awake)}% of your "
                              "waking hours"]})
    if not week["checks"]["activity_meets_150_min_guideline"]:
        out.append({"q": "How can I fit 150 minutes of exercise into my week?",
                    "facts": [f"{active} active minutes this week", "Goal: 150 a week"]})
    if not out:
        out.append({"q": "I'm meeting my sleep and activity goals. What else should I watch?",
                    "facts": [f"{sleep} h sleep a night", f"{active} active minutes a week"]})
    return out[:limit]


def sources_for(topics, per_topic=2):
    """MyHealthfinder guidance on the log's topics. Its "Take Action" sections (daily habits,
    when to see a doctor) come first: they are what the steps and warning signs need a source for."""
    marks = ",".join("?" * len(topics))
    return store.query(
        f"SELECT title || ' - ' || section AS title, substr(text, 1, 900) AS text, url, source "
        f"FROM {store.table('myhealthfinder')} WHERE topic IN ({marks}) AND text != '' "
        "ORDER BY CASE WHEN section LIKE 'Take Action%' THEN 0 ELSE 1 END LIMIT ?",
        (*topics, per_topic * len(topics)))


def score_sources(question, sources):
    """How close each source is to the question, by meaning (local embedding model)."""
    if not sources:
        return
    vectors = library.embed([f"search_query: {question}"] +
                            [f"search_document: {s['title']}. {s['text'][:600]}" for s in sources])
    q = library._unit(vectors[0])
    for s, v in zip(sources, vectors[1:]):
        s["relevance"] = round(sum(a * b for a, b in zip(q, library._unit(v))), 3)


def on_topic(question, sources, decisions):
    """Drop sources that are not about the question, such as a surgery case report for red dots
    on the legs. A source stays when it is close to the question and not far behind the best
    match. Remedy pages stay: they were found by the remedy's own name. The best source always
    stays, so an answer is never left without one to cite."""
    score_sources(question, sources)
    if not sources:
        return sources
    best = max(sources, key=lambda s: s["relevance"])
    floor = max(MIN_RELEVANCE, best["relevance"] - RELEVANCE_GAP)
    keep = [s for s in sources if s.get("kind") == "remedy" or s is best
            or s["relevance"] >= floor]
    if len(keep) > MAX_SOURCES:  # least relevant go first; remedy pages are never cut
        cut = sorted((s for s in keep if s.get("kind") != "remedy"),
                     key=lambda s: s["relevance"])[:len(keep) - MAX_SOURCES]
        keep = [s for s in keep if s not in cut]
    for s in sources:
        if s not in keep:
            decisions.append(f"Dropped as off-topic: {s['title'][:80]} "
                             f"(match {s['relevance']:.2f}, needed {floor:.2f})")
    return keep


def messages(prep):
    evidence = "\n\n".join(f"[{i}] {s['source']}: {s['title']}\n{s['text']}"
                           for i, s in enumerate(prep["sources"], 1)) or "None found."
    history = "\n".join(f"[m{i}] {m['learnedAt'][:10]} ({m['source']}): {m['content']}"
                        for i, m in enumerate(prep["past"], 1)) or "None yet."
    summary = prep["summary"]
    numbers = (f"User's own data (last {summary['days']} days):\n{json.dumps(summary)}"
               if summary else "User's own data: not relevant to this question.")
    convo = prep.get("conversation") or []
    follow = ("This is a follow-up in an ongoing conversation:\n"
              f"{clarify.transcript(convo, answer_chars=1500)}\n\n"
              "Answer the person's latest message directly. Don't repeat what the earlier "
              "answer already said; refer back to it in a phrase. Use only the headings that "
              "matter for this follow-up, but keep **See a doctor if** whenever there is any "
              "risk. Under 220 words.\n\n"
              if any(t.get("kind") == "answer" for t in convo) else "")
    asked = convo[-1]["content"] if follow else prep["question"]  # the transcript has the rest
    user = (follow + prep.get("caution", "") + f"Question: {asked}\n\nCandidate causes to weigh: "
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


def steps_in(text):
    """Every step under "What you can do now", without citation marks, so the journal and the
    next check-in see the whole suggestion, not just its first line."""
    part = re.split(r"\*\*What you can do now\*\*:?", text, flags=re.I)
    if len(part) < 2:
        return []
    body = NEXT_HEADING.split(part[1])[0]
    steps = [re.sub(r"\s*\[(\d+|log|m\d+)\]", "", ln).strip(" *-•\t") for ln in body.splitlines()]
    return [re.sub(r"^\d+[.)]\s*", "", st) for st in steps if len(st) > 3]


def whole_sentences(text, limit=300):
    """At most `limit` characters, cut after the last full sentence rather than mid-word."""
    if len(text) <= limit:
        return text
    cut = text[:limit]
    end = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "))
    return cut[:end + 1] if end > 0 else cut.rsplit(" ", 1)[0] + "…"


def remember_checkin(prep, text, cited_numbers):
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
    steps, kept = steps_in(text), []
    for st in steps:  # whole steps only, up to about 900 characters in all
        if sum(len(k) + 3 for k in kept) + len(st) > 900:
            break
        kept.append(st)
    if kept:
        parts.append("suggested: " + " / ".join(kept))
    refs += [prep["sources"][n - 1]["url"] for n in cited_numbers[:5]]
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


EVIDENCE_WAIT = 20  # seconds to wait for PubMed and H-MEM once the Zetaris queries are done


def find_reviews(terms, context):
    """PubMed reviews for these terms, or None when PubMed fails twice (slow or rate-limited)."""
    for attempt in range(2):
        try:
            return research.reviews(terms, top_n=2, context=context)
        except Exception:
            if attempt == 0:
                time.sleep(1.5)
    return None


def prepare(question, user_id, as_of=None, clarified=False, said=None, verdict=None):
    """Everything the answer is built from, gathered before it is written: the safety check,
    candidate causes, library topics and the user's numbers through Zetaris, live PubMed
    reviews, and past check-ins from H-MEM. `said` is what the person wrote themselves, when
    `question` is a whole conversation folded into one (turn() has already screened it)."""
    sql = store.start_log()
    decisions = []
    if said is None:
        urgent, verdict = danger(question, user_id)
        if urgent:
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
    words = set(re.findall(r"[a-z]+", (said or question).lower()))
    remedies = [r for r in found_terms["remedies"]
                if words & {w for w in re.findall(r"[a-z]+", r.lower()) if len(w) > 2}]
    for r in found_terms["remedies"]:
        if r not in remedies:
            decisions.append(f"Skipped remedy {r}: the person didn't name it")
    # The person's own words only: the merged question also holds the agent's earlier answer,
    # which may itself ask for "the ingredient list on the label".
    brands = ([] if "ingredients on the label" in (said or question).lower()
              else found_terms.get("brands", []))
    timings["hypotheses"] = round(time.time() - t0, 1)
    # PubMed and H-MEM are slow network calls that need nothing from Zetaris, so they run in
    # the background while the Zetaris queries run here (here, so their SQL is logged).
    t0 = time.time()
    pool = ThreadPoolExecutor(max_workers=2)
    generic = [r for r in remedies if r not in brands]  # PubMed knows ginger, not Gut FX
    # A remedy is searched for these conditions only: on its own, "honey" finds honey for
    # diabetic foot ulcers. With a remedy, the person's condition matters as it meets the
    # remedy ("antidepressants" with diabetes); without one, one review per candidate cause.
    wanted = [([name], name, hyps or None) for name in generic[:2]]
    wanted += ([([hyps[0]], hyps[0], generic[0])] if generic and hyps
               else [([h], h, None) for h in hyps[:3]])
    # One after another: PubMed allows 3 requests a second without a key.
    reviews = pool.submit(lambda: [(about, find_reviews(terms, context))
                                   for terms, about, context in wanted])
    # copy_context: the public demo's visitor id lives in a context variable, and without it
    # recall would read the shared demo memory instead of this visitor's own.
    recall = pool.submit(contextvars.copy_context().run, memory.relevant, user_id, question, 8)
    pool.shutdown(wait=False)
    topics = topics_for(question)
    summary = user_summary(user_id, as_of=as_of) if is_personal(question) else None
    decisions.append("Used your Fitbit week: the question is about sleep or activity"
                     if summary else "Left your Fitbit week out: the question isn't about sleep, "
                     "activity or weight")
    # Exact condition names first; meaning-based search only fills the gaps, because on its
    # own it can rank Diphtheria above Eczema for "red, dry skin in the folds of my arms".
    found = library.by_name(hyps)[:3]
    ids = {r["doc_id"] for r in found}
    found += [r for r in library.search(f"{question}. Possibly: {', '.join(hyps)}")
              if r["match"] >= MIN_MATCH and r["doc_id"] not in ids][:3 - len(found)]
    library_rows = [{"title": r["title"], "text": r["text"], "url": r["url"],
                     "source": r["source"], "kind": "library", "match": r["match"]} for r in found]
    guide_rows = ([dict(s, kind="guide") for s in sources_for(topics, per_topic=3)]
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
    papers, seen = [], set()
    try:  # a hung PubMed or H-MEM must not hang the check-in; late threads finish on their own
        found = reviews.result(timeout=EVIDENCE_WAIT)
    except TimeoutError:
        found = []
        decisions.append("PubMed didn't answer in time; went on without it")
    for about, found_reviews in found:  # first new review per search, in order
        if found_reviews is None:
            decisions.append(f"PubMed didn't answer for {about}; went on without it")
            continue
        for p in found_reviews:
            if p["url"] not in seen:
                seen.add(p["url"])
                papers.append(dict(p, kind="research", about=about))
                break
    try:
        past = latest_per_question(recall.result(timeout=EVIDENCE_WAIT))[:3]
    except TimeoutError:
        past = []
        decisions.append("H-MEM didn't answer in time; went on without past check-ins")
    timings["pubmed"] = round(time.time() - t0, 1)
    via = llm.via()
    if via != "Meterless Nightshift":
        decisions.append(f"Answer written by {via}")
    sources = on_topic(question, remedy_rows + library_rows + guide_rows[:3] + papers, decisions)
    return {
        "question": question, "user": user_id, "urgent": None, "summary": summary,
        "hypotheses": hyps, "remedies": remedies, "brands": brands,
        "topics": topics or [h.lower() for h in hyps[:2]],
        "sources": sources, "past": past, "decisions": decisions,
        "sql": list(sql), "backend": store.backend(), "timings": timings, "via": via,
        "guard": verdict, "caution": guard_note(verdict, decisions),
    }


def turn(turns, user_id, as_of=None):
    """One step of a conversation. `turns` is the whole conversation so far, newest last:
    {"role": "user" | "assistant", "content": ..., "kind": "ask" | "answer"}. Returns a
    follow-up question ({"ask": {...}}), the emergency message, or the prepared evidence for
    an answer (the page then streams it with /api/stream)."""
    # Screen everything the person wrote, not just the newest turn: the page sends the whole
    # conversation, so a danger sign in an earlier turn must not slip past.
    said = "\n".join(t["content"] for t in turns if t["role"] == "user")
    urgent, verdict = danger(said, user_id)
    if urgent:
        return {"urgent": urgent}
    t0 = time.time()
    ask = clarify.next_step(turns)
    if ask:
        return {"ask": ask, "timings": {"clarify": round(time.time() - t0, 1)}}
    clarify_s = round(time.time() - t0, 1)
    prep = prepare(clarify.case_text(turns), user_id, as_of, clarified=True, said=said,
                   verdict=verdict)
    prep["conversation"] = turns
    prep["timings"]["clarify"] = clarify_s
    return prep


def danger(text, user_id):
    """(emergency message or None, Nemotron Safety Guard verdict or None). The rules come first;
    the guard model adds harmful requests they can't phrase. Either path to help is logged to
    H-MEM."""
    # Rules line by line, so a "no" in one turn can't cancel a danger sign in the next.
    urgent = next(filter(None, map(safety.check, text.splitlines())), None)
    verdict = None if urgent else safety.guard(text)
    if verdict and not verdict["safe"] and "Suicide and Self Harm" in verdict["categories"]:
        urgent = safety.EMERGENCY
    if urgent:
        memory.remember(user_id, f"Danger sign reported: \"{text}\". Sent to emergency help.",
                        source="safety_filter", tags=["danger"], confidence=1.0)
    return urgent, verdict


def guard_note(verdict, decisions):
    """Log the guard's verdict; for a flagged question that isn't self-harm (a maximum dose,
    say), return the extra instruction that keeps the answer to labels and sources."""
    if verdict is None:
        decisions.append("Nemotron Safety Guard was unavailable, so the safety rules ran alone")
        return ""
    if verdict["safe"]:
        return ""
    cats = ", ".join(verdict["categories"]) or "unsafe"
    decisions.append(f"Nemotron Safety Guard flagged the question ({cats}), so the answer keeps "
                     "to labels and trusted sources and points to a pharmacist or doctor")
    return ("This question was flagged by a safety model (" + cats + "). Give no doses or amounts "
            "beyond what the evidence or a product label states, and tell the person to confirm "
            "with a pharmacist or doctor.\n")


def latest_per_question(past):
    """Keep only the newest check-in for each question asked, so asking the same thing three
    times does not fill the memory slots with copies of one old answer."""
    seen, keep = set(), []
    for m in sorted(past, key=lambda m: m["learnedAt"], reverse=True):
        asked = re.search(r'asked "(.*?)"(?=; |\.$)', m["content"], re.S)
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


def cited(text):
    """Source numbers the answer cites, in order of first use."""
    return list(dict.fromkeys(int(n) for n in re.findall(r"\[(\d+)\]", text)))


# Lines that only say what to tell the doctor are advice about the visit, not health facts,
# so they need no source.
VISIT = re.compile(r"\s*(?:[-*•]|\d+[.)])\s+(?:\*\*)?(?:tell|bring|mention|note|share|keep a|try (?:this|these)|track|log)\b", re.I)


LIST_ITEM = re.compile(r"\s*(?:[-*•]|\d+[.)])\s+")
NEXT_HEADING = re.compile(r"^[ \t]*(?:#{1,4}[ \t]*)?\*\*[^*\n]{3,40}\*\*", re.M)  # ends a section
GROUND_MIN = 0.72  # how close a line and a passage must be in meaning to count as support


def _loose_lines(text):
    """(line, section) for each cause, step and warning sign with no [n] and not about the visit."""
    out = []
    for part in re.split(r"^[ \t]*\*\*(?=Possible causes|What you can do now|See a doctor)", text,
                         flags=re.M | re.I)[1:]:
        body = NEXT_HEADING.split(part.split("\n", 1)[-1])[0]
        out += [ln for ln in body.splitlines()
                if LIST_ITEM.match(ln) and not re.search(r"\[\d+\]", ln) and not VISIT.match(ln)]
    return out


def ground(text, sources):
    """Cite each uncited line to a source passage that says the same thing, checked by meaning
    with the local embedding model. Lines no passage supports stay uncited (the page labels
    them "no source"). Returns the text and how many lines it cited."""
    loose = _loose_lines(text)
    if not loose or not sources:
        return text, 0
    passages = [(n, chunk) for n, src in enumerate(sources, 1)
                for chunk in re.findall(r"[^.!?]+[.!?]", src["text"]) if len(chunk) > 40]
    if not passages:
        return text, 0
    vectors = [library._unit(v) for v in library.embed(
        [f"search_query: {re.sub(r'[*]|\[(?:log|m\d+)\]', '', ln).strip(' -•')}" for ln in loose] +
        [f"search_document: {chunk.strip()}" for _, chunk in passages])]
    lines, chunks, added = vectors[:len(loose)], vectors[len(loose):], 0
    for ln, v in zip(loose, lines):
        score, n = max((sum(a * b for a, b in zip(v, c)), n) for c, (n, _) in zip(chunks, passages))
        if score >= GROUND_MIN:
            text = text.replace(ln, ln.rstrip().rstrip(".") + f" [{n}].", 1)
            added += 1
    return text, added


def drop_unsourced(text):
    """Remove causes, steps and warning signs that no source supports: an unsourced line would
    put the whole answer's credibility in doubt. A section left with nothing says so plainly.
    Returns the text and how many lines were removed."""
    loose = _loose_lines(text)
    for ln in loose:
        text = text.replace(ln + "\n", "", 1) if ln + "\n" in text else text.replace(ln, "", 1)
    parts = re.split(r"(^[ \t]*\*\*(?:Possible causes|What you can do now|See a doctor)[^\n]*\n)", text,
                     flags=re.M | re.I)
    for i in range(1, len(parts) - 1, 2):
        body = NEXT_HEADING.split(parts[i + 1], maxsplit=1)
        items = [ln for ln in body[0].splitlines() if LIST_ITEM.match(ln) and not VISIT.match(ln)]
        if items:
            continue
        if parts[i].lower().lstrip(" *").startswith("see a doctor"):  # never leave it without one
            parts[i + 1] = "If this lasts, gets worse or worries you, see a doctor.\n" + parts[i + 1]
        elif not body[0].strip():
            parts[i + 1] = ("The trusted sources found don't cover this. A doctor or pharmacist "
                            "can help.\n\n") + parts[i + 1]
    return "".join(parts), len(loose)


def finish(prep, text):
    """Check the written answer, rewrite it once if it cites no source, save it to H-MEM and
    write the decision trace."""
    decisions = prep.setdefault("decisions", [])
    raw = llm.clean(text)
    text = check_citations(raw, len(prep["sources"]), len(prep["past"]))
    marks = r"\[(?:\d+|log|m\d+)"
    if len(re.findall(marks, text)) < len(re.findall(marks, raw)):
        decisions.append("Removed citation marks that pointed at no source")
    if prep["sources"] and not cited(text):
        decisions.append("The answer cited no trusted source, so it was written again")
        retry = messages(prep)
        retry[-1]["content"] += ("\n\nYour last draft cited no source. Cite the evidence "
                                 "with [n] for every cause, step and research fact.")
        text = check_citations(llm.clean(llm.chat(retry)), len(prep["sources"]),
                               len(prep["past"]))
    text, matched = ground(text, prep["sources"])
    if matched:
        decisions.append(f"Cited {matched} line{'s' if matched > 1 else ''} the model left uncited "
                         "to the source passage that says the same thing")
    text, removed = drop_unsourced(text)
    if removed:
        decisions.append(f"Removed {removed} line{'s' if removed > 1 else ''} that no trusted source "
                         "supported")
    numbers = cited(text)
    if prep["sources"]:
        decisions.append(f"The answer cites {len(numbers)} of {len(prep['sources'])} sources; "
                         "only those are listed")
    saved = remember_checkin(prep, text, numbers)
    save_trace(prep, saved["id"], numbers, text)
    return {"text": text, "saved": saved, "cited": numbers, "decisions": decisions,
            "disclaimer": safety.DISCLAIMER}


def save_trace(prep, memory_id, numbers, text):
    """Everything the agent decided for this check-in, kept next to its H-MEM memory."""
    TRACES.mkdir(parents=True, exist_ok=True)
    trace = {k: prep.get(k) for k in ("question", "hypotheses", "remedies", "brands", "topics",
                                      "decisions", "sql", "backend", "timings")}
    trace["sources"] = [{k: s.get(k) for k in ("title", "source", "url", "kind", "relevance")}
                        for s in prep["sources"]]
    trace["cited"] = numbers
    trace["recalled"] = [m["id"] for m in prep["past"]]
    trace["answer"] = text
    trace_path(prep["user"], memory_id).write_text(json.dumps(trace, indent=1), encoding="utf-8")


def trace_path(user_id, memory_id):
    """Where a check-in's trace lives; public-demo visitors each have their own."""
    return TRACES / f"{memory.owner(user_id)}-{memory_id}.json"


def saved_answer(user_id, memory_id):
    """The full answer of a check-in, from its trace, or None for older check-ins."""
    path = trace_path(user_id, memory_id)
    return json.loads(path.read_text(encoding="utf-8")).get("answer") if path.exists() else None


def answer(question, user_id, dry_run=False, as_of=None, clarified=False):
    prep = prepare(question, user_id, as_of, clarified)
    if prep.get("urgent"):
        return prep["urgent"]
    if prep.get("clarify"):
        return "Before answering, Check-In needs to know:\n" + "\n".join(
            f"- {c['q']} ({' / '.join(c['options'])})" for c in prep["clarify"]) + \
            '\n\nRun again with --answers "..."'
    if dry_run:
        return json.dumps(prep, indent=1)
    out = respond(prep)
    refs = "\n".join(f"[{i}] {s['source']}: {s['title']} - {s['url']}"
                     for i, s in enumerate(prep["sources"], 1) if i in out["cited"])
    mems = "\n".join(f"[m{i}] {m['learnedAt'][:10]}, {m['source']}, confidence {m['confidence']:.2f}"
                     f" ({m['id']})" for i, m in enumerate(prep["past"], 1))
    return (f"{out['text']}\n\nSources:\n{refs}"
            + (f"\n\nRemembered from past check-ins (Meterless H-MEM):\n{mems}" if mems else "")
            + f"\n\nSaved this check-in to memory as {out['saved']['id']}.\n\n{out['disclaimer']}")


def journal_entry(m):
    """A stored memory split into the parts the journal shows: what was asked (and any
    follow-up), the person's answers to Check-In's questions, the causes considered, the log at
    the time and the suggestion. The parts come from the text remember_checkin() writes."""
    text = m["content"]
    if m.get("source") == "user_report":
        return {"kind": "note", "text": text.removeprefix("User reported: ")}
    if m.get("source") != "checkin":
        return {"kind": "safety" if m.get("source") == "safety_filter" else "other", "text": text}
    body = text.removeprefix("Check-in: ")
    # Older check-ins joined the parts with ". " and capitalised them ("Data: ...").
    found = re.match(r'asked "(.*?)"(?=; |\. |\.?$)', body, re.S)
    if not found:
        return {"kind": "other", "text": text}
    entry = {"kind": "checkin", "question": "", "follow_up": None, "answers": [],
             "considered": [], "data": None, "steps": [], "early": False}
    for part in found.group(1).split("\n\n"):  # the conversation as clarify.case_text folds it
        if part.startswith("My answers:"):
            for line in part.splitlines()[1:]:
                ask, _, reply = line.removeprefix("- ").partition("? ")
                entry["answers"].append({"ask": ask + "?" if reply else "", "reply": reply or ask})
        elif part.startswith("Follow-up question: "):
            entry["follow_up"] = part.removeprefix("Follow-up question: ")
        elif not part.startswith("(Check-In answered:") and not entry["question"]:
            entry["question"] = part
    rest = body[found.end():].lstrip("; .")
    for part in re.split(r"(?:; |\. )(?=(?:considered|data:|suggested:) )", rest, flags=re.I):
        part = part.rstrip(".")
        part = part[:1].lower() + part[1:]
        if part.startswith("considered "):
            entry["considered"] = part.removeprefix("considered ").split(", ")
        elif part.startswith("data: "):
            entry["data"] = part.removeprefix("data: ")
        elif part.startswith("suggested: ") and len(part) > len("suggested: ") + 3:
            tip = part.removeprefix("suggested: ").removeprefix("Try this: ")
            # Older check-ins kept only the first step, cut at 300 characters.
            tip = re.sub(r"\s*\[(?:\d+|log|m\d+)(?:,\s*(?:\d+|log|m\d+))*\]", "", tip)
            tip = re.sub(r"\s+([,.;])", r"\1", tip)
            steps = [whole_sentences(tip, 290) if len(tip) >= 290 else tip] \
                if " / " not in tip else tip.split(" / ")
            # Older check-ins sometimes kept a broken fragment ("Apply a."): drop anything that
            # isn't a real step.
            entry["steps"] = [st.strip().rstrip(" .") + "." for st in steps
                              if len(st.split()) >= 4]
            entry["early"] = " / " not in tip
    return entry


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
