// Bit, a mascote. As paginas dizem-lhe o que o bot esta a fazer:
//   Mascot.set(estado, texto)         estado de fundo (sleep | idle | scan | think)
//   Mascot.react(estado, texto, ms)   emocao passageira (happy | sad | alert) que volta ao estado de fundo
//   Mascot.onClick(() => texto)       resumo mostrado quando se clica nela
// Cada estado e uma imagem (static/mascot/<estado>.webp). Com o bot ligado o Bit passeia pela pagina toda; parado, dorme no canto.
(() => {
  const store = {
    get: (k) => { try { return localStorage.getItem(k); } catch { return null; } },
    set: (k, v) => { try { localStorage.setItem(k, v); } catch { /* sem armazenamento */ } },
  };
  const reduceMotion = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  const STATES = ["sleep", "idle", "scan", "think", "happy", "sad", "alert"];
  const SRC = (s) => `/static/mascot/${s}.webp`;
  STATES.forEach((s) => { const i = new Image(); i.src = SRC(s); });          // pre-carrega: a troca de estado nunca espera por uma imagem

  const root = document.createElement("div");
  root.className = "mascot";
  root.dataset.state = "sleep";
  root.innerHTML = `<div class="mascot-bubble" role="status" aria-live="polite"><b>BIT</b><span class="mb-text"></span></div>
    <div class="m-stage">
      <span class="m-shadow" aria-hidden="true"></span>
      <span class="m-pulse" aria-hidden="true"></span>
      <button type="button" class="mascot-body" aria-label="Bit, a mascote do bot. Carrega para ver o resumo.">
        <span class="m-fig"><span class="m-flip"><span class="m-bob">${STATES.map((s) => `<img class="m-img" data-s="${s}" src="${SRC(s)}" alt="" draggable="false" decoding="async">`).join("")}</span></span></span>
        <span class="m-z" aria-hidden="true"><i>z</i><i>z</i><i>z</i></span>
      </button>
      <div class="m-hit" title="Clica para o resumo, arrasta para mudar de sitio"></div>
      <div class="m-tools">
        <button type="button" class="mascot-roam" aria-label="Passear pela pagina" title="Passear / ficar quieto" aria-pressed="true">⇄</button>
        <button type="button" class="mascot-hide" aria-label="Ocultar a mascote" title="Ocultar">×</button>
      </div>
      <button type="button" class="mascot-pill" aria-label="Mostrar a mascote" title="Mostrar o Bit"><i></i></button>
    </div>`;
  document.body.appendChild(root);

  const body = root.querySelector(".mascot-body"), hit = root.querySelector(".m-hit"), textEl = root.querySelector(".mb-text");
  const roamBtn = root.querySelector(".mascot-roam");
  const state = { base: "sleep", baseText: "", reaction: null, timer: null, summary: null, autoTimer: null, lastAuto: 0, started: false };

  let swapTimer = 0;
  function render() {
    const r = state.reaction, st = r ? r.state : state.base, text = r ? r.text : state.baseText;
    if (root.dataset.state !== st) {                    // mudanca de estado: dispara o anel de energia que disfarca a troca de pose
      root.classList.remove("swap"); void root.offsetWidth; root.classList.add("swap");
      clearTimeout(swapTimer); swapTimer = setTimeout(() => root.classList.remove("swap"), 800);
    }
    root.dataset.state = st;
    if (textEl.textContent !== text) textEl.textContent = text;
  }

  // O balao abre sozinho um momento quando muda o que o Bit esta a fazer (no maximo de 20 em 20 s, para nao piscar)
  function autoTalk() {
    if (state.reaction || Date.now() - state.lastAuto < 20000) return;
    state.lastAuto = Date.now();
    root.classList.add("talk");
    clearTimeout(state.autoTimer);
    state.autoTimer = setTimeout(() => { if (!state.reaction) root.classList.remove("talk"); }, 3800);
  }

  const api = {
    set(st, text = "") {
      if (state.base === st && state.baseText === text) return;
      const changed = state.base !== st;
      state.base = st; state.baseText = text;
      render();
      if (changed || !state.started) autoTalk();
      state.started = true;
    },
    react(st, text = "", ms = 6000) {
      clearTimeout(state.timer);
      state.reaction = { state: st, text };
      root.classList.add("talk");
      render();
      state.timer = setTimeout(() => { state.reaction = null; root.classList.remove("talk"); render(); }, ms);
    },
    onClick(fn) { state.summary = fn; },
  };
  window.Mascot = api;

  // ---------- posicao e passeio ----------
  // x, y: canto superior esquerdo do Bit no ecra. mode: "walk" (a caminho de tx,ty) ou "pause" (parado ate "until").
  const R = { on: store.get("mascotRoam") !== "0" && !reduceMotion, x: 0, y: 0, tx: 0, ty: 0, speed: 58, mode: "pause", until: 0, face: 1, hover: false, drag: false, last: 0 };
  const dims = () => ({ w: root.offsetWidth || 168, h: root.offsetHeight || 168 });
  const bounds = () => { const { w, h } = dims(); return { minX: 6, maxX: Math.max(6, innerWidth - w - 6), minY: 82, maxY: Math.max(82, innerHeight - h - 6) }; };
  const home = () => { const b = bounds(); return { x: b.maxX - 8, y: b.maxY - 8 }; };

  function place() {
    root.style.transform = `translate3d(${Math.round(R.x)}px, ${Math.round(R.y)}px, 0)`;
    root.classList.toggle("below", R.y < 100);          // perto do topo o balao abre para baixo
    root.classList.toggle("b-left", R.x < 200);         // perto da esquerda o balao alinha pela esquerda
  }

  function pick(t) {
    const b = bounds(), scanning = root.dataset.state === "scan";
    let nx = R.x;
    for (let i = 0; i < 8; i++) { nx = b.minX + Math.random() * (b.maxX - b.minX); if (Math.abs(nx - R.x) > (b.maxX - b.minX) * 0.25) break; }
    R.tx = nx;
    R.ty = Math.random() < 0.65 ? b.maxY - Math.random() * 50 : b.minY + Math.random() * (b.maxY - b.minY);   // mais vezes pela base do ecra
    R.speed = scanning ? 125 : 58;                       // a procurar, anda depressa
    R.mode = "walk";
  }

  function frame(t) {
    requestAnimationFrame(frame);
    const dt = Math.min(0.05, (t - R.last) / 1000 || 0);
    R.last = t;
    const st = root.dataset.state;
    const canMove = R.on && (st === "idle" || st === "scan") && !R.hover && !R.drag && !root.classList.contains("min");
    if (!canMove) { root.classList.remove("walking"); return; }
    if (R.mode === "pause") {
      root.classList.remove("walking");
      if (t >= R.until) pick(t);
      return;
    }
    const dx = R.tx - R.x, dy = R.ty - R.y, dist = Math.hypot(dx, dy), step = R.speed * dt;
    if (dist <= step) {
      R.x = R.tx; R.y = R.ty; R.mode = "pause";
      R.until = t + (st === "scan" ? 500 + Math.random() * 1200 : 1800 + Math.random() * 4200);
      root.classList.remove("walking");
    } else {
      R.x += (dx / dist) * step; R.y += (dy / dist) * step;
      if (Math.abs(dx) > 6) { const f = dx > 0 ? 1 : -1; if (f !== R.face) { R.face = f; root.classList.toggle("left", f < 0); } }
      root.classList.add("walking");
    }
    place();
  }

  function setRoam(on, persist = true) {
    R.on = on;
    roamBtn.setAttribute("aria-pressed", String(on));
    roamBtn.classList.toggle("off", !on);
    root.classList.toggle("roaming", on);
    if (!on) root.classList.remove("walking");
    if (persist) store.set("mascotRoam", on ? "1" : "0");
  }

  // posicao inicial: a guardada, ou o canto inferior direito
  (() => {
    let start = home();
    try {
      const saved = JSON.parse(store.get("mascot2") || "null");
      if (saved && Number.isFinite(saved.x) && Number.isFinite(saved.y)) {
        const b = bounds();
        start = { x: Math.min(b.maxX, Math.max(b.minX, saved.x)), y: Math.min(b.maxY, Math.max(b.minY, saved.y)) };
      }
      if (saved && saved.min) root.classList.add("min");
    } catch { /* ignora */ }
    R.x = start.x; R.y = start.y; R.until = 2500;
    setRoam(R.on, false);
    place();
    requestAnimationFrame(frame);
  })();

  addEventListener("resize", () => { const b = bounds(); R.x = Math.min(b.maxX, Math.max(b.minX, R.x)); R.y = Math.min(b.maxY, Math.max(b.minY, R.y)); place(); });
  const save = () => store.set("mascot2", JSON.stringify({ x: Math.round(R.x), y: Math.round(R.y), min: root.classList.contains("min") }));

  roamBtn.addEventListener("click", () => setRoam(!R.on));
  root.querySelector(".mascot-hide").addEventListener("click", () => { root.classList.add("min"); const h = home(); R.x = h.x; R.y = h.y; place(); save(); });
  root.querySelector(".mascot-pill").addEventListener("click", () => { root.classList.remove("min"); const h = home(); R.x = h.x; R.y = h.y; place(); save(); });

  // ---------- parar quando o rato esta em cima ----------
  hit.addEventListener("pointerenter", () => { R.hover = true; });
  hit.addEventListener("pointerleave", () => { setTimeout(() => { if (!hit.matches(":hover")) R.hover = false; }, 500); });

  // ---------- olhar na direcao do cursor (so quando esta parado) ----------
  let raf = 0, px = 0, py = 0;
  document.addEventListener("pointermove", (e) => {
    px = e.clientX; py = e.clientY;
    if (raf) return;
    raf = requestAnimationFrame(() => {
      raf = 0;
      const r = body.getBoundingClientRect(), cx = r.left + r.width / 2, cy = r.top + r.height / 2;
      const clamp = (v, m) => Math.max(-m, Math.min(m, v));
      const nx = clamp((px - cx) / 300, 1), ny = clamp((py - cy) / 300, 1);
      root.style.setProperty("--ex", `${nx * 5}px`);
      root.style.setProperty("--ey", `${ny * 3}px`);
      root.style.setProperty("--ry", `${nx * 16}deg`);             // vira a cabeca para o cursor, em 3D
      root.style.setProperty("--rx", `${-ny * 9}deg`);
      root.style.setProperty("--ry-n", String(Math.abs(nx)));
    });
  }, { passive: true });

  // ---------- arrastar e clicar ----------
  let drag = null;
  function summary() {
    root.classList.remove("hop"); void root.offsetWidth; root.classList.add("hop");
    setTimeout(() => root.classList.remove("hop"), 800);
    const text = state.summary ? state.summary() : state.baseText;
    if (text) api.react(state.reaction ? state.reaction.state : state.base, text, 7000);
  }
  hit.addEventListener("pointerdown", (e) => {
    drag = { x: e.clientX, y: e.clientY, left: R.x, top: R.y, moved: false };
    try { hit.setPointerCapture(e.pointerId); } catch { /* ponteiro ja terminou */ }
  });
  hit.addEventListener("pointermove", (e) => {
    if (!drag) return;
    const dx = e.clientX - drag.x, dy = e.clientY - drag.y;
    if (!drag.moved && Math.hypot(dx, dy) < 5) return;
    drag.moved = true; R.drag = true;
    root.classList.add("dragging");
    const b = bounds();
    R.x = Math.max(0, Math.min(innerWidth - dims().w, drag.left + dx));
    R.y = Math.max(0, Math.min(Math.max(b.maxY + 6, 0), drag.top + dy));
    place();
  });
  hit.addEventListener("pointerup", () => {
    if (!drag) return;
    const moved = drag.moved;
    drag = null; R.drag = false;
    root.classList.remove("dragging");
    if (moved) { R.mode = "pause"; R.until = performance.now() + 4000; save(); return; }   // largado: fica ali um bocado e depois volta a passear
    summary();
  });
  body.addEventListener("click", (e) => { if (e.detail === 0) summary(); });                // teclado (Enter ou espaco)
})();
