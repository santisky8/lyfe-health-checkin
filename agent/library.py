"""Health library search: match a free-text question to MedlinePlus topics by meaning.

Embeddings come from a local model (nomic-embed-text through Ollama), so questions never
leave the computer. The index stores only doc ids and vectors; the topic text itself is read
back through Zetaris, so the library stays one of the agent's federated sources.

  python3 agent/library.py build      # embed every topic once (a few minutes on a CPU)
  python3 agent/library.py "stinging needles in the soles of my feet"
"""
import csv
import json
import math
import os
import re
import sys
import urllib.request
from pathlib import Path

import store

ROOT = Path(__file__).resolve().parent.parent
INDEX = ROOT / "data" / "clean" / "library_index.json"
TOPICS = ROOT / "data" / "clean" / "medlineplus_topics.csv"
_index = None


_cache = {}  # text -> vector; one check-in embeds its question for three steps


def embed(texts):
    """Vectors for the texts from the local embedding model, reusing ones already made."""
    missing = [t for t in dict.fromkeys(texts) if t not in _cache]
    if missing:
        base = os.environ.get("EMBED_URL", "http://localhost:11434")
        body = json.dumps({"model": os.environ.get("EMBED_MODEL", "nomic-embed-text"),
                           "input": missing}).encode()
        req = urllib.request.Request(f"{base}/api/embed", data=body,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=300) as r:
            if len(_cache) > 2000:
                _cache.clear()
            _cache.update(zip(missing, json.load(r)["embeddings"]))
    return [_cache[t] for t in texts]


def _unit(v):
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


def build(batch=32):
    with TOPICS.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    vectors = []
    for i in range(0, len(rows), batch):
        chunk = rows[i:i + batch]
        # nomic-embed-text expects task prefixes on documents and queries.
        texts = [f"search_document: {r['title']}. Also called: {r['also_called']}. "
                 f"{r['text'][:1200]}" for r in chunk]
        vectors += [_unit(v) for v in embed(texts)]
        print(f"{min(i + batch, len(rows))}/{len(rows)}", end="\r", flush=True)
    INDEX.write_text(json.dumps({"ids": [r["doc_id"] for r in rows],
                                 "titles": [r["title"] for r in rows],
                                 "vectors": [[round(x, 5) for x in v] for v in vectors]}))
    print(f"\n{INDEX.relative_to(ROOT)}: {len(rows)} topics")


def search(question, top_n=4):
    """Best-matching topics, read from Zetaris, each with its similarity score."""
    global _index
    if _index is None:
        _index = json.loads(INDEX.read_text())
    q = _unit(embed([f"search_query: {question}"])[0])
    scored = sorted(((sum(a * b for a, b in zip(q, v)), i)
                     for i, v in enumerate(_index["vectors"])), reverse=True)[:top_n]
    ids = [_index["ids"][i] for _, i in scored]
    score = {_index["ids"][i]: s for s, i in scored}
    marks = ",".join("?" * len(ids))
    rows = store.query(
        f"SELECT doc_id, title, also_called, substr(text, 1, 1000) AS text, url, source "
        f"FROM {store.table('medlineplus_topics')} WHERE doc_id IN ({marks})", tuple(ids))
    rows.sort(key=lambda r: -score[r["doc_id"]])
    for r in rows:
        r["match"] = round(score[r["doc_id"]], 3)
    return rows


def _stem(phrase):
    """Rough word roots, so "bruising" meets "Bruises" and "trauma" does not meet "traumatic"."""
    return " ".join(re.sub(r"(ing|es|s)$", "", w) for w in re.findall(r"[a-z0-9]+", phrase.lower()))


def by_name(names):
    """Topics whose title or "also called" names match a condition name, read through Zetaris.
    "Atopic dermatitis" finds Eczema (also called Atopic Dermatitis). Whole words only, so
    "trauma" does not find Post-Traumatic Stress Disorder. One topic per name."""
    found, seen = [], set()
    for name in names:
        n = _stem(name)
        if len(n) < 4:
            continue
        rows = store.query(
            f"SELECT doc_id, title, also_called, substr(text, 1, 1000) AS text, url, source "
            f"FROM {store.table('medlineplus_topics')} "
            f"WHERE lower(title) LIKE ? OR lower(also_called) LIKE ?", (f"%{n}%", f"%{n}%"))

        def rank(r):
            names_ = [_stem(r["title"])] + [_stem(a) for a in r["also_called"].split(";")]
            if n in names_:
                return 2
            return 1 if f" {n} " in f" {names_[0]} " else 0
        rows = [r for r in rows if r["doc_id"] not in seen and rank(r) > 0]
        if rows:
            best = max(rows, key=rank)
            seen.add(best["doc_id"])
            found.append(dict(best, match=1.0, about=name))
    return found


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).parent))
    if sys.argv[1:] == ["build"]:
        build()
    else:
        for r in search(" ".join(sys.argv[1:])):
            print(r["match"], r["title"], "|", r["also_called"][:60])
