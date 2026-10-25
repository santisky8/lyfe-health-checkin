"""Shared helpers for the source loaders. Standard library only."""
import csv
import html
import json
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CLEAN = ROOT / "data" / "clean"
RAW = ROOT / "data" / "raw"
UA = "why-checkin/0.1 (Open Agent Hackathon 2026)"

# Topics the check-in covers. Each loader pulls these from its own source.
TOPICS = [
    "sleep", "fatigue", "physical activity", "nutrition", "hydration",
    "stress", "headache", "weight", "back pain", "alcohol",
]


def get(url, params=None, retries=3):
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.read().decode("utf-8")
        except Exception:
            if attempt == retries - 1:
                raise
            time.sleep(2 ** attempt)


def get_json(url, params=None):
    return json.loads(get(url, params))


def strip_html(text):
    text = re.sub(r"<[^>]+>", " ", html.unescape(text or ""))
    return re.sub(r"\s+", " ", text).strip()


def write_csv(name, rows, fields):
    CLEAN.mkdir(parents=True, exist_ok=True)
    path = CLEAN / f"{name}.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    print(f"{path.relative_to(ROOT)}: {len(rows)} rows")
    return path
