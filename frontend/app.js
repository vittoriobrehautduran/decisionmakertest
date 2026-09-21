const $ = (id) => document.getElementById(id);

const DEFAULT_QUESTIONS = {
  department: {
    type: "choice",
    instructions: "Which department should handle this request?",
    criteria: {
      billing: "invoices, payments, refunds, duplicate charges",
      technical: "bugs, outages, login issues, system errors",
      sales: "pricing, new contracts, upgrades, demos",
      other: "everything else",
    },
  },
  urgency: {
    type: "score",
    instructions: "How urgent is this request?",
    criteria: ["not urgent, can wait", "should be handled soon", "critical deadline or blocking issue"],
  },
  frustration: {
    type: "score",
    instructions: "How frustrated does the customer appear?",
    criteria: ["calm, just stating facts", "frustrated but civil", "very angry, strong language"],
  },
  churn_risk: {
    type: "noul",
    instructions: "Does the user threaten to cancel, leave, or take their business elsewhere?",
    criteria: { true: "mentions cancelling, leaving, or switching providers", false: "no cancellation or leaving intent" },
  },
  refund_requested: {
    type: "noul",
    instructions: "Does the user explicitly request a refund or money back?",
    criteria: { true: "explicitly asks for a refund or chargeback", false: "does not ask for a refund" },
  },
};

const SPEED_STATE = {
  from: "user@acme.com",
  subject: "Duplicate charge on invoice #4411",
  body: "Hi, we were billed twice for March. Please refund the duplicate today or we will cancel our plan.",
};

let cases = [];
let benchRows = [];
const speedRuns = { jev: [], laya: [] };

async function api(path, options = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(data.detail || data.error || res.statusText);
  }
  return data;
}

function fmtMs(value) {
  if (value == null) return "—";
  return `${Number(value).toFixed(0)} ms`;
}

function fmtPct(value) {
  if (value == null) return "—";
  return `${(Number(value) * 100).toFixed(0)}%`;
}

function mean(values) {
  if (!values.length) return null;
  return values.reduce((sum, value) => sum + value, 0) / values.length;
}

function questionKind(question) {
  if (question.type === "choice") return "pick one";
  if (question.type === "score") return "0–2 scale";
  if (question.type === "noul") return "yes / no";
  return question.type;
}

function answerLine(name, question, answer) {
  const kind = questionKind(question);
  if (!answer) return `${name} (${kind}): —`;
  if (question.type === "choice") {
    const conf = answer.confidence != null ? ` (${Number(answer.confidence).toFixed(2)})` : "";
    return `${name}: ${answer.choice}${conf}`;
  }
  if (question.type === "score") {
    return `${name}: ${Number(answer.score).toFixed(2)} / 2`;
  }
  if (question.type === "noul") {
    const yes = Number(answer.noul) >= 0.5 ? "yes" : "no";
    return `${name}: ${yes} (${Number(answer.noul).toFixed(3)})`;
  }
  return `${name}: ${JSON.stringify(answer)}`;
}

function renderStatus(status) {
  const jev = status.jev;
  const laya = status.laya;
  $("status-row").innerHTML = `
    <div class="pill jev">
      <b>JEV · cloud</b>
      <span>${jev.configured ? `ready · ${jev.model}` : "needs API key"}</span>
    </div>
    <div class="pill laya">
      <b>LAYA · local GPU</b>
      <span>${laya.loaded ? `ready · ${laya.device}` : laya.message}</span>
    </div>
  `;

  const setup = $("setup");
  const bits = [];
  if (!jev.configured) {
    bits.push(`
      <strong>Jev needs a cloud key in <code>.env</code>.</strong>
      Official: <a href="https://console.typesafe.ai/settings/keys" target="_blank" rel="noreferrer">console.typesafe.ai</a>
      → <code>TYPESAFE_API_KEY</code>
    `);
  }
  if (!laya.loaded) {
    bits.push(`<div>Laya is not in GPU memory yet. Load it once, then speed tests are just inference. <button id="load-laya" class="btn laya">Load Laya</button></div>`);
  }
  setup.innerHTML = bits.join("");
  setup.classList.toggle("hidden", bits.length === 0);
  const loadBtn = $("load-laya");
  if (loadBtn) {
    loadBtn.onclick = async () => {
      loadBtn.disabled = true;
      loadBtn.textContent = "Loading…";
      try {
        await api("/api/laya/load", { method: "POST", body: "{}" });
        await pollLayaUntilReady();
      } catch (err) {
        setup.insertAdjacentHTML("beforeend", `<p class="err">${err.message}</p>`);
      }
    };
  }
}

async function pollLayaUntilReady() {
  for (let i = 0; i < 600; i += 1) {
    const status = await refreshStatus();
    if (status.laya.loaded) return status;
    if (status.laya.error) throw new Error(status.laya.error);
    await new Promise((resolve) => setTimeout(resolve, 2000));
  }
  throw new Error("Laya is still loading. Check the terminal and try again.");
}

async function ensureLayaIfNeeded(models) {
  if (!models.includes("laya")) return;
  const status = await refreshStatus();
  if (status.laya.loaded) return;
  await api("/api/laya/load", { method: "POST", body: "{}" });
  await pollLayaUntilReady();
}

function setBusy(ids, busy) {
  ids.forEach((id) => {
    const el = $(id);
    if (el) el.disabled = busy;
  });
}

function renderSummary(summary, targetId = "summary") {
  const target = $(targetId);
  if (!summary) {
    target.innerHTML = "";
    return;
  }
  const jev = summary.jev || {};
  const laya = summary.laya || {};
  target.innerHTML = `
    <div class="card">
      <h3>Jev average time</h3>
      <div class="stat jev">${fmtMs(jev.mean_ms)}</div>
      <div class="sub">${jev.runs || 0} runs · median ${fmtMs(jev.p50_ms)}</div>
    </div>
    <div class="card">
      <h3>Laya average time</h3>
      <div class="stat laya">${fmtMs(laya.mean_ms)}</div>
      <div class="sub">${laya.runs || 0} runs · median ${fmtMs(laya.p50_ms)}</div>
    </div>
    <div class="card">
      <h3>Did the answers match?</h3>
      <div class="sub">Jev ${fmtPct(jev.accuracy)} · Laya ${fmtPct(laya.accuracy)} vs gold labels</div>
      <div class="sub" style="margin-top:8px">They agreed with each other ${fmtPct(summary.agreement)} (${summary.agreement_hits || 0}/${summary.agreement_total || 0} questions)</div>
    </div>
  `;
}

function modelColumn(name, result, questions) {
  const title = name === "jev" ? "Jev (cloud)" : "Laya (local GPU)";
  if (!result) {
    return `<div class="model-col ${name}"><h3>${title}</h3><div class="sub">not run</div></div>`;
  }
  if (!result.ok) {
    return `<div class="model-col ${name}"><h3>${title}</h3><div class="err">${result.error}</div></div>`;
  }
  const quality = result.quality || {};
  const rows = Object.entries(questions).map(([qName, question]) => {
    const answer = (result.answers || {})[qName];
    const verdict = (quality.per_question || {})[qName];
    const mark = verdict ? (verdict.ok ? '<span class="ok">match</span>' : '<span class="no">miss</span>') : "";
    return `<div class="qrow"><span>${answerLine(qName, question, answer)}</span>${mark}</div>`;
  }).join("");
  return `
    <div class="model-col ${name}">
      <h3>${title}</h3>
      <div class="latency">${fmtMs(result.latency_ms)}${quality.accuracy != null ? ` · gold ${fmtPct(quality.accuracy)}` : ""}</div>
      ${rows}
    </div>
  `;
}

function renderRows(rows) {
  benchRows = rows;
  $("cases").innerHTML = rows.map((row) => `
    <article class="case" data-case-id="${row.id}">
      <div class="case-head">
        <div>
          <h2>${row.title}</h2>
          <div class="case-meta">${row.group} · ${Object.keys(row.questions).length} questions</div>
        </div>
        <div class="case-actions">
          <button class="btn jev" data-run-case="${row.id}" data-models="jev">Jev</button>
          <button class="btn laya" data-run-case="${row.id}" data-models="laya">Laya</button>
          <button class="primary" data-run-case="${row.id}" data-models="jev,laya">Both</button>
        </div>
      </div>
      <div class="compare">
        ${modelColumn("jev", row.jev, row.questions)}
        ${modelColumn("laya", row.laya, row.questions)}
      </div>
    </article>
  `).join("");
}

function renderSpeedChart() {
  const board = $("speed-chart");
  const jev = speedRuns.jev;
  const laya = speedRuns.laya;
  if (!jev.length && !laya.length) {
    board.innerHTML = `<p class="speed-empty">No race yet. Run Jev, run Laya, or race both on the same email.</p>`;
    return;
  }

  const jevMean = mean(jev);
  const layaMean = mean(laya);
  const maxMs = Math.max(jevMean || 0, layaMean || 0, 1);
  const rounds = Math.max(jev.length, laya.length);
  let verdict = "Run the other model to compare.";
  if (jevMean != null && layaMean != null) {
    if (jevMean < layaMean) {
      verdict = `Jev is ${(layaMean / jevMean).toFixed(2)}× faster on this machine.`;
    } else if (layaMean < jevMean) {
      verdict = `Laya is ${(jevMean / layaMean).toFixed(2)}× faster on this machine.`;
    } else {
      verdict = "They are tied.";
    }
  }

  const roundRows = [];
  for (let i = 0; i < rounds; i += 1) {
    const jevMs = jev[i];
    const layaMs = laya[i];
    const roundMax = Math.max(jevMs || 0, layaMs || 0, 1);
    roundRows.push(`
      <div class="round-row">
        <span>round ${i + 1}</span>
        <div class="round-bars">
          <div class="round-bar jev">${jevMs != null ? `<span style="width:${(jevMs / roundMax) * 100}%"></span>` : ""}</div>
          <div class="round-bar laya">${layaMs != null ? `<span style="width:${(layaMs / roundMax) * 100}%"></span>` : ""}</div>
        </div>
        <span>${jevMs != null ? fmtMs(jevMs) : "—"} / ${layaMs != null ? fmtMs(layaMs) : "—"}</span>
      </div>
    `);
  }

  board.innerHTML = `
    <div class="race-row">
      <div class="race-label jev"><span>Jev · cloud</span><span>${jevMean != null ? `${fmtMs(jevMean)} avg · ${jev.length} runs` : "not run"}</span></div>
      <div class="race-track"><div class="race-fill jev" style="width:${jevMean != null ? (jevMean / maxMs) * 100 : 0}%"></div></div>
    </div>
    <div class="race-row">
      <div class="race-label laya"><span>Laya · local GPU</span><span>${layaMean != null ? `${fmtMs(layaMean)} avg · ${laya.length} runs` : "not run"}</span></div>
      <div class="race-track"><div class="race-fill laya" style="width:${layaMean != null ? (layaMean / maxMs) * 100 : 0}%"></div></div>
    </div>
    <p class="race-verdict">${verdict}</p>
    <div class="round-chart">${roundRows.join("")}</div>
  `;
}

async function refreshStatus() {
  const status = await api("/api/status");
  renderStatus(status);
  return status;
}

async function loadCases() {
  cases = await api("/api/cases");
  renderRows(cases.map((item) => ({ ...item, jev: null, laya: null })));
  $("play-questions").value = JSON.stringify(DEFAULT_QUESTIONS, null, 2);
  renderSpeedChart();
}

function mergeCaseRow(previous, incoming) {
  return {
    ...previous,
    ...incoming,
    jev: incoming.jev || previous.jev,
    laya: incoming.laya || previous.laya,
  };
}

async function runBench(models, caseIds) {
  const note = $("run-note");
  setBusy(["bench-jev", "bench-laya", "bench-both"], true);
  note.textContent = `Running ${models.join(" + ")}…`;
  try {
    await ensureLayaIfNeeded(models);
    const data = await api("/api/run", {
      method: "POST",
      body: JSON.stringify({ models, case_ids: caseIds || null }),
    });
    if (caseIds && caseIds.length) {
      const next = benchRows.map((row) => {
        const fresh = data.rows.find((item) => item.id === row.id);
        return fresh ? mergeCaseRow(row, fresh) : row;
      });
      renderRows(next);
    } else {
      renderRows(data.rows);
      renderSummary(data.summary);
    }
    note.textContent = "Done.";
    await refreshStatus();
  } catch (err) {
    note.textContent = err.message;
  } finally {
    setBusy(["bench-jev", "bench-laya", "bench-both"], false);
  }
}

function parseState(text) {
  const trimmed = text.trim();
  try {
    return JSON.parse(trimmed);
  } catch {
    return trimmed;
  }
}

async function runPlay(models) {
  const note = $("play-note");
  setBusy(["play-jev", "play-laya", "play-both"], true);
  note.textContent = `Running ${models.join(" + ")}…`;
  try {
    await ensureLayaIfNeeded(models);
    const questions = JSON.parse($("play-questions").value);
    const data = await api("/api/play", {
      method: "POST",
      body: JSON.stringify({
        state: parseState($("play-state").value),
        questions,
        models,
      }),
    });
    renderSummary(data.summary, "play-summary");
    $("play-out").innerHTML = `
      <article class="case">
        <h2>Your message</h2>
        <div class="compare">
          ${modelColumn("jev", data.row.jev, data.row.questions)}
          ${modelColumn("laya", data.row.laya, data.row.questions)}
        </div>
      </article>
    `;
    note.textContent = "Done.";
  } catch (err) {
    note.textContent = err.message;
  } finally {
    setBusy(["play-jev", "play-laya", "play-both"], false);
  }
}

async function runPlayOnce(models) {
  const questions = JSON.parse($("play-questions").value || JSON.stringify(DEFAULT_QUESTIONS));
  const data = await api("/api/play", {
    method: "POST",
    body: JSON.stringify({
      state: SPEED_STATE,
      questions,
      models,
    }),
  });
  return data.row;
}

async function runSpeed(models) {
  const note = $("speed-note");
  const rounds = Number($("speed-rounds").value) || 5;
  const buttons = ["speed-jev", "speed-laya", "speed-both"];
  setBusy(buttons, true);
  if (models.includes("jev")) speedRuns.jev = [];
  if (models.includes("laya")) speedRuns.laya = [];
  renderSpeedChart();
  try {
    await ensureLayaIfNeeded(models);
    for (let round = 1; round <= rounds; round += 1) {
      note.textContent = `Round ${round} / ${rounds}…`;
      // One model at a time so the bars update as each finishes.
      for (const name of models) {
        const row = await runPlayOnce([name]);
        const result = row[name];
        if (!result || !result.ok) {
          throw new Error(result?.error || `${name} failed`);
        }
        speedRuns[name].push(result.latency_ms);
        renderSpeedChart();
      }
    }
    note.textContent = "Done.";
  } catch (err) {
    note.textContent = err.message;
  } finally {
    setBusy(buttons, false);
  }
}

let gameSession = null;
let gameStop = false;
let gameActing = null;

function kindVisual(kind) {
  const map = {
    monster: { icon: "🦇", label: "foe" },
    trap: { icon: "⚠", label: "trap" },
    merchant: { icon: "🪙", label: "shop" },
    shrine: { icon: "✦", label: "shrine" },
    fork: { icon: "⑂", label: "fork" },
    treasure: { icon: "▣", label: "chest" },
    boss: { icon: "♛", label: "boss" },
  };
  return map[kind] || { icon: "?", label: kind };
}

function sceneFxClass(turn) {
  if (!turn || !turn.ok) return "";
  const text = (turn.lines || []).join(" ").toLowerCase();
  if (text.includes("damage") || text.includes("cursed") || text.includes("trap") || text.includes("spotted") || text.includes("caught")) {
    return "fx-hit";
  }
  if (text.includes("heal") || text.includes("+4 hp") || text.includes("+5 hp") || text.includes("+3 hp")) {
    return "fx-heal";
  }
  if (text.includes("gold") || text.includes("looted") || text.includes("relic")) {
    return "fx-gold";
  }
  return "";
}

function foeActorHtml(kind) {
  if (kind === "monster") {
    return `<div class="actor foe-body monster"><div class="head"></div><div class="body"></div></div>`;
  }
  if (kind === "boss") {
    return `<div class="actor foe-body boss"><div class="head"></div><div class="body"></div></div>`;
  }
  if (kind === "treasure") {
    return `<div class="actor foe-body chest"><div class="body"></div></div>`;
  }
  if (kind === "merchant") {
    return `<div class="actor foe-body merchant"><div class="head"></div><div class="body"></div></div>`;
  }
  if (kind === "shrine") {
    return `<div class="actor foe-body shrine"><div class="head"></div><div class="body"></div></div>`;
  }
  if (kind === "trap") {
    return `<div class="actor trap-spikes"></div>`;
  }
  if (kind === "fork") {
    return `<div class="actor fork-sign"></div>`;
  }
  return "";
}

function renderStage(name, snap, turns) {
  const player = snap.players[name];
  if (!player) {
    return `<article class="stage ${name}"><div class="stage-top"><h3>${name}</h3></div><div class="stage-footer">Not in this run</div></article>`;
  }

  const pending = (snap.pending || {})[name];
  const turn = turns[name];
  const acting = gameActing === name;
  const hpPct = Math.max(0, Math.round((player.hp / player.max_hp) * 100));
  const kind = pending?.room?.kind
    || (player.finished && player.alive ? "clear" : (!player.alive ? "dead" : "monster"));
  const roomTitle = pending?.room?.title
    || (player.finished ? (player.alive ? "Gate cleared" : "Fallen") : "—");
  const action = turn?.action || player.last_decision?.action;
  const speech = acting
    ? `<div class="thinking-dots">•••</div>`
    : (action ? `<div class="speech">${String(action).replace(/_/g, " ")}</div>` : "");
  const fx = sceneFxClass(turn);
  const coin = fx === "fx-gold" ? `<div class="coin"></div>` : "";
  const lastLine = (turn?.lines || []).slice(-1)[0]
    || (player.log || []).slice(-1)[0]
    || "Waiting…";
  const err = turn && !turn.ok ? `<div class="err">${turn.error}</div>` : "";

  return `
    <article class="stage ${name}${acting ? " is-acting" : ""}">
      <div class="stage-top">
        <h3>${name === "jev" ? "Jev" : "Laya"}</h3>
        <span class="stage-score">score ${player.score}</span>
      </div>
      <div class="stage-scene kind-${kind} ${fx}">
        <div class="wall-left"></div>
        <div class="wall-right"></div>
        <div class="floor"></div>
        ${speech}
        ${coin}
        <div class="actor hero-body ${name}"><div class="head"></div><div class="body"></div></div>
        ${player.alive && !player.finished ? foeActorHtml(kind) : ""}
      </div>
      <div class="stage-hud">
        <div class="hud-block">
          <b>HP ${player.hp}/${player.max_hp}</b>
          <div class="hp-bar"><span style="width:${hpPct}%"></span></div>
        </div>
        <div class="hud-block"><b>Gold</b>${player.gold}</div>
        <div class="hud-block"><b>Relics</b>${player.relics}</div>
      </div>
      <div class="stage-footer"><strong>${roomTitle}</strong> — ${lastLine}${err}</div>
    </article>
  `;
}

function renderGame(snap, turns = {}) {
  const board = $("game-board");
  if (!snap) {
    board.innerHTML = `<p class="speed-empty">Hit Play to watch them walk the dungeon. Same rooms, different choices.</p>`;
    return;
  }

  const preview = snap.rooms_preview || [];
  const map = preview.map((room) => {
    const pawns = [];
    let roomClass = "map-room";
    let anyHere = false;
    let anyDead = false;
    let anyDone = false;

    for (const name of ["jev", "laya"]) {
      const player = snap.players[name];
      if (!player) continue;

      const cleared = player.room > room.index || (player.finished && player.alive && room.index < preview.length);
      const standingHere = player.alive && !player.finished && player.room === room.index;
      const diedHere = !player.alive && player.room === room.index;
      const finishedOnLast = player.finished && player.alive && room.index === preview.length - 1;

      if (cleared && room.index < (player.finished && player.alive ? preview.length : player.room)) {
        anyDone = true;
      }
      if (standingHere || finishedOnLast) {
        anyHere = true;
        pawns.push(`<span class="pawn ${name}"></span>`);
      } else if (diedHere) {
        anyDead = true;
        pawns.push(`<span class="pawn ${name} dead"></span>`);
      }
    }

    if (anyHere) roomClass = "map-room active";
    else if (anyDead) roomClass = "map-room dead-here";
    else if (anyDone) roomClass = "map-room done";

    const vis = kindVisual(room.kind);
    return `
      <div class="${roomClass}" title="${room.title}">
        <span class="icon">${vis.icon}</span>
        <span class="label">${vis.label}</span>
        <div class="map-pawns">${pawns.join("")}</div>
      </div>
    `;
  }).join("");

  let winner = "";
  if (snap.done && snap.ranking?.length) {
    const top = snap.ranking[0];
    const tied = snap.ranking.filter((row) => row.score === top.score);
    if (tied.length > 1) winner = `Dead heat · ${top.score} pts`;
    else winner = `${top.model === "jev" ? "Jev" : "Laya"} wins · ${top.score} pts`;
  }

  board.innerHTML = `
    <div class="game-meta">
      <span>Ashen Gate · seed ${snap.seed}</span>
      <span>${snap.done ? "Finished" : "Live"}</span>
    </div>
    <div class="dungeon-map">${map}</div>
    <div class="game-arena">
      ${renderStage("jev", snap, turns)}
      ${renderStage("laya", snap, turns)}
    </div>
    ${winner ? `<div class="game-winner">${winner}</div>` : ""}
  `;
}

async function playGame(models) {
  const note = $("game-note");
  const buttons = ["game-jev", "game-laya", "game-both"];
  gameStop = false;
  setBusy(buttons, true);
  $("game-stop").disabled = false;
  note.textContent = "Opening the gate…";
  try {
    await ensureLayaIfNeeded(models);
    gameSession = await api("/api/game/start", {
      method: "POST",
      body: JSON.stringify({ models }),
    });
    renderGame(gameSession);

    while (!gameSession.done && !gameStop) {
      const pendingModels = Object.keys(gameSession.pending || {}).filter((name) => models.includes(name));
      if (!pendingModels.length) break;

      for (const name of pendingModels) {
        if (gameStop) break;
        gameActing = name;
        note.textContent = `${name === "jev" ? "Jev" : "Laya"} is looking at the room…`;
        renderGame(gameSession);
        const snap = await api("/api/game/tick", {
          method: "POST",
          body: JSON.stringify({ session_id: gameSession.session_id, models: [name] }),
        });
        gameSession = snap;
        gameActing = null;
        renderGame(gameSession, snap.turns || {});
        const turn = (snap.turns || {})[name];
        if (turn && !turn.ok) {
          note.textContent = `${name} failed: ${turn.error}`;
          return;
        }
        // Pause so you can see the speech bubble + hit/gold FX.
        await new Promise((resolve) => setTimeout(resolve, 900));
      }
    }

    note.textContent = gameStop ? "Stopped." : "Run finished.";
    renderGame(gameSession);
  } catch (err) {
    note.textContent = err.message;
  } finally {
    gameActing = null;
    setBusy(buttons, false);
    $("game-stop").disabled = true;
  }
}

function showTab(tab) {
  document.querySelectorAll(".tab").forEach((item) => item.classList.toggle("is-on", item.dataset.tab === tab));
  $("panel-speed").classList.toggle("hidden", tab !== "speed");
  $("panel-game").classList.toggle("hidden", tab !== "game");
  $("panel-bench").classList.toggle("hidden", tab !== "bench");
  $("panel-play").classList.toggle("hidden", tab !== "play");
}

document.querySelectorAll(".tab").forEach((btn) => {
  btn.onclick = () => showTab(btn.dataset.tab);
});

$("speed-jev").onclick = () => runSpeed(["jev"]);
$("speed-laya").onclick = () => runSpeed(["laya"]);
$("speed-both").onclick = () => runSpeed(["jev", "laya"]);

$("game-jev").onclick = () => playGame(["jev"]);
$("game-laya").onclick = () => playGame(["laya"]);
$("game-both").onclick = () => playGame(["jev", "laya"]);
$("game-stop").onclick = () => { gameStop = true; };

$("bench-jev").onclick = () => runBench(["jev"]);
$("bench-laya").onclick = () => runBench(["laya"]);
$("bench-both").onclick = () => runBench(["jev", "laya"]);

$("play-jev").onclick = () => runPlay(["jev"]);
$("play-laya").onclick = () => runPlay(["laya"]);
$("play-both").onclick = () => runPlay(["jev", "laya"]);

$("cases").addEventListener("click", (event) => {
  const btn = event.target.closest("[data-run-case]");
  if (!btn) return;
  const models = btn.dataset.models.split(",");
  runBench(models, [btn.dataset.runCase]);
});

refreshStatus().then(loadCases).catch((err) => {
  $("setup").textContent = err.message;
  $("setup").classList.remove("hidden");
});
