"""SQLite persistence for competitions, teams, matches, standings and
computed predictions. One flat file, no ORM — the schema is small enough
that raw SQL stays readable.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path

DEFAULT_DB_PATH = Path.home() / ".football-predictor" / "football.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS competitions (
    id   TEXT PRIMARY KEY,
    name TEXT
);

CREATE TABLE IF NOT EXISTS seasons (
    id             TEXT PRIMARY KEY,
    competition_id TEXT NOT NULL,
    year           TEXT,
    name           TEXT,
    start_date     TEXT,
    end_date       TEXT,
    FOREIGN KEY (competition_id) REFERENCES competitions(id)
);

CREATE TABLE IF NOT EXISTS teams (
    id             TEXT PRIMARY KEY,
    name           TEXT NOT NULL,
    abbreviation   TEXT,
    competition_id TEXT
);

CREATE TABLE IF NOT EXISTS standings (
    season_id       TEXT NOT NULL,
    team_id         TEXT,
    team_name       TEXT NOT NULL,
    position        INTEGER,
    played          INTEGER,
    won             INTEGER,
    drawn           INTEGER,
    lost            INTEGER,
    goals_for       INTEGER,
    goals_against   INTEGER,
    goal_difference INTEGER,
    points          INTEGER,
    synced_at       TEXT NOT NULL,
    PRIMARY KEY (season_id, team_name)
);

CREATE TABLE IF NOT EXISTS matches (
    event_id       TEXT PRIMARY KEY,
    competition_id TEXT,
    season_id      TEXT,
    start_time     TEXT,
    status         TEXT,
    home_team_id   TEXT,
    home_team_name TEXT,
    away_team_id   TEXT,
    away_team_name TEXT,
    home_score     INTEGER,
    away_score     INTEGER,
    synced_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS team_strength (
    team_id   TEXT NOT NULL,
    as_of     TEXT NOT NULL,
    elo       REAL,
    source    TEXT,
    synced_at TEXT NOT NULL,
    PRIMARY KEY (team_id, as_of)
);

CREATE TABLE IF NOT EXISTS predictions (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id     TEXT,
    home_team    TEXT NOT NULL,
    away_team    TEXT NOT NULL,
    match_date   TEXT,
    p_home       REAL NOT NULL,
    p_draw       REAL NOT NULL,
    p_away       REAL NOT NULL,
    model        TEXT NOT NULL,
    confidence   TEXT NOT NULL,
    created_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sync_log (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    ts      TEXT NOT NULL,
    action  TEXT NOT NULL,
    detail  TEXT
);
"""


@contextmanager
def connect(db_path: Path | str = DEFAULT_DB_PATH):
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)


def log_sync(conn: sqlite3.Connection, action: str, detail: str = "") -> None:
    conn.execute(
        "INSERT INTO sync_log (ts, action, detail) VALUES (datetime('now'), ?, ?)",
        (action, detail),
    )
