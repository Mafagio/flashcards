"""
db.py — SQLite, sans ORM (2 utilisateurs : inutile de sur-ingénierer).

Une seule connexion partagée + un verrou pour sérialiser les écritures
(SQLite = un seul writer). En lecture, WAL autorise la concurrence.
"""

from __future__ import annotations
import os, sqlite3, threading, hashlib, secrets

DB_PATH = os.getenv("DB_PATH", "/data/battle.db")

_conn: sqlite3.Connection | None = None
LOCK = threading.Lock()


def get_db() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        d = os.path.dirname(DB_PATH)
        if d:
            os.makedirs(d, exist_ok=True)
        _conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.execute("PRAGMA journal_mode=WAL;")
        _conn.execute("PRAGMA foreign_keys=ON;")
    return _conn


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT UNIQUE NOT NULL,
    pass_hash       TEXT NOT NULL,
    xp              REAL NOT NULL DEFAULT 0,
    tokens          INTEGER NOT NULL DEFAULT 0,
    xp_milestone    REAL NOT NULL DEFAULT 0,   -- record perso pour les jetons
    known_since_audit INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS cards (
    id          TEXT PRIMARY KEY,             -- ex: "m330-ch5-03"
    course      TEXT NOT NULL,                -- ex: "MATH-330"
    category    TEXT NOT NULL,                -- ex: "Ch. 5", "Série 7"
    kind        TEXT NOT NULL,                -- "cours" | "exercice"
    front       TEXT NOT NULL,                -- énoncé
    back        TEXT NOT NULL,                -- réponse de référence
    bareme_json TEXT NOT NULL,                -- barème /6 (voir README)
    difficulty  INTEGER NOT NULL DEFAULT 2    -- 1=facile 2=moyen 3=dur
);

-- Une déclaration "connue/pas connue" en mode Réviser.
CREATE TABLE IF NOT EXISTS reviews (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL REFERENCES users(id),
    card_id     TEXT NOT NULL REFERENCES cards(id),
    known       INTEGER NOT NULL,             -- 1 connue, 0 pas connue
    q           REAL,                         -- confiance déclarée (si known)
    base_points REAL NOT NULL,
    status      TEXT NOT NULL,                -- 'cleared' | 'provisional' | 'audit_pending'
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Un audit (test écrit) à passer puis noté.
CREATE TABLE IF NOT EXISTS audits (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id       INTEGER NOT NULL REFERENCES users(id),
    card_id       TEXT NOT NULL REFERENCES cards(id),
    review_id     INTEGER REFERENCES reviews(id),
    q             REAL NOT NULL,
    source        TEXT NOT NULL,              -- 'audit' | 'challenge' | 'duel'
    challenger_id INTEGER REFERENCES users(id),
    duel_id       INTEGER,
    status        TEXT NOT NULL,              -- 'pending' | 'passed' | 'failed'
    answer        TEXT,
    score         INTEGER,
    justification TEXT,
    mastery       REAL NOT NULL DEFAULT 0,
    exam_id       TEXT,                       -- si source='exam_check' : examen visé (ts_exams.id)
    created_at    TEXT NOT NULL DEFAULT (datetime('now')),
    graded_at     TEXT
);

-- Examens à note déclarée (mode Time Series). Le payload (énoncés + corrigés +
-- barèmes) reste BACKEND UNIQUEMENT (importé depuis ts_exams.json, jamais commité).
CREATE TABLE IF NOT EXISTS ts_exams (
    id          TEXT PRIMARY KEY,             -- ex: "2024", "2020", "mock1"
    title       TEXT NOT NULL,
    n_exercises INTEGER NOT NULL,
    payload_json TEXT NOT NULL                -- [{id, front, back, bareme}] par exercice
);

-- Une note d'examen déclarée par un joueur (1 par (user, exam), non modifiable).
CREATE TABLE IF NOT EXISTS ts_results (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL REFERENCES users(id),
    exam_id     TEXT NOT NULL REFERENCES ts_exams(id),
    note20      REAL NOT NULL,
    xp_awarded  REAL NOT NULL DEFAULT 0,
    status      TEXT NOT NULL,                -- 'declared' | 'verified' | 'flagged'
    declared_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(user_id, exam_id)
);

CREATE TABLE IF NOT EXISTS duels (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    challenger_id INTEGER NOT NULL REFERENCES users(id),
    opponent_id   INTEGER NOT NULL REFERENCES users(id),
    course        TEXT NOT NULL,
    n             INTEGER NOT NULL,
    status        TEXT NOT NULL,              -- 'open' | 'done'
    winner_id     INTEGER,
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS duel_cards (
    duel_id INTEGER NOT NULL REFERENCES duels(id),
    card_id TEXT NOT NULL REFERENCES cards(id),
    idx     INTEGER NOT NULL
);

-- Fil d'activité (côté social : "qui a fait quoi").
CREATE TABLE IF NOT EXISTS events (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER REFERENCES users(id),
    type       TEXT NOT NULL,
    text       TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_reviews_user ON reviews(user_id, status);
CREATE INDEX IF NOT EXISTS idx_audits_user  ON audits(user_id, status);
"""


def init_db() -> None:
    db = get_db()
    with LOCK:
        db.executescript(SCHEMA)
        _migrate(db)
        db.commit()


def _migrate(db: sqlite3.Connection) -> None:
    """Migrations idempotentes pour les bases déjà créées (ADD COLUMN ne casse rien)."""
    cols = {r["name"] for r in db.execute("PRAGMA table_info(audits)").fetchall()}
    if "exam_id" not in cols:
        db.execute("ALTER TABLE audits ADD COLUMN exam_id TEXT")


# ---- passphrases (pbkdf2, suffisant pour 2 amis derrière HTTPS) -------------

def hash_pass(pw: str, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(8)
    h = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt.encode(), 100_000).hex()
    return f"{salt}${h}"


def verify_pass(pw: str, stored: str) -> bool:
    try:
        salt, h = stored.split("$", 1)
    except ValueError:
        return False
    calc = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt.encode(), 100_000).hex()
    return secrets.compare_digest(calc, h)


def log_event(db: sqlite3.Connection, user_id: int | None, etype: str, text: str) -> None:
    db.execute(
        "INSERT INTO events(user_id, type, text) VALUES (?,?,?)",
        (user_id, etype, text),
    )
