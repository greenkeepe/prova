"""Local web dashboard on top of the football_predictor engine.

Same three capabilities as the CLI (classifica / pronostico / sistemi),
exposed as a small JSON API plus a single-page frontend. No new business
logic lives here — every route is a thin wrapper around db/sync/predict/
systems so the two interfaces can never drift apart.
"""
from __future__ import annotations

import os

from flask import Flask, jsonify, render_template, request

from .. import db, detail, predict, systems, sync
from ..sports_client import SportsSkillsError, SportsSkillsNotInstalled

DISCLAIMER = (
    "Le probabilita' sono stime statistiche, non garanzie di risultato. "
    "Gioca responsabilmente e solo cio' che puoi permetterti di perdere."
)

# The full slug list from references/api-reference.md "Supported Leagues".
# Exposed as a dropdown so the UI can never send a typo'd competition_id
# (the "serie a" vs "serie-a" class of bug) the way a free-text field can.
KNOWN_COMPETITIONS = [
    {"id": "premier-league", "name": "Premier League"},
    {"id": "la-liga", "name": "La Liga"},
    {"id": "bundesliga", "name": "Bundesliga"},
    {"id": "serie-a", "name": "Serie A"},
    {"id": "ligue-1", "name": "Ligue 1"},
    {"id": "mls", "name": "MLS"},
    {"id": "championship", "name": "Championship"},
    {"id": "eredivisie", "name": "Eredivisie"},
    {"id": "primeira-liga", "name": "Primeira Liga"},
    {"id": "serie-a-brazil", "name": "Serie A Brazil"},
    {"id": "champions-league", "name": "Champions League"},
    {"id": "european-championship", "name": "European Championship"},
    {"id": "world-cup", "name": "World Cup"},
]
COMPETITION_NAMES = {c["id"]: c["name"] for c in KNOWN_COMPETITIONS}


def create_app(db_path: str | None = None) -> Flask:
    app = Flask(__name__)
    app.config["DB_PATH"] = db_path or str(db.DEFAULT_DB_PATH)

    def get_conn():
        conn_ctx = db.connect(app.config["DB_PATH"])
        return conn_ctx

    @app.errorhandler(Exception)
    def handle_unexpected_error(exc):
        # Flask's default unhandled-exception page is HTML, which our
        # frontend can't parse - it would just show a bare "Errore 500"
        # with no explanation. Always answer JSON instead so the real
        # cause reaches the UI.
        app.logger.exception("Unhandled error in %s", request.path)
        return jsonify({"error": str(exc) or exc.__class__.__name__}), 500

    @app.route("/")
    def index():
        return render_template("index.html", disclaimer=DISCLAIMER, competitions=KNOWN_COMPETITIONS)

    @app.route("/api/competitions")
    def api_competitions():
        return jsonify(KNOWN_COMPETITIONS)

    @app.route("/api/schedule")
    def api_schedule():
        date = request.args.get("date") or None
        try:
            with get_conn() as conn:
                db.init_db(conn)
                events = sync.sync_daily_schedule(conn, date)
        except SportsSkillsNotInstalled as exc:
            return jsonify({"error": str(exc)}), 500
        except SportsSkillsError as exc:
            return jsonify({"error": f"fonte dati non raggiungibile: {exc}"}), 502

        events.sort(key=lambda e: e.get("start_time") or "")
        for event in events:
            event["competition_name"] = COMPETITION_NAMES.get(
                event.get("competition_id"), event.get("competition_id")
            )
        return jsonify(events)

    @app.route("/api/events")
    def api_events():
        competition = request.args.get("competition", "").strip()
        season = request.args.get("season", "").strip() or None
        if not competition:
            return jsonify({"error": "parametro 'competition' richiesto"}), 400
        try:
            with get_conn() as conn:
                db.init_db(conn)
                season_id = sync.sync_competition_season(conn, competition, season)
                events = sync.fetch_season_schedule(season_id)
        except SportsSkillsNotInstalled as exc:
            return jsonify({"error": str(exc)}), 500
        except SportsSkillsError as exc:
            return jsonify({"error": f"fonte dati non raggiungibile: {exc}"}), 502
        except RuntimeError as exc:
            return jsonify({"error": str(exc)}), 400

        events.sort(key=lambda e: e.get("start_time") or "")
        return jsonify({"season_id": season_id, "events": events})

    @app.route("/api/event-detail", methods=["POST"])
    def api_event_detail():
        payload = request.get_json(force=True, silent=True) or {}
        status = payload.get("status")
        with get_conn() as conn:
            db.init_db(conn)
            if status in ("closed", "live", "halftime"):
                result = detail.match_report(conn, payload.get("event_id"))
            else:
                home_id = payload.get("home_id") or None
                away_id = payload.get("away_id") or None
                result = detail.match_preview(
                    conn, home_id, away_id,
                    str(payload.get("home_name") or ""), str(payload.get("away_name") or ""),
                    season_id=payload.get("season_id"),
                )
                prediction = result.get("prediction")
                if prediction:
                    conn.execute(
                        "INSERT INTO predictions (event_id, home_team, away_team, match_date, "
                        "p_home, p_draw, p_away, model, confidence, created_at) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))",
                        (
                            payload.get("event_id"), prediction["home_team"], prediction["away_team"],
                            payload.get("start_time"), prediction["p_home"], prediction["p_draw"],
                            prediction["p_away"], prediction["model"], prediction["confidence"],
                        ),
                    )
        return jsonify(result)

    @app.route("/api/standings")
    def api_standings():
        season = request.args.get("season", "").strip()
        if not season:
            return jsonify({"error": "parametro 'season' richiesto"}), 400
        with get_conn() as conn:
            db.init_db(conn)
            rows = conn.execute(
                "SELECT position, team_name, played, won, drawn, lost, "
                "goal_difference, points FROM standings WHERE season_id = ? "
                "ORDER BY position",
                (season,),
            ).fetchall()
        return jsonify([dict(r) for r in rows])

    @app.route("/api/sync/standings", methods=["POST"])
    def api_sync_standings():
        payload = request.get_json(force=True, silent=True) or {}
        competition = (payload.get("competition") or "").strip()
        season = (payload.get("season") or "").strip() or None
        if not competition:
            return jsonify({"error": "campo 'competition' richiesto"}), 400
        try:
            with get_conn() as conn:
                db.init_db(conn)
                season_id = sync.sync_competition_season(conn, competition, season)
                rows = sync.sync_standings(conn, season_id)
        except SportsSkillsNotInstalled as exc:
            return jsonify({"error": str(exc)}), 500
        except SportsSkillsError as exc:
            return jsonify({"error": f"fonte dati non raggiungibile: {exc}"}), 502
        except RuntimeError as exc:
            # e.g. an unknown/mistyped competition slug - a client input
            # problem, not a server fault.
            return jsonify({"error": str(exc)}), 400
        return jsonify({"season_id": season_id, "rows": rows})

    @app.route("/api/predict", methods=["POST"])
    def api_predict():
        payload = request.get_json(force=True, silent=True) or {}
        required = ["home_id", "away_id", "home", "away"]
        missing = [k for k in required if not str(payload.get(k, "")).strip()]
        if missing:
            return jsonify({"error": f"campi mancanti: {', '.join(missing)}"}), 400

        try:
            with get_conn() as conn:
                db.init_db(conn)
                prediction = predict.predict_match(
                    conn,
                    str(payload["home_id"]), str(payload["away_id"]),
                    str(payload["home"]), str(payload["away"]),
                    season_id=payload.get("season") or None,
                )
                if prediction is not None:
                    conn.execute(
                        "INSERT INTO predictions (event_id, home_team, away_team, match_date, "
                        "p_home, p_draw, p_away, model, confidence, created_at) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))",
                        (
                            payload.get("event_id"), prediction.home_team, prediction.away_team,
                            payload.get("date"), prediction.p_home, prediction.p_draw,
                            prediction.p_away, prediction.model, prediction.confidence,
                        ),
                    )
        except SportsSkillsNotInstalled as exc:
            return jsonify({"error": str(exc)}), 500

        if prediction is None:
            return jsonify({
                "error": "Nessuna fonte disponibile per questa partita. "
                         "Prova a sincronizzare la classifica della stagione, o verifica gli ID squadra."
            }), 404
        return jsonify(prediction.as_dict())

    @app.route("/api/system", methods=["POST"])
    def api_system():
        payload = request.get_json(force=True, silent=True) or {}
        try:
            raw_picks = payload.get("picks") or []
            picks = [list(str(p).strip().upper()) for p in raw_picks]
            labels = payload.get("labels") or None
            stake = float(payload.get("stake", 1.0))
            mode = payload.get("mode", "integrale")

            if mode == "integrale":
                result = systems.full_system(picks, match_labels=labels, stake_per_column=stake)
            elif mode == "ridotto":
                min_correct = int(payload["min_correct"])
                max_scenarios = int(payload.get("max_scenarios", systems.DEFAULT_MAX_SCENARIOS))
                result = systems.reduced_system(
                    picks, min_correct, match_labels=labels,
                    stake_per_column=stake, max_scenarios=max_scenarios,
                )
            else:
                return jsonify({"error": f"mode sconosciuto: {mode}"}), 400
        except (ValueError, KeyError, systems.SystemTooLargeError) as exc:
            return jsonify({"error": str(exc)}), 400

        return jsonify(result.as_dict())

    @app.route("/api/health")
    def api_health():
        return jsonify({"status": "ok"})

    return app


def main() -> None:
    host = os.environ.get("FOOTBALL_PREDICTOR_HOST", "127.0.0.1")
    port = int(os.environ.get("FOOTBALL_PREDICTOR_PORT", "5000"))
    debug = os.environ.get("FOOTBALL_PREDICTOR_DEBUG", "") == "1"
    app = create_app()
    app.run(host=host, port=port, debug=debug)


if __name__ == "__main__":
    main()
