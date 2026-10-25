// Barra de estado do topo: uptime a contar ao segundo, ciclo do bot e PID. O servidor so e consultado de 15 em 15 s.
(() => {
  const box = document.getElementById("hud");
  if (!box) return;
  const up = document.getElementById("hUp"), cy = document.getElementById("hCy"), pid = document.getElementById("hPid");
  const pad = (n) => String(n).padStart(2, "0");
  const fmt = (s) => `${pad(Math.floor(s / 3600))}:${pad(Math.floor(s / 60) % 60)}:${pad(s % 60)}`;
  let base = null;

  function paint() {
    if (!base) return;
    up.textContent = fmt(base.up + Math.floor((Date.now() - base.t0) / 1000));
    cy.textContent = `#${base.cycles}`;
    pid.textContent = base.pid;
  }

  async function sync() {
    try {
      const r = await (await fetch("/api/sys")).json();
      base = { t0: Date.now(), up: r.uptime, pid: r.pid, cycles: box.dataset.bot === "dex" ? r.dex_cycles : r.auto_cycles };
      paint();
    } catch { /* sem ligacao: mantem o ultimo valor */ }
  }

  sync();
  setInterval(paint, 1000);
  setInterval(() => { if (!document.hidden) sync(); }, 15000);
})();
