"""Check-in memory through the Meterless H-MEM engine (meterless/hmem_cli.ts).

Every memory carries its source, confidence and time it was learned, and every change goes
to an append-only ledger, so the agent can show why it remembers something."""
import contextvars
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
# Public demo: each visitor gets their own memory beside the demo person's, so strangers never
# see or change each other's check-ins. Set per request by server.py; empty for local use.
visitor = contextvars.ContextVar("visitor", default="")


def owner(user_id):
    """The id memories and traces are kept under: public-demo visitors each get their own."""
    return f"{user_id}-v{visitor.get()}" if visitor.get() else user_id


def _call(request):
    request = {**request, "user": owner(request["user"])}
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


def relevant(user_id, question, top_n=3, min_similarity=0.66):
    """H-MEM recall, re-ranked by meaning with the local embedding model. H-MEM's own scoring is
    word-based, so on its own a sleep check-in can surface for a question about feet."""
    import library  # local import: library pulls in the data layer
    found = recall(user_id, question, top_n=8, threshold=0)
    if not found:
        return []
    for m, score in zip(found, library.similarity(question, [m["content"] for m in found])):
        m["similarity"] = round(score, 3)
    found = [m for m in found if m["similarity"] >= min_similarity]
    return sorted(found, key=lambda m: -m["similarity"])[:top_n]


def feedback(user_id, memory_id, kind):
    return _call({"op": "feedback", "user": user_id, "id": memory_id, "kind": kind})


def all_memories(user_id):
    return _call({"op": "list", "user": user_id})


def history(user_id, memory_id):
    return _call({"op": "history", "user": user_id, "id": memory_id})
