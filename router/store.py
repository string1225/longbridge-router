import json
import secrets
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

from cryptography.fernet import Fernet

from router.security import digest


class Store:
    def __init__(self, data_dir: Path, encryption_key: str):
        data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = data_dir / "router.sqlite3"
        self.cipher = Fernet(encryption_key.encode())
        with self.connection() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS secrets (key TEXT PRIMARY KEY, value BLOB NOT NULL);
                CREATE TABLE IF NOT EXISTS tokens (
                    id TEXT PRIMARY KEY, name TEXT NOT NULL, hash TEXT UNIQUE NOT NULL,
                    prefix TEXT NOT NULL, scopes TEXT NOT NULL, markets TEXT NOT NULL,
                    rate_limit INTEGER NOT NULL, created_at REAL NOT NULL, expires_at REAL NOT NULL,
                    revoked INTEGER NOT NULL DEFAULT 0, last_used REAL, uses INTEGER DEFAULT 0);
                CREATE TABLE IF NOT EXISTS sessions (
                    hash TEXT PRIMARY KEY, csrf TEXT NOT NULL, expires_at REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS states (
                    hash TEXT PRIMARY KEY, session_hash TEXT NOT NULL,
                    expires_at REAL NOT NULL, value BLOB NOT NULL);
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, created_at REAL NOT NULL,
                    actor TEXT NOT NULL, action TEXT NOT NULL, market TEXT, status INTEGER,
                    duration_ms INTEGER, request_id TEXT);
            """)
        self.path.chmod(0o600)

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def execute(self, sql, params=()):
        with self.connection() as db:
            return db.execute(sql, params).rowcount

    def rows(self, sql, params=()):
        with self.connection() as db:
            return [dict(row) for row in db.execute(sql, params).fetchall()]

    def encode(self, value):
        return self.cipher.encrypt(json.dumps(value).encode())

    def secret_get(self, key, default=None):
        rows = self.rows("SELECT value FROM secrets WHERE key=?", (key,))
        return json.loads(self.cipher.decrypt(rows[0]["value"])) if rows else default

    def secret_set(self, key, value):
        self.execute("INSERT OR REPLACE INTO secrets VALUES (?,?)", (key, self.encode(value)))

    def secret_delete(self, key):
        self.execute("DELETE FROM secrets WHERE key=?", (key,))

    def create_token(self, spec, revoke=None):
        raw = "lbr_" + secrets.token_urlsafe(36)
        record = {
            "id": secrets.token_hex(12),
            "name": spec["name"],
            "hash": digest(raw),
            "prefix": raw[:12],
            "scopes": json.dumps(spec["scopes"]),
            "markets": json.dumps(spec["markets"]),
            "rate_limit": spec["rate_limit"],
            "created_at": time.time(),
            "expires_at": spec["expires_at"],
        }
        with self.connection() as db:
            if revoke:
                db.execute("UPDATE tokens SET revoked=1 WHERE id=?", (revoke,))
            db.execute(
                """INSERT INTO tokens
                (id,name,hash,prefix,scopes,markets,rate_limit,created_at,expires_at)
                VALUES (:id,:name,:hash,:prefix,:scopes,:markets,:rate_limit,
                        :created_at,:expires_at)
            """,
                record,
            )
        record.pop("hash")
        record["scopes"] = spec["scopes"]
        record["markets"] = spec["markets"]
        return {**record, "token": raw}

    def tokens(self):
        result = self.rows("""SELECT id,name,prefix,scopes,markets,rate_limit,created_at,
            expires_at,revoked,last_used,uses FROM tokens ORDER BY created_at DESC""")
        for row in result:
            row["scopes"], row["markets"] = json.loads(row["scopes"]), json.loads(row["markets"])
        return result

    def authenticate(self, raw):
        rows = self.rows(
            "SELECT * FROM tokens WHERE hash=? AND revoked=0 AND expires_at>?",
            (digest(raw), time.time()),
        )
        if not rows:
            return None
        row = rows[0]
        row["scopes"], row["markets"] = json.loads(row["scopes"]), json.loads(row["markets"])
        self.execute(
            "UPDATE tokens SET last_used=?,uses=uses+1 WHERE id=?", (time.time(), row["id"])
        )
        return row

    def state_create(self, state, session_hash, value):
        self.execute("DELETE FROM states WHERE expires_at<?", (time.time(),))
        self.execute(
            "INSERT INTO states VALUES (?,?,?,?)",
            (digest(state), session_hash, time.time() + 600, self.encode(value)),
        )

    def state_consume(self, state, session_hash):
        with self.connection() as db:
            row = db.execute(
                """DELETE FROM states WHERE hash=? AND session_hash=?
                AND expires_at>? RETURNING value""",
                (digest(state), session_hash, time.time()),
            ).fetchone()
        return json.loads(self.cipher.decrypt(row[0])) if row else None

    def audit(self, actor, action, market=None, status=200, duration_ms=None, request_id=None):
        with self.connection() as db:
            cursor = db.execute(
                """INSERT INTO events
                (created_at,actor,action,market,status,duration_ms,request_id)
                VALUES (?,?,?,?,?,?,?)
            """,
                (time.time(), actor, action, market, status, duration_ms, request_id),
            )
            if cursor.lastrowid % 100 == 0:
                db.execute("DELETE FROM events WHERE id<=?", (cursor.lastrowid - 10000,))
