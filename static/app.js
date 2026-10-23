const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const num = (n, d = 2) => (n == null ? "-" : Number(n).toLocaleString("pt-PT", { maximumFractionDigits: d }));

let pending = null;

async function api(url, body) {
  const res = await fetch(url, body ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } : undefined);
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || res.statusText);
  return data;
}

async function loadMarket() {
  const [base, quote] = $("symbol").value.split("/");
  $("market").innerHTML = "<dt>A carregar...</dt><dd></dd>";
  try {
    const m = await api(`/api/market/${base}/${quote}`);
    $("market").innerHTML = `
      <dt>Preco</dt><dd>${num(m.price)}</dd>
      <dt>24h</dt><dd>${num(m.change_24h_pct)}%</dd>
      <dt>RSI (14)</dt><dd>${m.rsi14}</dd>
      <dt>EMA 20 / 50</dt><dd>${num(m.ema20)} / ${num(m.ema50)}</dd>
      <dt>Min / max (100h)</dt><dd>${num(m.low_100)} / ${num(m.high_100)}</dd>`;
  } catch (e) {
    $("market").innerHTML = `<dt class="error">${esc(e.message)}</dt><dd></dd>`;
  }
}

async function loadPortfolio() {
  const p = await api("/api/portfolio");
  const tag = $("mode");
  tag.textContent = p.mode.toUpperCase();
  tag.className = "tag " + (p.mode === "paper" ? "paper" : "live");
  const pos = Object.entries(p.positions).map(([k, v]) => `<span class="k">${esc(k)}</span><dd>${num(v, 6)}</dd>`).join("");
  $("portfolio").innerHTML = `<span class="k">USDT</span><dd>${num(p.USDT)}</dd>${pos}`;
  $("trades").innerHTML = p.trades.length
    ? `<table><tr><th>Dia</th><th>Lado</th><th>Par</th><th>Preco</th><th>USDT</th></tr>${p.trades.slice().reverse().map((t) => `<tr><td>${esc(t.day)}</td><td>${esc(t.side)}</td><td>${esc(t.symbol)}</td><td>${num(t.price)}</td><td>${num(t.usdt)}</td></tr>`).join("")}</table>`
    : "Sem ordens.";
}

$("analyse").onclick = async () => {
  const btn = $("analyse");
  btn.disabled = true;
  btn.textContent = "A analisar...";
  $("result").hidden = false;
  $("proposal").innerHTML = "<span class='muted'>O Grok esta a pensar...</span>";
  $("confirm").hidden = true;
  try {
    const r = await api("/api/analyse", { symbol: $("symbol").value, question: $("question").value });
    const p = r.proposal;
    $("proposal").innerHTML = `
      <p><span class="badge ${esc(p.action)}">${esc(p.action)}</span> ${esc(p.symbol)} · confianca ${num((p.confidence ?? 0) * 100, 0)}%</p>
      <p>${esc(p.reason)}</p>
      <p class="muted">Riscos: ${esc(p.risks)}</p>
      ${r.blocked ? `<p class="blocked">${esc(r.blocked)}</p>` : ""}`;
    pending = r.order;
    if (pending) {
      const c = $("confirm");
      c.hidden = false;
      c.className = pending.action;
      c.textContent = `Confirmar: ${pending.action} ${num(pending.usdt)} USDT de ${pending.symbol}`;
    }
  } catch (e) {
    $("proposal").innerHTML = `<p class="error">${esc(e.message)}</p>`;
  } finally {
    btn.disabled = false;
    btn.textContent = "Pedir analise ao Grok";
  }
};

$("confirm").onclick = async () => {
  if (!pending) return;
  const btn = $("confirm");
  btn.disabled = true;
  try {
    const o = await api("/api/execute", pending);
    $("proposal").innerHTML += `<p>Executado (${esc(o.mode)}): ${esc(o.side)} ${num(o.qty, 6)} ${esc(o.symbol)} a ${num(o.price)}.</p>`;
    pending = null;
    btn.hidden = true;
    await loadPortfolio();
  } catch (e) {
    $("proposal").innerHTML += `<p class="error">${esc(e.message)}</p>`;
  } finally {
    btn.disabled = false;
  }
};

let autoOn = false;

async function loadAuto() {
  const a = await api("/api/auto");
  autoOn = a.enabled;
  const b = $("autoToggle");
  b.textContent = a.enabled ? "Desligar modo automatico" : "Ligar modo automatico";
  b.className = a.enabled ? "on" : "";
  $("autoState").textContent = a.halted ? "Pausado ate amanha: limite de perda diaria atingido." : a.enabled ? `Ativo. Ultimo ciclo: ${a.last_tick || "a arrancar..."}` : "Desligado.";
  $("autoLog").innerHTML = a.log.slice(0, 30).map((l) => `<tr class="${esc(l.kind)}"><td>${esc(l.t)}</td><td>${esc(l.msg)}</td></tr>`).join("");
  if (a.log.length) loadPortfolio();
}

$("autoToggle").onclick = async () => {
  if (!autoOn && !confirm("Ligar o modo automatico? O bot vai comprar e vender sozinho dentro dos limites configurados.")) return;
  try {
    await api("/api/auto", { enabled: !autoOn });
  } catch (e) {
    $("autoState").textContent = e.message;
    return;
  }
  loadAuto();
};

$("dismiss").onclick = () => { pending = null; $("result").hidden = true; };
$("symbol").onchange = loadMarket;

loadMarket();
loadPortfolio();
loadAuto();
setInterval(loadMarket, 30000);
setInterval(loadAuto, 10000);
