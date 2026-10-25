"""Data layer. SQLite stand-in until the Zetaris instance is up; the agent only sends SQL,
so switching to Zetaris (JDBC/REST) changes this file and nothing else."""
import csv
import sqlite3
from pathlib import Path

CLEAN = Path(__file__).resolve().parent.parent / "data" / "clean"
DB = CLEAN.parent / "checkin.sqlite"


def build():
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


def query(sql, params=()):
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in con.execute(sql, params)]
    finally:
        con.close()


if __name__ == "__main__":
    build()
