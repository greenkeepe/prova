"""1X2 probability estimation for a fixture.

Data sources are tried in order of how much they're actually worth
trusting, and the model/confidence used is always returned alongside the
numbers so nothing pretends to be more certain than it is:

1. ClubElo's own match forecast (`get_match_forecast`) — a real forecast
   for fixtures within ~a week, confidence "high".
2. ClubElo Elo-gap empirical outcome probabilities, when the local-Elo
   fallback resolves both teams to the same division
   (`get_team_strength` -> `outcome_probabilities`) — read off real
   division history for that Elo gap, confidence "medium".
3. A logistic-Elo + Gaussian-draw heuristic applied to a raw Elo
   difference — a standard approximation, not a calibrated model,
   confidence "low".
4. Recent league-table form (points per game) turned into a synthetic
   Elo-like gap and run through the same heuristic — used only when no
   Elo data exists at all (e.g. non-European clubs), confidence
   "very_low".

Nothing here invents a result. If none of the sources return anything,
`predict_match` returns None and callers must say so rather than guess.
"""
from __future__ import annotations

import math
import sqlite3
from dataclasses import dataclass

from .sports_client import call

HOME_ADVANTAGE_ELO = 65.0
DRAW_PEAK_PROB = 0.28
DRAW_SIGMA = 200.0


@dataclass
class Prediction:
    home_team: str
    away_team: str
    p_home: float
    p_draw: float
    p_away: float
    model: str
    confidence: str
    detail: str = ""

    def as_dict(self) -> dict:
        return {
            "home_team": self.home_team,
            "away_team": self.away_team,
            "p_home": round(self.p_home, 4),
            "p_draw": round(self.p_draw, 4),
            "p_away": round(self.p_away, 4),
            "model": self.model,
            "confidence": self.confidence,
            "detail": self.detail,
        }


def elo_diff_to_1x2(elo_diff: float) -> tuple[float, float, float]:
    """Logistic-Elo win expectancy + Gaussian draw heuristic.

    elo_diff is home_elo - away_elo, home advantage already folded in by
    the caller if applicable. Returns (p_home, p_draw, p_away) summing to 1.
    This is a documented approximation (see module docstring), not a fit
    against real results — treat its output as directional, not precise.
    """
    expected_points_share = 1.0 / (10 ** (-elo_diff / 400.0) + 1.0)
    p_draw = DRAW_PEAK_PROB * math.exp(-(elo_diff ** 2) / (2 * DRAW_SIGMA ** 2))
    win_minus_loss = 2 * expected_points_share - 1
    p_home = ((1 - p_draw) + win_minus_loss) / 2
    p_away = ((1 - p_draw) - win_minus_loss) / 2

    # Numerical safety: clip and renormalize rather than trust the algebra
    # at extreme elo_diff values.
    p_home, p_draw, p_away = (max(0.0, p) for p in (p_home, p_draw, p_away))
    total = p_home + p_draw + p_away
    if total == 0:
        return (1 / 3, 1 / 3, 1 / 3)
    return (p_home / total, p_draw / total, p_away / total)


def _from_match_forecast(home_id: str, away_id: str, home_name: str, away_name: str) -> Prediction | None:
    result = call("get_match_forecast", team_id=home_id, team_id_2=away_id)
    for fixture in result.data.get("fixtures", []):
        # team_id was passed as the home side, so these probs are from
        # the home team's perspective already.
        p_win = fixture.get("win_prob")
        p_draw = fixture.get("draw_prob")
        p_loss = fixture.get("loss_prob")
        if None in (p_win, p_draw, p_loss):
            continue
        return Prediction(
            home_team=home_name, away_team=away_name,
            p_home=p_win, p_draw=p_draw, p_away=p_loss,
            model="clubelo_forecast", confidence="high",
            detail=f"ClubElo forecast for {fixture.get('date', 'upcoming fixture')}",
        )
    return None


def _from_team_strength(home_id: str, away_id: str, home_name: str, away_name: str) -> Prediction | None:
    result = call("get_team_strength", team_id=home_id, team_id_2=away_id)
    teams = result.data.get("teams", [])
    if len(teams) < 2 or not all(t.get("resolved", True) for t in teams):
        return None

    outcome_probs = result.data.get("outcome_probabilities")
    if outcome_probs:
        sample = outcome_probs.get("sample")
        return Prediction(
            home_team=home_name, away_team=away_name,
            p_home=outcome_probs["home"], p_draw=outcome_probs["draw"], p_away=outcome_probs["away"],
            model="clubelo_elo_empirical", confidence="medium",
            detail=f"Empirical outcome rate for this Elo gap (sample={sample})",
        )

    elo_diff = result.data.get("elo_difference")
    if elo_diff is None:
        return None
    p_home, p_draw, p_away = elo_diff_to_1x2(elo_diff + HOME_ADVANTAGE_ELO)
    return Prediction(
        home_team=home_name, away_team=away_name,
        p_home=p_home, p_draw=p_draw, p_away=p_away,
        model="elo_heuristic", confidence="low",
        detail=f"Logistic-Elo heuristic, elo_difference={elo_diff} + home adv {HOME_ADVANTAGE_ELO}",
    )


def _from_form(conn: sqlite3.Connection, season_id: str, home_name: str, away_name: str) -> Prediction | None:
    rows = conn.execute(
        "SELECT team_name, played, points FROM standings WHERE season_id = ? AND team_name IN (?, ?)",
        (season_id, home_name, away_name),
    ).fetchall()
    by_name = {r["team_name"]: r for r in rows}
    home_row, away_row = by_name.get(home_name), by_name.get(away_name)
    if not home_row or not away_row or not home_row["played"] or not away_row["played"]:
        return None

    home_ppg = home_row["points"] / home_row["played"]
    away_ppg = away_row["points"] / away_row["played"]
    # Map a points-per-game gap onto a synthetic Elo-like difference.
    # 1 ppg of separation is treated as roughly a 200-point Elo gap - a
    # rough calibration, not a fitted constant. Confidence is marked
    # "very_low" precisely because of that.
    synthetic_elo_diff = (home_ppg - away_ppg) * 200.0 + HOME_ADVANTAGE_ELO
    p_home, p_draw, p_away = elo_diff_to_1x2(synthetic_elo_diff)
    return Prediction(
        home_team=home_name, away_team=away_name,
        p_home=p_home, p_draw=p_draw, p_away=p_away,
        model="form_heuristic", confidence="very_low",
        detail=f"PPG gap {home_ppg:.2f} vs {away_ppg:.2f}, no Elo data available",
    )


def predict_match(
    conn: sqlite3.Connection,
    home_id: str,
    away_id: str,
    home_name: str,
    away_name: str,
    season_id: str | None = None,
) -> Prediction | None:
    """Best-effort 1X2 prediction, trying sources from most to least trustworthy."""
    for source in (
        lambda: _from_match_forecast(home_id, away_id, home_name, away_name),
        lambda: _from_team_strength(home_id, away_id, home_name, away_name),
    ):
        try:
            prediction = source()
        except Exception:
            prediction = None
        if prediction is not None:
            return prediction

    if season_id is not None:
        try:
            return _from_form(conn, season_id, home_name, away_name)
        except Exception:
            return None
    return None
