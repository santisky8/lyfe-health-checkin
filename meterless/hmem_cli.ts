// Bridge between the Python agent and the Meterless H-MEM reference engine (meterless/hmem).
// One JSON request on stdin, one JSON reply on stdout. Each user gets their own memory
// folder (state.json + append-only ledger.jsonl), so memories never mix between people.
//
//   {"op":"remember","user":"1503960366","content":"...","source":"checkin","tags":[...],
//    "confidence":0.9,"origin":"chat_message"}
//   {"op":"recall","user":"1503960366","query":"why am I tired","topN":5}
//   {"op":"feedback","user":"1503960366","id":"mem-...","kind":"helpful|not_helpful|wrong"}
//   {"op":"history","user":"1503960366","id":"mem-..."}
//
// Run with Node 22.7+: node --experimental-transform-types meterless/hmem_cli.ts
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { HMEM } from "./hmem/src/index.ts";
import type { MemoryRecord, ProvenanceOrigin } from "./hmem/src/index.ts";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const req = JSON.parse(readFileSync(0, "utf-8"));
if (!/^[A-Za-z0-9_-]{1,64}$/.test(String(req.user ?? ""))) throw new Error("user must be a plain id");
const hmem = new HMEM({
  persistDir: path.join(root, "data", "memory", String(req.user)),
  actor: "lyfe-health-checkin",
});

const view = (m: MemoryRecord) => ({
  id: m.id, content: m.content, type: m.type, layer: m.layer, confidence: m.confidence,
  source: m.source, learnedAt: new Date(m.provenance.learnedAt).toISOString(),
  origin: m.provenance.origin, tags: m.tags, supersededBy: m.supersededBy ?? null,
});

let out: unknown;
switch (req.op) {
  case "remember": {
    const m = hmem.add({
      content: req.content,
      source: req.source,
      type: req.type ?? "personal",
      layer: req.layer ?? "working",
      tags: req.tags ?? [],
      confidence: req.confidence ?? 0.8,
      provenance: {
        origin: (req.origin ?? "chat_message") as ProvenanceOrigin,
        learnedAt: Date.now(),
        label: req.label ?? req.source,
        refs: req.refs ?? [],
      },
    });
    out = view(m);
    break;
  }
  case "recall": {
    const r = hmem.query(req.query, { topN: req.topN ?? 5, threshold: req.threshold ?? 0.2 });
    out = {
      memories: r.memories.map((x) => ({ ...view(x.memory), relevance: Number(x.relevance.toFixed(3)) })),
      strategy: r.trace.strategy,
      reason: r.trace.retrievalReason,
    };
    break;
  }
  case "feedback":
    hmem.feedback(req.id, req.kind);
    out = view(hmem.store.get(req.id)!);
    break;
  case "history":
    out = hmem.ledger.history(req.id);
    break;
  default:
    throw new Error(`unknown op ${req.op}`);
}
process.stdout.write(JSON.stringify(out) + "\n");
