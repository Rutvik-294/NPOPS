/* NPOPS console SPA — vanilla JS, hash routing, fetch API client. */
"use strict";

// ---------- API client ----------
const state = { user: null, csrf: null, season: 2026, trackingTimer: null };

async function api(path, opts = {}) {
  const headers = { "Content-Type": "application/json", ...(opts.headers || {}) };
  if (state.csrf && !["GET", "HEAD"].includes((opts.method || "GET").toUpperCase())) {
    headers["X-CSRF-Token"] = state.csrf;
  }
  const resp = await fetch(path, { ...opts, headers, credentials: "same-origin" });
  if (resp.status === 401 && !path.includes("/auth/")) {
    renderLogin();
    throw new Error("Session expired — sign in again");
  }
  const body = await resp.json().catch(() => ({}));
  if (!resp.ok) throw new Error(body.error || `HTTP ${resp.status}`);
  return body;
}

// ---------- helpers ----------
const $ = (sel, el = document) => el.querySelector(sel);
const fmt = (n, d = 0) => Number(n).toLocaleString("en-US", { maximumFractionDigits: d, minimumFractionDigits: d });
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

function toast(msg, isError = false) {
  const el = document.createElement("div");
  el.className = "toast" + (isError ? " error" : "");
  el.textContent = msg;
  $("#toasts").appendChild(el);
  setTimeout(() => el.remove(), 4200);
}

function kpiTile(label, value, sub = "", cls = "") {
  return `<div class="card kpi-tile ${cls}">
    <div class="kpi-label">${esc(label)}</div>
    <div class="kpi-value">${value}</div>
    ${sub ? `<div class="kpi-sub">${esc(sub)}</div>` : ""}</div>`;
}

function badge(status) {
  return `<span class="badge ${esc(status)}">${esc(status.replace(/_/g, " "))}</span>`;
}

// ---------- equirectangular projection for the operations map ----------
function proj(lat, lon, w, h) {
  return [((lon + 180) / 360) * w, ((90 - lat) / 180) * h];
}

function worldMap(cities, routes, currentPos) {
  const W = 720, H = 360;
  // simple continent outlines: coarse polylines (lat,lon chains)
  const landmasses = [
    // North America
    [[70,-160],[70,-140],[60,-130],[55,-125],[48,-125],[40,-124],[32,-117],[23,-110],[20,-105],[16,-95],[8,-80],[10,-84],[15,-92],[20,-97],[28,-95],[30,-90],[25,-80],[31,-81],[38,-75],[45,-65],[52,-56],[60,-65],[66,-75],[70,-85],[72,-100],[70,-160]],
    // South America
    [[12,-72],[10,-62],[5,-52],[0,-50],[-5,-35],[-15,-39],[-23,-42],[-34,-53],[-42,-62],[-52,-70],[-55,-68],[-48,-74],[-38,-73],[-30,-71],[-18,-70],[-5,-81],[2,-80],[8,-77],[12,-72]],
    // Europe
    [[71,25],[65,12],[58,5],[52,4],[48,-2],[43,-1],[36,-6],[35,0],[38,16],[41,13],[45,13],[54,10],[57,8],[62,5],[68,15],[71,25]],
    // Africa
    [[35,-6],[32,-9],[22,-17],[15,-17],[12,-16],[5,-4],[4,9],[-2,9],[-10,13],[-18,11],[-26,15],[-34,18],[-35,25],[-29,31],[-17,38],[-10,40],[-2,42],[5,48],[11,51],[12,43],[20,37],[31,32],[35,-6]],
    // Asia
    [[66,45],[70,90],[72,130],[66,180],[60,160],[55,140],[48,140],[43,132],[38,128],[30,122],[22,110],[15,109],[8,105],[1,104],[8,98],[15,95],[20,90],[22,88],[15,80],[8,77],[20,72],[25,66],[25,57],[28,50],[24,52],[13,45],[13,43],[20,39],[28,34],[31,30],[36,36],[45,38],[55,60],[60,70],[66,45]],
    // Australia
    [[-11,131],[-12,137],[-17,141],[-11,143],[-25,153],[-33,152],[-38,148],[-38,141],[-33,116],[-31,115],[-22,114],[-17,122],[-11,131]],
    // Greenland
    [[60,-44],[70,-22],[76,-18],[81,-20],[80,-60],[70,-54],[60,-44]],
  ];
  let land = "";
  for (const chain of landmasses) {
    const pts = chain.map(([la, lo]) => proj(la, lo, W, H).join(",")).join(" ");
    land += `<polyline class="map-land" points="${pts}" fill="var(--bg-inset)"/>`;
  }
  let routeEls = "";
  (routes || []).forEach((r, ri) => {
    const ids = JSON.parse(r.city_ids || "[]");
    const pts = ids.map(id => {
      const c = cities.find(x => x.id === id);
      return c ? proj(c.lat, c.lon, W, H) : null;
    }).filter(Boolean);
    const np = proj(90, 0, W, H);
    if (pts.length) {
      const d = `M ${np[0]} ${np[1]} L ${pts.map(p => p.join(" ")).join(" L ")} L ${np[0]} ${np[1]}`;
      routeEls += `<path class="map-route ${ri % 2 ? "leg2" : ""}" d="${d}"/>`;
    }
    for (const p of pts) routeEls += `<circle class="map-stop" cx="${p[0]}" cy="${p[1]}" r="2.2"/>`;
  });
  let hot = "";
  if (currentPos) {
    const p = proj(currentPos.lat, currentPos.lon, W, H);
    hot = `<circle class="map-stop hot" cx="${p[0]}" cy="${p[1]}" r="5"><animate attributeName="r" values="4;7;4" dur="1.6s" repeatCount="indefinite"/></circle>`;
  }
  const np = proj(90, 0, W, H);
  return `<div class="map-box"><svg viewBox="0 0 ${W} ${H}" role="img" aria-label="World route map">
    ${land}${routeEls}
    <circle class="map-depot" cx="${np[0]}" cy="${np[1]}" r="3.5"/>
    <text class="map-label" x="${np[0] + 6}" y="${np[1] - 6}">NORTH POLE</text>
    ${hot}</svg></div>`;
}

// ---------- views ----------
const views = {};

// login renders inside the shell; sidebar hidden via body class
views.login = async () => {
  document.body.classList.add("logged-out");
  const view = $("#view");
  view.innerHTML = `<div class="login-wrap"><div class="login-card card">
    <div class="brand">
      <svg class="brand-mark" viewBox="0 0 32 32"><circle cx="16" cy="16" r="13" class="brand-ring"/><path d="M16 6 L20 16 L16 26 L12 16 Z" class="brand-star"/><line x1="5" y1="16" x2="27" y2="16" class="brand-axis"/></svg>
      <div><div class="brand-name">NPOPS</div><div class="brand-sub">North Pole Operations</div></div>
    </div>
    <form id="login-form">
      <div class="field"><label for="f-user">Username</label><input id="f-user" name="username" autocomplete="username" required></div>
      <div class="field"><label for="f-pass">Password</label><input id="f-pass" type="password" name="password" autocomplete="current-password" required></div>
      <button class="btn" type="submit" style="width:100%">Sign in</button>
      <p class="login-error" id="login-error"></p>
    </form>
    <p class="tiny">Demo accounts: sclaus / ho-ho-ho · tinsel / joy · holly / joy</p>
  </div></div>`;
  $("#login-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    try {
      const me = await api("/api/auth/login", { method: "POST", body: JSON.stringify({
        username: $("#f-user").value, password: $("#f-pass").value }) });
      state.user = me.user;
      await loadMe();
      document.body.classList.remove("logged-out");
      bootShell();
      location.hash = "#/dashboard";
    } catch (err) {
      $("#login-error").textContent = err.message;
    }
  });
};

async function loadMe() {
  const me = await api("/api/auth/me");
  state.user = me;
  state.csrf = me.csrf_token;
}

const NAV = [
  ["Operations", [
    ["#/dashboard", "Dashboard"],
    ["#/tracking", "Live Tracking"],
    ["#/routes", "Route Planner"],
  ]],
  ["Workshop", [
    ["#/production", "Production & MRP"],
    ["#/inventory", "Inventory"],
  ]],
  ["Christmas Ops", [
    ["#/list", "Naughty & Nice"],
  ]],
  ["Governance", [
    ["#/admin", "Admin"],
  ]],
];

function bootShell() {
  const nav = $("#nav");
  nav.innerHTML = NAV.map(([group, items]) =>
    `<div class="nav-group">${esc(group)}</div>` +
    items.map(([href, label]) => `<a href="${href}" data-href="${href}">${esc(label)}</a>`).join("")
  ).join("");
  $("#user-chip").innerHTML = `<b>${esc(state.user.full_name)}</b>${esc(state.user.role)}`;
  $("#logout-btn").onclick = async () => {
    await api("/api/auth/logout", { method: "POST" }).catch(() => {});
    if (state.trackingTimer) clearInterval(state.trackingTimer);
    state.user = null; state.csrf = null;
    views.login();
  };
  window.addEventListener("hashchange", route);
  route();
}

function route() {
  if (!state.user) return;
  const hash = location.hash || "#/dashboard";
  const name = hash.replace("#/", "").split("?")[0] || "dashboard";
  const fn = views[name.replace("-", "_")] || views.dashboard;
  document.querySelectorAll(".nav a").forEach(a =>
    a.classList.toggle("active", a.dataset.href === "#/" + name));
  $("#page-title").textContent =
    (NAV.flatMap(([, items]) => items).find(([h]) => h === "#/" + name) || [, name])[1];
  if (state.trackingTimer && name !== "tracking") {
    clearInterval(state.trackingTimer);
    state.trackingTimer = null;
  }
  fn().catch(err => { toast(err.message, true); console.error(err); });
}

// ---------- dashboard ----------
views.dashboard = async () => {
  const year = state.season;
  const [kpis, stats, alerts, plan] = await Promise.all([
    api(`/api/kpis?year=${year}`),
    api("/api/list/stats"),
    api("/api/inventory/alerts"),
    api(`/api/plan?year=${year}`).catch(() => null),
  ]);
  const cities = plan ? await api("/api/cities") : [];
  $("#view").innerHTML = `
    <div class="grid kpi">
      ${kpiTile("Nice children", fmt(kpis.nice_children), "on the delivery manifest", "good")}
      ${kpiTile("Gifts planned", fmt(kpis.gifts_planned), `season ${year}`)}
      ${kpiTile("Route distance", fmt(kpis.total_km) + " km", `${kpis.sorties} sorties`)}
      ${kpiTile("Plan status", kpis.plan_feasible ? "Feasible" : "Violations",
        kpis.plan_feasible ? "all constraints met" : "see route planner", kpis.plan_feasible ? "good" : "bad")}
      ${kpiTile("Open POs", fmt(kpis.pos_open), "in the workshop", kpis.pos_open ? "warn" : "")}
      ${kpiTile("Naughty", fmt(kpis.naughty_children), "coal staged", "bad")}
    </div>
    <div class="grid plan" style="margin-top:14px">
      <div class="card"><h3>Global delivery plan ${plan ? "" : "— not yet computed"}</h3>
        ${plan ? worldMap(cities, plan.routes) : `<div class="empty">No route plan for ${year} yet.<br>Compute one in the Route Planner.</div>`}
      </div>
      <div class="card"><h3>Workshop status</h3>
        <div class="track-row"><span class="muted">Nice ratio</span><div class="track-bar"><div class="track-fill" style="width:${Math.round(100 * stats.by_status.nice / Math.max(stats.total, 1))}%"></div></div><span class="mono">${Math.round(100 * stats.by_status.nice / Math.max(stats.total, 1))}%</span></div>
        <div class="track-row"><span class="muted">Avg behavior</span><div class="track-bar"><div class="track-fill" style="width:${stats.avg_score}%"></div></div><span class="mono">${stats.avg_score}</span></div>
        <div class="track-row"><span class="muted">Coal needed</span><div class="track-bar"><div class="track-fill" style="width:${Math.min(100, kpis.naughty_children / 2)}%"></div></div><span class="mono">${fmt(kpis.naughty_children * 0.5)} kg</span></div>
        <h3 style="margin-top:18px">Reorder alerts</h3>
        ${alerts.length ? `<div class="table-wrap"><table><thead><tr><th>SKU</th><th class="num">On hand</th><th class="num">ROP</th></tr></thead><tbody>
          ${alerts.slice(0, 6).map(a => `<tr><td class="mono">${esc(a.sku)}</td><td class="num">${fmt(a.on_hand, 1)}</td><td class="num">${fmt(a.reorder_point, 1)}</td></tr>`).join("")}
        </tbody></table></div>` : `<div class="empty">All materials above reorder point.</div>`}
      </div>
    </div>`;
};

// ---------- route planner ----------
views.route_planner = async () => {
  const year = state.season;
  const plan = await api(`/api/plan?year=${year}`).catch(() => null);
  $("#view").innerHTML = `
    <div class="row" style="margin-bottom:14px">
      <button class="btn" id="compute-btn">Compute ${year} route plan</button>
      <span class="tiny">Clarke-Wright savings + simulated-annealing local search over ${plan ? plan.routes.length : "—"} sorties</span>
    </div>
    <div id="plan-output">${plan ? planTable(plan) : `<div class="card empty">No plan yet. Click compute — takes a few seconds.</div>`}</div>`;
  $("#compute-btn").onclick = async (e) => {
    e.target.disabled = true;
    e.target.textContent = "Optimizing…";
    try {
      const result = await api("/api/plan/compute", { method: "POST",
        body: JSON.stringify({ year, iterations: 4000 }) });
      $("#plan-output").innerHTML = planTable({ ...result, routes: result.routes, feasible: !result.violations.length });
      toast(`Plan computed: ${result.routes.length} sorties, ${fmt(result.total_km)} km`);
    } catch (err) { toast(err.message, true); }
    e.target.disabled = false;
    e.target.textContent = `Compute ${year} route plan`;
  };
};

function planTable(plan) {
  const violations = plan.violations || [];
  return `<div class="card"><h3>Sorties — season ${esc(plan.year)}</h3>
    ${violations.length ? `<p class="badge bad">${violations.length} violations</p>` : `<p class="badge ok">fully feasible</p>`}
    <div class="table-wrap"><table>
      <thead><tr><th>Route</th><th class="num">Stops</th><th class="num">Distance</th><th class="num">Load</th><th class="num">Window (h)</th><th>Status</th></tr></thead>
      <tbody>${plan.routes.map(r => `<tr>
        <td class="route-tag">${esc(r.id)}</td>
        <td class="num">${fmt(r.stop_count)}</td>
        <td class="num">${fmt(r.total_km)} km</td>
        <td class="num">${fmt(r.load_kg, 1)} kg</td>
        <td class="num mono">${(+r.departure_utc).toFixed(1)} → ${(+r.completion_utc).toFixed(1)}</td>
        <td>${r.feasible ? badge("ok") : badge("failed")}</td>
      </tr>`).join("")}</tbody></table></div></div>`;
}

// ---------- tracking ----------
views.tracking = async () => {
  $("#view").innerHTML = `<div class="card"><h3>Live mission tracking</h3>
    <div class="row" style="margin-bottom:12px">
      <label for="trk-elapsed" style="margin:0">Mission clock</label>
      <input id="trk-elapsed" type="range" min="0" max="48" step="0.25" value="0" style="width:min(360px,70vw)">
      <span class="mono" id="trk-readout">T+0.0h</span>
      <span class="spacer"></span>
      <button class="btn small" id="trk-play">Play night</button>
    </div>
    <div id="track-map"></div>
    <div id="track-rows"></div></div>`;

  const render = async (elapsed) => {
    const t = await api(`/api/tracking?year=${state.season}&elapsed=${elapsed}`);
    if (!t.active) { $("#track-rows").innerHTML = `<div class="empty">No plan — compute routes first.</div>`; return; }
    $("#trk-readout").textContent = `T+${(+elapsed).toFixed(2)}h · ${t.pct}% delivered (${fmt(t.delivered)}/${fmt(t.total)})`;
    const cities = await api("/api/cities");
    const cur = t.routes.map(r => r.current).find(Boolean) || null;
    $("#track-map").innerHTML = t.routes.length ? worldMap(cities, [], cur) : "";
    $("#track-rows").innerHTML = t.routes.map(r => `
      <div class="track-row">
        <span class="route-tag">${esc(r.route_id)}</span>
        <div class="track-bar"><div class="track-fill" style="width:${Math.round(r.progress * 100)}%"></div></div>
        <span class="tiny">${r.stops_done}/${r.stops_total} · ${badge(r.status)}</span>
      </div>`).join("");
  };
  await render(0);
  $("#trk-elapsed").addEventListener("input", (e) => render(e.target.value));
  $("#trk-play").onclick = () => {
    if (state.trackingTimer) { clearInterval(state.trackingTimer); state.trackingTimer = null; $("#trk-play").textContent = "Play night"; return; }
    $("#trk-play").textContent = "Pause";
    let t = 0;
    state.trackingTimer = setInterval(() => {
      t = (t + 0.5) % 48.5;
      $("#trk-elapsed").value = t;
      render(t);
    }, 800);
  };
};

// ---------- production ----------
views.production = async () => {
  const year = state.season;
  const [mrp, cap, orders] = await Promise.all([
    api(`/api/production/mrp?year=${year}`),
    api(`/api/production/capacity?year=${year}`),
    api("/api/production/orders"),
  ]);
  $("#view").innerHTML = `
    <div class="grid kpi">
      ${kpiTile("Gift demand", fmt(mrp.total_gifts_needed), "rank-1 wishes, nice list")}
      ${kpiTile("To build", fmt(mrp.total_to_build), "net of finished stock")}
      ${kpiTile("Material orders", fmt(mrp.material_proposals.length), "MRP proposals")}
    </div>
    <div class="row" style="margin:14px 0">
      <button class="btn" id="release-btn">Release MRP to shop floor</button>
      <span class="tiny">Creates draft production orders at the least-loaded feasible work center</span>
    </div>
    <div class="grid two">
      <div class="card"><h3>Build plan by gift</h3>
        <div class="table-wrap"><table><thead><tr><th>SKU</th><th>Gift</th><th class="num">Build</th><th class="num">Labor (min)</th></tr></thead><tbody>
        ${mrp.gift_plan.map(g => `<tr><td class="mono">${esc(g.sku)}</td><td>${esc(g.name)}</td><td class="num">${fmt(g.net_build)}</td><td class="num">${fmt(g.labor_minutes)}</td></tr>`).join("")}
        </tbody></table></div></div>
      <div class="card"><h3>Work center load (build week)</h3>
        ${cap.work_centers.map(w => `
          <div class="cap-row">
            <span class="mono tiny">${esc(w.work_center)}</span>
            <div class="cap-bar"><div class="cap-fill ${w.utilization_pct > 100 ? "over" : w.utilization_pct > 85 ? "warn" : ""}" style="width:${Math.min(100, w.utilization_pct)}%"></div></div>
            <span class="mono tiny">${w.utilization_pct}%</span>
          </div>`).join("")}
        <h3 style="margin-top:18px">Production orders</h3>
        <div class="table-wrap"><table><thead><tr><th>PO</th><th>SKU</th><th class="num">Qty</th><th>Status</th><th></th></tr></thead><tbody>
        ${orders.slice(0, 12).map(o => `<tr>
          <td class="mono">${esc(o.po_number)}</td><td class="mono">${esc(o.gift_sku)}</td>
          <td class="num">${fmt(o.qty)}</td><td>${badge(o.status)}</td>
          <td>${o.status === "draft" ? `<button class="btn small ghost" data-recv="${o.id}">Receive</button>` :
              o.status === "released" ? `<button class="btn small ghost" data-done="${o.id}">Complete</button>` : ""}</td>
        </tr>`).join("")}
        </tbody></table></div></div>
    </div>`;
  $("#release-btn").onclick = async () => {
    try {
      const r = await api("/api/production/release", { method: "POST", body: JSON.stringify({ year }) });
      toast(`Released ${r.created} production orders`);
      views.production();
    } catch (err) { toast(err.message, true); }
  };
  document.querySelectorAll("[data-recv]").forEach(b => b.onclick = async () => {
    try { await api(`/api/production/orders/${b.dataset.recv}/receive`, { method: "POST", body: "{}" }); toast("Materials received"); views.production(); }
    catch (err) { toast(err.message, true); }
  });
  document.querySelectorAll("[data-done]").forEach(b => b.onclick = async () => {
    try { await api(`/api/production/orders/${b.dataset.done}/complete`, { method: "POST", body: "{}" }); toast("PO completed — gifts to WH-GIFTS"); views.production(); }
    catch (err) { toast(err.message, true); }
  });
};

// ---------- inventory ----------
views.inventory = async () => {
  const [items, moves] = await Promise.all([
    api("/api/inventory"),
    api("/api/inventory/moves"),
  ]);
  $("#view").innerHTML = `
    <div class="grid two">
      <div class="card"><h3>Stock on hand</h3>
        <div class="table-wrap"><table><thead><tr><th>SKU</th><th>Location</th><th class="num">On hand</th><th class="num">ROP</th><th>Unit</th></tr></thead><tbody>
        ${items.map(i => `<tr><td class="mono">${esc(i.sku)}</td><td class="mono tiny">${esc(i.location)}</td>
          <td class="num">${fmt(i.on_hand, 1)}</td><td class="num">${fmt(i.reorder_point, 1)}</td><td class="tiny">${esc(i.unit)}</td></tr>`).join("")}
        </tbody></table></div></div>
      <div class="card"><h3>Movement ledger (last 100)</h3>
        <div class="table-wrap"><table><thead><tr><th>SKU</th><th class="num">Δ</th><th>Reason</th><th>Ref</th><th>By</th></tr></thead><tbody>
        ${moves.map(m => `<tr><td class="mono">${esc(m.sku)}</td>
          <td class="num" style="color:${m.delta >= 0 ? "var(--ok)" : "var(--red)"}">${m.delta >= 0 ? "+" : ""}${fmt(m.delta, 1)}</td>
          <td>${esc(m.reason)}</td><td class="tiny mono">${esc(m.ref_type)}${m.ref_id ? " " + esc(m.ref_id) : ""}</td><td class="tiny">${esc(m.actor)}</td></tr>`).join("")}
        </tbody></table></div></div>
    </div>`;
};

// ---------- naughty & nice ----------
views.list = async () => {
  const [stats, children] = await Promise.all([
    api("/api/list/stats"),
    api("/api/list/children"),
  ]);
  $("#view").innerHTML = `
    <div class="grid kpi">
      ${kpiTile("Nice", fmt(stats.by_status.nice), "on the manifest", "good")}
      ${kpiTile("Watchlist", fmt(stats.by_status.watchlist), "under review", "warn")}
      ${kpiTile("Naughty", fmt(stats.by_status.naughty), `${fmt(stats.by_status.naughty * 0.5)} kg coal`, "bad")}
      ${kpiTile("Avg score", stats.avg_score, "all children")}
    </div>
    <div class="row" style="margin:14px 0">
      <input id="child-q" placeholder="Search children…" style="width:220px">
      <select id="child-status"><option value="">All statuses</option>
        <option value="nice">Nice</option><option value="watchlist">Watchlist</option><option value="naughty">Naughty</option></select>
      <span class="spacer"></span>
      <button class="btn ghost" id="rescan-btn">Run annual rescan</button>
    </div>
    <div class="card"><div class="table-wrap"><table>
      <thead><tr><th>Child</th><th>City</th><th>Score</th><th>Status</th><th></th></tr></thead>
      <tbody id="child-rows"></tbody></table></div></div>`;
  const drawRows = (rows) => {
    $("#child-rows").innerHTML = rows.map(c => `<tr>
      <td>${esc(c.name)}</td><td class="tiny">${esc(c.city)}, ${esc(c.country)}</td>
      <td class="num mono">${c.behavior_score}</td><td>${badge(c.status)}</td>
      <td>${c.status !== "nice" && ["admin", "planner"].includes(state.user.role)
        ? `<button class="btn small ghost" data-pardon="${c.id}">Pardon</button>` : ""}</td>
    </tr>`).join("");
    document.querySelectorAll("[data-pardon]").forEach(b => b.onclick = async () => {
      try {
        await api(`/api/list/children/${b.dataset.pardon}/review`, { method: "POST",
          body: JSON.stringify({ decision: "nice", note: "manual pardon" }) });
        toast("Child moved to nice list");
        views.list();
      } catch (err) { toast(err.message, true); }
    });
  };
  drawRows(children);
  const filter = () => {
    const q = $("#child-q").value.toLowerCase();
    const st = $("#child-status").value;
    drawRows(children.filter(c =>
      (!q || c.name.toLowerCase().includes(q)) && (!st || c.status === st)));
  };
  $("#child-q").addEventListener("input", filter);
  $("#child-status").addEventListener("change", filter);
  $("#rescan-btn").onclick = async () => {
    try {
      const r = await api("/api/list/rescan", { method: "POST", body: "{}" });
      toast(`Rescan complete: ${fmt(r.rescored)} children re-scored`);
      views.list();
    } catch (err) { toast(err.message, true); }
  };
};

// ---------- admin ----------
views.admin = async () => {
  if (state.user.role !== "admin") {
    $("#view").innerHTML = `<div class="card empty">Admin console requires the admin role. You are signed in as ${esc(state.user.role)}.</div>`;
    return;
  }
  const [users, audit] = await Promise.all([api("/api/users"), api("/api/audit")]);
  $("#view").innerHTML = `
    <div class="grid two">
      <div class="card"><h3>Users & roles</h3>
        <div class="table-wrap"><table><thead><tr><th>User</th><th>Role</th><th>Active</th></tr></thead><tbody>
        ${users.map(u => `<tr><td>${esc(u.full_name)}<div class="tiny mono">${esc(u.username)}</div></td>
          <td><select data-user-role="${u.id}">
            ${["admin", "planner", "elf", "auditor", "viewer"].map(r =>
              `<option ${r === u.role ? "selected" : ""}>${r}</option>`).join("")}
          </select></td>
          <td>${u.active ? "yes" : "no"}</td></tr>`).join("")}
        </tbody></table></div></div>
      <div class="card"><h3>Audit log (latest 100)</h3>
        <div class="table-wrap"><table><thead><tr><th>When</th><th>Actor</th><th>Action</th><th>Entity</th></tr></thead><tbody>
        ${audit.map(a => `<tr><td class="tiny mono">${esc(a.ts)}</td><td>${esc(a.actor)}</td>
          <td class="mono tiny">${esc(a.action)}</td><td class="tiny">${esc(a.entity)} ${esc(a.entity_id || "")}</td></tr>`).join("")}
        </tbody></table></div></div>
    </div>`;
  document.querySelectorAll("[data-user-role]").forEach(sel => sel.addEventListener("change", async () => {
    try {
      await api(`/api/users/${sel.dataset.userRole}`, { method: "PATCH",
        body: JSON.stringify({ role: sel.value }) });
      toast(`Role updated to ${sel.value}`);
    } catch (err) { toast(err.message, true); views.admin(); }
  }));
};

// map hash names to view fns
views.routes = views.route_planner;
views.live_tracking = views.tracking;
views.mrp = views.production;

// ---------- boot ----------
(async function boot() {
  try {
    await loadMe();
    bootShell();
    if (!location.hash) location.hash = "#/dashboard";
  } catch {
    views.login();
  }
  $("#nav-toggle").onclick = () => {
    const sb = $("#sidebar");
    if (sb) sb.classList.toggle("open");
  };
})();
