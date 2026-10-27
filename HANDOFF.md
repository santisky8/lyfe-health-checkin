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

## Nightshift Web hotspot (2026-10-27, replaces the Windows laptop)
The agent calls a Nightshift Web Persistent Hotspot (relay on nightshift-hotspot.ns-proxy.workers.dev;
LLM_BASE_URL and the client token LLM_API_KEY are in `.env.local`). Meterless's companion script
(~/.local/share/nightshift-companion/, SHA-256 93e640b6..., config companion.json mode 600) runs
`serve` and forwards to NVIDIA cloud (upstream https://integrate.api.nvidia.com/v1, key from
NVIDIA_API_KEY, models nemotron-3-ultra-550b-a55b and nemotron-3.5-bolt-e4b). Quirks handled in
agent/llm.py: Cloudflare refuses Python's default User-Agent (error 1010); the relay's default
max_tokens is short, so a limit is always sent; about 1 Ultra reply in 3 arrives with its
reasoning in front, so reasoning models are asked non-streamed and retried. The hotspot and its
tokens are managed in Brave at https://meterless.ai/Nightshift/WEB/ (Setup > hotspot).

## Nightshift (done 2026-10-25, evening) (old setup)
Runs on the Windows laptop (Win10, 940MX 2 GB: too weak for local models, so it serves NVIDIA
cloud Nemotron through the user's nvapi key saved in Nightshift). Hotspot mode on, Wi-Fi Private,
firewall rule "Nightshift 8088 LAN" (TCP 8088, Private, 192.168.0.0/24). The laptop must stay
plugged in (it sleeps on battery). `.env.local`: LLM_BASE_URL=http://192.168.0.43:8088/v1,
LLM_MODEL=nvidia/nemotron-3-ultra-550b-a55b, LLM_API_KEY = runtime proxy-token. The Ollama lines
are kept as comments for fallback; embeddings still use local Ollama (nomic-embed-text).
Ultra sends its reasoning ending in </think> with no opening tag; llm.py strips it.
6 user tests: 14-50 s each (was 2-6 min). Weak spots are retrieval, not the model: empty
Sources in the red-dots and Gut FX answers, off-topic MedlinePlus pages for the skin question,
NCCIH arnica page not retrieved, and test check-ins in H-MEM steering later answers.

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
