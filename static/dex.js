const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const num = (n, d = 2) => (n == null || isNaN(n) ? "-" : Number(n).toLocaleString("pt-PT", { maximumFractionDigits: d }));
const signed = (n, d = 2) => (n == null || isNaN(n) ? "-" : (n > 0 ? "+" : "") + num(n, d));
const cls = (n) => (n > 0 ? "up" : n < 0 ? "down" : "");
const dur = (min) => (min >= 1440 ? `${num(min / 1440, 1)} d` : min >= 120 ? `${num(min / 60, 1)} h` : `${min} min`);
const usd = (n) => (n == null ? "-" : n >= 1e6 ? `${num(n / 1e6, 2)}M` : n >= 1e3 ? `${num(n / 1e3, 1)}k` : num(n, 0));
const decimals = (p) => (p > 0 ? Math.min(12, Math.max(2, 3 - Math.floor(Math.log10(p)))) : 2);
const fmtPrice = (p) => (p == null ? "-" : Number(p).toLocaleString("pt-PT", { minimumFractionDigits: decimals(p), maximumFractionDigits: decimals(p) }));
const css = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
const store = {
  get: (k) => { try { return localStorage.getItem(k); } catch { return null; } },
  set: (k, v) => { try { localStorage.setItem(k, v); } catch { /* sem armazenamento */ } },
};

let S = null;                 // ultimo estado do servidor
let on = false;
let tab = store.get("dexTab") || "positions";
let sel = null;               // {id, network, pool, token, name}
let chart, candles, volume, lines = [], eqChart, eqSeries, lastCandles = [], chartKey = null;

async function api(url, body) {
  const res = await fetch(url, body ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } : undefined);
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || res.statusText);
  return data;
}

const FUNNEL = {
  vistas: "Pools vistas", passam_filtros: "Passam os filtros", ja_tenho: "Ja tenho em carteira", ja_analisada: "Analisada ha menos de 30 min",
  pouca_liquidez: "Liquidez abaixo do minimo", pouca_liquidez_p_antiga: "Moeda antiga com pouca liquidez", muito_nova: "Demasiado nova",
  muito_velha: "Demasiado antiga", pouco_volume: "Volume baixo na ultima hora", poucos_compradores: "Poucos compradores",
  poucos_vendedores: "Poucos vendedores (saida duvidosa)", ja_disparou: "Ja disparou demasiado", sem_preco: "Sem preco",
  volume_suspeito: "Volume suspeito (falso?)", vendas_bloqueadas: "Compras sem vendas (ninguem consegue sair?)",
  "seguranca:rugcheck_grave": "RugCheck: risco grave", "seguranca:rugcheck_score": "RugCheck: score de risco alto", moeda_grande_ou_stable: "Moeda grande ou stablecoin",
  "seguranca:mint_ativo": "Dono pode criar mais moeda", "seguranca:freeze_ativo": "Dono pode congelar carteiras", "seguranca:honeypot": "Honeypot",
  "seguranca:dono_com_muito": "Dono com demasiada percentagem", "seguranca:holders_concentrados": "Holders muito concentrados",
};

const explorer = (n, token) => (n === "solana" ? `https://solscan.io/token/${token}` : n === "base" ? `https://basescan.org/token/${token}` : null);
const links = (n, pool, token) => [`<a href="https://dexscreener.com/${esc(n)}/${esc(pool)}" target="_blank" rel="noopener">DexScreener</a>`]
  .concat(token && explorer(n, token) ? [`<a href="${explorer(n, token)}" target="_blank" rel="noopener">Explorer</a>`] : []).join("");

// ---------- graficos ----------
function initCharts() {
  const base = { autoSize: true, layout: { background: { color: "transparent" }, textColor: css("--muted"), fontFamily: "system-ui, sans-serif" },
                 grid: { vertLines: { color: "rgba(133,144,162,.08)" }, horzLines: { color: "rgba(133,144,162,.08)" } },
                 rightPriceScale: { borderColor: css("--line") }, timeScale: { borderColor: css("--line"), timeVisible: true, secondsVisible: false },
                 crosshair: { mode: 0 } };
  chart = LightweightCharts.createChart($("chart"), base);
  candles = chart.addCandlestickSeries({ upColor: css("--good"), downColor: css("--bad"), borderVisible: false, wickUpColor: css("--good"), wickDownColor: css("--bad") });
  volume = chart.addHistogramSeries({ priceFormat: { type: "volume" }, priceScaleId: "vol", lastValueVisible: false, priceLineVisible: false });
  chart.priceScale("vol").applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });
  eqChart = LightweightCharts.createChart($("eqChart"), base);
  eqSeries = eqChart.addAreaSeries({ lineColor: css("--accent"), topColor: "rgba(79,140,255,.28)", bottomColor: "rgba(79,140,255,0)", lineWidth: 2, priceLineVisible: false });
}

function setLines(pos) {
  lines.forEach((l) => candles.removePriceLine(l));
  lines = [];
  if (!pos) return;
  const add = (price, color, title, style) => price && lines.push(candles.createPriceLine({ price, color, lineWidth: 1, lineStyle: style, axisLabelVisible: true, title }));
  add(pos.entry_price, css("--accent"), "entrada", 2);
  add(pos.stop_price, css("--bad"), "stop", 1);
  add(pos.target_price, css("--good"), "alvo", 1);
}

async function loadCandles(force) {
  if (!sel || !sel.pool) return;
  const key = `${sel.network}:${sel.pool}`;
  try {
    const rows = await api(`/api/dex/candles?network=${encodeURIComponent(sel.network)}&pool=${encodeURIComponent(sel.pool)}`);
    if (key !== `${sel.network}:${sel.pool}`) return;      // mudou de moeda enquanto carregava
    lastCandles = rows;
    const p = rows.length ? rows[rows.length - 1].close : 1;
    candles.applyOptions({ priceFormat: { type: "price", precision: decimals(p) + 1, minMove: Math.pow(10, -(decimals(p) + 1)) } });
    candles.setData(rows.map(({ time, open, high, low, close }) => ({ time, open, high, low, close })));
    volume.setData(rows.map((r) => ({ time: r.time, value: r.volume, color: r.close >= r.open ? "rgba(38,166,154,.4)" : "rgba(239,83,80,.4)" })));
    if (chartKey !== key || force) { chart.timeScale().fitContent(); chartKey = key; }
    header();
  } catch (e) {
    $("cLegend").textContent = `Sem velas para esta moeda (${e.message}). A GeckoTerminal pode estar a limitar pedidos.`;
  }
}

function header() {
  if (!sel) return;
  const pos = S && S.positions.find((p) => p.id === sel.id);
  const last = pos ? pos.price : lastCandles.length ? lastCandles[lastCandles.length - 1].close : null;
  const first = lastCandles.length ? lastCandles[0].open : null;
  $("cName").textContent = sel.name;
  $("cNet").textContent = sel.network;
  $("cTag").textContent = pos ? "em carteira" : "";
  $("cPrice").textContent = last ? `${fmtPrice(last)} USD` : "";
  const chg = first && last ? (last / first - 1) * 100 : null;
  $("cChg").innerHTML = chg == null ? "" : `<span class="${cls(chg)}">${signed(chg, 1)}%</span> <span class="muted">nas ultimas ${lastCandles.length} velas</span>`;
  $("cLinks").innerHTML = links(sel.network, sel.pool, sel.token);
  $("cLegend").textContent = pos ? "Velas de 1 minuto. Linhas: entrada (azul), stop (vermelho) e alvo (verde)." : "Velas de 1 minuto.";
}

function select(item) {
  const [network, pool] = item.id.split(":");
  sel = { id: item.id, network: item.network || network, pool: item.pool || pool, token: item.token, name: item.name };
  store.set("dexSel", JSON.stringify(sel));
  chartKey = null;
  const pos = S && S.positions.find((p) => p.id === sel.id);
  setLines(pos);
  header();
  loadCandles(true);
  renderLists();
  renderDetail();
}

// ---------- listas laterais e detalhe ----------
const badge = (d) => `<span class="badge ${esc(d)}">${esc(d)}</span>`;

function renderLists() {
  if (!S) return;
  $("watchPos").innerHTML = S.positions.length ? S.positions.map((p) => `<div class="wrow ${sel && sel.id === p.id ? "sel" : ""}" data-id="${esc(p.id)}">
      <div class="nm"><b>${esc(p.name)}</b><small>${esc(p.network)} | ${dur(p.held_min)} | alvo +${num(p.target_pct, 0)}%</small></div>
      <div class="vl"><b class="${cls(p.pnl_pct)}">${signed(p.pnl_pct, 1)}%</b><small class="muted"><br>${num(p.value)} USD</small></div></div>`).join("")
    : `<div class="empty">Sem posicoes abertas.</div>`;
  $("watchAn").innerHTML = S.analysed.length ? S.analysed.slice(0, 14).map((a) => `<div class="wrow ${sel && sel.id === a.id ? "sel" : ""}" data-id="${esc(a.id)}">
      <div class="nm"><b>${esc(a.name)}</b><small>${esc(a.t)} | ${esc(a.network)} | ${dur(a.age_min)}</small></div>
      <div class="vl">${badge(a.decision)}<small class="muted"><br>${a.confidence != null ? Math.round(a.confidence * 100) + "%" : ""}</small></div></div>`).join("")
    : `<div class="empty">Ainda sem analises.</div>`;
}

function renderDetail() {
  const box = $("detail");
  if (!S || !sel) { box.innerHTML = `<p class="muted">Clica numa posicao ou numa moeda analisada para veres o grafico e os detalhes.</p>`; return; }
  const pos = S.positions.find((p) => p.id === sel.id);
  const an = S.analysed.find((a) => a.id === sel.id);
  const cl = S.closed.find((c) => c.id === sel.id);
  let html = "";
  if (pos) {
    html += `<dl><dt>Custo</dt><dd>${num(pos.cost)} USD</dd><dt>Valor liquido</dt><dd>${num(pos.value)} USD</dd>
      <dt>Resultado</dt><dd class="${cls(pos.pnl_pct)}">${signed(pos.pnl_pct, 1)}%</dd><dt>Maximo</dt><dd>${signed(pos.peak_pct, 1)}%</dd>
      <dt>Entrada</dt><dd>${fmtPrice(pos.entry_price)}</dd><dt>Stop</dt><dd class="down">${fmtPrice(pos.stop_price)}</dd>
      <dt>Alvo</dt><dd class="up">${fmtPrice(pos.target_price)} (+${num(pos.target_pct, 0)}%)</dd><dt>Em carteira</dt><dd>${dur(pos.held_min)}</dd>
      <dt>Liquidez</dt><dd>${usd(pos.liq)} USD</dd></dl>`;
    if (pos.sig) html += `<p><a href="https://solscan.io/tx/${esc(pos.sig)}" target="_blank" rel="noopener">Ver transacao de compra</a></p>`;
    if (pos.reason) html += `<h4>Porque comprou</h4><p>${esc(pos.reason)}</p>`;
  }
  if (an) {
    html += `<h4>Ultima analise (${esc(an.t)})</h4><dl><dt>Decisao</dt><dd>${badge(an.decision)}</dd>
      ${an.confidence != null ? `<dt>Confianca</dt><dd>${Math.round(an.confidence * 100)}%</dd>` : ""}
      ${an.size_eur != null ? `<dt>Ordem</dt><dd>${num(an.size_eur)} EUR</dd>` : ""}${an.target_pct != null ? `<dt>Alvo</dt><dd>+${num(an.target_pct, 0)}%</dd>` : ""}
      <dt>Idade</dt><dd>${dur(an.age_min)}</dd><dt>Liquidez</dt><dd>${usd(an.liq)} USD</dd><dt>FDV</dt><dd>${usd(an.fdv)} USD</dd>
      <dt>Volume 1h</dt><dd>${usd(an.vol_h1)} USD</dd><dt>Variacao 1h / 24h</dt><dd>${signed(an.chg_h1, 1)}% / ${signed(an.chg_h24, 1)}%</dd>
      <dt>Compras / vendas 1h</dt><dd>${num(an.buyers, 0)} / ${num(an.sellers, 0)}</dd></dl>`;
    if (an.reason) html += `<h4>Raciocinio do Grok</h4><p>${esc(an.reason)}</p>`;
    if (an.risks) html += `<h4>Riscos apontados</h4><p>${esc(an.risks)}</p>`;
    if (an.seguranca) {
      const sg = an.seguranca;
      html += `<h4>Seguranca</h4><div class="chips">${[["mint", sg.mint_authority], ["freeze", sg.freeze_authority], ["honeypot", sg.is_honeypot]]
        .map(([k, v]) => `<span class="chip">${k}: ${esc(v ?? "?")}</span>`).join("")}<span class="chip">dono ${sg.dev_holding_pct ?? "?"}%</span><span class="chip">top10 ${sg.top10_pct ?? "?"}%</span><span class="chip">holders ${sg.holders ?? "?"}</span></div>`;
    }
  }
  if (cl && !pos) html += `<h4>Ultima operacao fechada</h4><dl><dt>Saida</dt><dd>${esc(cl.kind)}</dd><dt>Resultado</dt><dd class="${cls(cl.pnl_pct)}">${signed(cl.pnl_pct, 1)}% (${signed(cl.pnl_usd)} USD)</dd><dt>Em carteira</dt><dd>${dur(cl.held_min)}</dd></dl>`;
  box.innerHTML = html || `<p class="muted">Sem dados guardados desta moeda.</p>`;
}

// ---------- separadores ----------
const q = () => $("search").value.trim().toLowerCase();
const hit = (o) => !q() || JSON.stringify(o).toLowerCase().includes(q());
const empty = (t) => `<div class="empty">${t}</div>`;

function tablePositions() {
  const rows = S.positions.filter(hit);
  return rows.length ? `<table><tr><th>Moeda</th><th>Rede</th><th class="n">Custo</th><th class="n">Valor</th><th class="n">Resultado</th><th class="n">Maximo</th><th class="n">Alvo</th><th class="n">Liquidez</th><th class="n">Tempo</th></tr>` +
    rows.map((p) => `<tr class="row ${sel && sel.id === p.id ? "sel" : ""}" data-id="${esc(p.id)}"><td><b>${esc(p.name)}</b></td><td>${esc(p.network)}</td><td class="n">${num(p.cost)}</td><td class="n">${num(p.value)}</td>
      <td class="n ${cls(p.pnl_pct)}">${signed(p.pnl_pct, 1)}%</td><td class="n">${signed(p.peak_pct, 1)}%</td><td class="n">+${num(p.target_pct, 0)}%</td><td class="n">${usd(p.liq)}</td><td class="n">${dur(p.held_min)}</td></tr>`).join("") + "</table>"
    : empty("Sem posicoes abertas.");
}

function tableClosed() {
  const rows = S.closed.filter(hit);
  return rows.length ? `<table><tr><th>Moeda</th><th>Saida</th><th class="n">Resultado</th><th class="n">USD</th><th class="n">Custo</th><th class="n">Maximo</th><th class="n">Tempo</th><th>Motivo da entrada</th></tr>` +
    rows.map((r) => `<tr class="row ${sel && sel.id === r.id ? "sel" : ""}" data-id="${esc(r.id)}"><td><b>${esc(r.name)}</b></td><td>${esc(r.kind)}${r.kind === "rug" ? " (!)" : ""}</td>
      <td class="n ${cls(r.pnl_pct)}">${signed(r.pnl_pct, 1)}%</td><td class="n ${cls(r.pnl_usd)}">${signed(r.pnl_usd)}</td><td class="n">${num(r.cost)}</td><td class="n">${signed(r.peak_pnl_pct, 1)}%</td><td class="n">${dur(r.held_min)}</td><td class="why">${esc(r.reason)}</td></tr>`).join("") + "</table>"
    : empty("Sem operacoes fechadas.");
}

function tableAnalysed() {
  const d = $("decision").value;
  const rows = S.analysed.filter((a) => (!d || a.decision === d) && hit(a));
  return rows.length ? `<table><tr><th>Hora</th><th>Moeda</th><th>Decisao</th><th class="n">Conf.</th><th class="n">Idade</th><th class="n">Liquidez</th><th class="n">Vol 1h</th><th class="n">1h</th><th>Raciocinio</th></tr>` +
    rows.map((a) => `<tr class="row ${sel && sel.id === a.id ? "sel" : ""}" data-id="${esc(a.id)}"><td>${esc(a.t)}</td><td><b>${esc(a.name)}</b><br><span class="muted">${esc(a.network)}</span></td><td>${badge(a.decision)}</td>
      <td class="n">${a.confidence != null ? Math.round(a.confidence * 100) + "%" : "-"}</td><td class="n">${dur(a.age_min)}</td><td class="n">${usd(a.liq)}</td><td class="n">${usd(a.vol_h1)}</td>
      <td class="n ${cls(a.chg_h1)}">${signed(a.chg_h1, 0)}%</td><td class="why">${esc(a.reason)}</td></tr>`).join("") + "</table>"
    : empty("Sem analises que correspondam ao filtro.");
}

function tableScans() {
  const total = {};
  S.scans.forEach((sc) => Object.entries(sc.funnel).forEach(([k, v]) => { total[k] = (total[k] || 0) + v; }));
  const entries = Object.entries(total).sort((a, b) => b[1] - a[1]).filter(([k]) => hit(FUNNEL[k] || k));
  const max = Math.max(1, ...entries.map((e) => e[1]));
  const seen = S.scans.reduce((a, sc) => a + sc.vistas, 0), passed = S.scans.reduce((a, sc) => a + sc.passam, 0);
  let html = `<div class="sect">Porque foram rejeitadas as pools (ultimas ${S.scans.length} procuras: ${seen} vistas, ${passed} passaram)</div>`;
  html += entries.map(([k, v]) => `<div class="bar"><span>${esc(FUNNEL[k] || k)}</span><span class="track"><span class="fill" style="display:block;width:${(v / max) * 100}%"></span></span><b>${v}</b></div>`).join("") || empty("Ainda sem procuras.");
  html += `<div class="sect">Cada procura</div><table><tr><th>Hora</th><th class="n">Vistas</th><th class="n">Passam</th><th>Principais rejeicoes</th></tr>` +
    S.scans.map((sc) => `<tr><td>${esc(sc.t)}</td><td class="n">${sc.vistas}</td><td class="n">${sc.passam}</td><td class="why">${Object.entries(sc.funnel).sort((a, b) => b[1] - a[1]).slice(0, 4)
      .map(([k, v]) => `<span class="chip">${esc(FUNNEL[k] || k)} ${v}</span>`).join(" ")}</td></tr>`).join("") + "</table>";
  return html;
}

function tableLog() {
  const rows = S.log.filter(hit);
  return rows.length ? `<table>` + rows.map((l) => `<tr class="${esc(l.kind)}"><td class="n">${esc(l.t)}</td><td>${esc(l.msg)}</td></tr>`).join("") + "</table>" : empty("Sem registo.");
}

function renderTab() {
  if (!S) return;
  document.querySelectorAll(".tab").forEach((b) => b.classList.toggle("on", b.dataset.tab === tab));
  $("decision").hidden = tab !== "analysed";
  const body = $("tabBody");
  const top = body.scrollTop;
  body.innerHTML = { positions: tablePositions, closed: tableClosed, analysed: tableAnalysed, scans: tableScans, log: tableLog }[tab]();
  body.scrollTop = top;
}

// ---------- render geral ----------
function render(s) {
  S = s;
  on = s.enabled;
  const live = s.mode === "live";
  $("modeTag").textContent = !live ? "SIMULACAO" : s.dry_run ? "LIVE: DRY-RUN" : "DINHEIRO REAL";
  $("modeTag").className = "tag " + (!live ? "paper" : s.dry_run ? "dry" : "live");
  $("statusDot").className = "dot" + (on ? " on" : "");
  $("statusText").textContent = on ? "A funcionar" : "Parado";
  $("toggle").textContent = on ? "Parar" : "Ligar";
  $("toggle").className = on ? "on" : "";
  $("panic").hidden = !live;
  const w = s.wallet;
  $("wallet").hidden = !w;
  if (w) $("wallet").textContent = `${w.address.slice(0, 4)}...${w.address.slice(-4)}${w.sol != null ? ` | ${num(w.sol, 3)} SOL (${num(w.usd)} USD)` : ""}`;
  const b = $("banner");
  b.className = "banner" + (live && !s.dry_run ? " live" : "");
  b.textContent = !live ? "Simulacao com dinheiro virtual: nao ha carteira real nem chaves. Impacto no preco e comissoes sao modelados."
    : s.dry_run ? "Modo live em teste: cota e simula swaps reais, mas nao envia nada."
    : "DINHEIRO REAL: o bot compra e vende sozinho com a carteira indicada. Valores em USD.";
  $("disclaimer").textContent = `Regras: ordens de ${num(s.rules.size_min, 0)} a ${num(s.rules.size_max, 0)} EUR (1 EUR = ${num(s.rules.eurusd, 4)} USD), alvo entre +${s.rules.tp_min}% e +${s.rules.tp_max}%, stop-loss ${s.rules.stop}%, comissao ${s.rules.fee}% por lado, maximo ${s.rules.max_hold_h} h por posicao, procura a cada ${s.scan_sec} s. Resultados simulados nao garantem resultados reais.`;

  const pnlPct = (s.equity / s.start - 1) * 100;
  $("tEquity").textContent = `${num(s.equity)} USD`;
  $("tStart").textContent = `inicio ${num(s.start)} USD`;
  $("tPnl").innerHTML = `<span class="${cls(s.pnl_usd)}">${signed(s.pnl_usd)} USD</span>`;
  $("tPnlSub").textContent = `${signed(pnlPct)}%`;
  $("tToday").innerHTML = `<span class="${cls(s.today.pnl_usd)}">${signed(s.today.pnl_usd)} USD</span>`;
  $("tTodaySub").textContent = `${s.today.n} fechadas, ${s.today.wins} ganhas`;
  $("tCash").textContent = `${num(s.cash)} USD`;
  $("tPos").textContent = `${s.positions.length} / ${s.max_positions}`;
  $("tPosSub").textContent = `em jogo ${num(s.positions.reduce((a, p) => a + p.value, 0))} USD`;
  $("tWin").textContent = s.stats ? `${s.stats.win_rate_pct}%` : "-";
  $("tWinSub").textContent = s.stats ? `${s.stats.n} ops, ${s.stats.rugs} rug(s), media ${signed(s.stats.avg_pnl_pct, 1)}%` : "ainda sem operacoes";
  $("tScan").textContent = s.last_scan || "-";
  $("tScanSub").textContent = s.scans[0] ? `${s.scans[0].vistas} vistas, ${s.scans[0].passam} passam` : "";
  $("nPositions").textContent = s.positions.length || "";
  $("nClosed").textContent = s.closed.length || "";
  $("nAnalysed").textContent = s.analysed.length || "";

  const pos = sel && s.positions.find((p) => p.id === sel.id);
  setLines(pos);
  if (!sel) {
    const first = s.positions[0] || s.analysed[0];
    if (first) select(first);
  } else { header(); }
  renderLists();
  renderDetail();
  renderTab();

  const seen = new Set();
  const pts = (s.equity_curve || []).filter((p) => !seen.has(p[0]) && seen.add(p[0])).sort((a, b) => a[0] - b[0]);
  $("eqEmpty").hidden = pts.length >= 2;
  eqSeries.setData(pts.map((p) => ({ time: p[0], value: p[1] })));
  if (pts.length >= 2) eqChart.timeScale().fitContent();
}

// ---------- eventos ----------
document.addEventListener("click", (e) => {
  const row = e.target.closest("[data-id]");
  if (row && S) {
    const id = row.dataset.id;
    const item = S.positions.find((p) => p.id === id) || S.analysed.find((a) => a.id === id) || S.closed.find((c) => c.id === id);
    if (item) select(item);
    return;
  }
  const t = e.target.closest(".tab");
  if (t) { tab = t.dataset.tab; store.set("dexTab", tab); renderTab(); }
});
$("search").addEventListener("input", renderTab);
$("decision").addEventListener("change", renderTab);
$("toggle").onclick = async () => { render(await api("/api/dex/toggle", { enabled: !on })); };
$("panic").onclick = async () => {
  if (!confirm("Vender TODAS as posicoes ja e parar o bot?")) return;
  render(await api("/api/dex/panic", {}));
};

initCharts();
try { const saved = JSON.parse(store.get("dexSel") || "null"); if (saved && saved.id) sel = saved; } catch { /* ignora */ }
const tick = () => api("/api/dex/status").then(render).catch((e) => { $("statusText").textContent = `sem ligacao (${e.message})`; });
tick();
setInterval(tick, 3000);
setInterval(() => loadCandles(false), 10000);
if (sel) loadCandles(true);
