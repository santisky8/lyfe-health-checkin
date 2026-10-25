# Handoff: Lyfe Health Check-In, Open Agent Hackathon 2026 (solo)

Read this first in a new session.

## Deadline
Tue 27 Oct 2026, 23:45 UTC = 7:45 PM Toronto. Hard. Submit by 4:45 PM Toronto (calendar block "Hackathon 8").

## Entry
- Track 02: The Agent That Can Explain Why. Solo team, profile filled (2026-10-25).
- Must integrate Zetaris AND Meterless. Cursor optional. NVIDIA optional (Nemotron prize).
- Submit: demo video 1-4 min, slide deck, GitHub repo + README, written sponsor-tech explanation.
- Rules: https://hackathon.genai.works/event/open-agent-hackathon-2026 (hidden rules are in the page JSON).
- Questions: hackathons@genai.works, Discord https://discord.gg/tfwSeqVWmR.

## State (2026-10-25 ~1 PM Toronto)
- Repo works end to end: `./load_all.sh`, then `agent/checkin.py`. Tested on Ollama
  (`LLM_BASE_URL=http://localhost:11434/v1 LLM_MODEL=qwen3:8b`).
- Prompt now cites user numbers as [log]; not rerun since.

## Meterless plan (2026-10-25, decided)
Use the open Meterless ENGINES, not Nightshift. GenAI Academy page: "Build layer: implement a
Meterless Engine for memory, long tasks, shared state or intent routing". Repo
github.com/Meterless/Meterless, engines/ folder (Apache-2.0, TypeScript, Node 24 on this PC:
~/.var/app/com.vscodium.codium/data/node/bin).
- H-MEM reference: reviewed (1,147 lines, zero runtime deps, no network), 10/10 tests pass on Linux.
  Plan: vendor into meterless/hmem, small Node CLI, Python calls it to store check-ins and
  retrieve memories with source and confidence.
- Scout Intent: spec + eval harness only (no src). Build a small Scout class for danger signs
  and topic routing, verify with SCOUT_IMPL=... npm run evals.
- Nightshift (Windows app, unsigned) is optional; only for the NVIDIA prize.

## Zetaris (done 2026-10-25, ~3 PM Toronto)
Running locally from ~/Downloads/zetaris/zetaris-platform (docker compose; Docker Desktop must be
on). Registry login lives in ~/.docker-zetaris (DOCKER_CONFIG) because `pass` is not set up.
Tables LYFE_HEALTH_CHECKIN.{user_log,nutrient_limits,myhealthfinder,medlineplus,pubmed} registered
(zetaris/load.sql), counts match. Agent queries Zetaris when ZETARIS_URL is in .env.local.
After the hackathon: `docker compose stop` (never `down -v`), then stop Docker Desktop.

## App (2026-10-25 evening)
`python3 server.py` -> http://localhost:8765 (web/index.html, stdlib server). Prepare step is
fast; local qwen3:8b answer takes 2-5 min on this CPU while Zetaris runs. Demo story: person
1503960366, week to 2016-04-25 (5.7 h sleep), note "went to bed earlier", week to 2016-05-12
(6.3 h). Reset demo memory: delete data/memory/1503960366/.

## Blockers
1. (old note) Meterless (Nightshift) supports only Windows 10/11, Mac M5+, DGX Spark. Web edition and Mac
   M1-M4 have no local endpoint. Linux not listed. Endpoint when installed:
   `http://127.0.0.1:8088/v1`, bearer token from the runtime's token file. Asked organizers? -> pending.
2. Zetaris: platform zip + .env from https://cloud.enterprise.zetaris.com/dashboard/download
   (user must log in). Needs Docker Desktop (start it, stop it after). Then replace
   `agent/store.py` SQLite with Zetaris SQL.
3. NHS API key: optional, registration pending.

## Next
Zetaris load of data/clean/*.csv -> agent queries through Zetaris -> simple chat UI ->
Meterless swap -> video, slides, write-up.
