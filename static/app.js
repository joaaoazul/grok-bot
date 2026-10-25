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

const store = {
  get: (k) => { try { return localStorage.getItem(k); } catch { return null; } },
  set: (k, v) => { try { localStorage.setItem(k, v); } catch { /* sem armazenamento */ } },
};
const TF_SEC = { "5m": 300, "15m": 900, "1h": 3600, "4h": 14400 };

/* ---------- Tempo real: o browser liga-se direto aos WebSockets publicos da Binance ---------- */
const live = {};          // "BTC/USDT" -> { price, open24 }
const WS_HOSTS = ["wss://stream.binance.com:9443", "wss://stream.binance.com:443", "wss://data-stream.binance.vision:443"];
let hostIdx = 0, ws = null, wsKey = "", wsNames = {};
let renderTimer = null;

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
    if (sym === $("symbol").value) bumpBar(+d.p);
  } else if (d.e === "kline" && d.k.i === $("tf").value && sym === $("symbol").value) {
    pushKline(d.k);
  }
  scheduleRender();
}

/* ---------- Graficos (lightweight-charts: so a ultima vela e atualizada, nunca o grafico inteiro) ---------- */
let priceChart, candleSeries, volumeSeries, equityChart, equitySeries;
let lastBar = null, barDirty = false, avgLine = null, stopLine = null, priceKey = "";

const localTick = (t) => {
  const d = new Date(t * 1000);
  return d.getHours() === 0 && d.getMinutes() === 0
    ? d.toLocaleDateString("pt-PT", { day: "2-digit", month: "2-digit" })
    : d.toLocaleTimeString("pt-PT", { hour: "2-digit", minute: "2-digit" });
};

function chartOptions() {
  return {
    autoSize: true,
    layout: { background: { color: "transparent" }, textColor: css("--muted"), fontFamily: "JetBrains Mono, ui-monospace, Consolas, monospace" },
    grid: { vertLines: { color: "rgba(139,148,163,.08)" }, horzLines: { color: "rgba(139,148,163,.08)" } },
    rightPriceScale: { borderColor: css("--line") },
    timeScale: { borderColor: css("--line"), timeVisible: true, secondsVisible: false, tickMarkFormatter: localTick },
    localization: { timeFormatter: (t) => new Date(t * 1000).toLocaleString("pt-PT", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" }) },
    crosshair: { mode: 0 },
  };
}

function initCharts() {
  priceChart = LightweightCharts.createChart($("priceChart"), chartOptions());
  candleSeries = priceChart.addCandlestickSeries({ upColor: css("--good"), downColor: css("--bad"), borderVisible: false, wickUpColor: css("--good"), wickDownColor: css("--bad") });
  volumeSeries = priceChart.addHistogramSeries({ priceFormat: { type: "volume" }, priceScaleId: "vol", lastValueVisible: false, priceLineVisible: false });
  priceChart.priceScale("vol").applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });
  equityChart = LightweightCharts.createChart($("equityChart"), chartOptions());
  equitySeries = equityChart.addAreaSeries({ lineColor: css("--series"), topColor: "rgba(230,235,240,.16)", bottomColor: "rgba(230,235,240,0)", lineWidth: 2, priceLineVisible: false });
}

// Cada negocio mexe so no fecho/maximo/minimo da vela em curso. O desenho vai no proximo frame (ate ~60/s),
// sem esperar pelo resto da pagina, e varios negocios no mesmo frame fundem-se num so desenho.
function bumpBar(px) {
  if (!lastBar) return;
  lastBar.close = px;
  lastBar.high = Math.max(lastBar.high, px);
  lastBar.low = Math.min(lastBar.low, px);
  if (!barDirty) { barDirty = true; requestAnimationFrame(paintBar); }
}

function paintBar() {
  if (barDirty && lastBar) { barDirty = false; candleSeries.update(lastBar); }
}

function pushKline(k) {
  const t = Math.floor(k.t / 1000);
  if (lastBar && t < lastBar.time) return;
  lastBar = { time: t, open: +k.o, high: +k.h, low: +k.l, close: +k.c };
  candleSeries.update(lastBar);
  volumeSeries.update({ time: t, value: +k.v, color: +k.c >= +k.o ? "rgba(61,220,151,.35)" : "rgba(255,77,106,.35)" });
  barDirty = false;
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
  if (barDirty && lastBar) { barDirty = false; candleSeries.update(lastBar); }
}

async function loadEquity() {
  const pts = await api("/api/equity");
  $("equityEmpty").hidden = pts.length >= 2;
  $("equityChart").hidden = pts.length < 2;
  if (pts.length < 2) return;
  const seen = new Set();
  equitySeries.setData(pts.filter((p) => !seen.has(p[0]) && seen.add(p[0])).sort((a, b) => a[0] - b[0]).map((p) => ({ time: p[0], value: p[1] })));
  equityChart.timeScale().fitContent();
}

function drawLines() {
  if (avgLine) { candleSeries.removePriceLine(avgLine); avgLine = null; }
  if (stopLine) { candleSeries.removePriceLine(stopLine); stopLine = null; }
  const pos = (window.lastSummary?.positions || []).find((p) => p.symbol === $("symbol").value);
  if (pos?.avg) avgLine = candleSeries.createPriceLine({ price: pos.avg, color: css("--muted"), lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: "entrada" });
  if (pos?.stop) stopLine = candleSeries.createPriceLine({ price: pos.stop, color: css("--bad"), lineWidth: 1, lineStyle: 1, axisLabelVisible: true, title: "stop" });
}

async function loadPrice() {
  const symbol = $("symbol").value, tf = $("tf").value;
  if (!symbol) return;
  const [base, quote] = symbol.split("/");
  let r;
  try {
    r = await api(`/api/candles/${base}/${quote}?tf=${tf}`);
  } catch (e) {
    $("priceChart").classList.remove("loading");
    return;
  }
  if (symbol !== $("symbol").value || tf !== $("tf").value) return;   // mudou enquanto carregava
  $("priceChart").classList.remove("loading");
  const rows = r.candles.map((c) => ({ time: c[0] / 1000, open: c[1], high: c[2], low: c[3], close: c[4] }));
  if (!rows.length) return;
  const p = rows[rows.length - 1].close;
  const prec = p >= 100 ? 2 : p >= 1 ? 4 : 8;
  candleSeries.applyOptions({ priceFormat: { type: "price", precision: prec, minMove: Math.pow(10, -prec) } });
  candleSeries.setData(rows);
  volumeSeries.setData(r.candles.map((c) => ({ time: c[0] / 1000, value: c[5], color: c[4] >= c[1] ? "rgba(61,220,151,.35)" : "rgba(255,77,106,.35)" })));
  lastBar = { ...rows[rows.length - 1] };
  barDirty = false;

  // Cada ordem fica na vela onde aconteceu (ordens anteriores ao grafico ficam de fora)
  const step = TF_SEC[tf], first = rows[0].time;
  const marks = r.trades.filter((t) => t.ts >= first).map((t) => ({
    time: Math.floor(t.ts / step) * step, position: t.side === "buy" ? "belowBar" : "aboveBar", shape: t.side === "buy" ? "arrowUp" : "arrowDown",
    color: t.side === "buy" ? css("--good") : css("--bad"), text: `${t.side === "buy" ? "C" : "V"} ${price(t.price)}`,
  })).sort((a, b) => a.time - b.time);
  candleSeries.setMarkers(marks);
  drawLines();
  const key = `${symbol}:${tf}`;
  if (key !== priceKey) { priceKey = key; priceChart.timeScale().fitContent(); }
}

/* ---------- Carteira (valores do servidor, recalculados com o preco ao vivo) ---------- */
let posOrder = [], posSortKey = store.get("posSort") || "value", posSortDir = Number(store.get("posDir")) || -1, posTableSig = "";
const posFilter = { q: store.get("posQ") || "", res: store.get("posRes") || "" };

async function loadSummary() {
  window.lastSummary = await api("/api/summary");
  renderSummary(true);
  drawLines();
  wsConnect(); // as posicoes podem ter mudado: subscreve as moedas novas
}

const POS_COLS = [["symbol", "Moeda", ""], ["qty", "Quantidade", "n"], ["avg", "Entrada", "n"], ["price", "Atual", "n"], ["value", "Valor (USDT)", "n"],
                  ["pnl_pct", "Resultado", "n"], ["stop", "Stop-loss", "n"]];

function liveRows() {
  return window.lastSummary.positions.map((p) => {
    const px = live[p.symbol]?.price ?? p.price;
    return { ...p, price: px, value: p.qty * px, pnl: p.avg ? (px - p.avg) * p.qty : null, pnl_pct: p.avg ? (px / p.avg - 1) * 100 : null };
  });
}

function sortRows(rows) {
  const k = posSortKey, d = posSortDir;
  return rows.slice().sort((a, b) => (k === "symbol" ? a.symbol.localeCompare(b.symbol) * d : ((a[k] ?? -Infinity) - (b[k] ?? -Infinity)) * d));
}

const posVisible = (p) => (!posFilter.q || p.symbol.toLowerCase().includes(posFilter.q.toLowerCase()))
  && (!posFilter.res || (posFilter.res === "win" ? (p.pnl ?? 0) > 0 : (p.pnl ?? 0) < 0));

function renderSummary(resort) {
  const s = window.lastSummary;
  if (!s) return;
  const tag = $("mode");
  tag.textContent = s.mode.toUpperCase();
  tag.className = "tag " + (s.mode === "paper" ? "paper" : "live");

  const rows = liveRows();
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

  renderPositions(rows, resort);
}

// A tabela so e reconstruida quando muda a lista, a ordem ou os filtros; entre dois ticks so os numeros mudam.
// Assim os botoes de venda nao desaparecem debaixo do rato.
function renderPositions(rows, resort) {
  const tbl = $("positions");
  if (resort || !posOrder.length) posOrder = sortRows(rows).map((p) => p.symbol);
  const by = Object.fromEntries(rows.map((p) => [p.symbol, p]));
  const shown = posOrder.filter((sym) => by[sym] && posVisible(by[sym]));
  const sig = shown.join(",") + posSortKey + posSortDir;
  if (!rows.length) { tbl.innerHTML = `<tr><td class="muted">Sem moedas em carteira. O bot ainda nao comprou nada.</td></tr>`; posTableSig = ""; return; }
  if (!shown.length) { tbl.innerHTML = `<tr><td class="muted">Nenhuma posicao corresponde ao filtro.</td></tr>`; posTableSig = ""; return; }
  if (sig !== posTableSig) {
    posTableSig = sig;
    tbl.innerHTML = `<tr>${POS_COLS.map(([k, label, c]) => `<th class="sortable ${c}" data-sort="${k}">${label}${k === posSortKey ? (posSortDir < 0 ? " ▼" : " ▲") : ""}</th>`).join("")}<th class="n">Vender</th></tr>` +
      shown.map((sym) => `<tr class="click" data-symbol="${esc(sym)}"><td><b>${esc(sym)}</b></td><td class="n" data-f="qty"></td><td class="n" data-f="avg"></td>
        <td class="n" data-f="price"></td><td class="n" data-f="value"></td><td class="n" data-f="res"></td><td class="n" data-f="stop"></td>
        <td class="n sellcell"><button type="button" class="rowsell" data-sell="${esc(sym)}" data-pct="25">25%</button><button type="button" class="rowsell" data-sell="${esc(sym)}" data-pct="50">50%</button><button type="button" class="rowsell all" data-sell="${esc(sym)}" data-pct="100">Tudo</button></td></tr>`).join("");
  }
  tbl.querySelectorAll("tr.click").forEach((tr) => {
    const p = by[tr.dataset.symbol];
    if (!p) return;
    // n: valor numerico; se mudou, a celula pisca (verde a subir, vermelho a descer)
    const set = (f, v, html, n) => {
      const td = tr.querySelector(`[data-f=${f}]`);
      if (!td || td.dataset.v === String(v)) return;
      const prev = Number(td.dataset.n);
      td.dataset.v = v;
      html ? (td.innerHTML = v) : (td.textContent = v);
      if (n != null) {
        td.dataset.n = n;
        if (prev && n !== prev) { td.classList.remove("flash-up", "flash-down"); void td.offsetWidth; td.classList.add(n > prev ? "flash-up" : "flash-down"); }
      }
    };
    set("qty", num(p.qty, 6)); set("avg", p.avg ? price(p.avg) : "-"); set("price", price(p.price), false, p.price); set("value", num(p.value), false, p.value);
    set("res", p.pnl == null ? "-" : `${arrow(p.pnl)}${signed(p.pnl)} USDT (${signed(p.pnl_pct)}%)`, true); set("stop", p.stop ? price(p.stop) : "-");
  });
}

$("positions").addEventListener("click", async (e) => {
  const th = e.target.closest("th[data-sort]");
  if (th) {
    posSortDir = th.dataset.sort === posSortKey ? -posSortDir : -1;
    posSortKey = th.dataset.sort;
    store.set("posSort", posSortKey); store.set("posDir", posSortDir);
    renderSummary(true);
    return;
  }
  const btn = e.target.closest("button[data-sell]");
  if (btn) {
    const sym = btn.dataset.sell, pct = +btn.dataset.pct;
    const p = liveRows().find((x) => x.symbol === sym);
    const what = pct >= 100 ? "TODA a posicao" : `${pct}% da posicao`;
    if (!confirm(`Vender ${what} em ${sym} ao preco de mercado?${p ? ` (valor atual ~${num(p.value * pct / 100)} USDT)` : ""}`)) return;
    document.querySelectorAll("button.rowsell").forEach((b) => { b.disabled = true; });
    try {
      const o = await api("/api/sell", { symbol: sym, pct });
      toast(`Vendido ${num(o.qty, 6)} ${sym} a ${price(o.price)} (${signed(o.pnl)} USDT)`);
    } catch (err) {
      toast(err.message, true);
    }
    posTableSig = "";
    refreshAll();
    return;
  }
  const tr = e.target.closest("tr.click");
  if (!tr) return;
  $("symbol").value = tr.dataset.symbol;
  refreshSymbol();
  window.scrollTo({ top: $("priceChart").offsetTop - 120, behavior: "smooth" });
});

function toast(msg, bad) {
  const t = $("toast");
  t.textContent = msg;
  t.className = "toast show" + (bad ? " bad" : "");
  clearTimeout(toast.t);
  toast.t = setTimeout(() => { t.className = "toast"; }, 5000);
}

/* ---------- Filtros (guardados no browser) ---------- */
function bindFilters() {
  [["posQ", posFilter, "q"], ["posRes", posFilter, "res"]].forEach(([id, obj, prop]) => {
    $(id).value = obj[prop];
    $(id).addEventListener("input", () => { obj[prop] = $(id).value; store.set(id, obj[prop]); posTableSig = ""; renderSummary(); });
  });
  ["fSide", "fRes", "fPeriod", "fQ"].forEach((id) => {
    const saved = store.get(id);
    if (saved != null) $(id).value = saved;
    $(id).addEventListener("input", () => { store.set(id, $(id).value); renderTrades(); });
  });
  $("fSymbol").addEventListener("input", renderTrades);
  $("fReset").onclick = () => {
    ["fSide", "fRes", "fSymbol", "fQ"].forEach((id) => { $(id).value = ""; store.set(id, ""); });
    $("fPeriod").value = "all"; store.set("fPeriod", "all");
    renderTrades();
  };
}

let allTrades = [], tradesSig = "";

async function loadTrades() {
  allTrades = await api("/api/trades");
  const sel = $("fSymbol"), cur = sel.value || store.get("fSymbol") || "";
  const syms = [...new Set(allTrades.map((t) => t.symbol))].sort();
  if (sel.options.length - 1 !== syms.length) {
    sel.innerHTML = `<option value="">Todas as moedas</option>` + syms.map((s) => `<option>${esc(s)}</option>`).join("");
    if (syms.includes(cur)) sel.value = cur;
  }
  tradesSig = "";
  renderTrades();
}

function renderTrades() {
  store.set("fSymbol", $("fSymbol").value);
  const side = $("fSide").value, res = $("fRes").value, sym = $("fSymbol").value, per = $("fPeriod").value, q = $("fQ").value.trim().toLowerCase();
  const now = Date.now() / 1000;
  const since = per === "today" ? new Date().setHours(0, 0, 0, 0) / 1000 : per === "7d" ? now - 7 * 86400 : per === "30d" ? now - 30 * 86400 : 0;
  const rows = allTrades.filter((t) => (!side || t.side === side) && (!sym || t.symbol === sym) && t.ts >= since
    && (!res || (t.side === "sell" && (res === "win" ? t.pnl > 0 : t.pnl < 0))) && (!q || `${t.symbol} ${t.why}`.toLowerCase().includes(q)));
  const sells = rows.filter((t) => t.side === "sell");
  const total = sells.reduce((a, t) => a + t.pnl, 0), wins = sells.filter((t) => t.pnl > 0).length;
  const fees = rows.reduce((a, t) => a + (t.fee || 0), 0), bought = rows.filter((t) => t.side === "buy").reduce((a, t) => a + t.usdt, 0), sold = sells.reduce((a, t) => a + t.usdt, 0);
  $("fSummary").textContent = `${rows.length} de ${allTrades.length} ordens | comprado ${num(bought)} USDT, vendido ${num(sold)} USDT | ${sells.length} vendas, ${sells.length ? Math.round(100 * wins / sells.length) : 0}% ganhas | comissoes ${num(fees, 4)} USDT | resultado ${signed(total)} USDT`;
  const sig = JSON.stringify([side, res, sym, per, q, rows.length, rows[0]?.ts, total]);
  if (sig === tradesSig) return;
  tradesSig = sig;
  $("trades").innerHTML = rows.length
    ? `<tr><th>Data</th><th>Lado</th><th>Moeda</th><th class="n">Quantidade</th><th class="n">Preco</th><th class="n">Entrada media</th><th class="n">USDT</th><th class="n">Comissao</th><th class="n">Resultado</th><th class="n">Restante</th><th>Motivo</th></tr>` +
      rows.map((t) => `<tr><td>${esc(new Date(t.ts * 1000).toLocaleString("pt-PT", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" }))}</td>
        <td>${t.side === "buy" ? '<span class="up">▲</span> Compra' : '<span class="down">▼</span> Venda'}</td><td>${esc(t.symbol)}</td>
        <td class="n">${num(t.qty, 6)}</td><td class="n">${price(t.price)}</td><td class="n">${t.avg ? price(t.avg) : "-"}</td><td class="n">${num(t.usdt)}</td>
        <td class="n">${t.fee ? num(t.fee, 4) : "-"}</td>
        <td class="n">${t.side === "sell" ? `${arrow(t.pnl)}${signed(t.pnl)} USDT${t.pnl_pct != null ? ` (${signed(t.pnl_pct)}%)` : ""}` : "-"}</td>
        <td class="n">${t.left != null ? num(t.left, 6) : "-"}</td><td class="why">${esc(t.why)}</td></tr>`).join("")
    : `<tr><td class="muted">Sem ordens que correspondam aos filtros.</td></tr>`;
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

const dim = () => $("priceChart").classList.add("loading");           // esbate o grafico antigo ate chegarem as velas novas
const refreshSymbol = () => { dim(); loadMarket(); loadPrice().then(wsConnect); wsConnect(); };

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
$("tf").onchange = () => { dim(); loadPrice().then(wsConnect); wsConnect(); };

initCharts();
bindFilters();
(async () => {
  await safe(loadSymbols);
  await safe(loadSummary);
  refreshSymbol();
  safe(loadEquity); safe(loadTrades); safe(loadAuto);
  setInterval(() => { if (!document.hidden) safe(loadAuto); }, 5000);
  const visible = (fn) => () => { if (!document.hidden) fn(); };       // com o separador escondido nao se pede nada
  setInterval(visible(() => { safe(loadSummary); safe(loadTrades); }), 10000);   // posicoes e ordens do servidor
  setInterval(visible(() => safe(loadEquity)), 60000);
  setInterval(visible(loadMarket), 30000);                                      // indicadores
  document.addEventListener("visibilitychange", () => { if (!document.hidden) { safe(loadSummary); safe(loadPrice); } });
  setInterval(() => safe(loadSymbols), 300000);
})();
