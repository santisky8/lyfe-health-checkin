# Meterless engines used here

`hmem/` is the H-MEM reference implementation from
https://github.com/Meterless/Meterless/tree/main/engines/hmem (Apache-2.0, see `hmem/LICENSE`),
copied unchanged on 2026-10-25. Its upstream tests passed on this machine (10/10).

`hmem_cli.ts` is ours: a small bridge the Python agent calls with one JSON request on stdin.
Each user gets a memory folder under `data/memory/<user>/` with `state.json` and the
append-only `ledger.jsonl`.
