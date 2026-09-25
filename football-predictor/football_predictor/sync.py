"""Pull real data (competitions, standings, schedules, Elo) from the
sports-skills sources and upsert it into the local SQLite database.

Every function here is a thin, honest mapping from the documented
sports-skills response shape (see the football-data skill's
references/api-reference.md) into our schema — no invented fields.
"""
from __future__ import annotations

import sqlite3

from . import db
from .sports_client import call


def sync_competition_season(conn: sqlite3.Connection, competition_id: str, season_id: str | None = None) -> str:
    """Ensure the competition + season rows exist. Returns the resolved season_id."""
    if season_id is None:
        result = call("get_current_season", competition_id=competition_id)
        season_id = result.data.get("season", {}).get("id")
        if not season_id:
            raise RuntimeError(
                f"Could not determine current season for '{competition_id}': {result.message}"
            )

    conn.execute(
        "INSERT INTO competitions (id, name) VALUES (?, ?) "
        "ON CONFLICT(id) DO NOTHING",
        (competition_id, competition_id),
    )
    conn.execute(
        "INSERT INTO seasons (id, competition_id, year) VALUES (?, ?, ?) "
        "ON CONFLICT(id) DO UPDATE SET competition_id = excluded.competition_id",
        (season_id, competition_id, season_id.split("-")[-1]),
    )
    db.log_sync(conn, "sync_competition_season", f"{competition_id} -> {season_id}")
    return season_id


def sync_standings(conn: sqlite3.Connection, season_id: str) -> int:
    """Fetch the league table for a season and upsert it. Returns row count."""
    result = call("get_season_standings", season_id=season_id)
    rows = 0
    for group in result.data.get("standings", []):
        for entry in group.get("entries", []):
            team = entry.get("team", {}) or {}
            team_id = team.get("id") or None
            team_name = team.get("name")
            if not team_name:
                continue
            if team_id:
                conn.execute(
                    "INSERT INTO teams (id, name, abbreviation, competition_id) "
                    "VALUES (?, ?, ?, (SELECT competition_id FROM seasons WHERE id = ?)) "
                    "ON CONFLICT(id) DO UPDATE SET name = excluded.name",
                    (team_id, team_name, team.get("abbreviation"), season_id),
                )
            conn.execute(
                """
                INSERT INTO standings (
                    season_id, team_id, team_name, position, played, won, drawn, lost,
                    goals_for, goals_against, goal_difference, points, synced_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                ON CONFLICT(season_id, team_name) DO UPDATE SET
                    team_id = excluded.team_id,
                    position = excluded.position,
                    played = excluded.played,
                    won = excluded.won,
                    drawn = excluded.drawn,
                    lost = excluded.lost,
                    goals_for = excluded.goals_for,
                    goals_against = excluded.goals_against,
                    goal_difference = excluded.goal_difference,
                    points = excluded.points,
                    synced_at = excluded.synced_at
                """,
                (
                    season_id, team_id, team_name, entry.get("position"),
                    entry.get("played"), entry.get("won"), entry.get("drawn"), entry.get("lost"),
                    entry.get("goals_for"), entry.get("goals_against"),
                    entry.get("goal_difference"), entry.get("points"),
                ),
            )
            rows += 1
    db.log_sync(conn, "sync_standings", f"{season_id}: {rows} rows ({result.warnings or 'ok'})")
    return rows


def sync_daily_schedule(conn: sqlite3.Connection, date: str | None = None) -> int:
    """Fetch all matches for a date (default: today) across every league."""
    result = call("get_daily_schedule", date=date)
    rows = 0
    for event in result.data.get("events", []):
        competitors = {c.get("qualifier"): c for c in event.get("competitors", [])}
        home = competitors.get("home", {}).get("team", {}) or {}
        away = competitors.get("away", {}).get("team", {}) or {}
        scores = event.get("scores", {}) or {}
        conn.execute(
            """
            INSERT INTO matches (
                event_id, competition_id, season_id, start_time, status,
                home_team_id, home_team_name, away_team_id, away_team_name,
                home_score, away_score, synced_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
            ON CONFLICT(event_id) DO UPDATE SET
                status = excluded.status,
                home_score = excluded.home_score,
                away_score = excluded.away_score,
                synced_at = excluded.synced_at
            """,
            (
                event.get("id"),
                (event.get("competition") or {}).get("id"),
                (event.get("season") or {}).get("id"),
                event.get("start_time"),
                event.get("status"),
                home.get("id"), home.get("name"),
                away.get("id"), away.get("name"),
                scores.get("home"), scores.get("away"),
            ),
        )
        rows += 1
    db.log_sync(conn, "sync_daily_schedule", f"{date or 'today'}: {rows} rows ({result.warnings or 'ok'})")
    return rows


def sync_team_strength(conn: sqlite3.Connection, team_id: str, league_slug: str | None = None) -> dict | None:
    """Fetch and store the current Elo rating for a single team."""
    result = call("get_team_strength", team_id=team_id, league_slug=league_slug)
    teams = result.data.get("teams", [])
    if not teams:
        db.log_sync(conn, "sync_team_strength", f"{team_id}: unresolved ({result.data.get('message')})")
        return None
    entry = teams[0]
    if not entry.get("resolved", True):
        db.log_sync(conn, "sync_team_strength", f"{team_id}: unresolved ({entry.get('reason')})")
        return None
    conn.execute(
        """
        INSERT INTO team_strength (team_id, as_of, elo, source, synced_at)
        VALUES (?, ?, ?, ?, datetime('now'))
        ON CONFLICT(team_id, as_of) DO UPDATE SET elo = excluded.elo, source = excluded.source
        """,
        (team_id, entry.get("as_of", "unknown"), entry.get("elo"), entry.get("source", "clubelo")),
    )
    db.log_sync(conn, "sync_team_strength", f"{team_id}: elo={entry.get('elo')}")
    return dict(entry)
