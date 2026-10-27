# Lyfe Health Check-In

A private health check-in agent. Describe what's going on in your own words ("the soles of
my feet feel like stinging needles", "how do I get rid of milia?", "why am I tired every
afternoon?") and it explains what it could be, what you can do, what the research says and
when to see a doctor, with a source behind every claim. Built for the Open Agent Hackathon
2026, Track 02: The Agent That Can Explain Why.

It never diagnoses, never treats and never replaces a doctor: it weighs possible causes and
says how to tell them apart. Medicines and procedures appear only as options to ask a doctor
about. Danger signs skip the advice and show emergency help. The data, search and memory run
on the user's own computer; only the question, its evidence and a weekly summary go to the
model.

## How it works

1. **Danger-sign filter** (`agent/safety.py`): chest pain, stroke signs, trouble breathing,
   a spreading red swelling, rash with fever, self-harm and similar go straight to emergency
   help, by plain rules with no model call. Then NVIDIA's **Nemotron Safety Guard**
   (`llama-3.1-nemotron-safety-guard-8b-v3`) screens for harmful requests the rules can't
   phrase: a self-harm verdict also goes to crisis help; other flags (a maximum dose, say)
   keep the answer to labels and sources. Its verdict and categories show under "Show your
   work". If the model is unreachable, the rules still run and the trace says so.
2. **Questions first** (`agent/clarify.py`): when the safe answer depends on a detail the
   question leaves out, the agent asks up to three short questions with tap answers before
   anything else. "How long should I take arnica?" asks how it is taken, because arnica
   swallowed as an herbal supplement is toxic while gels and homeopathic pellets are not.
   Clear questions ("why am I tired every afternoon?") go straight on.
3. **Possible causes** (`agent/hypotheses.py`): a fast model (Nemotron 3.5 Bolt, `HYPO_MODEL`)
   turns the person's words into up to four standard condition names. They are search terms,
   not a diagnosis.
4. **Health library and the user's log through Zetaris** (`agent/library.py`, `agent/store.py`):
   1,016 MedlinePlus topics are matched first by name (each condition against topic titles and
   "also called" names, so "atopic dermatitis" finds Eczema), then by meaning with a local
   embedding model (`nomic-embed-text`) for anything the names miss, and read through the Zetaris Lightning REST API, together with the
   user's last 7 days of sleep and activity when the question is about them. All sources are
   Lightning filestore tables in database `LYFE_HEALTH_CHECKIN` (`zetaris/load.sql`). A local
   SQLite copy is the offline fallback.
5. **Live research** (`agent/research.py`): PubMed is searched at question time for a recent
   systematic review (or review) on each possible cause, or, for a remedy question, on the
   remedy for the person's conditions. Case reports are never used. PubMed and the H-MEM
   recall run in the background while the Zetaris queries run, which saves several seconds.
6. **Memory with provenance through Meterless H-MEM** (`agent/memory.py`, `meterless/`):
   before answering, past check-ins and reported outcomes are recalled with H-MEM and
   re-ranked by meaning; after answering, the check-in (question, causes considered,
   suggestion, source links, Zetaris rows) is saved with a source and confidence. Every
   change goes to H-MEM's append-only trust ledger.
7. **Model through Meterless Nightshift** (`agent/llm.py`): the agent calls a Nightshift Web
   Persistent Hotspot, one OpenAI-compatible address with its own client token. Nightshift's
   companion runs on the same Linux machine as a background service and serves NVIDIA
   Nemotron 3 Ultra and 3.5 Bolt from build.nvidia.com, so the question and its evidence go
   to NVIDIA to be answered and the agent never holds the NVIDIA key. (Until 27 Oct it was the
   Nightshift Windows app in Hotspot mode on a second laptop.) The user's raw log stays local:
   only the weekly summary is sent. Any OpenAI-compatible endpoint works, including a local
   Ollama for a fully private mode. If a reply arrives with the model's reasoning in front of
   the answer, it is asked again. If Nightshift fails and `NVIDIA_API_KEY` is set, the same
   Nemotron models are called on NVIDIA's own cloud instead, and "Show your work" says which
   one wrote the answer.
8. **Suggested questions** (`checkin.suggestions`, `/api/suggest`): fixed rules on the
   person's own week and notes suggest what to ask (sleep down from last week, under 7 hours,
   long sitting, under 150 active minutes, "did it help?" on their latest note). Each shows the
   numbers behind it. No model is involved, so a suggestion can't invent anything.
9. **Only on-topic sources** (`checkin.on_topic`): every source is scored against the question
   by meaning; sources far behind the best match are dropped, and PubMed case reports are
   never used.
10. **Cited answer** in four parts: possible causes, what you can do now, what the research
   says, see a doctor if. Sources are `[n]`, the user's numbers `[log]`, past check-ins `[m]`.
   Every cause, step and fact must cite a source: an answer with no `[n]` is rewritten once,
   citation marks that point at nothing are removed, and only the sources the answer cites
   are listed under it, each with its publisher and site icon.

## Sources

| Table | Source | Licence | Access |
|---|---|---|---|
| `user_log` | Fitbit data from 33 consenting people (Furberg et al., [Zenodo 53894](https://zenodo.org/records/53894)) | CC BY 4.0 | download |
| `myhealthfinder` | [MyHealthfinder](https://odphp.health.gov/myhealthfinder), US ODPHP | public domain | API, no key |
| `medlineplus` | [MedlinePlus](https://medlineplus.gov), US National Library of Medicine | public domain | API, no key |
| `medlineplus_topics` | All 1,016 English MedlinePlus health topics | public domain | NLM search API, no key |
| live | [PubMed](https://pubmed.ncbi.nlm.nih.gov) reviews per question | titles, short excerpts and links | E-utilities, no key |
| `pubmed` | [PubMed](https://pubmed.ncbi.nlm.nih.gov) systematic reviews and meta-analyses | abstracts, cited | E-utilities, no key |
| `nccih` | [NCCIH](https://www.nccih.nih.gov) herb and supplement pages, US NIH | public domain | download |
| `nutrient_limits` | [NIH Office of Dietary Supplements](https://ods.od.nih.gov) fact sheets | public domain | typed from fact sheets |

## Setup

Python 3.10+, standard library only.

```sh
./load_all.sh                                   # pull sources, build data/checkin.sqlite
python3 agent/library.py build                  # embed the 1,016 library topics (needs Ollama)
# Zetaris: copy data/clean/<table>/ into the driver's customer-data/shared/lyfe_health_checkin/ and run
# zetaris/load.sql with lightning-sql.sh; then set ZETARIS_URL, ZETARIS_EMAIL and
# ZETARIS_PASSWORD in .env.local (gitignored). Without ZETARIS_URL the agent uses SQLite.
python3 agent/checkin.py --dry-run "Why am I tired every afternoon?"   # evidence only
LLM_BASE_URL=<nightshift hotspot>/v1 LLM_API_KEY=<client token> LLM_MODEL=<model> \
  python3 agent/checkin.py "Why am I tired every afternoon?"
```

**Web app:** `python3 server.py`, then open http://localhost:8765. Pick a person and a week,
ask a why question, and the right-hand panel shows each step: the safety check, the SQL sent
to Zetaris, the memories H-MEM recalled, the model, and the memory it saved. Settings
(`ZETARIS_*`, `LLM_*`) come from `.env.local`.

`--user <id>` picks one of the 33 Fitbit users (default `1503960366`).
`--note "Went to bed earlier, less tired"` saves what the user tried and how it went.
Memory needs Node 22.7+ (it runs the TypeScript engine with `--experimental-transform-types`).

## Decisions you can audit

Every choice the agent makes is recorded with its reason: whether the log is used, remedies it
skipped because the person didn't name them, sources dropped as off-topic (with their match
score and the score needed), PubMed searches that failed, citation marks removed, and whether
the answer had to be rewritten to cite a source. The app shows them under "Show your work",
next to the SQL sent to Zetaris and the memories recalled from H-MEM, and each check-in's full
trace is saved to `data/traces/<user>-<memory id>.json`, next to its H-MEM memory and ledger.

## Sample check-ins

Three real runs: the input, the output, and the log behind it. The full traces of the first
two (SQL sent to Zetaris, sources, H-MEM recalls, decisions, timings) are in
[`docs/examples/`](docs/examples/). Both answers were written by NVIDIA Nemotron 3 Ultra
through Meterless Nightshift. Answers are shortened here; the traces hold them in full.

**1. A question about the person's own week** (Fitbit user `1503960366`, as of 2016-04-25)

Input: `Why has my sleep gotten worse this week, and what can I change?`

Output (excerpt):

> **What you describe:** Over the past week you averaged 5.7 hours of sleep per night, with 5
> of 6 nights below the 7-hour guideline [log]. This matches the pattern in your three previous
> check-ins [m1][m2][m3].
>
> **Possible causes:** 1. Sleep deprivation: less than 7 hours builds a sleep debt [6].
> 2. Stress: even short-term stress can trigger acute insomnia [1][7]. 3. Poor sleep hygiene [3][4].
> 4. Insomnia, if it happens most nights for a month or more [1].
> *Do you notice racing thoughts or worry at bedtime, or is it mainly a habit of staying up late?*
>
> **What you can do now:** Move bedtime 30 minutes earlier tonight and keep the same wake time
> every day [3][4]. Stop screens 1 hour before bed [4]. ...
>
> **See a doctor if:** sleep trouble persists more than 2 weeks after trying the steps [5]; you
> snore loudly, gasp, or have been told you stop breathing during sleep [2]. ...

Log: 2 Zetaris queries (the user's week, then MedlinePlus topics), 3 past check-ins recalled
from H-MEM, 7 sources cited. Decisions: "Used your Fitbit week: the question is about sleep or
activity"; "Dropped as off-topic: Stress (match 0.51, needed 0.55)"; "Removed 1 line that no
trusted source supported". Trace: [`sleep-worse-this-week.json`](docs/examples/sleep-worse-this-week.json).

**2. A remedy question, with clarifying questions** (user `4445114986`)

Input: `I've got a sore throat. What can I do? Would eating ginger help?`, then the answers to
the two clarifying questions: `No fever, both sides` and `Fresh ginger in food or tea`.

Output (excerpt):

> **Your question:** Ginger has not been studied for sore throat. It is researched for nausea,
> menstrual cramps, and osteoarthritis [1][2]. Ginger can cause mouth and throat irritation [3],
> so it may not help and could worsen discomfort.
>
> **Possible causes:** 1. Viral pharyngitis (common cold/flu): most likely; no fever, both
> sides [4][5]. 2. Streptococcal pharyngitis (strep throat): usually sudden severe pain, fever,
> one-sided swelling [4][5]. ...
>
> **See a doctor if:** the sore throat lasts more than 7 days or worsens after 3 days [4]. ...

Log: the Fitbit week was left out ("the question isn't about sleep, activity or weight"),
honey was skipped ("the person didn't name it"), 3 sources were dropped as off-topic, and
5 of 5 sources were cited (3 NCCIH ginger pages, 2 MedlinePlus topics). Trace:
[`sore-throat-ginger.json`](docs/examples/sore-throat-ginger.json).

**3. A danger sign**

Input: `I have crushing chest pain and my left arm feels numb. What should I do?`

Output (complete):

> This could be serious. Please get help now: call your local emergency number (911 in North
> America, 112 in Europe, 999 in the UK). If you're thinking about harming yourself, find a
> free, confidential line at https://findahelpline.com (in Canada and the US, call or text 988).

Log: the safety rules matched before any model call, so no advice was written and no
check-in was saved to memory.

## Pre-existing work (declared)

- Open-source and public data listed above.
- `meterless/hmem/`: Meterless H-MEM reference engine, Apache-2.0, copied unchanged.
- The safety stance (no diagnosis, basics first, safe amounts only, "see a doctor if" with
  what to tell them) follows the editorial rules of the author's Lyfe Health project. No
  Lyfe Health code is in this repo.

All code in this repository was written during the build window (from 22 Oct 2026 00:00 UTC).

## Disclaimer

General health information, not medical advice.

## Showcase site and live demo

- `site/`: one static page (problem, how it works, sponsor tech, screenshots, video), live at
  https://santisky8.github.io/lyfe-health-checkin/ (the `gh-pages` branch holds a copy of
  `site/`; the older Netlify copy may be out of date). It checks `<demo>/api/status` every minute and only enables the "Try the live
  demo" button while the demo answers.
- `demo_service.sh`: run at login by the systemd user service `lyfe-checkin-demo`. It starts
  Docker Desktop, waits for Zetaris, then runs a public-mode copy of the app on port 8766
  (`PUBLIC=1`: each visitor gets their own H-MEM memory through a cookie, errors show no
  details, only the 33 Fitbit people are accepted, and check-ins are rate-limited per caller
  and per day so nobody can run up the model bill). After the judging window it disables
  itself.
- `./demo_on.sh`: starts that service and publishes port 8766 with Tailscale Funnel (the
  Funnel setting survives reboots). Needs the Nightshift companion service running, or `NVIDIA_API_KEY`
  in `.env.local` as the backup.
- `./demo_off.sh`: closes the Funnel and stops the service.
