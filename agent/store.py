"""Data layer. Queries go to Zetaris (Lightning REST API) when ZETARIS_URL is set, else to a
local SQLite copy of the same tables. The agent only sends SQL, so it never knows which."""
import csv
import json
import os
import sqlite3
import urllib.request
import uuid
from pathlib import Path

import config  # noqa: F401  (loads .env.local)

CLEAN = Path(__file__).resolve().parent.parent / "data" / "clean"
DB = CLEAN.parent / "checkin.sqlite"
ZETARIS_DB = "LYFE_HEALTH_CHECKIN"
_session = {}
executed = []  # SQL sent in the current check-in, shown in the app as evidence


def backend():
    return "zetaris" if os.environ.get("ZETARIS_URL") else "sqlite"


def table(name):
    """Fully qualified table name for the active backend."""
    return f"{ZETARIS_DB}.{name}" if backend() == "zetaris" else f'"{name}"'


def _literal(value):
    if isinstance(value, (int, float)):
        return str(value)
    return "'" + str(value).replace("'", "''") + "'"


def _inline(sql, params):
    # The REST API takes plain SQL, so parameters are inlined as quoted literals.
    parts = sql.split("?")
    if len(parts) - 1 != len(params):
        raise ValueError("parameter count does not match placeholders")
    out = parts[0]
    for value, rest in zip(params, parts[1:]):
        out += _literal(value) + rest
    return out


def _post(path, body, headers=None):
    req = urllib.request.Request(
        os.environ["ZETARIS_URL"].rstrip("/") + path, data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", **(headers or {})})
    with urllib.request.urlopen(req, timeout=180) as r:
        return json.load(r)


def _zetaris(sql, retry=True):
    if not _session:
        login = _post("/api/auth/login", {"username": os.environ["ZETARIS_EMAIL"],
                                          "password": os.environ["ZETARIS_PASSWORD"]})
        _session.update(token=login["idToken"], org=str(login["orgId"]))
    headers = {"Authorization": f"Bearer {_session['token']}", "X-Org-ID": _session["org"],
               "X-Request-ID": str(uuid.uuid4())}
    try:
        rows = _post("/api/proxy/query/sql/start", {"select": sql, "pageLimit": 200},
                     headers)["records"]
        # Empty CSV cells come back as null; the SQLite path returns "", so match it.
        return [{k: ("" if v is None else v) for k, v in r.items()} for r in rows]
    except urllib.error.HTTPError as e:
        # An expired token comes back as 400 or 401 from Lightning: log in again once.
        if e.code in (400, 401, 403) and retry:
            _session.clear()
            return _zetaris(sql, retry=False)
        raise


def query(sql, params=()):
    executed.append(_inline(sql, params))
    if backend() == "zetaris":
        return _zetaris(_inline(sql, params))
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in con.execute(sql, params)]
    finally:
        con.close()


def build():
    """Build the local SQLite copy (offline fallback). Zetaris tables: see zetaris/load.sql."""
    con = sqlite3.connect(DB)
    for path in sorted(CLEAN.glob("*.csv")):
        with path.open(encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        if not rows:
            continue
        cols = list(rows[0])
        con.execute(f'DROP TABLE IF EXISTS "{path.stem}"')
        con.execute(f'CREATE TABLE "{path.stem}" ({", ".join(f"{c!r}" for c in cols)})')
        con.executemany(f'INSERT INTO "{path.stem}" VALUES ({", ".join("?" * len(cols))})',
                        [[r[c] for c in cols] for r in rows])
        print(f"{path.stem}: {len(rows)} rows")
    con.commit()
    con.close()


if __name__ == "__main__":
    build()
