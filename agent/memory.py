"""Check-in memory through the Meterless H-MEM engine (meterless/hmem_cli.ts).

Every memory carries its source, confidence and time it was learned, and every change goes
to an append-only ledger, so the agent can show why it remembers something."""
import json
import os
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CLI = ROOT / "meterless" / "hmem_cli.ts"
# Node 22.7+ runs the TypeScript engine directly. VSCodium's Flatpak node is the fallback here.
NODE = os.environ.get("NODE_BIN") or shutil.which("node") or str(
    Path.home() / ".var/app/com.vscodium.codium/data/node/bin/node")


def _call(request):
    r = subprocess.run([NODE, "--no-warnings", "--experimental-transform-types", str(CLI)],
                       input=json.dumps(request), capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        raise RuntimeError(f"H-MEM failed: {r.stderr.strip()[:300]}")
    return json.loads(r.stdout)


def remember(user_id, content, source, tags=(), confidence=0.8, origin="chat_message",
             refs=()):
    return _call({"op": "remember", "user": user_id, "content": content, "source": source,
                  "tags": list(tags), "confidence": confidence, "origin": origin,
                  "refs": list(refs)})


def recall(user_id, query, top_n=5, threshold=0.1):
    return _call({"op": "recall", "user": user_id, "query": query, "topN": top_n,
                  "threshold": threshold})["memories"]


def feedback(user_id, memory_id, kind):
    return _call({"op": "feedback", "user": user_id, "id": memory_id, "kind": kind})


def history(user_id, memory_id):
    return _call({"op": "history", "user": user_id, "id": memory_id})
