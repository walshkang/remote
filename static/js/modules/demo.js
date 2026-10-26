export function mount(el, { send, onState, lockedSlider, bindStepRepeat }) {
  el.setAttribute("aria-label", "Demo Sync Test");
  el.innerHTML = `
    <div class="card-header">
      <div class="card-title-group">
        <h2>Demo (Sync Test)</h2>
        <span class="card-subtitle">Coalesced hardware echo simulator</span>
      </div>
      <span class="pill neutral">Applied: <strong id="demo-applied">–</strong></span>
    </div>

    <div class="fill-slider" style="margin-bottom: 10px;">
      <div class="fill-slider-bar"></div>
      <div class="fill-slider-meta">
        <span class="fill-slider-label">Level</span>
        <span class="fill-slider-value" id="demo-level">–</span>
      </div>
      <input type="range" min="0" max="80" value="40" id="demo-slider" aria-label="Demo level">
    </div>

    <div style="display:grid; grid-template-columns: 1fr 1fr; gap: 8px;">
      <button type="button" class="step-btn" data-d="-1" aria-label="Decrease demo level">− 1</button>
      <button type="button" class="step-btn" data-d="1" aria-label="Increase demo level">+ 1</button>
    </div>
  `;

  const level = el.querySelector("#demo-level");
  const applied = el.querySelector("#demo-applied");
  const slider = lockedSlider(el.querySelector("#demo-slider"), {
    formatValue: (v) => `${v}`,
    onInput: (v) => send("demo", "set", { value: v }),
  });

  el.querySelectorAll("button[data-d]").forEach((b) => {
    const step = () => send("demo", "delta", { delta: Number(b.dataset.d) });
    if (bindStepRepeat) bindStepRepeat(b, step);
    else b.addEventListener("click", step);
  });

  onState("demo", (s) => {
    level.textContent = s.level;
    applied.textContent = s.applied;
    slider.set(s.level);
  });
}
