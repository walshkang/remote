export function mount(el, { send, onState }) {
  el.setAttribute("aria-label", "BuildingLink Front Desk & Deliveries");

  let manualSetupOpen = false;

  const esc = (s) => {
    const d = document.createElement("div");
    d.textContent = s ?? "";
    return d.innerHTML;
  };

  const getCarrierInfo = (carrierRaw) => {
    const c = (carrierRaw || "").toLowerCase();
    if (c.includes("amazon")) return { cls: "amazon", icon: "📦", name: "Amazon" };
    if (c.includes("ups")) return { cls: "ups", icon: "🟫", name: "UPS" };
    if (c.includes("fedex")) return { cls: "fedex", icon: "🟣", name: "FedEx" };
    if (c.includes("usps") || c.includes("postal")) return { cls: "usps", icon: "📬", name: "USPS" };
    if (c.includes("dhl")) return { cls: "dhl", icon: "🟡", name: "DHL" };
    return { cls: "other", icon: "📦", name: carrierRaw || "Package" };
  };

  onState("buildinglink", (s) => {
    const prop = s.property_name || "BuildingLink";
    const unit = s.unit ? ` · ${s.unit}` : "";
    const pkgs = Array.isArray(s.packages) ? s.packages : [];
    const count = typeof s.packages_count === "number" ? s.packages_count : pkgs.length;
    const needsAuth = !s.configured || Boolean(s.error && /expired|token/i.test(s.error));
    const showSetup = manualSetupOpen || needsAuth;

    // Card highlight when packages exist
    if (count > 0) {
      el.classList.add("highlight-amber");
    } else {
      el.classList.remove("highlight-amber");
    }

    // 1. SETUP / AUTH VIEW
    if (needsAuth) {
      el.innerHTML = `
        <div class="card-header" style="margin-bottom:10px;">
          <div class="card-title-group">
            <h2>Front Desk Deliveries</h2>
            <span class="card-subtitle">${esc(prop)}${esc(unit)}</span>
          </div>
          <span class="pill off" role="status">Setup needed</span>
        </div>
        ${s.error ? `<div class="muted" style="color:var(--danger); margin-bottom:8px;">${esc(s.error)}</div>` : ""}
        <div class="callout" style="margin-bottom:0;">
          <div class="muted" style="margin-bottom:6px;">
            Paste your BuildingLink <code>accessToken</code> or cURL snippet:
          </div>
          <div class="input-row">
            <input id="bl-token-input" class="text-input" type="password" placeholder="eyJhbGci... or {&quot;accessToken&quot;:...}" autocomplete="off">
            <button id="bl-token-save" class="primary-btn" type="button">Save</button>
          </div>
        </div>
      `;
      bindSetupInputs(el, send);
      return;
    }

    // 2. QUIET RESTING STATE: 0 PACKAGES
    if (count === 0 && !showSetup) {
      el.innerHTML = `
        <div class="bl-quiet-banner">
          <div class="bl-quiet-left">
            <div class="bl-quiet-icon" aria-hidden="true">✓</div>
            <div>
              <div class="bl-quiet-title">Front Desk Clear</div>
              <div class="bl-quiet-meta">${esc(prop)}${esc(unit)} · Synced ${esc(s.last_synced || "recently")}</div>
            </div>
          </div>
          <div style="display:flex; align-items:center; gap:6px;">
            <button id="bl-refresh-btn" class="icon-refresh-btn" type="button" title="Check Front Desk" aria-label="Check Deliveries">↻</button>
            <button id="bl-settings-btn" class="icon-refresh-btn" type="button" title="Token Settings" aria-label="Settings" style="font-size:14px;">⚙</button>
          </div>
        </div>
      `;

      el.querySelector("#bl-refresh-btn").addEventListener("click", (e) => {
        const btn = e.currentTarget;
        btn.classList.add("spinning");
        send("buildinglink", "refresh");
        setTimeout(() => btn.classList.remove("spinning"), 1000);
      });

      el.querySelector("#bl-settings-btn").addEventListener("click", () => {
        manualSetupOpen = true;
        send("buildinglink", "poll"); // trigger re-render
      });
      return;
    }

    // 3. ACTIVE DELIVERIES VIEW: 1+ PACKAGES (OR MANUAL SETUP OPEN)
    el.innerHTML = `
      <div class="card-header">
        <div class="card-title-group">
          <h2>Front Desk Deliveries</h2>
          <span class="card-subtitle">${esc(prop)}${esc(unit)}</span>
        </div>
        <span class="pill pkg-pill" role="status">
          <span aria-hidden="true">📦</span>
          <span>${count === 1 ? "1 Waiting for Pickup" : `${count} Waiting for Pickup`}</span>
        </span>
      </div>

      ${s.error ? `<div class="muted" style="color:var(--danger); margin-bottom:10px;">${esc(s.error)}</div>` : ""}

      <div id="bl-setup-drawer" class="callout" ${manualSetupOpen ? "" : "hidden"}>
        <div class="muted" style="margin-bottom:6px;">
          Update your BuildingLink <code>accessToken</code>:
        </div>
        <div class="input-row">
          <input id="bl-token-input" class="text-input" type="password" placeholder="Paste token..." autocomplete="off">
          <button id="bl-token-save" class="primary-btn" type="button">Save</button>
        </div>
      </div>

      <div class="pkg-card-list">
        ${pkgs.map((p, idx) => {
          const info = getCarrierInfo(p.carrier);
          const location = p.location || "Front Desk";
          const time = p.received_at || "Logged in";
          const tracking = p.tracking ? String(p.tracking).trim() : "";
          const desc = p.description ? String(p.description).trim() : "";

          return `
            <div class="pkg-card">
              <div class="pkg-card-top">
                <span class="carrier-badge ${info.cls}">
                  <span aria-hidden="true">${info.icon}</span>
                  <span>${esc(info.name)}</span>
                </span>
                <span class="pkg-location-pill">${esc(location)}</span>
              </div>
              <div class="pkg-meta">
                <span>Received ${esc(time)}</span>
                ${tracking ? `
                  <button class="pkg-copy-btn" type="button" data-copy="${esc(tracking)}" title="Copy tracking number">
                    Copy #${esc(tracking.slice(-6))}
                  </button>
                ` : ""}
              </div>
              ${desc ? `<div class="muted" style="font-size:12px;">${esc(desc)}</div>` : ""}
            </div>
          `;
        }).join("")}
      </div>

      <div style="display:flex; justify-content:space-between; align-items:center; margin-top:8px;">
        <span class="muted" style="font-size:12px;">Last synced ${esc(s.last_synced || "–")}</span>
        <div style="display:flex; gap:6px;">
          <button id="bl-refresh-btn" class="chip-btn" type="button">↻ Check Now</button>
          <button id="bl-settings-btn" class="chip-btn" type="button">${manualSetupOpen ? "Close Key" : "Key"}</button>
        </div>
      </div>
    `;

    bindSetupInputs(el, send);

    // Refresh button
    const refreshBtn = el.querySelector("#bl-refresh-btn");
    if (refreshBtn) {
      refreshBtn.addEventListener("click", () => {
        send("buildinglink", "refresh");
      });
    }

    // Settings toggle button
    const settingsBtn = el.querySelector("#bl-settings-btn");
    if (settingsBtn) {
      settingsBtn.addEventListener("click", () => {
        manualSetupOpen = !manualSetupOpen;
        const drawer = el.querySelector("#bl-setup-drawer");
        if (drawer) drawer.hidden = !manualSetupOpen;
        settingsBtn.textContent = manualSetupOpen ? "Close Key" : "Key";
      });
    }

    // Tracking Copy Buttons
    el.querySelectorAll(".pkg-copy-btn").forEach((btn) => {
      btn.addEventListener("click", async (e) => {
        const text = btn.getAttribute("data-copy");
        if (!text) return;
        try {
          await navigator.clipboard.writeText(text);
          const orig = btn.textContent;
          btn.textContent = "Copied! ✓";
          setTimeout(() => { btn.textContent = orig; }, 1500);
        } catch (_) {}
      });
    });
  });

  function bindSetupInputs(container, sendFn) {
    const tokenInput = container.querySelector("#bl-token-input");
    const tokenSave = container.querySelector("#bl-token-save");
    if (!tokenInput || !tokenSave) return;

    const submit = () => {
      const val = tokenInput.value.trim();
      if (!val) return;
      sendFn("buildinglink", "set_token", { token: val });
      tokenInput.value = "";
      manualSetupOpen = false;
    };

    tokenSave.addEventListener("click", submit);
    tokenInput.addEventListener("keydown", (e) => {
      if (e.key === "Enter") submit();
    });
  }
}
