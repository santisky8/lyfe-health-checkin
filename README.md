# Lyfe Health Check-In

A private health check-in agent. Describe what's going on in your own words ("the soles of
my feet feel like stinging needles", "how do I get rid of milia?", "why am I tired every
afternoon?") and it explains what it could be, what you can do, what the research says and
when to see a doctor, with a source behind every claim. Built for the Open Agent Hackathon
2026, Track 02: The Agent That Can Explain Why.

It never diagnoses, never treats and never replaces a doctor: it weighs possible causes and
says how to tell them apart. Medicines and procedures appear only as options to ask a doctor
about. Danger signs skip the advice and show emergency help. Everything runs on the user's
own computer.

## How it works

1. **Danger-sign filter** (`agent/safety.py`): chest pain, stroke signs, trouble breathing,
   a spreading red swelling, rash with fever, self-harm and similar go straight to emergency
   help. No model call.
2. **Possible causes** (`agent/hypotheses.py`): a fast model (Nemotron 3.5 Bolt, `HYPO_MODEL`)
   turns the person's words into up to four standard condition names. They are search terms,
   not a diagnosis.
3. **Health library and the user's log through Zetaris** (`agent/library.py`, `agent/store.py`):
   1,016 MedlinePlus topics are matched first by name (each condition against topic titles and
   "also called" names, so "atopic dermatitis" finds Eczema), then by meaning with a local
   embedding model (`nomic-embed-text`) for anything the names miss, and read through the Zetaris Lightning REST API, together with the
   user's last 7 days of sleep and activity when the question is about them. All sources are
   Lightning filestore tables in database `LYFE_HEALTH_CHECKIN` (`zetaris/load.sql`). A local
   SQLite copy is the offline fallback.
4. **Live research** (`agent/research.py`): PubMed is searched at question time for a recent
   systematic review (or review) on each possible cause.
5. **Memory with provenance through Meterless H-MEM** (`agent/memory.py`, `meterless/`):
   before answering, past check-ins and reported outcomes are recalled with H-MEM and
   re-ranked by meaning; after answering, the check-in (question, causes considered,
   suggestion, source links, Zetaris rows) is saved with a source and confidence. Every
   change goes to H-MEM's append-only trust ledger.
6. **Model through Meterless Nightshift** (`agent/llm.py`): Nightshift runs on a Windows PC on
   the same network (Hotspot mode) and serves NVIDIA Nemotron 3 Ultra from build.nvidia.com,
   so the question and its evidence go to NVIDIA to be answered. The user's raw log stays
   local: only the weekly summary is sent. Any OpenAI-compatible endpoint works, including a
   local Ollama for a fully private mode. The answer streams to the page as it is written.
7. **Cited answer** in four parts: possible causes, what you can do now, what the research
   says, see a doctor if. Sources are `[n]`, the user's numbers `[log]`, past check-ins `[m]`.

## Sources

| Table | Source | Licence | Access |
|---|---|---|---|
| `user_log` | Fitbit data from 30 consenting people (Furberg et al., [Zenodo 53894](https://zenodo.org/records/53894)) | CC BY 4.0 | download |
| `myhealthfinder` | [MyHealthfinder](https://odphp.health.gov/myhealthfinder), US ODPHP | public domain | API, no key |
| `medlineplus` | [MedlinePlus](https://medlineplus.gov), US National Library of Medicine | public domain | API, no key |
| `medlineplus_topics` | All 1,016 English MedlinePlus health topics | public domain | NLM search API, no key |
| live | [PubMed](https://pubmed.ncbi.nlm.nih.gov) reviews per question | titles, short excerpts and links | E-utilities, no key |
| `pubmed` | [PubMed](https://pubmed.ncbi.nlm.nih.gov) systematic reviews and meta-analyses | abstracts, cited | E-utilities, no key |
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
LLM_BASE_URL=http://<meterless-host>:8088/v1 LLM_API_KEY=<key> LLM_MODEL=<model> \
  python3 agent/checkin.py "Why am I tired every afternoon?"
```

**Web app:** `python3 server.py`, then open http://localhost:8765. Pick a person and a week,
ask a why question, and the right-hand panel shows each step: the safety check, the SQL sent
to Zetaris, the memories H-MEM recalled, the model, and the memory it saved. Settings
(`ZETARIS_*`, `LLM_*`) come from `.env.local`.

`--user <id>` picks one of the 30 Fitbit users (default `1503960366`).
`--note "Went to bed earlier, less tired"` saves what the user tried and how it went.
Memory needs Node 22.7+ (it runs the TypeScript engine with `--experimental-transform-types`).

## Pre-existing work (declared)

- Open-source and public data listed above.
- `meterless/hmem/`: Meterless H-MEM reference engine, Apache-2.0, copied unchanged.
- The safety stance (no diagnosis, basics first, safe amounts only, "see a doctor if" with
  what to tell them) follows the editorial rules of the author's Lyfe Health project. No
  Lyfe Health code is in this repo.

All code in this repository was written during the build window (from 22 Oct 2026 00:00 UTC).

## Disclaimer

General health information, not medical advice.
