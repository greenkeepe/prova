from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import db, predict, sync, systems
from .sports_client import SportsSkillsNotInstalled

DISCLAIMER = (
    "Le probabilita' qui sotto sono stime statistiche basate su dati storici "
    "(Elo, forma, xG dove disponibile). Non sono una garanzia di risultato: "
    "il calcio e' intrinsecamente imprevedibile e nessun modello elimina il "
    "rischio. Se scommetti, gioca solo cio' che puoi permetterti di perdere "
    "e nel rispetto delle leggi della tua giurisdizione."
)


def _print_disclaimer() -> None:
    print(f"\n[!] {DISCLAIMER}\n", file=sys.stderr)


def cmd_sync_standings(args: argparse.Namespace) -> None:
    with db.connect(args.db) as conn:
        db.init_db(conn)
        season_id = sync.sync_competition_season(conn, args.competition, args.season)
        rows = sync.sync_standings(conn, season_id)
        print(f"Synced {rows} standings rows for {season_id}")


def cmd_sync_schedule(args: argparse.Namespace) -> None:
    with db.connect(args.db) as conn:
        db.init_db(conn)
        rows = sync.sync_daily_schedule(conn, args.date)
        print(f"Synced {rows} matches for {args.date or 'today'}")


def cmd_standings(args: argparse.Namespace) -> None:
    with db.connect(args.db) as conn:
        db.init_db(conn)
        rows = conn.execute(
            "SELECT position, team_name, played, won, drawn, lost, goal_difference, points "
            "FROM standings WHERE season_id = ? ORDER BY position",
            (args.season,),
        ).fetchall()
    if not rows:
        print(f"No standings cached for {args.season}. Run 'sync-standings' first.")
        return
    print(f"{'Pos':<4}{'Team':<28}{'P':<4}{'W':<4}{'D':<4}{'L':<4}{'GD':<5}{'Pts':<4}")
    for r in rows:
        print(
            f"{r['position'] or '-':<4}{r['team_name']:<28}{r['played'] or 0:<4}"
            f"{r['won'] or 0:<4}{r['drawn'] or 0:<4}{r['lost'] or 0:<4}"
            f"{r['goal_difference'] or 0:<5}{r['points'] or 0:<4}"
        )


def cmd_predict(args: argparse.Namespace) -> None:
    with db.connect(args.db) as conn:
        db.init_db(conn)
        prediction = predict.predict_match(
            conn, args.home_id, args.away_id, args.home, args.away, season_id=args.season,
        )
        if prediction is None:
            print(
                f"No data source could produce a prediction for {args.home} vs {args.away}. "
                "Try syncing standings for their season, or check the team IDs with "
                "'sports-skills football search_team --query=\"...\"'.",
                file=sys.stderr,
            )
            sys.exit(1)

        conn.execute(
            """
            INSERT INTO predictions (event_id, home_team, away_team, match_date, p_home, p_draw, p_away, model, confidence, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
            """,
            (
                args.event_id, prediction.home_team, prediction.away_team, args.date,
                prediction.p_home, prediction.p_draw, prediction.p_away,
                prediction.model, prediction.confidence,
            ),
        )

    result = prediction.as_dict()
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(f"{prediction.home_team} vs {prediction.away_team}")
        print(f"  1 (casa)   {prediction.p_home:.1%}")
        print(f"  X (pareggio) {prediction.p_draw:.1%}")
        print(f"  2 (trasferta) {prediction.p_away:.1%}")
        print(f"  modello: {prediction.model} (confidenza: {prediction.confidence})")
        if prediction.detail:
            print(f"  dettaglio: {prediction.detail}")
    _print_disclaimer()


def _parse_picks(picks_str: str) -> list[list[str]]:
    valid = {"1", "X", "2"}
    matches = []
    for token in picks_str.split(","):
        token = token.strip().upper()
        signs = list(token)
        invalid = [s for s in signs if s not in valid]
        if invalid or not signs:
            raise ValueError(f"Invalid pick token '{token}' (use combinations of 1, X, 2)")
        matches.append(signs)
    return matches


def cmd_system(args: argparse.Namespace) -> None:
    picks = _parse_picks(args.picks)
    labels = args.labels.split(",") if args.labels else None
    if labels and len(labels) != len(picks):
        print("Error: --labels must have the same number of entries as --picks", file=sys.stderr)
        sys.exit(1)

    try:
        if args.mode == "integrale":
            result = systems.full_system(picks, match_labels=labels, stake_per_column=args.stake)
        else:
            if args.min_correct is None:
                print("Error: --min-correct is required for a sistema ridotto", file=sys.stderr)
                sys.exit(1)
            result = systems.reduced_system(
                picks, args.min_correct, match_labels=labels,
                stake_per_column=args.stake, max_scenarios=args.max_scenarios,
            )
    except (ValueError, systems.SystemTooLargeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    payload = result.as_dict()
    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        print(f"Sistema {result.kind} — {result.num_columns} colonne su {result.total_scenarios} scenari possibili")
        if result.kind == "ridotto":
            print(f"Garanzia verificata: almeno {result.guarantee}/{len(picks)} pronostici corretti "
                  f"(se il risultato reale e' tra i segni giocati per ogni partita)")
            print(f"Risparmio rispetto all'integrale: {result.savings_vs_integral:.1%}")
        print(f"Costo totale: {result.total_cost:.2f} (a {result.stake_per_column:.2f} a colonna)")
        print()
        for i, col in enumerate(result.columns, 1):
            print(f"  {i:>4}: " + " ".join(f"{lbl}={sign}" for lbl, sign in zip(result.match_labels, col)))
    _print_disclaimer()

    if args.out:
        Path(args.out).write_text(json.dumps(payload, indent=2, ensure_ascii=False))
        print(f"\nSalvato in {args.out}", file=sys.stderr)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="football-predictor", description="Statistiche calcistiche, pronostici e sistemi (uso informativo — non garantisce vincite)")
    parser.add_argument("--db", default=str(db.DEFAULT_DB_PATH), help="Percorso del database SQLite locale")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("sync-standings", help="Scarica e salva la classifica di una stagione")
    p.add_argument("--competition", required=True, help="es. premier-league, serie-a, la-liga")
    p.add_argument("--season", default=None, help="es. premier-league-2025 (default: stagione corrente)")
    p.set_defaults(func=cmd_sync_standings)

    p = sub.add_parser("sync-schedule", help="Scarica e salva le partite del giorno")
    p.add_argument("--date", default=None, help="YYYY-MM-DD (default: oggi)")
    p.set_defaults(func=cmd_sync_schedule)

    p = sub.add_parser("standings", help="Mostra la classifica salvata localmente")
    p.add_argument("--season", required=True)
    p.set_defaults(func=cmd_standings)

    p = sub.add_parser("predict", help="Stima le probabilita' 1X2 di una partita")
    p.add_argument("--home-id", required=True, help="ESPN team id squadra di casa")
    p.add_argument("--away-id", required=True, help="ESPN team id squadra ospite")
    p.add_argument("--home", required=True, help="Nome squadra di casa")
    p.add_argument("--away", required=True, help="Nome squadra ospite")
    p.add_argument("--season", default=None, help="season_id per il fallback basato sulla forma in classifica")
    p.add_argument("--event-id", default=None)
    p.add_argument("--date", default=None)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_predict)

    p = sub.add_parser("system", help="Genera un sistema integrale o ridotto")
    p.add_argument("mode", choices=["integrale", "ridotto"])
    p.add_argument("--picks", required=True, help="Segni per partita separati da virgola, es. '1X,1,12,X2,1'")
    p.add_argument("--labels", default=None, help="Nomi partita separati da virgola, stesso numero di --picks")
    p.add_argument("--min-correct", type=int, default=None, help="Richiesto per 'ridotto': minimo pronostici garantiti corretti")
    p.add_argument("--stake", type=float, default=1.0, help="Puntata per colonna")
    p.add_argument("--max-scenarios", type=int, default=systems.DEFAULT_MAX_SCENARIOS)
    p.add_argument("--json", action="store_true")
    p.add_argument("--out", default=None, help="Salva il sistema anche su file JSON")
    p.set_defaults(func=cmd_system)

    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        args.func(args)
    except SportsSkillsNotInstalled as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
