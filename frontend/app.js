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

let cases = [];

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

function answerLine(name, question, answer) {
  if (!answer) return `${name}: —`;
  if (question.type === "choice") {
    const conf = answer.confidence != null ? ` (${Number(answer.confidence).toFixed(2)})` : "";
    return `${name}: ${answer.choice}${conf}`;
  }
  if (question.type === "score") {
    return `${name}: ${Number(answer.score).toFixed(2)}`;
  }
  if (question.type === "noul") {
    return `${name}: ${Number(answer.noul).toFixed(3)}`;
  }
  return `${name}: ${JSON.stringify(answer)}`;
}

function renderStatus(status) {
  const jev = status.jev;
  const laya = status.laya;
  $("status-row").innerHTML = `
    <div class="pill jev">
      <b>JEV</b>
      <span>${jev.configured ? `${jev.provider} · ${jev.model}` : "no API key"}</span>
    </div>
    <div class="pill laya">
      <b>LAYA</b>
      <span>${laya.message}${laya.device ? ` · ${laya.device}` : ""}</span>
    </div>
  `;

  const setup = $("setup");
  const bits = [];
  if (!jev.configured) {
    bits.push(`
      <strong>Jev is hosted, not installable.</strong> Get a key and put it in <code>.env</code>:
      <ol>
        <li>Official (preferred): waitlist at <a href="https://typesafe.ai" target="_blank" rel="noreferrer">typesafe.ai</a>, then create a key at <a href="https://console.typesafe.ai/settings/keys" target="_blank" rel="noreferrer">console.typesafe.ai/settings/keys</a> → <code>TYPESAFE_API_KEY</code></li>
        <li>Free fallback while you wait: sign in at <a href="https://jev-agent.com/api-access" target="_blank" rel="noreferrer">jev-agent.com/api-access</a> → <code>JEV_AGENT_KEY</code></li>
      </ol>
    `);
  }
  if (!laya.loaded) {
    bits.push(`<div style="margin-top:8px">Laya downloads ~800MB of weights from Hugging Face on first load. Click <b>Run all cases</b> or load it now. <button id="load-laya">Load Laya</button></div>`);
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

function selectedModels() {
  const models = [];
  if ($("use-jev").checked) models.push("jev");
  if ($("use-laya").checked) models.push("laya");
  return models;
}

async function pollLayaUntilReady() {
  for (let i = 0; i < 600; i += 1) {
    const status = await refreshStatus();
    if (status.laya.loaded) return status;
    if (status.laya.error) throw new Error(status.laya.error);
    await new Promise((resolve) => setTimeout(resolve, 2000));
  }
  throw new Error("Laya is still downloading. Check the terminal and try again.");
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
      <h3>Jev speed</h3>
      <div class="stat jev">${fmtMs(jev.mean_ms)}</div>
      <div class="sub">mean · p50 ${fmtMs(jev.p50_ms)} · ${jev.runs || 0} runs</div>
    </div>
    <div class="card">
      <h3>Laya speed</h3>
      <div class="stat laya">${fmtMs(laya.mean_ms)}</div>
      <div class="sub">mean · p50 ${fmtMs(laya.p50_ms)} · ${laya.runs || 0} runs</div>
    </div>
    <div class="card">
      <h3>Quality vs gold labels</h3>
      <div class="sub">Jev ${fmtPct(jev.accuracy)} · Laya ${fmtPct(laya.accuracy)}</div>
      <div class="sub" style="margin-top:8px">Agreement ${fmtPct(summary.agreement)} (${summary.agreement_hits || 0}/${summary.agreement_total || 0} questions)</div>
    </div>
  `;
}

function modelColumn(name, result, questions) {
  if (!result) {
    return `<div class="model-col ${name}"><h3>${name}</h3><div class="sub">not run</div></div>`;
  }
  if (!result.ok) {
    return `<div class="model-col ${name}"><h3>${name}</h3><div class="err">${result.error}</div></div>`;
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
      <h3>${name} · ${result.model_id || ""}</h3>
      <div class="latency">${fmtMs(result.latency_ms)}${quality.accuracy != null ? ` · gold ${fmtPct(quality.accuracy)}` : ""}</div>
      ${rows}
    </div>
  `;
}

function renderRows(rows) {
  $("cases").innerHTML = rows.map((row) => `
    <article class="case">
      <h2>${row.title}</h2>
      <div class="case-meta">${row.id} · ${row.group}</div>
      <div class="compare">
        ${modelColumn("jev", row.jev, row.questions)}
        ${modelColumn("laya", row.laya, row.questions)}
      </div>
    </article>
  `).join("");
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
}

async function runAll() {
  const models = selectedModels();
  if (!models.length) {
    $("run-note").textContent = "Pick at least one model.";
    return;
  }
  $("run-all").disabled = true;
  $("run-note").textContent = "Running… first Laya call also downloads weights if needed.";
  try {
    const data = await api("/api/run", {
      method: "POST",
      body: JSON.stringify({ models }),
    });
    renderSummary(data.summary);
    renderRows(data.rows);
    $("run-note").textContent = "Done.";
    await refreshStatus();
  } catch (err) {
    $("run-note").textContent = err.message;
  } finally {
    $("run-all").disabled = false;
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

async function runPlay() {
  const models = selectedModels();
  $("run-play").disabled = true;
  $("play-note").textContent = "Running…";
  try {
    const questions = JSON.parse($("play-questions").value);
    const data = await api("/api/play", {
      method: "POST",
      body: JSON.stringify({
        state: parseState($("play-state").value),
        questions,
        models,
      }),
    });
    $("play-out").innerHTML = "";
    renderSummary(data.summary, "play-summary");
    const holder = document.createElement("div");
    holder.id = "play-rows";
    $("play-out").innerHTML = "";
    $("play-out").appendChild(holder);
    holder.innerHTML = `
      <article class="case">
        <h2>Playground</h2>
        <div class="compare">
          ${modelColumn("jev", data.row.jev, data.row.questions)}
          ${modelColumn("laya", data.row.laya, data.row.questions)}
        </div>
      </article>
    `;
    $("play-note").textContent = "Done.";
  } catch (err) {
    $("play-note").textContent = err.message;
  } finally {
    $("run-play").disabled = false;
  }
}

document.querySelectorAll(".tab").forEach((btn) => {
  btn.onclick = () => {
    document.querySelectorAll(".tab").forEach((item) => item.classList.remove("is-on"));
    btn.classList.add("is-on");
    $("panel-bench").classList.toggle("hidden", btn.dataset.tab !== "bench");
    $("panel-play").classList.toggle("hidden", btn.dataset.tab !== "play");
  };
});

$("run-all").onclick = runAll;
$("run-play").onclick = runPlay;

refreshStatus().then(loadCases).catch((err) => {
  $("setup").textContent = err.message;
});
