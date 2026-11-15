export function mount(el, { send, onState }) {
  el.setAttribute("aria-label", "Going Out & Commute");

  const esc = (s) => {
    const d = document.createElement("div");
    d.textContent = s ?? "";
    return d.innerHTML;
  };

  let dockMode = "bikes"; // "bikes" | "docks"
  let lastState = null;

  const renderTrains = (arrivals) => {
    if (!arrivals || arrivals.length === 0) {
      return `<span class="muted" style="font-size:12px;">No upcoming trains</span>`;
    }
    return arrivals
      .map((a) => {
        const cls = a.reachable ? "commute-chip reachable" : "commute-chip tight";
        const label = a.minutes === 0 ? "Now" : `${a.minutes}m`;
        const title = a.reachable ? "Walkable" : "Tight (< 4m walk)";
        return `<span class="${cls}" title="${title}">${label}</span>`;
      })
      .join("");
  };

  const renderFerryTimes = (departures) => {
    if (!departures || departures.length === 0) {
      return `<span class="muted" style="font-size:12px;">–</span>`;
    }
    return departures
      .slice(0, 2)
      .map((d) => {
        const label = d.minutes <= 60 ? `${d.minutes}m` : esc(d.time_str);
        return `<span class="commute-chip ferry${d.realtime ? " rt" : ""}" title="${esc(d.time_str)}">${label}</span>`;
      })
      .join("");
  };

  const render = (s) => {
    if (!s) return;
    lastState = s;

    const w = s.weather;
    const sub = s.subway;
    const ferry = s.ferry;
    const cb = s.citibike;

    const weatherBadge = w
      ? `<span class="pill weather-pill" title="${esc(w.condition)} · Wind ${w.wind_mph} mph">
           <span aria-hidden="true">${w.icon}</span>
           <span>${w.temp_f}°F</span>
         </span>`
      : `<span class="pill neutral">Loading…</span>`;

    const headline = w
      ? `${esc(w.headline)}${w.sunset ? ` · Sunset ${esc(w.sunset)}` : ""}`
      : "Fetching Williamsburg weather & transit…";

    const alertsHtml =
      sub && Array.isArray(sub.alerts) && sub.alerts.length > 0
        ? `<div class="commute-alert" role="status">
             <strong>⚠ L Service Alert:</strong> ${esc(sub.alerts[0])}
           </div>`
        : "";

    const subwayHtml = sub
      ? `
        <div class="commute-block">
          <div class="commute-row-head">
            <div class="commute-title">
              <span class="mta-bullet mta-l" aria-hidden="true">L</span>
              <span>${esc(sub.station)}</span>
            </div>
            <span class="muted" style="font-size:11px;">${sub.walk_minutes}m walk</span>
          </div>
          ${alertsHtml}
          <div class="commute-dir-grid">
            <div class="commute-dir">
              <span class="commute-dir-label">Manhattan · 8 Av</span>
              <div class="commute-chips">${renderTrains(sub.manhattan)}</div>
            </div>
            <div class="commute-dir">
              <span class="commute-dir-label">Brooklyn · Canarsie</span>
              <div class="commute-chips">${renderTrains(sub.brooklyn)}</div>
            </div>
          </div>
        </div>
      `
      : "";

    const ferryHtml = ferry
      ? `
        <div class="commute-block">
          <div class="commute-row-head">
            <div class="commute-title">
              <span class="ferry-badge" aria-hidden="true">⛴</span>
              <span>NYC Ferry · ${esc(ferry.landing)}</span>
            </div>
            <span class="muted" style="font-size:11px;">${esc(ferry.route)}</span>
          </div>
          <div class="commute-dir-grid">
            <div class="commute-dir">
              <span class="commute-dir-label">Wall St / Pier 11</span>
              <div class="commute-chips">${renderFerryTimes(ferry.southbound)}</div>
            </div>
            <div class="commute-dir">
              <span class="commute-dir-label">East 34th St</span>
              <div class="commute-chips">${renderFerryTimes(ferry.northbound)}</div>
            </div>
          </div>
        </div>
      `
      : "";

    const citibikeHtml =
      cb && Array.isArray(cb.stations) && cb.stations.length > 0
        ? `
        <div class="commute-block">
          <div class="commute-row-head">
            <div class="commute-title">
              <span aria-hidden="true">🚲</span>
              <span>Citi Bike</span>
            </div>
            <div class="cb-mode-toggle" role="group" aria-label="Citi Bike mode">
              <button type="button" class="chip-btn cb-mode-btn" data-mode="bikes" aria-pressed="${dockMode === "bikes"}">Take</button>
              <button type="button" class="chip-btn cb-mode-btn" data-mode="docks" aria-pressed="${dockMode === "docks"}">Return</button>
            </div>
          </div>
          <div class="citibike-grid">
            ${cb.stations
              .map((st) => {
                const statusCls = dockMode === "bikes" ? st.bike_status : st.dock_status;
                const metrics =
                  dockMode === "bikes"
                    ? `<span class="cb-metric" title="E-bikes">⚡ ${st.ebikes}</span><span class="cb-metric" title="Classic bikes">🚲 ${st.classic}</span>`
                    : `<span class="cb-metric" title="Open docks">🅿️ ${st.docks} docks</span>`;
                return `
                  <div class="citibike-tile status-${esc(statusCls)}">
                    <div class="cb-name">${esc(st.name)}</div>
                    <div class="cb-counts">${metrics}</div>
                  </div>
                `;
              })
              .join("")}
          </div>
        </div>
      `
        : "";

    el.innerHTML = `
      <div class="card-header" style="margin-bottom:12px;">
        <div class="card-title-group">
          <h2>Going Out</h2>
          <span class="card-subtitle">${headline}</span>
        </div>
        <div style="display:flex; align-items:center; gap:6px;">
          ${weatherBadge}
          <button id="commute-refresh" class="icon-refresh-btn" type="button" title="Refresh transit & weather" aria-label="Refresh commute telemetry">↻</button>
        </div>
      </div>

      <div class="commute-stack">
        ${subwayHtml}
        ${ferryHtml}
        ${citibikeHtml}
      </div>

      ${s.last_updated ? `<div class="muted" style="font-size:11px; margin-top:10px; text-align:right;">Updated ${esc(s.last_updated)}</div>` : ""}
    `;

    const refBtn = el.querySelector("#commute-refresh");
    if (refBtn) {
      refBtn.addEventListener("click", () => {
        refBtn.classList.add("spinning");
        send("commute", "refresh");
        setTimeout(() => refBtn.classList.remove("spinning"), 900);
      });
    }

    el.querySelectorAll(".cb-mode-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        dockMode = btn.getAttribute("data-mode") || "bikes";
        render(lastState);
      });
    });
  };

  onState("commute", render);
}
