/* Mailbox Triage — GitHub Pages demo. Replays docs/data/mailbox.json; "Try it" runs the Python pipeline in Pyodide. */
(() => {
  "use strict";

  const PYODIDE = "https://cdn.jsdelivr.net/npm/pyodide@0.27.7/";
  const ROUTES = ["JIRA", "SSI_CALLBACK", "HUMAN_REVIEW", "FYI"];
  const ROUTE_LABEL = { JIRA: "Jira ticket", SSI_CALLBACK: "SSI call-back", HUMAN_REVIEW: "Human review", FYI: "FYI" };
  const CAT = { TRADE_QUERY: "Trade query", SETTLEMENT_FAIL: "Settlement fail", SSI_UPDATE: "SSI update",
    CA_ELECTION: "CA election", PRICE_CHALLENGE: "Price challenge", OTHER: "Other" };
  const CATS = Object.keys(CAT);
  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  const $ = (s, el = document) => el.querySelector(s);
  const $$ = (s, el = document) => [...el.querySelectorAll(s)];
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const nf0 = new Intl.NumberFormat("en-US");
  const store = {
    get(k, d) { try { const v = localStorage.getItem(k); return v ? JSON.parse(v) : d; } catch { return d; } },
    set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* private mode */ } },
  };
  const D = {};

  // ------------------------------------------------------------------ helpers
  const pill = (cat) => `<span class="pill" style="--c:var(--c-${cat})">${esc(CAT[cat] || cat)}</span>`;
  const prio = (p) => (p ? `<span class="prio ${p}">${p}</span>` : "");
  const icon = {
    lock: '<svg width="12" height="12" viewBox="0 0 24 24" aria-hidden="true"><rect x="5" y="10" width="14" height="10" rx="2" fill="currentColor"/><path d="M8 10V7a4 4 0 0 1 8 0v3" fill="none" stroke="currentColor" stroke-width="2.2"/></svg>',
    person: '<svg width="12" height="12" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="8" r="4" fill="currentColor"/><path d="M4 21c1-4.5 4.5-7 8-7s7 2.5 8 7" fill="currentColor"/></svg>',
  };
  function dayLabel(iso) {
    const d = new Date(`${iso.slice(0, 10)}T12:00:00Z`);
    return d.toLocaleDateString("en-US", { weekday: "short", day: "numeric", month: "short", timeZone: "UTC" });
  }
  function highlight(text, spans) {
    const s = [...spans].sort((a, b) => a.start - b.start);
    let out = "", pos = 0;
    for (const sp of s) {
      if (sp.start < pos) continue;
      out += esc(text.slice(pos, sp.start)) + `<mark class="hl" data-f="${sp.field}">${esc(text.slice(sp.start, sp.end))}</mark>`;
      pos = sp.end;
    }
    return out + esc(text.slice(pos));
  }
  function fieldsHTML(ex) {
    const sec = ex.cusip ? `CUSIP ${ex.cusip}` : ex.isin ? `ISIN ${ex.isin}` : "—";
    const f = [
      ["trade_id", "Trade ID", (ex.trade_ids || []).join(", ") || "—"],
      ["cusip", "Security", sec],
      ["quantity", "Quantity", ex.quantity != null ? nf0.format(ex.quantity) : "—"],
      ["settlement_date", ex.deadline ? "Deadline" : "Settlement", ex.deadline || ex.settlement_date || "—"],
      ["cp", "Counterparty", ex.counterparty || "—"],
      ["conf", "Confidence", `${Math.round(ex.confidence * 100)}%`],
    ];
    return `<div class="fields">${f.map(([k, l, v]) => `<div class="field f-${k}"><span>${l}</span><b title="${esc(v)}">${esc(v)}</b></div>`).join("")}</div>`;
  }
  function decisionHTML(r) {
    const d = r.decision;
    const head = d.route === "JIRA"
      ? `${r.jira_action === "commented" ? "Comment on" : "Opened"} <span class="mono">${esc(r.jira_key)}</span> ${prio(d.priority)}`
      : d.route === "SSI_CALLBACK" ? `${icon.lock} SSI call-back. Not actioned from the email`
        : d.route === "HUMAN_REVIEW" ? `${icon.person} Sent to a person` : "FYI, no action";
    const items = (d.ssi_flags && d.ssi_flags.length ? d.ssi_flags : d.reasons) || [];
    return `<div class="decision" style="--rc:var(--r-${d.route})"><h4>${head}</h4>
      <ul>${items.map((x) => `<li>${esc(x)}</li>`).join("")}${r.draft ? "<li>Reply drafted, waiting for approval</li>" : ""}</ul></div>`;
  }
  function pathFor(r) {
    const p = ["IMAP", "Normalize", "Classify", "Controls", "Route"];
    const d = r.decision.route;
    if (d === "JIRA") p.push(r.jira_action === "commented" ? "Jira comment" : "Jira create", "Draft", "Postgres");
    else if (d === "SSI_CALLBACK") p.push("Call-back queue", "Alert static data");
    else if (d === "HUMAN_REVIEW") p.push("Review queue");
    else p.push("FYI");
    return p;
  }

  // ------------------------------------------------------------------ theme + stats
  function initTheme() {
    const saved = store.get("mt.theme", null);
    if (saved) document.documentElement.dataset.theme = saved;
    else if (window.matchMedia("(prefers-color-scheme: dark)").matches) document.documentElement.dataset.theme = "dark";
    $("#theme").addEventListener("click", () => {
      const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
      document.documentElement.dataset.theme = next;
      store.set("mt.theme", next);
    });
  }
  function renderStats() {
    const b = D.bench;
    const vals = { n: [b.n, ""], ssi: [b.ssi.routed_to_callback, `/${b.ssi.changes}`], wrong: [b.outcome.wrong || 0, ""], sent: [0, ""] };
    $$("#stats b").forEach((el) => {
      const [to, suf] = vals[el.dataset.k];
      if (reduceMotion || !to) { el.textContent = to + suf; return; }
      const t0 = performance.now();
      const tick = (t) => {
        const p = Math.min(1, (t - t0) / 1200), e = 1 - Math.pow(1 - p, 3);
        el.textContent = Math.round(to * e) + suf;
        if (p < 1) requestAnimationFrame(tick);
      };
      requestAnimationFrame(tick);
    });
  }

  // ------------------------------------------------------------------ live replay
  const L = { i: 0, playing: true, speed: 1, gen: 0, started: false, counts: {}, stats: {}, queue: [] };
  function resetLive() {
    L.i = 0; L.gen++;
    L.counts = Object.fromEntries(ROUTES.map((r) => [r, 0]));
    L.stats = { processed: 0, tickets: 0, comments: 0, drafts: 0, risk: 0 };
    $("#mailList").innerHTML = "";
    $$(".lane ol").forEach((o) => { o.innerHTML = ""; });
    $$(".lane header b").forEach((b) => { b.textContent = "0"; });
    renderKpis();
  }
  function renderKpis() {
    const s = L.stats, c = L.counts, n = s.processed || 0;
    const auto = n ? Math.round(((c.JIRA + c.FYI) / n) * 100) : 0;
    const k = [[n, "processed"], [`${auto}%`, "auto-handled"], [s.tickets, "tickets opened"], [s.comments, "follow-ups as comments"],
      [c.SSI_CALLBACK, "SSI call-backs"], [c.HUMAN_REVIEW, "to a person"], [s.drafts, "drafts awaiting approval"], [s.risk, "T+1 at risk"]];
    $("#kpis").innerHTML = k.map(([v, l]) => `<div class="kpi"><b>${v}</b><span>${l}</span></div>`).join("");
  }
  function laneCard(row) {
    const r = row.result, ex = r.extraction, d = r.decision, e = row.email;
    const ref = (ex.trade_ids || [])[0] || ex.cusip || ex.isin || "";
    if (d.route === "JIRA") {
      return `<li class="card"><div class="c-top"><span class="k">${esc(r.jira_key)}</span>${prio(d.priority)}${r.jira_action === "commented" ? '<span class="muted">+ comment</span>' : ""}</div>
        <div class="c-sub">${esc(CAT[ex.category])} · ${esc(ref)}${ex.counterparty ? ` · ${esc(ex.counterparty)}` : ""}</div></li>`;
    }
    if (d.route === "SSI_CALLBACK") {
      return `<li class="card"><div class="c-top">${icon.lock}<span>${esc(e.from_addr.split("@")[1])}</span></div><div class="c-sub">${esc(d.ssi_flags[0] || "")}</div></li>`;
    }
    if (d.route === "HUMAN_REVIEW") {
      return `<li class="card"><div class="c-top">${icon.person}<span class="c-sub" style="font-weight:600">${esc(e.subject)}</span></div><div class="c-sub">${esc(d.reasons[0] || "")}</div></li>`;
    }
    return `<li class="card"><div class="c-sub">${esc(e.subject)}</div></li>`;
  }
  function account(row) {
    const r = row.result, d = r.decision;
    L.counts[d.route]++;
    L.stats.processed++;
    if (r.jira_action === "created") L.stats.tickets++;
    if (r.jira_action === "commented") L.stats.comments++;
    if (r.draft) L.stats.drafts++;
    if (d.route === "JIRA" && ["Highest", "High"].includes(d.priority) && ["SETTLEMENT_FAIL", "TRADE_QUERY"].includes(r.extraction.category)) L.stats.risk++;
  }
  function pushLane(row, animate = true) {
    const lane = $(`.lane[data-route="${row.result.decision.route}"]`);
    const ol = $("ol", lane);
    ol.insertAdjacentHTML("afterbegin", laneCard(row));
    if (!animate) ol.firstElementChild.style.animation = "none";
    while (ol.children.length > 8) ol.lastElementChild.remove();
    $("header b", lane).textContent = L.counts[row.result.decision.route];
    if (animate && !reduceMotion) { lane.classList.remove("bump"); void lane.offsetWidth; lane.classList.add("bump"); }
  }
  function inboxItem(row, injected) {
    const e = row.email;
    const li = document.createElement("li");
    li.className = "mail now";
    li.innerHTML = `<div class="m-top"><span>${esc(e.from_name || e.from_addr)}</span><span>${e.received_at.slice(11, 16)}</span></div>
      <div class="m-sub">${esc(e.subject)}</div>${injected ? '<div class="m-route"><span class="tag">injected</span></div>' : ""}`;
    $$("#mailList .mail.now").forEach((m) => m.classList.remove("now"));
    $("#mailList").prepend(li);
    while ($("#mailList").children.length > 60) $("#mailList").lastElementChild.remove();
    return li;
  }
  function renderReader(host, row, opts = {}) {
    const e = row.email, r = row.result, ex = r.extraction;
    const subjSpans = (ex.spans || []).filter((s) => s.where === "subject");
    const bodySpans = (ex.spans || []).filter((s) => s.where !== "subject");
    host.innerHTML = `
      <div class="r-head"><div><h3>${highlight(e.subject, subjSpans)}</h3>
        <div class="r-from">${esc(e.from_name)} &lt;${esc(e.from_addr)}&gt; · ${dayLabel(e.received_at)} ${e.received_at.slice(11, 16)}</div></div>
        ${opts.label ? `<span class="tag">${esc(opts.label)}</span>` : ""}</div>
      <div class="r-tags">${pill(ex.category)}<span class="conf" style="--w:${Math.round(ex.confidence * 100)}%;--cc:var(--c-${ex.category})">confidence <i></i> ${Math.round(ex.confidence * 100)}%</span>
        ${row.label ? `<span class="tag">${esc(row.label.variant.replace(/_/g, " "))}</span>` : ""}</div>
      <div class="r-body scan">${highlight(e.body, bodySpans)}</div>
      <div class="r-fields"></div><div class="r-decision"></div>
      <div class="path">${pathFor(r).map((p) => `<span>${esc(p)}</span>`).join("")}</div>`;
  }
  async function revealReader(host, row, gen, fast) {
    const r = row.result;
    const body = $(".r-body", host);
    const marks = $$("mark.hl", host);
    const t = (ms) => (fast || reduceMotion ? Promise.resolve() : sleep(ms / L.speed));
    if (!fast && !reduceMotion) body.classList.add("scanning");
    for (const m of marks) { if (gen !== L.gen) return; m.classList.add("on"); await t(110); }
    $(".r-fields", host).innerHTML = fieldsHTML(r.extraction);
    await t(220);
    const steps = $$(".path span", host);
    for (const s of steps) { if (gen !== L.gen) return; s.classList.add("on"); await t(70); }
    $(".r-decision", host).innerHTML = decisionHTML(r);
  }
  async function liveLoop() {
    const gen = L.gen;
    while (gen === L.gen) {
      if (!L.playing) { await sleep(150); continue; }
      if (L.i >= L.queue.length) { setPlaying(false); return; }
      const item = L.queue[L.i++];
      const row = item.row;
      const li = inboxItem(row, item.injected);
      $("#clockDay").textContent = dayLabel(row.email.received_at);
      $("#clockTime").textContent = row.email.received_at.slice(11, 16);
      $("#progress").style.width = `${(L.i / L.queue.length) * 100}%`;
      $("#inboxCount").textContent = `${L.i} received`;
      renderReader($("#reader"), row, { label: item.injected ? "injected" : "" });
      await revealReader($("#reader"), row, gen, L.speed >= 16);
      if (gen !== L.gen) return;
      account(row);
      pushLane(row);
      li.classList.add("done");
      li.querySelector(".m-route")?.remove();
      li.insertAdjacentHTML("beforeend", `<div class="m-route"><span class="pill" style="--c:var(--r-${row.result.decision.route})">${ROUTE_LABEL[row.result.decision.route]}</span></div>`);
      renderKpis();
      await sleep(reduceMotion ? 50 : Math.max(40, 900 / L.speed));
    }
  }
  function setPlaying(p) {
    L.playing = p;
    $(".live-bar").classList.toggle("paused", !p);
    $("#play span").textContent = p ? "Pause" : (L.i >= L.queue.length ? "Replay" : "Play");
    $("#play").setAttribute("aria-label", p ? "Pause" : "Play");
  }
  function bindLive() {
    $("#play").addEventListener("click", () => {
      if (L.i >= L.queue.length) { resetLive(); setPlaying(true); liveLoop(); return; }
      setPlaying(!L.playing);
    });
    $("#speed").addEventListener("click", (e) => {
      const b = e.target.closest("button");
      if (!b) return;
      $$("#speed button").forEach((x) => x.setAttribute("aria-selected", x === b));
      L.speed = +b.dataset.s;
    });
    $("#spoof").addEventListener("click", () => {
      const spoofs = D.mail.filter((r) => r.label.variant === "lookalike_domain" || (r.label.variant === "loose" && r.label.ssi_change));
      const pick = spoofs[Math.floor(Math.random() * spoofs.length)];
      L.queue.splice(L.i, 0, { row: pick, injected: true });
      if (!L.playing) setPlaying(true);
      $("#live").scrollIntoView({ behavior: reduceMotion ? "auto" : "smooth", block: "start" });
    });
    $("#skipWeek").addEventListener("click", () => {
      L.gen++;
      while (L.i < L.queue.length) {
        const item = L.queue[L.i++];
        account(item.row);
        if (L.queue.length - L.i < 60) inboxItem(item.row, item.injected).classList.add("done");
        if (L.queue.length - L.i < 24) pushLane(item.row, false);
      }
      ROUTES.forEach((r) => { $(`.lane[data-route="${r}"] header b`).textContent = L.counts[r]; });
      const last = L.queue[L.queue.length - 1].row;
      renderReader($("#reader"), last);
      revealReader($("#reader"), last, L.gen, true);
      $("#progress").style.width = "100%";
      $("#inboxCount").textContent = `${L.queue.length} received`;
      $("#clockDay").textContent = "Fri 20 Nov";
      $("#clockTime").textContent = "18:30";
      renderKpis();
      setPlaying(false);
    });
    document.addEventListener("visibilitychange", () => { if (document.hidden && L.playing) setPlaying(false); });
    const io = new IntersectionObserver((en) => {
      if (!en.some((x) => x.isIntersecting) || L.started) return;
      L.started = true;
      io.disconnect();
      liveLoop();
    }, { threshold: 0.6 });
    io.observe($(".live-bar"));
  }

  // ------------------------------------------------------------------ try it (Pyodide)
  const PRESETS = [
    ["Fail notice", "Meridian Custody Settlements <settlements.notify@meridiancustody.example>", "FAIL NOTIFICATION - T7392210 - NVDA",
      "The following transaction has failed to settle.\n\nClient ref: T7392210\nSecurity: NVIDIA Corp\nISIN: US67066G1040\nQuantity: 42,500\nContractual settlement date: 17-Nov-2026\nCounterparty: Kestrel Prime\nFail reason: counterparty short\n\nPlease contact your counterparty.", false],
    ["Loosely worded", "Marcus Brennan <marcus.brennan@sablestreet.example>", "T7390114",
      "Can someone look at T7390114? Numbers don't tie out with what we have. 12,300 MSFT, CUSIP 594918104, settles tomorrow.", false],
    ["Spoofed bank change", "Leah Novak <leah.novak@ha1den-sec.example>", "URGENT - change of bank details",
      "Dear Operations,\n\nDue to an internal audit our bank details have changed with immediate effect. Please use the following for all payments and DVP settlements today:\n\nBeneficiary: Halden Securities\nAccount: 8812345678\nSWIFT: FCBKUS33\n\nDo not call the old number, it is being decommissioned.", true],
    ["Election deadline", "Atlas Trust Corporate Actions <corporate.actions@atlastrust.example>", "ELECTION REQUIRED: ASML voluntary tender offer",
      "Corporate action notification\n\nEvent: voluntary tender offer\nSecurity: ASML Holding NV (ISIN NL0010273215)\nAccount: HP Global Equity\nEligible position: 3,400\nResponse deadline: 11/19/2026 5:00 PM ET\n\nPlease submit your election before the deadline.", false],
    ["Bad CUSIP", "Kenji Mori <kenji.mori@northgatecm.example>", "Confirm mismatch T7394471",
      "Team - our confirm for T7394471 doesn't match your affirmation. Net amount is off by 1,240 USD. 8,000 JPM, CUSIP 46625H109, SD 11/19/2026. Please review.", false],
  ];
  const T = { ready: false, py: null, loading: false };
  function renderPresets() {
    $("#presets").innerHTML = PRESETS.map(([n, , , , bad], i) => `<button class="preset ${bad ? "bad" : ""}" type="button" data-i="${i}">${esc(n)}</button>`).join("");
    $("#presets").addEventListener("click", (e) => {
      const b = e.target.closest(".preset");
      if (!b) return;
      const [, from, subj, body] = PRESETS[+b.dataset.i];
      $("#tFrom").value = from; $("#tSubject").value = subj; $("#tBody").value = body;
      runTry();
    });
    const [, from, subj, body] = PRESETS[0];
    $("#tFrom").value = from; $("#tSubject").value = subj; $("#tBody").value = body;
  }
  function loadScript(src) {
    return new Promise((res, rej) => {
      const s = document.createElement("script");
      s.src = src; s.async = true; s.crossOrigin = "anonymous";
      s.onload = res; s.onerror = () => rej(new Error(`couldn't load ${src}`));
      document.head.append(s);
    });
  }
  async function bootPython() {
    if (T.loading) return;
    T.loading = true;
    try {
      $("#tStatus").textContent = "Downloading Python for the browser…";
      await loadScript(PYODIDE + "pyodide.js");
      const py = await window.loadPyodide({ indexURL: PYODIDE });
      $("#tStatus").textContent = "Loading the triage package…";
      const pkg = await fetch("py/triage.zip").then((r) => r.arrayBuffer());
      py.FS.mkdirTree("/home/pyodide/lib");
      py.unpackArchive(pkg, "zip", { extractDir: "/home/pyodide/lib" });
      py.runPython("import sys; sys.path.insert(0, '/home/pyodide/lib')\nfrom triage import web");
      T.py = py; T.ready = true;
      $("#tStatus").textContent = `Ready · Python ${py.runPython("import sys; sys.version.split()[0]")} in your browser`;
      $("#tGo").disabled = false;
      runTry();
    } catch (err) {
      console.error(err);
      $("#tStatus").textContent = "Python couldn't load in this browser. The live replay above still works.";
    }
  }
  function runTry() {
    if (!T.ready) return;
    const fromRaw = $("#tFrom").value.trim();
    const m = fromRaw.match(/^\s*"?(.*?)"?\s*<([^>]+)>\s*$/);
    const fromName = m ? m[1] : "", fromAddr = (m ? m[2] : fromRaw).toLowerCase();
    const when = $("#tWhen").value || "2026-11-18T10:30";
    const g = T.py.globals;
    g.set("S", $("#tSubject").value); g.set("B", $("#tBody").value); g.set("FN", fromName); g.set("FA", fromAddr);
    g.set("W", when.length === 16 ? `${when}:00` : when);
    const t0 = performance.now();
    const r = JSON.parse(T.py.runPython("web.triage(S, B, FN, FA, W)"));
    const ms = (performance.now() - t0).toFixed(1);
    const row = { email: { email_id: "TRY-1", received_at: r.received_at, from_name: fromName, from_addr: fromAddr, subject: $("#tSubject").value, body: $("#tBody").value }, result: r };
    const out = $("#tryOut");
    renderReader(out, row, { label: `${ms} ms` });
    revealReader(out, row, L.gen, false);
    if (r.jira_payload) out.insertAdjacentHTML("beforeend", `<details class="json"><summary>Jira REST payload (POST /rest/api/3/issue)</summary><pre>${esc(JSON.stringify(r.jira_payload, null, 2))}</pre></details>`);
    if (r.draft) out.insertAdjacentHTML("beforeend", `<div class="draft-box"><h4>Draft reply, waiting for approval</h4>${esc(r.draft)}</div>`);
  }
  function bindTry() {
    renderPresets();
    $("#tGo").disabled = true;
    $("#tryForm").addEventListener("submit", (e) => { e.preventDefault(); runTry(); });
    const io = new IntersectionObserver((en) => {
      if (en.some((x) => x.isIntersecting)) { io.disconnect(); bootPython(); }
    }, { rootMargin: "600px 0px" });
    io.observe($("#try"));
  }

  // ------------------------------------------------------------------ drafts
  function renderDrafts() {
    const picks = [];
    const seen = new Set();
    for (const r of D.mail) {
      if (!r.result.draft) continue;
      const c = r.result.extraction.category;
      if (seen.has(c) && picks.length < 4) continue;
      seen.add(c);
      picks.push(r);
      if (picks.length >= 6) break;
    }
    const state = store.get("mt.drafts", {});
    const total = D.dash.drafts;
    const draw = () => {
      const approved = picks.filter((r) => state[r.email.email_id]?.s === "approved").length;
      const discarded = picks.filter((r) => state[r.email.email_id]?.s === "discarded").length;
      $("#draftsOut").innerHTML = `<div class="drafts-sum"><span><b>${nf0.format(total - approved - discarded)}</b> drafts waiting</span>
          <span><b>${approved}</b> approved by you</span><span><b>${discarded}</b> discarded</span><span><b>0</b> sent without approval</span></div>`
        + picks.map((r) => {
          const st = state[r.email.email_id] || {};
          const ex = r.result.extraction;
          return `<article class="dcard ${st.s || ""}" data-id="${r.email.email_id}">
            <div class="d-top"><span class="mono">${esc(r.result.jira_key)}</span>${pill(ex.category)}</div>
            <h4>RE: ${esc(r.email.subject)}</h4>
            <div class="muted small">To ${esc(r.email.from_addr)}</div>
            <textarea aria-label="Draft reply" ${st.s ? "disabled" : ""}>${esc(st.text || r.result.draft)}</textarea>
            ${st.s ? `<div class="d-status" style="color:var(--${st.s === "approved" ? "ok" : "text2"})">${st.s === "approved" ? "Approved. The approval webhook would send it and mark it SENT." : "Discarded. Nothing sent."}</div>
              <div class="d-act"><button class="btn sm" data-a="undo" type="button">Undo</button></div>`
              : `<div class="d-act"><button class="btn sm ok" data-a="approve" type="button">Approve</button><button class="btn sm danger" data-a="discard" type="button">Discard</button></div>`}
          </article>`;
        }).join("");
    };
    draw();
    $("#draftsOut").addEventListener("click", (e) => {
      const b = e.target.closest("button[data-a]");
      if (!b) return;
      const card = b.closest(".dcard");
      const id = card.dataset.id;
      if (b.dataset.a === "undo") delete state[id];
      else state[id] = { s: b.dataset.a === "approve" ? "approved" : "discarded", text: $("textarea", card).value };
      store.set("mt.drafts", state);
      draw();
    });
  }

  // ------------------------------------------------------------------ workflow canvas
  const W = { nodes: [], byName: {} };
  function wrap(label, n = 15) {
    const words = label.split(" "), lines = [];
    let cur = "";
    for (const w of words) {
      if ((cur + " " + w).trim().length > n && cur) { lines.push(cur); cur = w; } else cur = (cur + " " + w).trim();
    }
    if (cur) lines.push(cur);
    return lines.slice(0, 3);
  }
  function nodeIcon(n) {
    const t = n.type.split(".").pop();
    const url = n.parameters.url || "";
    if (t === "emailReadImap") return ["mail", "#ff9f0a"];
    if (t === "code") return ["code", "#ff6b2c"];
    if (t === "httpRequest") return url.includes("openai") ? ["ai", "#30d158"] : ["jira", "#2997ff"];
    if (t === "postgres") return ["db", "#5e5ce6"];
    if (t === "switch" || t === "if") return ["fork", "#bf5af2"];
    if (t === "emailSend") return ["send", "#ff375f"];
    return ["dot", "#8e8e93"];
  }
  const GLYPH = {
    mail: '<path d="M-9 -6h18v12h-18z M-9 -6l9 7 9-7" fill="none" stroke="#fff" stroke-width="2" stroke-linejoin="round"/>',
    code: '<path d="M-4 -7l-5 7 5 7M4 -7l5 7-5 7" fill="none" stroke="#fff" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/>',
    ai: '<text x="0" y="4.5" text-anchor="middle" fill="#fff" style="font:700 12px var(--sans)">AI</text>',
    jira: '<path d="M0 -8l8 8-8 8-8-8z" fill="none" stroke="#fff" stroke-width="2.2"/><path d="M0 -3l3 3-3 3-3-3z" fill="#fff"/>',
    db: '<ellipse cx="0" cy="-5" rx="7" ry="2.8" fill="none" stroke="#fff" stroke-width="2"/><path d="M-7 -5v10c0 1.5 3 2.8 7 2.8s7-1.3 7-2.8V-5" fill="none" stroke="#fff" stroke-width="2"/>',
    fork: '<path d="M-8 0h6l6-6h4M-2 0l6 6h4" fill="none" stroke="#fff" stroke-width="2.2" stroke-linecap="round"/>',
    send: '<path d="M-8 -1l16-7-6 16-3-6z" fill="none" stroke="#fff" stroke-width="2" stroke-linejoin="round"/>',
    dot: '<circle r="4" fill="#fff"/>',
  };
  function renderWorkflow() {
    const wf = D.wf;
    const S = 0.56, SY = 0.8, T = 62;
    const xs = wf.nodes.map((n) => n.position[0]), ys = wf.nodes.map((n) => n.position[1]);
    const minX = Math.min(...xs), minY = Math.min(...ys);
    const pos = (n) => [40 + (n.position[0] - minX) * S, 30 + (n.position[1] - minY) * SY];
    const width = 80 + (Math.max(...xs) - minX) * S + T + 40, height = 60 + (Math.max(...ys) - minY) * SY + T + 60;
    const svg = $("#wf");
    svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
    svg.setAttribute("width", width);
    svg.setAttribute("height", height);
    const edges = [];
    for (const [src, c] of Object.entries(wf.connections)) {
      const a = wf.nodes.find((n) => n.name === src);
      c.main.forEach((outs, oi) => outs.forEach((t) => {
        const b = wf.nodes.find((n) => n.name === t.node);
        const [x1, y1] = pos(a), [x2, y2] = pos(b);
        const sx = x1 + T, sy = y1 + T / 2 + (c.main.length > 1 ? (oi - (c.main.length - 1) / 2) * 10 : 0), ex = x2, ey = y2 + T / 2;
        const mx = (sx + ex) / 2;
        let label = "";
        if (a.type.endsWith(".switch")) label = a.parameters.rules.values[oi].outputKey;
        if (a.type.endsWith(".if")) label = oi === 0 ? "true" : "false";
        edges.push(`<path class="we" data-a="${esc(src)}" data-b="${esc(t.node)}" d="M${sx},${sy} C${mx},${sy} ${mx},${ey} ${ex},${ey}"/>`
          + (label ? `<text class="wlabel" x="${ex - 6}" y="${ey - 7}" text-anchor="end">${esc(label)}</text>` : ""));
      }));
    }
    const nodes = wf.nodes.map((n) => {
      const [x, y] = pos(n);
      const [g, color] = nodeIcon(n);
      const lines = wrap(n.name);
      return `<g class="wn" data-n="${esc(n.name)}" tabindex="0" role="button" aria-label="${esc(n.name)}">
        <rect class="box" x="${x}" y="${y}" width="${T}" height="${T}" rx="14"/>
        <circle class="ico" cx="${x + T / 2}" cy="${y + T / 2}" r="17" style="--wc:${color}"/>
        <g transform="translate(${x + T / 2} ${y + T / 2})">${GLYPH[g]}</g>
        ${lines.map((l, i) => `<text x="${x + T / 2}" y="${y + T + 16 + i * 14}" text-anchor="middle">${esc(l)}</text>`).join("")}
      </g>`;
    }).join("");
    svg.innerHTML = edges.join("") + nodes;
    svg.addEventListener("click", (e) => { const g = e.target.closest(".wn"); if (g) showNode(g.dataset.n); });
    svg.addEventListener("keydown", (e) => { if (e.key === "Enter") { const g = e.target.closest(".wn"); if (g) showNode(g.dataset.n); } });
    $("#wfRun").addEventListener("click", runThrough);
    showNode("Parse + controls");
  }
  function showNode(name) {
    const n = D.wf.nodes.find((x) => x.name === name);
    $$(".wn").forEach((g) => g.classList.toggle("sel", g.dataset.n === name));
    const p = n.parameters;
    let body;
    if (p.jsCode) body = p.jsCode.split("\n").slice(0, 60).join("\n") + (p.jsCode.split("\n").length > 60 ? "\n…" : "");
    else if (p.query) body = p.query;
    else if (p.url) body = `${p.method} ${p.url}\n\nbody: ${p.jsonBody || ""}`;
    else body = JSON.stringify(p, null, 2);
    $("#wfDetail").innerHTML = `<h4>${esc(n.name)}</h4><p class="muted small" style="margin:0 0 8px"><span class="mono">${esc(n.type)}</span> v${n.typeVersion}${n.credentials ? ` · credential: ${esc(Object.values(n.credentials)[0].name)}` : ""}</p><pre>${esc(body)}</pre>`;
  }
  async function runThrough() {
    const rows = D.mail;
    const row = rows[Math.floor(Math.random() * rows.length)];
    const r = row.result, d = r.decision;
    const path = ["Shared mailbox (IMAP)", "Normalize email", "Build OpenAI request", "OpenAI: classify + extract", "Parse + controls", "Save triage result", "Route"];
    if (d.route === "JIRA") path.push("Build Jira payload", "Jira: find open ticket", "Already open?", r.jira_action === "commented" ? "Jira: add comment" : "Jira: create issue", "Build draft request", "OpenAI: draft reply", "Save draft (pending approval)");
    else if (d.route === "SSI_CALLBACK") path.push("Queue SSI call-back", "Alert static data team");
    else if (d.route === "HUMAN_REVIEW") path.push("Queue for human review");
    else path.push("FYI - no action");
    $$(".wn").forEach((g) => g.classList.remove("lit"));
    $$(".we").forEach((p) => p.classList.remove("lit"));
    $("#wfNote").innerHTML = `${esc(row.email.email_id)} · “${esc(row.email.subject)}” → <b>${ROUTE_LABEL[d.route]}</b>${r.jira_key ? ` ${esc(r.jira_key)}` : ""}${d.priority && d.route === "JIRA" ? ` (${d.priority})` : ""}`;
    $("#wfRun").disabled = true;
    for (let i = 0; i < path.length; i++) {
      const g = $(`.wn[data-n="${CSS.escape(path[i])}"]`);
      if (g) g.classList.add("lit");
      if (i) { const e = $(`.we[data-a="${CSS.escape(path[i - 1])}"][data-b="${CSS.escape(path[i])}"]`); if (e) e.classList.add("lit"); }
      if (g && i > 3) { const sc = $("#wfScroll"); const bx = g.getBBox(); if (bx.x * 1 > sc.scrollLeft + sc.clientWidth - 140) sc.scrollTo({ left: bx.x - 200, behavior: reduceMotion ? "auto" : "smooth" }); }
      await sleep(reduceMotion ? 0 : 230);
    }
    $("#wfRun").disabled = false;
  }

  // ------------------------------------------------------------------ dashboard
  function renderDash() {
    const b = D.bench, d = D.dash;
    const days = Object.keys(d.by_day);
    const kpi = [[b.n, "emails received"], [`${Math.round(b.auto_handled * 100)}%`, "auto-handled"], [d.tickets, `tickets opened (+${d.comments} comments)`],
      [b.routes.SSI_CALLBACK, "SSI call-backs"], [b.routes.HUMAN_REVIEW, "sent to a person"], [d.drafts, "drafts awaiting approval"]];
    const maxDay = Math.max(...days.map((k) => Object.values(d.by_day[k]).reduce((a, x) => a + x, 0)));
    const cw = 640, ch = 230, bw = 64, gap = (cw - 60 - days.length * bw) / (days.length - 1 || 1);
    let cols = "";
    days.forEach((k, i) => {
      let y = ch - 26;
      const x = 40 + i * (bw + gap);
      for (const c of CATS) {
        const v = d.by_day[k][c] || 0;
        const h = (v / maxDay) * (ch - 50);
        if (v) cols += `<rect x="${x}" y="${y - h}" width="${bw}" height="${Math.max(0, h - 2)}" rx="4" style="fill:var(--c-${c})"><title>${dayLabel(k)}: ${v} ${CAT[c]}</title></rect>`;
        y -= h;
      }
      const tot = Object.values(d.by_day[k]).reduce((a, x) => a + x, 0);
      cols += `<text class="ax" x="${x + bw / 2}" y="${ch - 8}" text-anchor="middle">${dayLabel(k).split(",")[0]}</text><text class="ax" x="${x + bw / 2}" y="${y - 8}" text-anchor="middle">${tot}</text>`;
    });
    const tot = ROUTES.reduce((a, r) => a + (b.routes[r] || 0), 0);
    let ang = -Math.PI / 2, donut = "";
    for (const r of ROUTES) {
      const v = b.routes[r] || 0, a2 = ang + (v / tot) * Math.PI * 2;
      const large = a2 - ang > Math.PI ? 1 : 0, R = 70, rr = 44;
      const p = (a, rad) => [100 + rad * Math.cos(a), 100 + rad * Math.sin(a)];
      const [x1, y1] = p(ang, R), [x2, y2] = p(a2, R), [x3, y3] = p(a2, rr), [x4, y4] = p(ang, rr);
      donut += `<path d="M${x1},${y1} A${R},${R} 0 ${large} 1 ${x2},${y2} L${x3},${y3} A${rr},${rr} 0 ${large} 0 ${x4},${y4}Z" style="fill:var(--r-${r})"><title>${ROUTE_LABEL[r]}: ${v}</title></path>`;
      ang = a2;
    }
    const bars = (items, color) => `<div class="bars">${items.map(([l, v, max, txt, c]) => `<div class="bar"><span>${esc(l)}</span><span class="bt"><i style="--c:${c || color}" data-w="${max ? (v / max) * 100 : 0}"></i></span><b>${txt ?? v}</b></div>`).join("")}</div>`;
    const pr = ["Highest", "High", "Medium", "Low"].map((p) => [p, d.priority[p] || 0]);
    const pmax = Math.max(...pr.map((x) => x[1]));
    const fmax = Math.max(...d.counterparty_fails.map((x) => x[1]));
    const st = b.by_style;
    const styleRows = [["Plain", st.plain], ["Tricky", st.hard], ["Loosely worded", st.loose]].filter((x) => x[1]);
    $("#dash").innerHTML = kpi.map(([v, l]) => `<div class="dk"><b>${v}</b><span>${l}</span></div>`).join("")
      + `<div class="dc span4"><h3>Emails by day and category</h3><svg viewBox="0 0 ${cw} ${ch}" width="100%" role="img" aria-label="Emails by day">${cols}</svg>
          <div class="legend">${CATS.map((c) => `<span><i style="--c:var(--c-${c})"></i>${CAT[c]}</span>`).join("")}</div></div>
        <div class="dc span2"><h3>Where they went</h3><svg viewBox="0 0 200 200" width="100%" style="max-width:220px;display:block;margin:auto" role="img" aria-label="Routes">${donut}
          <text x="100" y="98" text-anchor="middle" style="fill:var(--text);font:700 26px var(--sans)">${tot}</text><text x="100" y="118" text-anchor="middle" class="ax">emails</text></svg>
          <div class="legend">${ROUTES.map((r) => `<span><i style="--c:var(--r-${r})"></i>${ROUTE_LABEL[r]} ${b.routes[r] || 0}</span>`).join("")}</div></div>
        <div class="dc span3"><h3>Ticket priority (T+1)</h3>${bars(pr.map(([p, v]) => [p, v, pmax]), "var(--accent)")}
          <p class="note">Fails are never below High. Trade queries go Highest when settlement is today or past, High at T+1. Thanksgiving is in the calendar.</p></div>
        <div class="dc span3"><h3>Fail emails by counterparty</h3>${bars(d.counterparty_fails.map(([c, v]) => [c, v, fmax]), "var(--c-SETTLEMENT_FAIL)")}</div>
        <div class="dc span3"><h3>Rules baseline: category accuracy by how the email was written</h3>
          ${bars(styleRows.map(([l, s]) => [`${l} · ${s.n}`, s.correct, s.n, `${Math.round(s.accuracy * 100)}%`, s.accuracy > 0.9 ? "var(--ok)" : "var(--warn)"]))}
          <p class="note">Keyword rules are perfect on well-formed mail and fall apart on how people actually type. That's why the LLM does the reading in production. Every rules miss still landed with a person: <b>${b.outcome.wrong || 0}</b> misrouted.</p></div>
        <div class="dc span3"><h3>Field extraction (rules baseline)</h3>
          ${bars(Object.entries(b.fields).map(([f, v]) => [f.replace(/_/g, " "), v.correct, v.n, `${Math.round(v.accuracy * 100)}%`, "var(--c-TRADE_QUERY)"]))}
          <p class="note">SSI changes routed to call-back: <b>${b.ssi.routed_to_callback}/${b.ssi.changes}</b>, false alarms ${b.ssi.false_positives}. Priority right on <b>${b.priority.correct}/${b.priority.n}</b> correctly opened tickets.</p></div>`;
    const io = new IntersectionObserver((en) => {
      if (!en.some((x) => x.isIntersecting)) return;
      io.disconnect();
      $$("#dash i[data-w]").forEach((i, k) => setTimeout(() => { i.style.width = `${i.dataset.w}%`; }, k * 50));
    }, { threshold: 0.15 });
    io.observe($("#dash"));
  }

  // ------------------------------------------------------------------ boot
  function reveal() {
    const els = $$(".reveal");
    if (reduceMotion || !("IntersectionObserver" in window)) { els.forEach((e) => e.classList.add("in")); return; }
    const io = new IntersectionObserver((en) => en.forEach((x) => { if (x.isIntersecting) { x.target.classList.add("in"); io.unobserve(x.target); } }), { threshold: 0.06 });
    els.forEach((e) => io.observe(e));
  }
  async function boot() {
    initTheme();
    reveal();
    try {
      const [mail, bench, dash, wf] = await Promise.all(["mailbox", "benchmark", "dashboard", "mailbox_triage"].map((n) =>
        fetch(`data/${n}.json`).then((r) => { if (!r.ok) throw new Error(`${n}: ${r.status}`); return r.json(); })));
      Object.assign(D, { mail, bench, dash, wf });
    } catch (e) {
      console.error(e);
      $("#reader").innerHTML = `<p class="muted">Couldn't load the demo data (${esc(e.message)}).</p>`;
      return;
    }
    renderStats();
    L.queue = D.mail.map((row) => ({ row, injected: false }));
    resetLive();
    bindLive();
    bindTry();
    renderDrafts();
    renderWorkflow();
    renderDash();
  }
  document.addEventListener("DOMContentLoaded", boot);
})();
