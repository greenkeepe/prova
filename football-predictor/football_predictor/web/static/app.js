// Vanilla JS — tab switching + fetch calls to the /api/* endpoints.
// No build step, no framework: this is a small local dashboard, not a SPA.

const AUTO_PREDICT_LIMIT = 15; // cap on how many not-started fixtures get an automatic prediction

// Mirrors KNOWN_COMPETITIONS in web/app.py. Used only to prioritize which
// fixtures get an automatic prediction first: a busy day's schedule spans
// every league ESPN carries (down to obscure regional friendlies), most of
// which no data source here covers at all (ClubElo is European clubs only,
// and we only have standings for leagues someone has synced). Without this,
// the chronologically-first matches - often exactly those uncovered minor
// fixtures - would eat the whole auto-predict budget on real games.
const PRIORITY_COMPETITION_IDS = new Set([
  "premier-league", "la-liga", "bundesliga", "serie-a", "ligue-1", "mls",
  "championship", "eredivisie", "primeira-liga", "serie-a-brazil",
  "champions-league", "european-championship", "world-cup",
]);

function switchTab(name) {
  document.querySelectorAll(".tab").forEach(t => {
    const active = t.dataset.tab === name;
    t.classList.toggle("is-active", active);
    t.setAttribute("aria-selected", active ? "true" : "false");
  });
  document.querySelectorAll(".panel").forEach(p => {
    p.classList.toggle("is-active", p.id === `panel-${name}`);
  });
}

document.querySelectorAll(".tab").forEach(tab => {
  tab.addEventListener("click", () => switchTab(tab.dataset.tab));
});

async function postJSON(url, body) {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(data.error || `Errore ${res.status}`);
  }
  return data;
}

async function getJSON(url) {
  const res = await fetch(url);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(data.error || `Errore ${res.status}`);
  }
  return data;
}

function renderStandingsTable(container, rows) {
  if (!rows.length) {
    container.innerHTML = `<p class="hint">Nessun dato per questa stagione. Sincronizza prima.</p>`;
    return;
  }
  const body = rows.map(r => `
    <tr>
      <td>${r.position ?? "-"}</td>
      <td>${r.team_name}</td>
      <td>${r.played ?? 0}</td>
      <td>${r.won ?? 0}</td>
      <td>${r.drawn ?? 0}</td>
      <td>${r.lost ?? 0}</td>
      <td>${r.goal_difference ?? 0}</td>
      <td><strong>${r.points ?? 0}</strong></td>
    </tr>`).join("");
  container.innerHTML = `
    <table>
      <thead><tr><th>#</th><th>Squadra</th><th>G</th><th>V</th><th>N</th><th>P</th><th>DR</th><th>Pt</th></tr></thead>
      <tbody>${body}</tbody>
    </table>`;
}

function predictionBadgeHTML(data) {
  const pct = (x) => Math.round(x * 1000) / 10;
  return `
    <div class="mini-prob-bar" title="${data.model} · confidenza ${data.confidence}">
      <span class="p-home" style="width:${pct(data.p_home)}%"></span>
      <span class="p-draw" style="width:${pct(data.p_draw)}%"></span>
      <span class="p-away" style="width:${pct(data.p_away)}%"></span>
    </div>
    <span class="mini-prob-text">1: ${pct(data.p_home)}% · X: ${pct(data.p_draw)}% · 2: ${pct(data.p_away)}%</span>
    <span class="badge ${data.confidence}">${data.confidence}</span>`;
}

// --- Oggi ----------------------------------------------------------------

const scheduleTable = document.getElementById("schedule-table");
const scheduleStatus = document.getElementById("schedule-status");
const scheduleDateInput = document.getElementById("schedule-date");
const btnReloadSchedule = document.getElementById("btn-reload-schedule");

const STATUS_LABEL = {
  not_started: "Da giocare",
  live: "In corso",
  halftime: "Intervallo",
  closed: "Finita",
  postponed: "Rinviata",
};

function formatKickoff(iso) {
  if (!iso) return "-";
  try {
    return new Date(iso).toLocaleString("it-IT", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
  } catch {
    return iso;
  }
}

async function loadSchedule() {
  const date = scheduleDateInput.value || undefined;
  scheduleStatus.textContent = "Caricamento partite in corso...";
  scheduleStatus.className = "hint";
  scheduleTable.innerHTML = "";
  btnReloadSchedule.disabled = true;
  try {
    const url = date ? `/api/schedule?date=${encodeURIComponent(date)}` : "/api/schedule";
    const events = await getJSON(url);
    if (!events.length) {
      scheduleStatus.textContent = "Nessuna partita trovata per questa data.";
      return;
    }
    scheduleStatus.textContent = `${events.length} partite trovate.`;

    const rowsHTML = events.map((ev, i) => `
      <tr data-idx="${i}">
        <td>${formatKickoff(ev.start_time)}</td>
        <td>${ev.competition_name || ev.competition_id || "-"}</td>
        <td>${ev.home_name || "?"}</td>
        <td>${ev.away_name || "?"}</td>
        <td>${
          ev.status === "closed" || ev.status === "live" || ev.status === "halftime"
            ? `<strong>${ev.home_score ?? "-"} - ${ev.away_score ?? "-"}</strong> <span class="hint">(${STATUS_LABEL[ev.status] || ev.status})</span>`
            : `<span class="hint">${STATUS_LABEL[ev.status] || ev.status || "-"}</span>`
        }</td>
        <td class="predict-cell">${ev.status === "not_started" ? "" : "<span class=\"hint\">—</span>"}</td>
      </tr>`).join("");

    scheduleTable.innerHTML = `
      <table>
        <thead><tr><th>Ora</th><th>Campionato</th><th>Casa</th><th>Ospite</th><th>Risultato</th><th>Pronostico</th></tr></thead>
        <tbody>${rowsHTML}</tbody>
      </table>`;

    const notStarted = events
      .map((ev, i) => ({ ev, i }))
      .filter(({ ev }) => ev.status === "not_started" && ev.home_id && ev.away_id);

    // Prioritize fixtures from leagues we actually have coverage for, so
    // the auto-predict budget isn't spent on friendlies/regional leagues
    // that will just come back with "nessuna fonte disponibile".
    const prioritized = [
      ...notStarted.filter(({ ev }) => PRIORITY_COMPETITION_IDS.has(ev.competition_id)),
      ...notStarted.filter(({ ev }) => !PRIORITY_COMPETITION_IDS.has(ev.competition_id)),
    ];
    const toAutoPredict = prioritized.slice(0, AUTO_PREDICT_LIMIT);
    const rest = prioritized.slice(AUTO_PREDICT_LIMIT);

    toAutoPredict.forEach(({ ev, i }) => {
      const cell = scheduleTable.querySelector(`tr[data-idx="${i}"] .predict-cell`);
      if (cell) cell.innerHTML = `<span class="spinner"></span>`;
    });

    // Sequential, not parallel: each call spawns a subprocess + external
    // network requests upstream, so firing all of them at once would
    // hammer the free-tier data sources and the dyno's CPU at the same time.
    for (const { ev, i } of toAutoPredict) {
      const cell = scheduleTable.querySelector(`tr[data-idx="${i}"] .predict-cell`);
      try {
        const data = await postJSON("/api/predict", {
          home: ev.home_name, away: ev.away_name,
          home_id: ev.home_id, away_id: ev.away_id,
          season: ev.season_id, event_id: ev.event_id, date: ev.start_time,
        });
        if (cell) cell.innerHTML = predictionBadgeHTML(data);
      } catch (err) {
        if (cell) cell.innerHTML = `<span class="hint no-data" title="${err.message}">nessun dato</span>`;
      }
    }

    rest.forEach(({ ev, i }) => {
      const cell = scheduleTable.querySelector(`tr[data-idx="${i}"] .predict-cell`);
      if (!cell) return;
      const btn = document.createElement("button");
      btn.textContent = "Calcola";
      btn.className = "btn-inline";
      btn.addEventListener("click", async () => {
        btn.disabled = true;
        cell.innerHTML = `<span class="spinner"></span>`;
        try {
          const data = await postJSON("/api/predict", {
            home: ev.home_name, away: ev.away_name,
            home_id: ev.home_id, away_id: ev.away_id,
            season: ev.season_id, event_id: ev.event_id, date: ev.start_time,
          });
          cell.innerHTML = predictionBadgeHTML(data);
        } catch (err) {
          cell.innerHTML = `<span class="hint">${err.message}</span>`;
        }
      });
      cell.innerHTML = "";
      cell.appendChild(btn);
    });
  } catch (err) {
    scheduleStatus.textContent = err.message;
    scheduleStatus.className = "status err";
  } finally {
    btnReloadSchedule.disabled = false;
  }
}

btnReloadSchedule.addEventListener("click", loadSchedule);

// --- Classifica ------------------------------------------------------

const competitionSelect = document.getElementById("competition-select");
const syncForm = document.getElementById("form-sync-standings");
const syncStatus = document.getElementById("sync-status");
const standingsTable = document.getElementById("standings-table");

async function loadCompetitions() {
  try {
    const competitions = await getJSON("/api/competitions");
    competitionSelect.innerHTML = competitions
      .map(c => `<option value="${c.id}">${c.name}</option>`).join("");
  } catch (err) {
    competitionSelect.innerHTML = `<option value="">Errore caricamento campionati</option>`;
  }
}

syncForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const fd = new FormData(syncForm);
  const btn = syncForm.querySelector("button");
  btn.disabled = true;
  syncStatus.textContent = "Sincronizzazione in corso (può richiedere qualche secondo)...";
  syncStatus.className = "status";
  try {
    const data = await postJSON("/api/sync/standings", {
      competition: fd.get("competition"),
      season: fd.get("season"),
    });
    syncStatus.textContent = `Sincronizzate ${data.rows} squadre per ${data.season_id}`;
    syncStatus.className = "status ok";
    const rows = await getJSON(`/api/standings?season=${encodeURIComponent(data.season_id)}`);
    renderStandingsTable(standingsTable, rows);
  } catch (err) {
    syncStatus.textContent = err.message;
    syncStatus.className = "status err";
  } finally {
    btn.disabled = false;
  }
});

// --- Pronostico -------------------------------------------------------

const predictForm = document.getElementById("form-predict");
const predictResult = document.getElementById("predict-result");

predictForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const fd = new FormData(predictForm);
  const btn = predictForm.querySelector("button");
  btn.disabled = true;
  predictResult.innerHTML = `<p class="hint">Calcolo in corso...</p>`;
  try {
    const data = await postJSON("/api/predict", {
      home: fd.get("home"), away: fd.get("away"),
      home_id: fd.get("home_id"), away_id: fd.get("away_id"),
      season: fd.get("season"),
    });
    const pct = (x) => Math.round(x * 1000) / 10;
    predictResult.innerHTML = `
      <div class="result-card">
        <strong>${data.home_team}</strong> vs <strong>${data.away_team}</strong>
        <div class="prob-bar">
          <span class="p-home" style="width:${pct(data.p_home)}%">1: ${pct(data.p_home)}%</span>
          <span class="p-draw" style="width:${pct(data.p_draw)}%">X: ${pct(data.p_draw)}%</span>
          <span class="p-away" style="width:${pct(data.p_away)}%">2: ${pct(data.p_away)}%</span>
        </div>
        <span class="badge ${data.confidence}">${data.model} · confidenza ${data.confidence}</span>
        <p class="hint">${data.detail || ""}</p>
      </div>`;
  } catch (err) {
    predictResult.innerHTML = `<p class="error-box">${err.message}</p>`;
  } finally {
    btn.disabled = false;
  }
});

// --- Sistemi ------------------------------------------------------------

const systemForm = document.getElementById("form-system");
const systemResult = document.getElementById("system-result");
const systemMode = document.getElementById("system-mode");
const minCorrectRow = document.querySelector(".row-min-correct");

systemMode.addEventListener("change", () => {
  minCorrectRow.style.display = systemMode.value === "ridotto" ? "flex" : "none";
});

function parsePicksRaw(raw) {
  const picks = [];
  const labels = [];
  raw.split("\n").map(l => l.trim()).filter(Boolean).forEach(line => {
    const [signsPart, labelPart] = line.split("=").map(s => s && s.trim());
    picks.push(signsPart.toUpperCase());
    labels.push(labelPart || `Match ${picks.length}`);
  });
  return { picks, labels };
}

systemForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const fd = new FormData(systemForm);
  const btn = systemForm.querySelector("button");
  const { picks, labels } = parsePicksRaw(fd.get("picks_raw"));
  const mode = fd.get("mode");
  const body = {
    mode, picks, labels,
    stake: parseFloat(fd.get("stake") || "1"),
  };
  if (mode === "ridotto") {
    body.min_correct = parseInt(fd.get("min_correct"), 10);
  }
  btn.disabled = true;
  systemResult.innerHTML = `<p class="hint">Generazione in corso...</p>`;
  try {
    const data = await postJSON("/api/system", body);
    const cols = data.columns.map((col, i) =>
      `<div>${i + 1}. ${data.matches.map((m, j) => `${m}=${col[j]}`).join("  ")}</div>`
    ).join("");
    const guarantee = data.kind === "ridotto"
      ? `<p>Garanzia verificata: <strong>${data.guaranteed_min_correct}/${data.matches.length}</strong> corretti · risparmio ${Math.round(data.savings_vs_integral * 1000) / 10}%</p>`
      : "";
    systemResult.innerHTML = `
      <div class="result-card">
        <p><strong>${data.num_columns}</strong> colonne su ${data.total_scenarios} scenari — costo totale <strong>${data.total_cost}</strong></p>
        ${guarantee}
        <div class="columns-list">${cols}</div>
      </div>`;
  } catch (err) {
    systemResult.innerHTML = `<p class="error-box">${err.message}</p>`;
  } finally {
    btn.disabled = false;
  }
});

// --- Boot -----------------------------------------------------------------

loadCompetitions();
loadSchedule();
