export function mount(el, { send, onState, lockedSlider }) {
  el.innerHTML = `
    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:12px;">
      <h2 style="margin:0;">Hue Lights</h2>
      <span id="hue-status" class="pill off" style="font-size:11px;">Offline</span>
    </div>
    <div id="hue-pair" style="display:none; background:#1c212a; padding:12px; border-radius:12px; margin-bottom:12px;">
      <div style="font-size:13px; color:var(--muted); margin-bottom:8px;">
        Press the round button on top of your Hue Bridge, then tap Pair.
      </div>
      <button id="hue-pair-btn" style="width:auto; height:auto; padding:8px 16px; font-size:14px;">Pair</button>
      <div id="hue-error" class="muted" style="margin-top:8px; color:#ff9aa2;"></div>
    </div>
    <div id="hue-rooms"></div>`;

  const statusEl = el.querySelector("#hue-status");
  const pairBox = el.querySelector("#hue-pair");
  const errEl = el.querySelector("#hue-error");
  const roomsEl = el.querySelector("#hue-rooms");
  el.querySelector("#hue-pair-btn").addEventListener("click", () => send("hue", "pair"));

  const chip = "width:auto; height:36px; padding:0 12px; font-size:13px; border-radius:18px;";
  const onStyle = (b, on) => {
    b.style.background = on ? "#b8860b" : "#232932";
    b.style.color = on ? "#fff" : "var(--fg)";
  };
  const HUE_GRAD = "linear-gradient(90deg,red,yellow,lime,cyan,blue,magenta,red)";

  let signature = "";
  const refs = { rooms: {}, lights: {} }; // id -> { update(roomOrLight) }

  function build(s) {
    roomsEl.innerHTML = "";
    refs.rooms = {}; refs.lights = {};
    for (const room of s.rooms) {
      const card = document.createElement("div");
      card.style.cssText = "background:#10141b; border-radius:12px; padding:12px; margin-bottom:10px;";
      card.innerHTML = `
        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:6px;">
          <div style="font-weight:600;">${room.name}</div>
          <div style="display:flex; gap:8px;">
            <button class="expand" style="${chip} background:#232932;">Bulbs ▾</button>
            <button class="toggle" style="${chip}">Off</button>
          </div>
        </div>
        <input type="range" class="bri" min="1" max="100">
        <div class="scenes" style="display:flex; gap:6px; flex-wrap:wrap; margin:6px 0;"></div>
        <div class="colors" style="display:none; margin-top:6px;">
          <div class="muted" style="font-size:12px;">Room color (color bulbs)</div>
          <input type="range" class="hue" min="0" max="360" style="background:${HUE_GRAD}; height:14px; border-radius:7px; margin:10px 0 4px;">
          <input type="range" class="sat" min="0" max="100" value="100">
        </div>
        <div class="bulbs" style="display:none; margin-top:8px;"></div>`;
      roomsEl.appendChild(card);

      const toggle = card.querySelector(".toggle");
      const bri = lockedSlider(card.querySelector(".bri"), {
        throttleMs: 80,
        onInput: (v) => send("hue", "room_brightness", { room: room.id, value: v }),
      });
      let on = false;
      toggle.addEventListener("click", () => send("hue", "room_toggle", { room: room.id, on: !on }));

      const scenesEl = card.querySelector(".scenes");
      for (const sc of room.scenes) {
        const b = document.createElement("button");
        b.textContent = sc.name;
        b.style.cssText = chip + "background:#232932;";
        b.addEventListener("click", () => send("hue", "scene_recall", { scene: sc.id }));
        scenesEl.appendChild(b);
      }

      const colors = card.querySelector(".colors");
      const bulbs = card.querySelector(".bulbs");
      card.querySelector(".expand").addEventListener("click", () => {
        const open = bulbs.style.display === "none";
        bulbs.style.display = open ? "block" : "none";
        colors.style.display = open ? "block" : "none";
      });
      const hueS = card.querySelector(".hue"), satS = card.querySelector(".sat");
      const sendRoomColor = () => send("hue", "room_color", { room: room.id, h: +hueS.value, s: +satS.value });
      lockedSlider(hueS, { throttleMs: 150, onInput: sendRoomColor });
      lockedSlider(satS, { throttleMs: 150, onInput: sendRoomColor });

      for (const lid of room.light_ids) {
        const light = s.lights[lid];
        const row = document.createElement("div");
        row.style.cssText = "border-top:1px solid #1f2530; padding:10px 0;";
        row.innerHTML = `
          <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:4px;">
            <div style="font-size:14px;">${light.name}</div>
            <button class="ltoggle" style="${chip}">Off</button>
          </div>
          ${light.dimmable ? '<input type="range" class="lbri" min="1" max="100">' : ""}
          ${light.has_ct ? `<div class="muted" style="font-size:12px;">Warm ↔ Cool</div>
            <input type="range" class="lct" min="${light.mirek_min}" max="${light.mirek_max}" style="direction:rtl;">` : ""}
          ${light.has_color ? `<div class="muted" style="font-size:12px;">Color</div>
            <input type="range" class="lhue" min="0" max="360" style="background:${HUE_GRAD}; height:14px; border-radius:7px; margin:10px 0 4px;">
            <input type="range" class="lsat" min="0" max="100" value="100">` : ""}
          ${light.effects.length ? `<select class="leffect" style="background:#232932;color:var(--fg);border:0;border-radius:8px;padding:8px;margin-top:6px;">
            <option value="">Effect…</option>
            ${light.effects.map((e) => `<option>${e}</option>`).join("")}
            <option value="no_effect">none</option></select>` : ""}`;
        bulbs.appendChild(row);

        const lt = row.querySelector(".ltoggle");
        let lon = false;
        lt.addEventListener("click", () => send("hue", "light_toggle", { light: lid, on: !lon }));
        const lb = row.querySelector(".lbri");
        const lbS = lb && lockedSlider(lb, { throttleMs: 100, onInput: (v) => send("hue", "light_brightness", { light: lid, value: v }) });
        const lc = row.querySelector(".lct");
        const lcS = lc && lockedSlider(lc, { throttleMs: 100, onInput: (v) => send("hue", "light_temp", { light: lid, mirek: v }) });
        const lh = row.querySelector(".lhue"), ls = row.querySelector(".lsat");
        if (lh) {
          const sendColor = () => send("hue", "light_color", { light: lid, h: +lh.value, s: +ls.value });
          lockedSlider(lh, { throttleMs: 100, onInput: sendColor });
          lockedSlider(ls, { throttleMs: 100, onInput: sendColor });
        }
        const fx = row.querySelector(".leffect");
        if (fx) fx.addEventListener("change", () => fx.value && send("hue", "light_effect", { light: lid, effect: fx.value }));

        refs.lights[lid] = (l) => {
          lon = l.on;
          lt.textContent = l.on ? "On" : "Off";
          onStyle(lt, l.on);
          if (lbS) lbS.set(l.brightness);
          if (lcS && l.mirek) lcS.set(l.mirek);
        };
      }

      refs.rooms[room.id] = (r) => {
        on = r.on;
        toggle.textContent = r.on ? "On" : "Off";
        onStyle(toggle, r.on);
        bri.set(r.brightness);
      };
    }
  }

  onState("hue", (s) => {
    pairBox.style.display = s.paired ? "none" : "block";
    errEl.textContent = s.error || "";
    statusEl.textContent = s.connected ? "Connected" : s.paired ? "Connecting…" : "Not paired";
    statusEl.className = s.connected ? "pill" : "pill off";
    if (!s.rooms || !s.rooms.length) return;

    const sig = JSON.stringify([
      s.rooms.map((r) => [r.id, r.light_ids, r.scenes.map((x) => x.id)]),
      Object.values(s.lights).map((l) => [l.id, l.dimmable, l.has_ct, l.has_color, l.effects]),
    ]);
    if (sig !== signature) { signature = sig; build(s); }
    s.rooms.forEach((r) => refs.rooms[r.id] && refs.rooms[r.id](r));
    Object.values(s.lights).forEach((l) => refs.lights[l.id] && refs.lights[l.id](l));
  });
}
