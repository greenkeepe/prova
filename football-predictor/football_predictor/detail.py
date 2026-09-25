"""Assemble the "click an event, see everything" payload.

Two shapes, depending on the fixture's status:

- **Preview** (not_started): the 1X2 prediction (via predict.predict_match)
  plus head-to-head history and an Elo comparison, when covered.
- **Report** (closed/live/halftime): team statistics and the goal/card
  timeline, when covered, plus whatever prediction we stored for this
  event_id before kickoff (if any), so a played match can be compared
  against what the model said beforehand.

Every piece is independently best-effort: a source with no coverage for
this fixture (wrong league, unresolved team, no event_id because the
data came from the openfootball fallback, ...) yields None for that
piece rather than failing the whole response. Nothing here fabricates
data a source didn't actually return.
"""
from __future__ import annotations

import sqlite3

from . import predict
from .sports_client import call


def _try_call(command: str, **params):
    try:
        return call(command, **params)
    except Exception:
        return None


def match_preview(
    conn: sqlite3.Connection,
    home_id: str | None, away_id: str | None,
    home_name: str, away_name: str,
    season_id: str | None = None,
) -> dict:
    prediction = None
    if home_id and away_id:
        prediction = predict.predict_match(conn, home_id, away_id, home_name, away_name, season_id=season_id)

    head_to_head = None
    team_strength = None
    if home_id and away_id:
        h2h = _try_call("get_head_to_head", team_id=home_id, team_id_2=away_id)
        if h2h and h2h.data.get("summary", {}).get("total_meetings"):
            head_to_head = {
                "summary": h2h.data.get("summary"),
                "recent": h2h.data.get("events", [])[:5],
            }

        strength = _try_call("get_team_strength", team_id=home_id, team_id_2=away_id)
        if strength:
            teams = strength.data.get("teams", [])
            if len(teams) >= 2 and all(t.get("resolved", True) for t in teams):
                team_strength = {
                    "teams": teams,
                    "elo_difference": strength.data.get("elo_difference"),
                    "favorite": strength.data.get("favorite"),
                    "outcome_probabilities": strength.data.get("outcome_probabilities"),
                }

    return {
        "kind": "preview",
        "prediction": prediction.as_dict() if prediction else None,
        "head_to_head": head_to_head,
        "team_strength": team_strength,
    }


def match_report(conn: sqlite3.Connection, event_id: str | None) -> dict:
    statistics = None
    timeline = None
    if event_id:
        stats = _try_call("get_event_statistics", event_id=event_id)
        if stats and stats.data.get("teams"):
            statistics = stats.data["teams"]

        tl = _try_call("get_event_timeline", event_id=event_id)
        if tl and tl.data.get("timeline"):
            timeline = tl.data["timeline"]

    stored_prediction = None
    if event_id:
        row = conn.execute(
            "SELECT home_team, away_team, p_home, p_draw, p_away, model, confidence "
            "FROM predictions WHERE event_id = ? ORDER BY created_at DESC LIMIT 1",
            (event_id,),
        ).fetchone()
        if row:
            stored_prediction = dict(row)

    return {
        "kind": "report",
        "statistics": statistics,
        "timeline": timeline,
        "stored_prediction": stored_prediction,
    }
