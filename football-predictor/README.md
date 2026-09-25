# football-predictor

CLI Python che usa dati calcistici reali (classifiche, partite, gol, Elo,
xG dove disponibile) per stimare le probabilità 1X2 di una partita e
generare sistemi multipli (integrale / ridotto) in stile Totocalcio.

> **Avviso.** Le probabilità prodotte sono stime statistiche, non
> previsioni certe: nessun modello elimina l'imprevedibilità del calcio.
> Lo strumento è pensato per uso informativo/personale. Se lo usi per
> scommettere, gioca in modo responsabile, solo ciò che puoi permetterti
> di perdere, e nel rispetto delle leggi della tua giurisdizione.

## Setup

```bash
cd football-predictor
pip install -e .          # oppure: pip install -r requirements.txt
```

Richiede Python 3.10+ e la CLI [`sports-skills`](https://github.com/machina-sports/sports-skills)
(installata automaticamente come dipendenza), che recupera i dati reali
da ESPN, ClubElo, Understat, FPL, Transfermarkt e football-data.co.uk —
nessuna API key richiesta.

## Da dove vengono i dati

Tutte le fonti sono quelle documentate dallo skill `football-data`
(`.claude/skills/football-data/references/api-reference.md`): ESPN è
l'autorità per punteggi/classifiche su tutti i 13 campionati coperti;
ClubElo fornisce Elo e previsioni per i club europei; Understat l'xG per
le top-5 leghe; football-data.co.uk lo storico head-to-head. Copertura
non uniforme tra campionati — vedi quel file per i dettagli.

## Comandi

### Sincronizzare i dati

```bash
football-predictor sync-standings --competition premier-league
football-predictor sync-standings --competition serie-a --season serie-a-2025
football-predictor sync-schedule --date 2026-09-27
football-predictor standings --season premier-league-2026
```

I dati vengono salvati in un DB SQLite locale (default
`~/.football-predictor/football.db`, override con `--db`).

### Pronostico di una partita

```bash
football-predictor predict \
  --home-id 359 --away-id 363 \
  --home "Arsenal" --away "Chelsea" \
  --season premier-league-2026
```

Trova gli ID squadra ESPN con:
```bash
sports-skills football search_team --query="Arsenal"
```

Il comando prova le fonti in ordine di affidabilità e riporta sempre
quale modello ha usato:

1. **`clubelo_forecast`** (confidenza *high*) — previsione ClubElo per
   partite entro ~una settimana.
2. **`clubelo_elo_empirical`** (confidenza *medium*) — tasso di 1/X/2
   osservato storicamente per quel divario Elo, quando disponibile.
3. **`elo_heuristic`** (confidenza *low*) — euristica logistica-Elo +
   pareggio gaussiano applicata al divario Elo grezzo. È
   un'approssimazione standard, non un modello calibrato sui risultati
   reali.
4. **`form_heuristic`** (confidenza *very_low*) — usata solo quando non
   esiste alcun dato Elo (es. club extra-europei): converte il divario
   di punti-a-partita in classifica in un Elo sintetico.

Se nessuna fonte produce un risultato, il comando fallisce esplicitamente
invece di indovinare.

### Sistemi (integrale / ridotto)

```bash
# Sistema integrale: tutte le combinazioni dei segni scelti
football-predictor system integrale --picks "1X,1,12,X2,1" --stake 1

# Sistema ridotto: meno colonne, garanzia minima verificata
football-predictor system ridotto --picks "1X,12,1X,12,1X" --min-correct 4 --stake 2
```

- `--picks`: segni per partita separati da virgola, es. `1X` = giochi 1
  e X su quella partita, `12` = doppia chance 1 e 2.
- `--min-correct` (solo `ridotto`): minimo di pronostici corretti che il
  sistema deve garantire.

**Come funziona la garanzia.** Un sistema può garantire qualcosa solo
sugli scenari in cui il risultato reale è tra i segni che hai giocato su
ogni partita — questo vale per qualunque sistema, non solo per il
nostro. Non avendo accesso alle tabelle combinatorie ufficiali (es.
SNAI) per i sistemi ridotti, questo tool **costruisce** una riduzione con
un algoritmo greedy di set-cover e poi **verifica esaustivamente** — per
ogni singolo scenario possibile — che almeno una colonna giocata
raggiunga la soglia `--min-correct`. Il numero di colonne può quindi
essere più alto di una tabella ufficiale ottimale per la stessa garanzia,
ma la garanzia stessa è dimostrata per costruzione, non presunta.

Per motivi di performance, la generazione di un sistema ridotto è
limitata a 20.000 scenari totali (`--max-scenarios` per alzare il
limite, a costo di tempo di calcolo maggiore: l'algoritmo è O(round ×
scenari²)).

## Dashboard web

Stessa logica della CLI, esposta come piccola dashboard locale (schede
Classifica / Pronostico / Sistemi) su Flask, senza build step.

```bash
pip install -e ".[web]"     # oppure: pip install -r requirements.txt
football-predictor-web
```

Apri `http://127.0.0.1:5000`. Variabili d'ambiente opzionali:

```bash
FOOTBALL_PREDICTOR_HOST=0.0.0.0   # per ascoltare su tutte le interfacce
FOOTBALL_PREDICTOR_PORT=8080
FOOTBALL_PREDICTOR_DEBUG=1         # reload automatico durante lo sviluppo
```

La dashboard usa lo stesso DB SQLite e le stesse funzioni della CLI
(`db.py`, `sync.py`, `predict.py`, `systems.py`) tramite una API JSON
sottile in `football_predictor/web/app.py` — nessuna logica duplicata.

**Nota sull'esposizione online.** Di default il server ascolta solo su
`127.0.0.1` (accessibile solo dalla stessa macchina). Per renderlo
raggiungibile da altri dispositivi sulla tua rete, avvialo con
`FOOTBALL_PREDICTOR_HOST=0.0.0.0`. Per pubblicarlo su un URL pubblico su
internet serve un hosting (Render, Fly.io, un VPS, ecc.) — il server
Flask integrato (`app.run(...)`) è pensato per uso locale/di sviluppo:
per un vero deploy pubblico va messo dietro un server WSGI di produzione
(es. gunicorn) e un hosting a tua scelta.

## Test

```bash
pip install pytest
python -m pytest tests/
```

I test coprono la matematica del modello di probabilità e la
combinatoria dei sistemi (nessuna chiamata di rete). La sincronizzazione
dati (`sync-*`) richiede accesso reale a internet verso le fonti sopra
elencate.

## Struttura

```
football_predictor/
  sports_client.py   wrapper subprocess attorno alla CLI sports-skills
  db.py               schema e connessione SQLite
  sync.py             fetch dati reali -> upsert nel DB
  predict.py          stima probabilità 1X2 (cascata di fonti)
  systems.py          generatore sistemi integrale/ridotto + verifica
  cli.py              comandi da terminale
  web/
    app.py            API Flask (thin wrapper sulle stesse funzioni)
    templates/index.html
    static/style.css, app.js
tests/
  test_predict.py
  test_systems.py
```
