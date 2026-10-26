export function mount(el, { send, onState }) {
  el.setAttribute("aria-label", "BuildingLink Front Desk & Deliveries");
  el.innerHTML = `
    <div class="card-header">
      <div class="card-title-group">
        <h2>Front Desk & Mail</h2>
        <span class="card-subtitle" id="bl-subtitle">BuildingLink</span>
      </div>
      <span id="bl-status" class="pill neutral" role="status">
        <span class="status-dot" aria-hidden="true"></span>
        <span id="bl-status-text">Checking…</span>
      </span>
    </div>

    <div id="bl-error" class="muted" style="color:var(--danger); margin-bottom:10px;" hidden></div>

    <div id="bl-setup" class="callout" hidden>
      <div class="muted" style="margin-bottom:6px;">
        Paste your BuildingLink <code>accessToken</code>, <code>bl.application</code> JSON, or cURL snippet:
      </div>
      <div class="input-row">
        <input id="bl-token-input" class="text-input" type="password" placeholder="eyJhbGci... or {&quot;accessToken&quot;:...}" autocomplete="off">
        <button id="bl-token-save" class="primary-btn" type="button">Save</button>
      </div>
    </div>

    <div class="telemetry-grid">
      <div class="telemetry-tile">
        <div class="telemetry-label">Waiting Packages</div>
        <div class="telemetry-value" id="bl-count">0</div>
      </div>
      <div class="telemetry-tile">
        <div class="telemetry-label">Last Checked</div>
        <div class="telemetry-value" id="bl-synced">–</div>
      </div>
    </div>

    <div id="bl-packages" class="bulb-list" style="margin-bottom:12px;" hidden></div>
    <div id="bl-empty" class="muted" style="margin-bottom:12px; text-align:center; padding:6px 0;" hidden>
      No packages waiting at the front desk.
    </div>

    <div id="bl-notice" class="lr-notice" role="status" aria-live="polite" hidden></div>

    <div class="chip-row" style="margin-top:8px;">
      <button id="bl-refresh" class="chip-btn" type="button">↻ Check Deliveries</button>
      <button id="bl-toggle-setup" class="chip-btn" type="button" aria-expanded="false">Key / Token</button>
    </div>`;

  const $ = (sel) => el.querySelector(sel);
  const subtitleEl = $("#bl-subtitle");
  const statusEl = $("#bl-status");
  const statusText = $("#bl-status-text");
  const errEl = $("#bl-error");
  const setupEl = $("#bl-setup");
  const tokenInput = $("#bl-token-input");
  const tokenSave = $("#bl-token-save");
  const countEl = $("#bl-count");
  const syncedEl = $("#bl-synced");
  const listEl = $("#bl-packages");
  const emptyEl = $("#bl-empty");
  const noticeEl = $("#bl-notice");
  const refreshBtn = $("#bl-refresh");
  const toggleSetupBtn = $("#bl-toggle-setup");

  let manualSetupOpen = false;

  const esc = (s) => {
    const d = document.createElement("div");
    d.textContent = s ?? "";
    return d.innerHTML;
  };

  refreshBtn.addEventListener("click", () => {
    send("buildinglink", "refresh");
  });

  toggleSetupBtn.addEventListener("click", () => {
    manualSetupOpen = !manualSetupOpen;
    toggleSetupBtn.setAttribute("aria-expanded", String(manualSetupOpen));
    setupEl.hidden = !manualSetupOpen;
    if (manualSetupOpen) tokenInput.focus();
  });

  const submitToken = () => {
    const val = tokenInput.value.trim();
    if (!val) return;
    send("buildinglink", "set_token", { token: val });
    tokenInput.value = "";
    manualSetupOpen = false;
    toggleSetupBtn.setAttribute("aria-expanded", "false");
  };

  tokenSave.addEventListener("click", submitToken);
  tokenInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") submitToken();
  });

  onState("buildinglink", (s) => {
    const prop = s.property_name || "BuildingLink";
    const unit = s.unit ? ` · ${s.unit}` : "";
    subtitleEl.textContent = `${prop}${unit}`;

    const needsAuth = !s.configured || Boolean(s.error && /expired|token/i.test(s.error));
    setupEl.hidden = !(manualSetupOpen || needsAuth);

    errEl.hidden = !s.error;
    errEl.textContent = s.error || "";

    noticeEl.hidden = !s.notice;
    noticeEl.textContent = s.notice || "";

    const pkgs = Array.isArray(s.packages) ? s.packages : [];
    const count = typeof s.packages_count === "number" ? s.packages_count : pkgs.length;

    countEl.textContent = String(count);
    countEl.style.color = count > 0 ? "var(--amber)" : "var(--fg)";
    syncedEl.textContent = s.last_synced || "–";

    if (!s.configured) {
      statusText.textContent = "Setup needed";
      statusEl.className = "pill off";
    } else if (!s.connected && s.error) {
      statusText.textContent = "Token expired";
      statusEl.className = "pill off";
    } else if (count > 0) {
      statusText.textContent = count === 1 ? "1 Package Waiting" : `${count} Packages Waiting`;
      statusEl.className = "pill";
      statusEl.style.background = "var(--amber-soft)";
      statusEl.style.color = "var(--amber)";
    } else if (s.connected) {
      statusText.textContent = "All Picked Up";
      statusEl.className = "pill";
      statusEl.style.background = "";
      statusEl.style.color = "";
    } else {
      statusText.textContent = "Syncing…";
      statusEl.className = "pill neutral";
      statusEl.style.background = "";
      statusEl.style.color = "";
    }

    if (pkgs.length > 0) {
      listEl.hidden = false;
      emptyEl.hidden = true;
      listEl.innerHTML = pkgs
        .map(
          (p) => `
        <div class="bulb-item">
          <div class="bulb-top">
            <span class="bulb-title">📦 ${esc(p.carrier || "Package")}</span>
            <span class="muted">${esc(p.received_at || p.location || "Front Desk")}</span>
          </div>
          ${
            p.description || p.tracking
              ? `<div class="muted" style="font-size:12px;">
                   ${esc(p.description)}${p.description && p.tracking ? " · " : ""}${
                  p.tracking ? `<code>${esc(p.tracking)}</code>` : ""
                }
                 </div>`
              : ""
          }
        </div>`
        )
        .join("");
    } else {
      listEl.hidden = true;
      listEl.innerHTML = "";
      emptyEl.hidden = !s.connected;
    }
  });
}
