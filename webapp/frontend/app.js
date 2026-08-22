(function () {
  "use strict";

  var STRATEGY_ORDER = ["zero_shot", "few_shot", "chain_of_thought", "structured_output"];
  var STRATEGY_META = {
    zero_shot: { label: "Zero-shot", color: "var(--series-1)" },
    few_shot: { label: "Few-shot", color: "var(--series-2)" },
    chain_of_thought: { label: "Chain-of-Thought", color: "var(--series-3)" },
    structured_output: { label: "Structured Output", color: "var(--series-4)" },
  };
  var STAGE_TITLES = {
    data_loader: "Load RAGTruth dataset",
    ingest: "Chunk → embed → index",
    calibration: "Calibrate hallucination judge",
    report: "Generate report & charts",
  };

  var state = {
    summaryByStrategy: {},
    activeStrategies: STRATEGY_ORDER.slice(),
    browseStrategy: null,
    browseRowsCache: {},
    apiKeyOk: true,
  };

  var $ = function (id) { return document.getElementById(id); };
  var svgns = function (tag) { return document.createElementNS("http://www.w3.org/2000/svg", tag); };

  // ---------------- theme ----------------
  (function initTheme() {
    var saved = null;
    try { saved = localStorage.getItem("theme"); } catch (e) {}
    if (saved === "light" || saved === "dark") {
      document.documentElement.setAttribute("data-theme", saved);
    }
    $("theme-toggle").addEventListener("click", function () {
      var current = document.documentElement.getAttribute("data-theme");
      var prefersDark = window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
      var isDark = current ? current === "dark" : prefersDark;
      var next = isDark ? "light" : "dark";
      document.documentElement.setAttribute("data-theme", next);
      try { localStorage.setItem("theme", next); } catch (e) {}
    });
  })();

  // ---------------- init ----------------
  function init() {
    buildLegend();
    buildStepper(STRATEGY_ORDER, true);
    buildBrowseTabs();
    renderCharts();

    fetch("/api/config-defaults").then(function (r) { return r.json(); }).then(function (cfg) {
      $("sample-size").value = cfg.sample_size;
      $("calibration-size").value = cfg.calibration_size;
      buildStrategyChecks(cfg.strategies);
      state.apiKeyOk = cfg.has_api_key;
      $("api-key-warning").style.display = cfg.has_api_key ? "none" : "flex";
    }).catch(function () {});

    fetch("/api/summary").then(function (r) { return r.json(); }).then(function (data) {
      (data.rows || []).forEach(function (row) { state.summaryByStrategy[row.strategy] = row; });
      renderCharts();
    }).catch(function () {});

    fetch("/api/calibration").then(function (r) { return r.json(); }).then(function (data) {
      if (data) renderCalibration(data);
    }).catch(function () {});

    $("run-btn").addEventListener("click", startRun);
    connectWS();
  }

  function buildStrategyChecks(strategies) {
    var container = $("strategy-checks");
    container.innerHTML = "";
    strategies.forEach(function (s) {
      var meta = STRATEGY_META[s] || { label: s, color: "var(--accent)" };
      var row = document.createElement("label");
      row.className = "check-row";
      row.innerHTML = '<input type="checkbox" checked data-strategy="' + s + '">' +
        '<span class="swatch" style="background:' + meta.color + '"></span>' + meta.label;
      container.appendChild(row);
    });
  }

  function selectedStrategies() {
    var boxes = document.querySelectorAll("#strategy-checks input[type=checkbox]");
    var out = [];
    boxes.forEach(function (b) { if (b.checked) out.push(b.getAttribute("data-strategy")); });
    return out.length ? out : STRATEGY_ORDER.slice();
  }

  // ---------------- run ----------------
  function startRun() {
    var strategies = selectedStrategies();
    var payload = {
      sample_size: parseInt($("sample-size").value, 10) || null,
      calibration_size: parseInt($("calibration-size").value, 10) || null,
      strategies: strategies,
      use_fixture: $("use-fixture").checked,
      skip_ragas: $("skip-ragas").checked,
      skip_calibration: $("skip-calibration").checked,
    };

    hideError();
    fetch("/api/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }).then(function (r) {
      return r.json().then(function (body) { return { ok: r.ok, body: body }; });
    }).then(function (res) {
      if (!res.ok) { showError(res.body.detail || "Failed to start run."); return; }
      state.activeStrategies = strategies;
      strategies.forEach(function (s) { delete state.summaryByStrategy[s]; });
      renderCharts();
      clearFeed();
      buildStepper(strategies, payload.skip_calibration);
      applyStatus({ status: "running" });
    }).catch(function (err) { showError(String(err)); });
  }

  function applyStatus(status) {
    var pill = $("status-pill");
    var s = status.status || "idle";
    pill.className = "status-pill " + s;
    pill.textContent = s.charAt(0).toUpperCase() + s.slice(1);
    var runBtn = $("run-btn");
    runBtn.disabled = s === "running" || !state.apiKeyOk;
    if (status.error) showError(status.error);
  }

  function showError(msg) {
    var el = $("error-banner");
    el.style.display = "flex";
    el.innerHTML = "<span>&#9888;</span><span>" + escapeHtml(msg) + "</span>";
  }
  function hideError() { $("error-banner").style.display = "none"; }

  // ---------------- websocket ----------------
  function connectWS() {
    var proto = location.protocol === "https:" ? "wss" : "ws";
    var ws = new WebSocket(proto + "://" + location.host + "/ws");
    ws.onopen = function () {
      $("conn-status").className = "conn-status live";
      $("conn-label").textContent = "Live";
    };
    ws.onclose = function () {
      $("conn-status").className = "conn-status offline";
      $("conn-label").textContent = "Reconnecting…";
      setTimeout(connectWS, 2000);
    };
    ws.onerror = function () { ws.close(); };
    ws.onmessage = function (evt) {
      var event = JSON.parse(evt.data);
      if (event.type === "hello") {
        applyStatus(event.status);
        if (event.status && event.status.request && event.status.request.strategies) {
          state.activeStrategies = event.status.request.strategies;
          buildStepper(state.activeStrategies, event.status.request.skip_calibration);
        }
        (event.history || []).forEach(handleEvent);
        return;
      }
      handleEvent(event);
    };
  }

  function handleEvent(event) {
    switch (event.type) {
      case "stage": updateStepper(event); break;
      case "row": addFeedItem(event); updateStrategyProgress(event); break;
      case "calibration_row": addCalibrationFeedItem(event); updateCalibrationProgress(event); break;
      case "strategy_summary":
        state.summaryByStrategy[event.strategy] = event.summary;
        renderCharts();
        break;
      case "summary":
        (event.rows || []).forEach(function (row) { state.summaryByStrategy[row.strategy] = row; });
        renderCharts();
        break;
      case "job_done":
        applyStatus({ status: event.status });
        if (event.status === "done") {
          if (state.browseStrategy) fetchBrowse(state.browseStrategy);
          fetch("/api/calibration").then(function (r) { return r.json(); }).then(function (d) { if (d) renderCalibration(d); }).catch(function () {});
        }
        break;
      case "error": showError(event.message); break;
    }
  }

  // ---------------- stepper ----------------
  function buildStepper(strategies, skipCalibration) {
    var steps = [
      { key: "data_loader", title: STAGE_TITLES.data_loader },
      { key: "ingest", title: STAGE_TITLES.ingest },
    ];
    if (!skipCalibration) steps.push({ key: "calibration", title: STAGE_TITLES.calibration });
    strategies.forEach(function (s) {
      var meta = STRATEGY_META[s] || { label: s };
      steps.push({ key: "strategy:" + s, title: "Run " + meta.label, progress: true });
    });
    steps.push({ key: "report", title: STAGE_TITLES.report });

    var container = $("stepper-steps");
    container.innerHTML = "";
    steps.forEach(function (step) {
      var div = document.createElement("div");
      div.className = "step pending";
      div.setAttribute("data-stage", step.key);
      div.innerHTML =
        '<div class="step-icon"><svg viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="3" style="display:none"><path d="M5 12l5 5L20 7"></path></svg></div>' +
        '<div class="step-body">' +
        '<div class="step-title">' + escapeHtml(step.title) + '</div>' +
        '<div class="step-detail"></div>' +
        (step.progress ? '<div class="step-progress" style="display:none"><div class="step-progress-bar"></div></div>' : "") +
        "</div>";
      container.appendChild(div);
    });
  }

  function stepEl(stage) { return document.querySelector('.step[data-stage="' + cssEscape(stage) + '"]'); }

  function updateStepper(event) {
    var el = stepEl(event.stage);
    if (!el) return;
    if (event.status === "start") {
      el.className = "step running";
      el.querySelector(".step-icon").innerHTML = '<span class="spinner"></span>';
    } else if (event.status === "done") {
      el.className = "step done";
      el.querySelector(".step-icon").innerHTML =
        '<svg viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="3"><path d="M5 12l5 5L20 7"></path></svg>';
      el.querySelector(".step-detail").textContent = summarizeStageDetail(event.stage, event.detail);
      var pb = el.querySelector(".step-progress");
      if (pb) pb.style.display = "none";
    }
  }

  function summarizeStageDetail(stage, detail) {
    if (!detail) return "";
    if (stage === "data_loader") return detail.eval_rows + " eval rows · " + detail.calibration_rows + " calibration · " + detail.corpus_docs + " docs";
    if (stage === "ingest") return detail.chunks + " chunks from " + detail.documents + " docs";
    if (stage.indexOf("strategy:") === 0) {
      var acc = detail.accuracy != null ? (detail.accuracy * 100).toFixed(0) + "% acc" : "";
      var hal = detail.hallucination_rate != null ? (detail.hallucination_rate * 100).toFixed(0) + "% halluc." : "";
      return [acc, hal].filter(Boolean).join(" · ");
    }
    return "";
  }

  function updateStrategyProgress(event) {
    var el = stepEl("strategy:" + event.strategy);
    if (!el) return;
    var pb = el.querySelector(".step-progress");
    var bar = el.querySelector(".step-progress-bar");
    if (pb) { pb.style.display = "block"; bar.style.width = (100 * event.index / event.total) + "%"; }
    el.querySelector(".step-detail").textContent = event.index + " / " + event.total + " questions";
  }

  function updateCalibrationProgress(event) {
    var el = stepEl("calibration");
    if (!el) return;
    el.querySelector(".step-detail").textContent = event.index + " / " + event.total + " rows";
  }

  // ---------------- calibration stat tiles ----------------
  function renderCalibration(detail) {
    setStat("cal-precision", detail.precision);
    setStat("cal-recall", detail.recall);
    setStat("cal-f1", detail.f1);
    setStat("cal-accuracy", detail.accuracy);
  }
  function setStat(id, v) {
    $(id).textContent = (v == null) ? "—" : (v * 100).toFixed(0) + "%";
  }

  // ---------------- live feed ----------------
  function clearFeed() {
    $("feed-list").innerHTML = '<div class="feed-empty">No activity yet.</div>';
    $("feed-hint").textContent = "waiting for a run…";
  }
  function ensureFeedReady() {
    var empty = $("feed-list").querySelector(".feed-empty");
    if (empty) empty.remove();
  }
  function pushFeedItem(el) {
    ensureFeedReady();
    var list = $("feed-list");
    list.appendChild(el);
    while (list.children.length > 40) list.removeChild(list.firstChild);
    $("feed-hint").textContent = "live";
  }
  function addFeedItem(event) {
    var meta = STRATEGY_META[event.strategy] || { label: event.strategy, color: "var(--muted)" };
    var badgeClass = event.judge_is_hallucinated ? "bad" : "ok";
    var badgeText = event.judge_label || (event.error ? "error" : "…");
    var el = document.createElement("div");
    el.className = "feed-item";
    el.innerHTML =
      '<span class="feed-dot" style="background:' + meta.color + '"></span>' +
      '<span class="feed-q" title="' + escapeHtml(event.query || "") + '">' + escapeHtml(meta.label) + ": " + escapeHtml(truncate(event.query, 70)) + "</span>" +
      '<span class="feed-badge ' + badgeClass + '">' + escapeHtml(badgeText) + "</span>" +
      '<span class="feed-meta">' + event.latency_seconds.toFixed(1) + "s · " + event.total_tokens + "tok</span>";
    pushFeedItem(el);
  }
  function addCalibrationFeedItem(event) {
    var match = event.predicted_is_hallucinated === event.actual_is_hallucinated;
    var el = document.createElement("div");
    el.className = "feed-item";
    el.innerHTML =
      '<span class="feed-dot" style="background:var(--accent)"></span>' +
      '<span class="feed-q">Calibration #' + event.index + ": predicted " + escapeHtml(event.predicted_label) + "</span>" +
      '<span class="feed-badge ' + (match ? "ok" : "bad") + '">' + (match ? "agree" : "disagree") + "</span>" +
      '<span class="feed-meta">' + event.index + "/" + event.total + "</span>";
    pushFeedItem(el);
  }

  // ---------------- legend ----------------
  function buildLegend() {
    var el = $("legend");
    el.innerHTML = "";
    STRATEGY_ORDER.forEach(function (s) {
      var meta = STRATEGY_META[s];
      var item = document.createElement("div");
      item.className = "legend-item";
      item.innerHTML = '<span class="legend-swatch" style="background:' + meta.color + '"></span>' + meta.label;
      el.appendChild(item);
    });
  }

  // ---------------- charts ----------------
  var METRICS = [
    { key: "accuracy", title: "Accuracy", unit: "judge-rated correctness", pct: true, max: 1 },
    { key: "hallucination_rate", title: "Hallucination Rate", unit: "Evident Conflict + Baseless Info", pct: true, max: 1 },
    { key: "ragas_faithfulness", title: "Faithfulness", unit: "RAGAS, 0–1", pct: false, max: 1 },
    { key: "ragas_answer_relevancy", title: "Answer Relevancy", unit: "RAGAS, 0–1", pct: false, max: 1 },
    { key: "avg_latency_seconds", title: "Avg. Latency", unit: "seconds / answer", pct: false, dynamicMax: true, suffix: "s" },
    { key: "avg_cost_usd", title: "Avg. Cost", unit: "USD / query", pct: false, dynamicMax: true, prefix: "$", decimals: 5 },
  ];

  function fmtValue(metric, v) {
    if (v == null) return "—";
    if (metric.pct) return (v * 100).toFixed(1) + "%";
    if (metric.prefix) return metric.prefix + v.toFixed(metric.decimals || 4);
    if (metric.suffix) return v.toFixed(2) + metric.suffix;
    return v.toFixed(3);
  }

  function renderCharts() {
    var grid = $("chart-grid");
    grid.innerHTML = "";
    METRICS.forEach(function (m) { grid.appendChild(buildBarChart(m)); });
    buildRadar();
  }

  function buildBarChart(metric) {
    var W = 240, H = 160, padL = 6, padR = 6, padT = 10, baseline = 128;
    var values = STRATEGY_ORDER.map(function (s) {
      var row = state.summaryByStrategy[s];
      return row && row[metric.key] != null ? row[metric.key] : null;
    });
    var maxVal = metric.max;
    if (metric.dynamicMax) {
      var present = values.filter(function (v) { return v != null; });
      maxVal = present.length ? Math.max.apply(null, present) * 1.25 : 1;
    }

    var svg = svgns("svg");
    svg.setAttribute("viewBox", "0 0 " + W + " " + H);
    svg.setAttribute("role", "img");
    svg.setAttribute("aria-label", metric.title + " by strategy");

    [0.25, 0.5, 0.75, 1].forEach(function (f) {
      var y = baseline - f * (baseline - padT);
      var line = svgns("line");
      line.setAttribute("x1", padL); line.setAttribute("x2", W - padR);
      line.setAttribute("y1", y); line.setAttribute("y2", y);
      line.setAttribute("class", "gridline"); line.setAttribute("stroke-width", "1");
      svg.appendChild(line);
    });
    var base = svgns("line");
    base.setAttribute("x1", padL); base.setAttribute("x2", W - padR);
    base.setAttribute("y1", baseline); base.setAttribute("y2", baseline);
    base.setAttribute("class", "gridline"); base.setAttribute("stroke-width", "1.4");
    svg.appendChild(base);

    var n = STRATEGY_ORDER.length;
    var slot = (W - padL - padR) / n;
    var barW = slot * 0.46;

    STRATEGY_ORDER.forEach(function (s, i) {
      var meta = STRATEGY_META[s];
      var v = values[i];
      var frac = v != null && maxVal > 0 ? Math.min(v / maxVal, 1) : 0;
      var h = frac * (baseline - padT);
      var x = padL + i * slot + (slot - barW) / 2;
      var y = baseline - h;

      var rect = svgns("rect");
      rect.setAttribute("x", x.toFixed(1));
      rect.setAttribute("y", y.toFixed(1));
      rect.setAttribute("width", barW.toFixed(1));
      rect.setAttribute("height", Math.max(h, v != null ? 2 : 0).toFixed(1));
      rect.setAttribute("rx", "3");
      rect.setAttribute("fill", meta.color);
      rect.setAttribute("opacity", v == null ? "0.18" : "1");
      rect.setAttribute("class", "bar-rect");
      var title = svgns("title");
      title.textContent = meta.label + ": " + fmtValue(metric, v);
      rect.appendChild(title);
      svg.appendChild(rect);

      if (v != null) {
        var label = svgns("text");
        label.setAttribute("x", (x + barW / 2).toFixed(1));
        label.setAttribute("y", (y - 5).toFixed(1));
        label.setAttribute("text-anchor", "middle");
        label.setAttribute("font-size", "9.5");
        label.setAttribute("class", "value-label");
        label.textContent = fmtValue(metric, v);
        svg.appendChild(label);
      }

      var axis = svgns("text");
      axis.setAttribute("x", (x + barW / 2).toFixed(1));
      axis.setAttribute("y", baseline + 13);
      axis.setAttribute("text-anchor", "middle");
      axis.setAttribute("font-size", "7.8");
      axis.setAttribute("class", "axis-label");
      axis.textContent = meta.label.replace("Chain-of-Thought", "CoT").replace("Structured Output", "Struct.");
      svg.appendChild(axis);
    });

    var card = document.createElement("div");
    card.className = "chart-card";
    var h4 = document.createElement("h4"); h4.textContent = metric.title;
    var unit = document.createElement("span"); unit.className = "chart-unit"; unit.textContent = metric.unit;
    card.appendChild(h4); card.appendChild(unit); card.appendChild(svg);
    return card;
  }

  function buildRadar() {
    var svg = $("radar-svg");
    svg.innerHTML = "";
    var axesDef = [
      { label: "Accuracy", key: "accuracy", invert: false },
      { label: "Faithfulness", key: "ragas_faithfulness", invert: false },
      { label: "Relevancy", key: "ragas_answer_relevancy", invert: false },
      { label: "1 − Hallucination", key: "hallucination_rate", invert: true },
    ];
    var cx = 190, cy = 155, R = 108;
    var n = axesDef.length;
    var angle = function (i) { return -Math.PI / 2 + i * (2 * Math.PI / n); };
    var pt = function (i, frac) {
      var a = angle(i);
      return [cx + Math.cos(a) * R * frac, cy + Math.sin(a) * R * frac];
    };

    [0.25, 0.5, 0.75, 1].forEach(function (f) {
      var pts = [];
      for (var i = 0; i < n; i++) pts.push(pt(i, f).join(","));
      var poly = svgns("polygon");
      poly.setAttribute("points", pts.join(" "));
      poly.setAttribute("fill", "none");
      poly.setAttribute("class", "gridline");
      poly.setAttribute("stroke-width", "1");
      svg.appendChild(poly);
    });

    for (var i = 0; i < n; i++) {
      var p0 = pt(i, 0), p1 = pt(i, 1);
      var line = svgns("line");
      line.setAttribute("x1", p0[0]); line.setAttribute("y1", p0[1]);
      line.setAttribute("x2", p1[0]); line.setAttribute("y2", p1[1]);
      line.setAttribute("class", "gridline"); line.setAttribute("stroke-width", "1");
      svg.appendChild(line);

      var lp = pt(i, 1.2);
      var t = svgns("text");
      t.setAttribute("x", lp[0]); t.setAttribute("y", lp[1]);
      t.setAttribute("text-anchor", i === 0 ? "middle" : (lp[0] > cx + 2 ? "start" : (lp[0] < cx - 2 ? "end" : "middle")));
      t.textContent = axesDef[i].label;
      svg.appendChild(t);
    }

    STRATEGY_ORDER.forEach(function (s) {
      var row = state.summaryByStrategy[s];
      if (!row) return;
      var meta = STRATEGY_META[s];
      var values = axesDef.map(function (ax) {
        var v = row[ax.key];
        if (v == null) return 0;
        return ax.invert ? 1 - v : v;
      });
      var pts = values.map(function (v, i) { return pt(i, Math.max(0, Math.min(1, v))); });
      var poly = svgns("polygon");
      poly.setAttribute("points", pts.map(function (p) { return p.join(","); }).join(" "));
      poly.setAttribute("fill", meta.color);
      poly.setAttribute("fill-opacity", "0.09");
      poly.setAttribute("stroke", meta.color);
      poly.setAttribute("stroke-width", "1.8");
      svg.appendChild(poly);
      pts.forEach(function (p) {
        var dot = svgns("circle");
        dot.setAttribute("cx", p[0]); dot.setAttribute("cy", p[1]);
        dot.setAttribute("r", "2.4"); dot.setAttribute("fill", meta.color);
        svg.appendChild(dot);
      });
    });
  }

  // ---------------- browse ----------------
  function buildBrowseTabs() {
    var container = $("browse-tabs");
    container.innerHTML = "";
    STRATEGY_ORDER.forEach(function (s, i) {
      var meta = STRATEGY_META[s];
      var btn = document.createElement("button");
      btn.className = "tab-btn" + (i === 0 ? " active" : "");
      btn.style.setProperty("--tab-color", meta.color);
      btn.textContent = meta.label;
      btn.addEventListener("click", function () {
        container.querySelectorAll(".tab-btn").forEach(function (b) { b.classList.remove("active"); });
        btn.classList.add("active");
        fetchBrowse(s);
      });
      container.appendChild(btn);
    });
    fetchBrowse(STRATEGY_ORDER[0]);
  }

  function fetchBrowse(strategy) {
    state.browseStrategy = strategy;
    $("browse-detail").innerHTML = "";
    if (state.browseRowsCache[strategy]) {
      renderBrowseTable(state.browseRowsCache[strategy]);
      return;
    }
    fetch("/api/raw/" + strategy).then(function (r) { return r.json(); }).then(function (data) {
      state.browseRowsCache[strategy] = data.rows || [];
      if (state.browseStrategy === strategy) renderBrowseTable(state.browseRowsCache[strategy]);
    }).catch(function () { renderBrowseTable([]); });
  }

  function renderBrowseTable(rows) {
    var tbody = $("browse-tbody");
    tbody.innerHTML = "";
    $("browse-empty").style.display = rows.length ? "none" : "block";
    rows.forEach(function (row, idx) {
      var tr = document.createElement("tr");
      var badgeClass = row.judge_is_hallucinated ? "bad" : "ok";
      tr.innerHTML =
        "<td>" + (idx + 1) + "</td>" +
        '<td class="q-cell" title="' + escapeHtml(row.query || "") + '">' + escapeHtml(row.query || "") + "</td>" +
        '<td><span class="feed-badge ' + badgeClass + '">' + escapeHtml(row.judge_label || "—") + "</span></td>" +
        "<td>" + (row.judge_is_correct == null ? "—" : (row.judge_is_correct ? "✓" : "✗")) + "</td>" +
        '<td class="num-cell">' + (row.latency_seconds != null ? row.latency_seconds.toFixed(2) + "s" : "—") + "</td>" +
        '<td class="num-cell">' + (row.total_tokens != null ? row.total_tokens : "—") + "</td>";
      tr.addEventListener("click", function () { showDetail(row); });
      tbody.appendChild(tr);
    });
  }

  function showDetail(row) {
    var html = '<div class="detail-card">' +
      '<button class="detail-close" id="detail-close">close ✕</button>' +
      "<h5>Question</h5><p>" + escapeHtml(row.query || "") + "</p>" +
      "<h5>Retrieved context</h5><p>" + escapeHtml(truncate(row.retrieved_context || "", 1400)) + "</p>";
    if (row.reasoning) html += "<h5>Reasoning (Chain-of-Thought)</h5><p>" + escapeHtml(row.reasoning) + "</p>";
    html += "<h5>Answer</h5><p>" + escapeHtml(row.answer || "") + "</p>";
    if (row.supporting_quotes && row.supporting_quotes.length) {
      html += "<h5>Supporting quotes (Structured Output)</h5><ul class=\"quote-list\">" +
        row.supporting_quotes.map(function (q) { return "<li>" + escapeHtml(q) + "</li>"; }).join("") + "</ul>";
    }
    if (row.is_grounded_self_reported != null) {
      html += "<h5>Self-reported grounding</h5><p>is_grounded=" + row.is_grounded_self_reported +
        ", confidence=" + row.confidence_self_reported + "</p>";
    }
    if (row.reference_answer) html += "<h5>RAGTruth reference answer</h5><p>" + escapeHtml(row.reference_answer) + "</p>";
    html += "<h5>Judge verdict</h5><p>" + escapeHtml(row.judge_label || "—") +
      " · correct=" + row.judge_is_correct + " · hallucinated=" + row.judge_is_hallucinated + "<br>" +
      escapeHtml(row.judge_rationale || "") + "</p>";
    html += "</div>";
    var el = $("browse-detail");
    el.innerHTML = html;
    $("detail-close").addEventListener("click", function () { el.innerHTML = ""; });
    el.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }

  // ---------------- utils ----------------
  function truncate(s, n) { s = s || ""; return s.length > n ? s.slice(0, n) + "…" : s; }
  function escapeHtml(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  function cssEscape(s) { return String(s).replace(/[:\.]/g, "\\$&"); }

  document.addEventListener("DOMContentLoaded", init);
})();
