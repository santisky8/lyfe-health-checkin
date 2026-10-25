# Handoff: Open Agent Hackathon 2026 (solo)

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

## Blockers
1. Meterless (Nightshift) supports only Windows 10/11, Mac M5+, DGX Spark. Web edition and Mac
   M1-M4 have no local endpoint. Linux not listed. Endpoint when installed:
   `http://127.0.0.1:8088/v1`, bearer token from the runtime's token file. Asked organizers? -> pending.
2. Zetaris: platform zip + .env from https://cloud.enterprise.zetaris.com/dashboard/download
   (user must log in). Needs Docker Desktop (start it, stop it after). Then replace
   `agent/store.py` SQLite with Zetaris SQL.
3. NHS API key: optional, registration pending.

## Next
Zetaris load of data/clean/*.csv -> agent queries through Zetaris -> simple chat UI ->
Meterless swap -> video, slides, write-up.
