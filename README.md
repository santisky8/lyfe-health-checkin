# Lyfe Health Check-In

A health check-in agent that answers "why" questions ("Why am I tired every afternoon?")
by joining the user's own habit data with trusted public health sources, and shows the
evidence behind every claim. Built for the Open Agent Hackathon 2026, Track 02: The Agent
That Can Explain Why.

It never diagnoses, never treats and never replaces a doctor. It points to everyday causes
the user's own numbers show, suggests one safe change for the week, and says when to see a
doctor and what to tell them. Danger signs skip the advice and show emergency help.

## How it works

1. **Danger-sign filter** (`agent/safety.py`): chest pain, stroke signs, trouble breathing,
   self-harm and similar go straight to emergency help. No model call.
2. **Topic routing**: the question picks topics (sleep, fatigue, activity, nutrition...).
3. **SQL over federated sources through Zetaris** (`agent/store.py`): the user's last 14 days
   plus passages from each source, queried through the Zetaris Lightning REST API. The five
   sources are registered as Lightning filestore tables in database `LYFE_HEALTH_CHECKIN`
   (`zetaris/load.sql`). A local SQLite copy is the offline fallback.
4. **Memory with provenance through Meterless H-MEM** (`agent/memory.py`, `meterless/`):
   before answering, the agent recalls the user's past check-ins and reported outcomes; after
   answering, it saves this check-in (the numbers, the suggestion, the Zetaris rows it came
   from) with a source and confidence. Every change goes to an append-only trust ledger, so
   the agent can say why it remembers something and follow up on last week's suggestion.
5. **Local model** through any OpenAI-compatible endpoint (Ollama in development; Meterless
   Nightshift where available), so health data stays on the user's machine.
6. **Cited answer**: user numbers cited as `[log]`, sources as `[n]`, past check-ins as `[m]`,
   plus a disclaimer.

## Sources

| Table | Source | Licence | Access |
|---|---|---|---|
| `user_log` | Fitbit data from 30 consenting people (Furberg et al., [Zenodo 53894](https://zenodo.org/records/53894)) | CC BY 4.0 | download |
| `myhealthfinder` | [MyHealthfinder](https://odphp.health.gov/myhealthfinder), US ODPHP | public domain | API, no key |
| `medlineplus` | [MedlinePlus](https://medlineplus.gov), US National Library of Medicine | public domain | API, no key |
| `pubmed` | [PubMed](https://pubmed.ncbi.nlm.nih.gov) systematic reviews and meta-analyses | abstracts, cited | E-utilities, no key |
| `nutrient_limits` | [NIH Office of Dietary Supplements](https://ods.od.nih.gov) fact sheets | public domain | typed from fact sheets |

## Setup

Python 3.10+, standard library only.

```sh
./load_all.sh                                   # pull sources, build data/checkin.sqlite
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
