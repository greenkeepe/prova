// Vanilla JS — tab switching + fetch calls to the /api/* endpoints.
// No build step, no framework: this is a small local dashboard, not a SPA.

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

// --- Classifica -----------------------------------------------------

const syncForm = document.getElementById("form-sync-standings");
const syncStatus = document.getElementById("sync-status");

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
    document.querySelector('#form-view-standings [name=season]').value = data.season_id;
  } catch (err) {
    syncStatus.textContent = err.message;
    syncStatus.className = "status err";
  } finally {
    btn.disabled = false;
  }
});

const viewForm = document.getElementById("form-view-standings");
const standingsTable = document.getElementById("standings-table");

viewForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const fd = new FormData(viewForm);
  const season = fd.get("season");
  try {
    const rows = await getJSON(`/api/standings?season=${encodeURIComponent(season)}`);
    if (!rows.length) {
      standingsTable.innerHTML = `<p class="hint">Nessun dato per questa stagione. Sincronizza prima.</p>`;
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
    standingsTable.innerHTML = `
      <table>
        <thead><tr><th>#</th><th>Squadra</th><th>G</th><th>V</th><th>N</th><th>P</th><th>DR</th><th>Pt</th></tr></thead>
        <tbody>${body}</tbody>
      </table>`;
  } catch (err) {
    standingsTable.innerHTML = `<p class="error-box">${err.message}</p>`;
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
