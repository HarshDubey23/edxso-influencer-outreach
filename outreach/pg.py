"""Postgres backend for hosted installs (DATABASE_URL set, e.g. Neon). It speaks the small slice of the sqlite3 API
the code uses, so no caller changes.

Hosts like Render wipe the local disk on every restart, so besides the tables, the JSON files the pipeline writes
(stage outputs, the campaign) are mirrored into a `files` table and written back to disk when the server starts.
"""
import os
import re
import threading
from pathlib import Path

_local = threading.local()
_schemas_done = set()


def enabled() -> bool:
    return bool(os.environ.get("DATABASE_URL"))


class Row(dict):
    """Like sqlite3.Row: row["col"], row[0] and dict(row) all work."""

    def __getitem__(self, k):
        return list(self.values())[k] if isinstance(k, int) else super().__getitem__(k)


def _rows(cursor):
    names = [c.name for c in cursor.description or []]
    return lambda values: Row(zip(names, values))


def translate(sql: str) -> str:
    sql = sql.replace("INTEGER PRIMARY KEY AUTOINCREMENT", "BIGSERIAL PRIMARY KEY")
    if "INSERT OR IGNORE INTO" in sql:
        sql = sql.replace("INSERT OR IGNORE INTO", "INSERT INTO") + " ON CONFLICT DO NOTHING"
    return sql.replace("%", "%%").replace("?", "%s")  # literal % (LIKE 'email%') must be escaped for psycopg


class _Cursor:
    def __init__(self, cur, lastrowid=None):
        self._cur, self.lastrowid, self.rowcount = cur, lastrowid, cur.rowcount

    def fetchone(self):
        return self._cur.fetchone() if self._cur.description else None

    def fetchall(self):
        return self._cur.fetchall() if self._cur.description else []

    def __iter__(self):
        return iter(self.fetchall())


class Connection:
    """One autocommit connection per thread, reopened if Neon closed it while idle."""

    def _conn(self):
        import psycopg
        c = getattr(_local, "conn", None)
        if c is None or c.closed or c.broken:
            c = _local.conn = psycopg.connect(os.environ["DATABASE_URL"], autocommit=True, row_factory=_rows,
                                              prepare_threshold=None)  # the Neon pooler (PgBouncer) can't keep prepared statements
        return c

    def execute(self, sql, params=()):
        import psycopg
        q = translate(sql)
        returning = q.lstrip().upper().startswith("INSERT INTO OUTREACH_LOG")
        q += " RETURNING id" if returning else ""
        for attempt in (1, 2):
            try:
                cur = self._conn().execute(q, tuple(params))
                break
            except psycopg.OperationalError:
                if attempt == 2:
                    raise
                _local.conn = None  # dropped connection: reconnect once
        return _Cursor(cur, cur.fetchone()[0] if returning else None)

    def executescript(self, script):
        if script in _schemas_done:
            return  # DDL once per process; it costs a network round trip per statement
        for stmt in filter(str.strip, re.sub(r"--[^\n]*", "", script).split(";")):
            self.execute(stmt)
        _schemas_done.add(script)

    def commit(self):
        pass  # autocommit

    def close(self):
        pass  # the per-thread connection is reused


FILES = "CREATE TABLE IF NOT EXISTS files (path TEXT PRIMARY KEY, content TEXT NOT NULL)"


def save_file(path: Path, root: Path) -> None:
    db = Connection()
    db.execute(FILES)
    db.execute("INSERT INTO files (path, content) VALUES (?, ?) ON CONFLICT (path) DO UPDATE SET content=excluded.content",
               (path.relative_to(root).as_posix(), path.read_text(encoding="utf-8")))


def restore_files(root: Path) -> int:
    db = Connection()
    db.execute(FILES)
    rows = db.execute("SELECT path, content FROM files").fetchall()
    for r in rows:
        p = (root / r["path"]).resolve()
        if root.resolve() in p.parents:  # only paths inside the app
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(r["content"], encoding="utf-8")
    return len(rows)
