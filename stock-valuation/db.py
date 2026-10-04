"""Saved valuations. Uses Postgres when DATABASE_URL is set (needed on hosts
with a wiped disk, e.g. Render's free plan), otherwise a local SQLite file."""

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
SQLITE_PATH = os.environ.get("SQLITE_PATH", str(Path(__file__).parent / "valuations.db"))
IS_POSTGRES = DATABASE_URL.startswith(("postgres://", "postgresql://"))

SUMMARY_COLUMNS = ["id", "created_at", "ticker", "name", "currency", "price",
                   "fair_value", "buy_price", "signal", "method", "note", "models"]


@contextmanager
def connect():
    if IS_POSTGRES:
        import psycopg

        conn = psycopg.connect(DATABASE_URL)
    else:
        conn = sqlite3.connect(SQLITE_PATH)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _sql(query):
    """Queries are written with %s placeholders; SQLite wants ?."""
    return query if IS_POSTGRES else query.replace("%s", "?")


def init():
    pk = "SERIAL PRIMARY KEY" if IS_POSTGRES else "INTEGER PRIMARY KEY AUTOINCREMENT"
    with connect() as conn:
        conn.execute(f"""
            CREATE TABLE IF NOT EXISTS valuations (
                id {pk},
                created_at TEXT NOT NULL,
                ticker TEXT NOT NULL,
                name TEXT,
                currency TEXT,
                price DOUBLE PRECISION,
                fair_value DOUBLE PRECISION,
                buy_price DOUBLE PRECISION,
                signal TEXT,
                method TEXT,
                note TEXT,
                models TEXT,
                inputs TEXT,
                data TEXT
            )""")


def save(v):
    row = (datetime.now(timezone.utc).isoformat(timespec="seconds"), v["ticker"].upper(),
           v.get("name"), v.get("currency"), v.get("price"), v.get("fairValue"), v.get("buyPrice"),
           v.get("signal"), v.get("method"), v.get("note"),
           json.dumps(v.get("models") or {}), json.dumps(v.get("inputs") or {}), json.dumps(v.get("data") or {}))
    q = """INSERT INTO valuations (created_at, ticker, name, currency, price, fair_value, buy_price,
           signal, method, note, models, inputs, data) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)"""
    with connect() as conn:
        if IS_POSTGRES:
            return conn.execute(q + " RETURNING id", row).fetchone()[0]
        return conn.execute(_sql(q), row).lastrowid


def _summary(r):
    d = dict(zip(SUMMARY_COLUMNS, r))
    d["models"] = json.loads(d["models"] or "{}")
    return d


def list_all():
    with connect() as conn:
        rows = conn.execute(f"SELECT {', '.join(SUMMARY_COLUMNS)} FROM valuations ORDER BY id DESC").fetchall()
    return [_summary(r) for r in rows]


def get(vid):
    with connect() as conn:
        r = conn.execute(_sql(f"SELECT {', '.join(SUMMARY_COLUMNS)}, inputs, data FROM valuations WHERE id = %s"),
                         (vid,)).fetchone()
    if not r:
        return None
    d = _summary(r[:-2])
    d["inputs"] = json.loads(r[-2] or "{}")
    d["data"] = json.loads(r[-1] or "{}")
    return d


def delete(vid):
    with connect() as conn:
        cur = conn.execute(_sql("DELETE FROM valuations WHERE id = %s"), (vid,))
        return cur.rowcount > 0


def storage_info():
    if IS_POSTGRES:
        return {"kind": "postgres", "persistent": True}
    # Render sets RENDER=true; its free-plan disk is wiped on every restart.
    return {"kind": "sqlite", "persistent": os.environ.get("RENDER") != "true"}
