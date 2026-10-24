const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const num = (n, d = 2) => (n == null ? "-" : Number(n).toLocaleString("pt-PT", { maximumFractionDigits: d }));
const signed = (n, d = 2) => (n == null ? "-" : (n > 0 ? "+" : "") + num(n, d));
const price = (n) => num(n, n >= 100 ? 2 : n >= 1 ? 4 : 8);
const arrow = (n) => (n > 0 ? '<span class="up">▲</span> ' : n < 0 ? '<span class="down">▼</span> ' : "");
const css = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();

async function api(url, body) {
  const res = await fetch(url, body ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } : undefined);
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || res.statusText);
  return data;
}

/* ---------- Tempo real: o browser liga-se direto aos WebSockets publicos da Binance ---------- */
const live = {};          // "BTC/USDT" -> { price, open24 }
const WS_HOSTS = ["wss://stream.binance.com:9443", "wss://stream.binance.com:443", "wss://data-stream.binance.vision:443"];
let hostIdx = 0, ws = null, wsKey = "", wsNames = {};
let renderTimer = null, chartDirty = false;

const streamName = (s) => s.replace("/", "").toLowerCase();

function setLive(ok) {
  const t = $("liveTag");
  t.textContent = ok ? "● ao vivo" : "○ a reconectar";
  t.className = "tag " + (ok ? "ws-on" : "ws-off");
}

function wsConnect() {
  const selected = $("symbol").value;
  const held = (window.lastSummary?.positions || []).map((p) => p.symbol);
  const symbols = [...new Set([selected, ...held].filter(Boolean))];
  if (!symbols.length) return;
  // miniTicker (1/s) para todas as moedas; aggTrade (cada negocio) e kline so para a moeda do grafico
  const streams = symbols.map((s) => `${streamName(s)}@miniTicker`);
  streams.push(`${streamName(selected)}@aggTrade`, `${streamName(selected)}@kline_${$("tf").value}`);
  const key = streams.join("/");
  if (key === wsKey && ws && ws.readyState <= 1) return;
  wsKey = key;
  wsNames = Object.fromEntries(symbols.map((s) => [s.replace("/", ""), s]));
  if (ws) { ws.onclose = null; ws.close(); }
  const sock = (ws = new WebSocket(`${WS_HOSTS[hostIdx]}/stream?streams=${key}`));
  let opened = false;
  sock.onopen = () => { opened = true; setLive(true); };
  sock.onerror = () => sock.close();
  sock.onclose = () => {
    setLive(false);
    wsKey = "";
    if (!opened) hostIdx = (hostIdx + 1) % WS_HOSTS.length; // este endereco nao ligou: tenta o seguinte
    setTimeout(wsConnect, opened ? 1000 : 2000);
  };
  ws.onmessage = (ev) => onTick(JSON.parse(ev.data).data);
}

function onTick(d) {
  const sym = wsNames[d.s];
  if (!sym) return;
  const cur = (live[sym] ||= {});
  if (d.e === "24hrMiniTicker") {
    cur.open24 = +d.o;
    cur.price = +d.c;
  } else if (d.e === "aggTrade") {
    cur.price = +d.p;
    applyPrice(sym, +d.p);
  } else if (d.e === "kline" && d.k.i === $("tf").value) {
    applyKline(d.k);
  }
  scheduleRender();
}

// A vela em curso acompanha cada negocio; velas novas entram quando a kline muda de abertura
let candleTs = [];
function applyPrice(sym, px) {
  if (!priceChart || sym !== $("symbol").value || !candleTs.length) return;
  priceChart.data.datasets[0].data[candleTs.length - 1] = px;
  chartDirty = true;
}

function applyKline(k) {
  if (!priceChart || !candleTs.length) return;
  const last = candleTs[candleTs.length - 1];
  if (k.t > last) {
    candleTs.push(k.t);
    priceChart.data.labels.push(fmtTime(k.t / 1000, $("tf").value === "4h" || $("tf").value === "1h"));
    priceChart.data.datasets.forEach((ds, i) => ds.data.push(i === 0 ? +k.c : i === 2 ? ds.data[ds.data.length - 1] : null));
  } else if (k.t === last) {
    priceChart.data.datasets[0].data[candleTs.length - 1] = +k.c;
  }
  chartDirty = true;
}

// No maximo 4 repintagens por segundo, para o ecra nao ficar a tremer
function scheduleRender() {
  if (renderTimer) return;
  renderTimer = setTimeout(() => {
    renderTimer = null;
    renderLive();
  }, 250);
}

function renderLive() {
  renderSummary();
  const sym = $("symbol").value, l = live[sym];
  if (l?.price != null && $("mPrice")) {
    $("mPrice").textContent = price(l.price);
    if (l.open24) {
      const chg = (l.price / l.open24 - 1) * 100;
      $("m24").innerHTML = `${arrow(chg)}${signed(chg)}%`;
    }
  }
  if (chartDirty && priceChart) { chartDirty = false; priceChart.update("none"); }
}

/* ---------- Graficos ---------- */
let equityChart, priceChart;

function baseOptions(valueLabel) {
  const text = css("--muted"), grid = "rgba(139,148,163,.15)";
  return {
    responsive: true, maintainAspectRatio: false, animation: false,
    interaction: { mode: "index", intersect: false },
    plugins: {
      legend: { display: false },
      tooltip: { callbacks: { label: (c) => (c.parsed.y == null ? null : `${c.dataset.label}: ${valueLabel(c.parsed.y)}`) } },
    },
    scales: {
      x: { ticks: { color: text, maxTicksLimit: 7, maxRotation: 0 }, grid: { display: false } },
      y: { ticks: { color: text, callback: (v) => price(v) }, grid: { color: grid } },
    },
  };
}

const fmtTime = (ts, withDay) => {
  const d = new Date(ts * 1000);
  const hm = d.toLocaleTimeString("pt-PT", { hour: "2-digit", minute: "2-digit" });
  return withDay ? `${d.toLocaleDateString("pt-PT", { day: "2-digit", month: "2-digit" })} ${hm}` : hm;
};

async function loadEquity() {
  const pts = await api("/api/equity");
  $("equityEmpty").hidden = pts.length >= 2;
  $("equityChart").hidden = pts.length < 2;
  if (pts.length < 2) return;
  const multiDay = pts[pts.length - 1][0] - pts[0][0] > 86400;
  const labels = pts.map((p) => fmtTime(p[0], multiDay));
  const data = pts.map((p) => p[1]);
  if (!equityChart) {
    equityChart = new Chart($("equityChart"), {
      type: "line",
      data: { labels, datasets: [{ label: "Carteira", data, borderColor: css("--series"), borderWidth: 2, pointRadius: 0, pointHoverRadius: 4, tension: 0.2 }] },
      options: baseOptions((v) => `${num(v)} USDT`),
    });
  } else {
    equityChart.data.labels = labels;
    equityChart.data.datasets[0].data = data;
    equityChart.update();
  }
}

async function loadPrice() {
  const symbol = $("symbol").value;
  if (!symbol) return;
  const [base, quote] = symbol.split("/");
  let r;
  try {
    r = await api(`/api/candles/${base}/${quote}?tf=${$("tf").value}`);
  } catch (e) {
    return;
  }
  candleTs = r.candles.map((c) => c[0]);
  const labels = r.candles.map((c) => fmtTime(c[0] / 1000, $("tf").value === "4h" || $("tf").value === "1h"));
  const closes = r.candles.map((c) => c[1]);

  // Cada ordem vai para a vela mais proxima (ordens anteriores ao grafico ficam de fora)
  const marks = closes.map(() => null), styles = [], rotation = [], colors = [];
  r.trades.forEach((t) => {
    const ms = t.ts * 1000;
    if (ms < candleTs[0] - 1) return;
    const i = candleTs.reduce((best, x, k) => (Math.abs(x - ms) < Math.abs(candleTs[best] - ms) ? k : best), 0);
    marks[i] = t.price;
    styles[i] = "triangle";
    rotation[i] = t.side === "buy" ? 0 : 180;
    colors[i] = t.side === "buy" ? css("--good") : css("--bad");
  });

  const pos = (window.lastSummary?.positions || []).find((p) => p.symbol === symbol);
  const datasets = [
    { label: "Preco", data: closes, borderColor: css("--series"), borderWidth: 2, pointRadius: 0, pointHoverRadius: 4, tension: 0.15, order: 2 },
    { label: "Ordens", data: marks, showLine: false, pointStyle: styles, rotation, pointRadius: 8, pointHoverRadius: 10,
      backgroundColor: colors, borderColor: css("--card"), borderWidth: 2, order: 1 },
    { label: "Entrada media", data: closes.map(() => pos?.avg ?? null), borderColor: css("--muted"), borderDash: [6, 4], borderWidth: 1.5, pointRadius: 0, order: 3 },
  ];

  if (!priceChart) {
    priceChart = new Chart($("priceChart"), { type: "line", data: { labels, datasets }, options: baseOptions(price) });
  } else {
    priceChart.data.labels = labels;
    priceChart.data.datasets = datasets;
    priceChart.update("none");
  }
}

/* ---------- Carteira (valores do servidor, recalculados com o preco ao vivo) ---------- */
async function loadSummary() {
  window.lastSummary = await api("/api/summary");
  renderSummary();
  wsConnect(); // as posicoes podem ter mudado: subscreve as moedas novas
}

function renderSummary() {
  const s = window.lastSummary;
  if (!s) return;
  const tag = $("mode");
  tag.textContent = s.mode.toUpperCase();
  tag.className = "tag " + (s.mode === "paper" ? "paper" : "live");

  const rows = s.positions.map((p) => {
    const px = live[p.symbol]?.price ?? p.price;
    return { ...p, price: px, value: p.qty * px, pnl: p.avg ? (px - p.avg) * p.qty : null, pnl_pct: p.avg ? (px / p.avg - 1) * 100 : null };
  });
  const exposure = rows.reduce((a, p) => a + p.value, 0);
  const equity = s.usdt + exposure;
  const dayPnl = equity - s.day_start;
  const dayPct = s.day_start ? (equity / s.day_start - 1) * 100 : 0;
  const loss = Math.max(0, s.day_start - equity);

  $("tEquity").textContent = `${num(equity)} USDT`;
  $("tUsdt").textContent = `${num(s.usdt)} USDT`;
  $("tDay").innerHTML = `${arrow(dayPnl)}${signed(dayPnl)} USDT`;
  $("tDaySub").textContent = `${signed(dayPct)}% | realizado ${signed(s.realized_today)}`;
  $("tExp").textContent = `${num(exposure)} USDT`;
  $("tExpSub").textContent = `limite ${num(s.max_exposure, 0)} | ${rows.length} moeda(s)`;

  const pct = Math.min(100, (loss / s.max_daily_loss) * 100);
  $("tLoss").textContent = `${num(loss)} / ${num(s.max_daily_loss, 0)}`;
  $("tLossBar").style.width = `${pct}%`;
  $("tLossBar").className = pct >= 80 ? "hot" : "";
  $("tLossSub").textContent = pct >= 80 ? "⚠ perto do limite: o bot vende tudo e pausa" : `${num(pct, 0)}% do limite`;

  $("positions").innerHTML = rows.length
    ? `<tr><th>Moeda</th><th class="n">Quantidade</th><th class="n">Entrada</th><th class="n">Atual</th><th class="n">Valor (USDT)</th><th class="n">Resultado</th><th class="n">Stop-loss</th></tr>` +
      rows.map((p) => `<tr class="click" data-symbol="${esc(p.symbol)}">
        <td><b>${esc(p.symbol)}</b></td><td class="n">${num(p.qty, 6)}</td><td class="n">${p.avg ? price(p.avg) : "-"}</td>
        <td class="n">${price(p.price)}</td><td class="n">${num(p.value)}</td>
        <td class="n">${p.pnl == null ? "-" : `${arrow(p.pnl)}${signed(p.pnl)} USDT (${signed(p.pnl_pct)}%)`}</td>
        <td class="n">${p.stop ? price(p.stop) : "-"}</td></tr>`).join("")
    : `<tr><td class="muted">Sem moedas em carteira. O bot ainda nao comprou nada.</td></tr>`;
}

$("positions").addEventListener("click", (e) => {
  const tr = e.target.closest("tr.click");
  if (!tr) return;
  $("symbol").value = tr.dataset.symbol;
  refreshSymbol();
  window.scrollTo({ top: $("priceChart").offsetTop - 120, behavior: "smooth" });
});

async function loadTrades() {
  const ts = await api("/api/trades");
  $("trades").innerHTML = ts.length
    ? `<tr><th>Data</th><th>Lado</th><th>Moeda</th><th class="n">Preco</th><th class="n">USDT</th><th class="n">Resultado</th><th>Motivo</th></tr>` +
      ts.map((t) => `<tr><td>${esc(new Date(t.ts * 1000).toLocaleString("pt-PT", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" }))}</td>
        <td>${t.side === "buy" ? '<span class="up">▲</span> Compra' : '<span class="down">▼</span> Venda'}</td><td>${esc(t.symbol)}</td>
        <td class="n">${price(t.price)}</td><td class="n">${num(t.usdt)}</td>
        <td class="n">${t.side === "sell" ? `${arrow(t.pnl)}${signed(t.pnl)} USDT` : "-"}</td><td class="why">${esc(t.why)}</td></tr>`).join("")
    : `<tr><td class="muted">Sem ordens ainda.</td></tr>`;
}

/* ---------- Mercado e analise ---------- */
async function loadSymbols() {
  const list = await api("/api/symbols");
  const sel = $("symbol"), cur = sel.value;
  sel.innerHTML = list.map((s) => `<option>${esc(s)}</option>`).join("");
  if (list.includes(cur)) sel.value = cur;
}

// Indicadores (RSI, EMAs) vem do servidor; preco e variacao 24h sao atualizados ao vivo por renderLive
async function loadMarket() {
  if (!$("symbol").value) return;
  const [base, quote] = $("symbol").value.split("/");
  try {
    const m = await api(`/api/market/${base}/${quote}`);
    $("market").innerHTML = `
      <dt>Preco</dt><dd id="mPrice">${price(m.price)}</dd>
      <dt>24h</dt><dd id="m24">${arrow(m.change_24h_pct)}${signed(m.change_24h_pct)}%</dd>
      <dt>RSI (14)</dt><dd>${m.rsi14}</dd>
      <dt>EMA 20 / 50</dt><dd>${price(m.ema20)} / ${price(m.ema50)}</dd>
      <dt>Volatilidade (ATR)</dt><dd>${num(m.atr_pct)}% por vela</dd>
      <dt>Tendencia 1h / 4h</dt><dd>${esc(m.trend_1h?.ema20_vs_ema50 ?? "-")} / ${esc(m.trend_4h?.ema20_vs_ema50 ?? "-")}</dd>
      <dt>Min / max (100 velas)</dt><dd>${price(m.low_100)} / ${price(m.high_100)}</dd>`;
  } catch (e) {
    $("market").innerHTML = `<dt class="error">${esc(e.message)}</dt><dd></dd>`;
  }
}

const refreshSymbol = () => { loadMarket(); loadPrice().then(wsConnect); wsConnect(); };

let pending = null;

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
    $("proposal").innerHTML += `<p>Executado (${esc(o.mode)}): ${esc(o.side)} ${num(o.qty, 6)} ${esc(o.symbol)} a ${price(o.price)}.</p>`;
    pending = null;
    btn.hidden = true;
    refreshAll();
  } catch (e) {
    $("proposal").innerHTML += `<p class="error">${esc(e.message)}</p>`;
  } finally {
    btn.disabled = false;
  }
};

$("dismiss").onclick = () => { pending = null; $("result").hidden = true; };

/* ---------- Modo automatico ---------- */
let autoOn = false;

async function loadAuto() {
  const a = await api("/api/auto");
  autoOn = a.enabled;
  const b = $("autoToggle");
  b.textContent = a.enabled ? "Desligar modo automatico" : "Ligar modo automatico";
  b.className = a.enabled ? "on" : "";
  const watching = a.universe?.length ? ` A vigiar: ${a.universe.map((s) => s.split("/")[0]).join(", ")}.` : "";
  $("autoState").textContent = a.halted ? "Pausado ate amanha: limite de perda diaria atingido."
    : a.enabled ? `Ativo. Ultimo ciclo: ${a.last_tick || "a arrancar..."}.${watching}` : "Desligado.";
  $("autoLog").innerHTML = a.log.slice(0, 30).map((l) => `<tr class="${esc(l.kind)}"><td>${esc(l.t)}</td><td>${esc(l.msg)}</td></tr>`).join("");
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

/* ---------- Arranque ---------- */
const safe = (fn) => fn().catch((e) => console.error(e));

async function refreshAll() {
  await safe(loadSummary);
  await Promise.all([safe(loadEquity), safe(loadTrades)]);
}

$("symbol").onchange = refreshSymbol;
$("tf").onchange = () => { loadPrice().then(wsConnect); wsConnect(); };

(async () => {
  await safe(loadSymbols);
  await safe(loadSummary);
  refreshSymbol();
  safe(loadEquity); safe(loadTrades); safe(loadAuto);
  setInterval(() => safe(loadAuto), 5000);
  setInterval(() => { safe(loadSummary); safe(loadTrades); }, 10000);   // posicoes e ordens do servidor
  setInterval(() => safe(loadEquity), 60000);
  setInterval(loadMarket, 30000);                                      // indicadores
  setInterval(() => safe(loadSymbols), 300000);
})();
