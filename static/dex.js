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

const F = { net: "", res: "", kind: "", per: "all", ...(() => { try { return JSON.parse(store.get("dexF") || "{}"); } catch { return {}; } })() };
const SORT = { positions: ["pnl_pct", -1], closed: ["ts", -1], ...(() => { try { return JSON.parse(store.get("dexSort") || "{}"); } catch { return {}; } })() };
const busy = new Set();       // posicoes com venda em curso

// So mexe no DOM quando o HTML mudou: poupa trabalho e evita perder cliques em botoes que seriam recriados iguais
const setHtml = (el, html) => { if (el._h !== html) { el._h = html; el.innerHTML = html; } };

function toast(msg, bad) {
  const t = $("toast");
  t.textContent = msg;
  t.className = "toast show" + (bad ? " bad" : "");
  clearTimeout(toast.t);
  toast.t = setTimeout(() => { t.className = "toast"; }, 5000);
}

async function sellOne(id) {
  const p = S && S.positions.find((x) => x.id === id);
  if (!p || busy.has(id)) return;
  const real = S.mode === "live" && !S.dry_run;
  if (!confirm(`Vender ${p.name} agora?\nValor liquido ~${num(p.value)} USD (${signed(p.pnl_pct, 1)}%).${real ? "\nIsto usa dinheiro REAL." : ""}`)) return;
  busy.add(id);
  renderLists(); renderDetail(); renderTab();
  try {
    const r = await api("/api/dex/sell", { id });
    toast(r.message);
    render(r);
  } catch (e) {
    toast(e.message, true);
  } finally {
    busy.delete(id);
    if (S) { renderLists(); renderDetail(); renderTab(); }
  }
}
const sellBtn = (id, cls = "sellbtn", label = "Vender") => `<button type="button" class="${cls}" data-sell="${esc(id)}"${busy.has(id) ? " disabled" : ""}>${busy.has(id) ? "a vender..." : label}</button>`;

let S = null;                 // ultimo estado do servidor
let on = false;
let tab = store.get("dexTab") || "positions";
let sel = null;               // {id, network, pool, token, name}
let chart, candles, volume, lines = [], eqChart, eqSeries, lastCandles = [], chartKey = null;
let tf = ["1m", "5m", "15m", "1h", "4h", "1d"].includes(store.get("dexTf")) ? store.get("dexTf") : "1m";
const TF_LABEL = { "1m": "1 minuto", "5m": "5 minutos", "15m": "15 minutos", "1h": "1 hora", "4h": "4 horas", "1d": "1 dia" };
const TF_POLL = { "1m": 5000, "5m": 8000, "15m": 15000, "1h": 30000, "4h": 60000, "1d": 120000 };   // a GeckoTerminal limita pedidos
const keyOf = () => (sel ? `${sel.network}:${sel.pool}:${tf}` : null);

// Realca por instantes o numero que acabou de mudar (verde a subir, vermelho a descer)
function flash(el, dir) {
  if (!dir) return;
  el.classList.remove("flash-up", "flash-down");
  void el.offsetWidth;
  el.classList.add(dir > 0 ? "flash-up" : "flash-down");
}

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

const money = (n, d = 2) => (n == null || isNaN(n) ? "-" : `${num(n, d)} USD`);
const when = (ts) => (ts ? new Date(ts * 1000).toLocaleString("pt-PT", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" }) : "-");
const qty = (t) => (t == null ? "-" : t >= 1000 ? num(t, 0) : num(t, 4));
const txLink = (net, sig, label) => (sig ? `<a href="${net === "solana" ? "https://solscan.io/tx/" : "https://basescan.org/tx/"}${esc(sig)}" target="_blank" rel="noopener">${label}</a>` : "");
const rows = (pairs) => `<dl>${pairs.filter(Boolean).map(([k, v, c]) => `<dt>${k}</dt><dd${c ? ` class="${c}"` : ""}>${v}</dd>`).join("")}</dl>`;

const explorer = (n, token) => (n === "solana" ? `https://solscan.io/token/${token}` : n === "base" ? `https://basescan.org/token/${token}` : null);
const links = (n, pool, token) => [`<a href="https://dexscreener.com/${esc(n)}/${esc(pool)}" target="_blank" rel="noopener">DexScreener</a>`]
  .concat(token && explorer(n, token) ? [`<a href="${explorer(n, token)}" target="_blank" rel="noopener">Explorer</a>`] : []).join("");

// ---------- graficos ----------
function initCharts() {
  const base = { autoSize: true, layout: { background: { color: "transparent" }, textColor: css("--muted"), fontFamily: "JetBrains Mono, ui-monospace, Consolas, monospace" },
                 grid: { vertLines: { color: "rgba(133,144,162,.08)" }, horzLines: { color: "rgba(133,144,162,.08)" } },
                 rightPriceScale: { borderColor: css("--line") }, timeScale: { borderColor: css("--line"), timeVisible: true, secondsVisible: false, rightOffset: 4,
                              tickMarkFormatter: (t) => { const d = new Date(t * 1000); return d.getHours() === 0 && d.getMinutes() === 0 ? d.toLocaleDateString("pt-PT", { day: "2-digit", month: "2-digit" }) : d.toLocaleTimeString("pt-PT", { hour: "2-digit", minute: "2-digit" }); } },
                 localization: { timeFormatter: (t) => new Date(t * 1000).toLocaleString("pt-PT", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" }) },
                 crosshair: { mode: 0 } };
  chart = LightweightCharts.createChart($("chart"), base);
  candles = chart.addCandlestickSeries({ upColor: css("--good"), downColor: css("--bad"), borderVisible: false, wickUpColor: css("--good"), wickDownColor: css("--bad") });
  volume = chart.addHistogramSeries({ priceFormat: { type: "volume" }, priceScaleId: "vol", lastValueVisible: false, priceLineVisible: false });
  chart.priceScale("vol").applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });
  eqChart = LightweightCharts.createChart($("eqChart"), base);
  eqSeries = eqChart.addAreaSeries({ lineColor: css("--series"), topColor: "rgba(230,235,240,.16)", bottomColor: "rgba(230,235,240,0)", lineWidth: 2, priceLineVisible: false });
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
  const key = keyOf();
  if (loading === key) return;     // ja ha um pedido igual a caminho
  loading = key;
  try {
    const rows = await api(`/api/dex/candles?network=${encodeURIComponent(sel.network)}&pool=${encodeURIComponent(sel.pool)}&tf=${tf}`);
    if (key !== keyOf()) return;      // mudou de moeda ou de intervalo enquanto carregava
    const same = chartKey === key && !force && lastCandles.length && rows.length > 2 && rows[0].time === lastCandles[0].time;
    lastCandles = rows;
    const vcol = (r) => (r.close >= r.open ? "rgba(61,220,151,.35)" : "rgba(255,77,106,.35)");
    if (same) {
      // Mesma moeda e mesma janela: so as ultimas velas mudam, nao se redesenha o grafico todo
      rows.slice(-3).forEach((r) => {
        candles.update({ time: r.time, open: r.open, high: r.high, low: r.low, close: r.close });
        volume.update({ time: r.time, value: r.volume, color: vcol(r) });
      });
    } else {
      const p = rows.length ? rows[rows.length - 1].close : 1;
      candles.applyOptions({ priceFormat: { type: "price", precision: decimals(p) + 1, minMove: Math.pow(10, -(decimals(p) + 1)) } });
      candles.setData(rows.map(({ time, open, high, low, close }) => ({ time, open, high, low, close })));
      volume.setData(rows.map((r) => ({ time: r.time, value: r.volume, color: vcol(r) })));
    }
    if (chartKey !== key || force) { chart.timeScale().fitContent(); chartKey = key; }
    $("chart").classList.remove("loading");
    header();
  } catch (e) {
    $("chart").classList.remove("loading");
    $("cLegend").textContent = `Sem velas para esta moeda (${e.message}). A GeckoTerminal pode estar a limitar pedidos.`;
  } finally {
    if (loading === key) loading = null;
  }
}
let loading = null;

function setTf(next) {
  if (next === tf) return;
  tf = next;
  store.set("dexTf", tf);
  chartKey = null;
  $("chart").classList.add("loading");       // esbate o grafico antigo ate chegarem as velas novas
  document.querySelectorAll("#tfBar button").forEach((b) => b.classList.toggle("on", b.dataset.tf === tf));
  header();
  loadCandles(true);
}

// O preco da posicao chega a cada ciclo do servidor: move a ultima vela logo, sem esperar pelas velas
function tickLast(price) {
  if (!price || !lastCandles.length || chartKey !== keyOf()) return;
  const c = lastCandles[lastCandles.length - 1];
  c.close = price; c.high = Math.max(c.high, price); c.low = Math.min(c.low, price);
  candles.update({ time: c.time, open: c.open, high: c.high, low: c.low, close: c.close });
}

function header() {
  if (!sel) return;
  const pos = S && S.positions.find((p) => p.id === sel.id);
  const last = pos ? pos.price : lastCandles.length ? lastCandles[lastCandles.length - 1].close : null;
  const first = lastCandles.length ? lastCandles[0].open : null;
  $("cName").textContent = sel.name;
  $("cNet").textContent = sel.network;
  $("cTag").textContent = pos ? "em carteira" : "";
  const priceTxt = last ? `${fmtPrice(last)} USD` : "";
  if ($("cPrice").textContent !== priceTxt) {
    const prev = Number($("cPrice").dataset.v);
    $("cPrice").textContent = priceTxt;
    $("cPrice").dataset.v = last || "";
    if (prev && last && sel.id === $("cPrice").dataset.id) flash($("cPrice"), Math.sign(last - prev));
    $("cPrice").dataset.id = sel.id;
  }
  const chg = first && last ? (last / first - 1) * 100 : null;
  $("cChg").innerHTML = chg == null ? "" : `<span class="${cls(chg)}">${signed(chg, 1)}%</span> <span class="muted">nas ultimas ${lastCandles.length} velas</span>`;
  $("cLinks").innerHTML = links(sel.network, sel.pool, sel.token);
  $("cLegend").textContent = `Velas de ${TF_LABEL[tf]}.${pos ? " Linhas: entrada (azul), stop (vermelho) e alvo (verde)." : ""}`;
}

function select(item) {
  const [network, pool] = item.id.split(":");
  sel = { id: item.id, network: item.network || network, pool: item.pool || pool, token: item.token, name: item.name };
  store.set("dexSel", JSON.stringify(sel));
  chartKey = null;
  $("chart").classList.add("loading");
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
  setHtml($("watchPos"), S.positions.length ? S.positions.map((p) => `<div class="wrow ${sel && sel.id === p.id ? "sel" : ""}" data-id="${esc(p.id)}">
      <div class="nm"><b>${esc(p.name)}</b><small>${esc(p.network)} | ${dur(p.held_min)} | alvo +${num(p.target_pct, 0)}%</small></div>
      <div class="vl"><b class="${cls(p.pnl_pct)}">${signed(p.pnl_pct, 1)}%</b><small class="muted"><br>${num(p.value)} USD</small><br>${sellBtn(p.id)}</div></div>`).join("")
    : `<div class="empty">Sem posicoes abertas.</div>`);
  setHtml($("watchLog"), S.log.length ? S.log.slice(0, 16).map((l) => `<div class="${esc(l.kind)}"><span class="t">[${esc(l.t)}]</span>${esc(l.msg)}</div>`).join("") : `<div class="info">Sem atividade ainda.</div>`);
  setHtml($("watchAn"), S.analysed.length ? S.analysed.filter((a) => !F.net || a.network === F.net).slice(0, 14).map((a) => `<div class="wrow ${sel && sel.id === a.id ? "sel" : ""}" data-id="${esc(a.id)}">
      <div class="nm"><b>${esc(a.name)}</b><small>${esc(a.t)} | ${esc(a.network)} | ${dur(a.age_min)}</small></div>
      <div class="vl">${badge(a.decision)}<small class="muted"><br>${a.confidence != null ? Math.round(a.confidence * 100) + "%" : ""}</small></div></div>`).join("")
    : `<div class="empty">Ainda sem analises.</div>`);
}

function renderDetail() {
  const box = $("detail");
  if (!S || !sel) { setHtml(box, `<p class="muted">Clica numa posicao ou numa moeda analisada para veres o grafico e os detalhes.</p>`); return; }
  const pos = S.positions.find((p) => p.id === sel.id);
  const an = S.analysed.find((a) => a.id === sel.id);
  const cl = S.closed.find((c) => c.id === sel.id && (!sel.closedTs || c.ts === sel.closedTs)) || S.closed.find((c) => c.id === sel.id);
  let html = "";
  if (pos) {
    html += `<h4>Compra</h4>` + rows([["Data", when(pos.entry_ts)], ["Quantidade (tokens)", qty(pos.tokens)], ["Preco de entrada", fmtPrice(pos.entry_price)],
      ["Valor pago", money(pos.cost)], ["Comissao + impacto na compra", money(pos.buy_cost_usd), "down"], ["Liquidez na entrada", `${usd(pos.entry_liq)} USD`],
      ["Tipo", pos.real ? "dinheiro real" : "simulada"]]);
    html += `<h4>Agora</h4>` + rows([["Preco", fmtPrice(pos.price)], ["Valor de mercado", money(pos.gross)], ["Custo estimado de sair", money(pos.exit_cost), "down"],
      ["Valor liquido se vender", money(pos.value)], ["Resultado", `${signed(pos.value - pos.cost)} USD (${signed(pos.pnl_pct, 1)}%)`, cls(pos.pnl_pct)],
      ["Maximo atingido", `${signed(pos.peak_pct, 1)}%`], ["Em carteira", dur(pos.held_min)], ["Liquidez", `${usd(pos.liq)} USD`]]);
    html += `<h4>Saidas programadas</h4>` + rows([["Stop", `${fmtPrice(pos.stop_price)} (-${num(pos.stop_pct, 1)}%)`, "down"], pos.conviction != null && ["Conviccao da compra", `${Math.round(pos.conviction * 100)}%`], ["Alvo", `${fmtPrice(pos.target_price)} (+${num(pos.target_pct, 0)}%)`, "up"]]);
    html += sellBtn(pos.id, "sellbig", "Vender esta posicao agora");
    if (pos.sig) html += `<p>${txLink(pos.network, pos.sig, "Ver transacao de compra")}</p>`;
    if (pos.reason) html += `<h4>Porque comprou</h4><p>${esc(pos.reason)}</p>`;
  }
  const head = html;
  html = "";
  if (an) {
    html += `<h4>Ultima analise (${esc(an.t)})</h4><dl><dt>Decisao</dt><dd>${badge(an.decision)}</dd>
      ${an.confidence != null ? `<dt>Confianca</dt><dd>${Math.round(an.confidence * 100)}%</dd>` : ""}
      ${an.size_eur != null ? `<dt>Ordem</dt><dd>${num(an.size_eur)} EUR</dd>` : ""}${an.target_pct != null ? `<dt>Alvo</dt><dd>+${num(an.target_pct, 0)}%</dd>` : ""}${an.stop_pct != null ? `<dt>Stop</dt><dd>-${num(an.stop_pct, 1)}%${an.conviction != null ? ` (conviccao ${Math.round(an.conviction * 100)}%)` : ""}</dd>` : ""}
      <dt>Idade</dt><dd>${dur(an.age_min)}</dd><dt>Liquidez</dt><dd>${usd(an.liq)} USD</dd><dt>FDV</dt><dd>${usd(an.fdv)} USD</dd>
      <dt>Volume 1h</dt><dd>${usd(an.vol_h1)} USD</dd><dt>Variacao 1h / 24h</dt><dd>${signed(an.chg_h1, 1)}% / ${signed(an.chg_h24, 1)}%</dd>
      <dt>Compras / vendas 1h</dt><dd>${num(an.buyers, 0)} / ${num(an.sellers, 0)}</dd></dl>`;
    if (an.sinais) {
      const g = an.sinais, pc = (x) => (x == null ? "-" : `${Math.round(x * 100)}%`), xr = (x) => (x == null ? "-" : `${num(x, 1)}x`);
      html += `<h4>Volume de compra (DexScreener 5m e 1h)</h4>` + rows([["Forca de compra", `${Math.round(g.forca_compra * 100)}% (${esc(String(g.classe).replace("_", " "))})`, g.forca_compra >= 0.5 ? "up" : ""],
        ["Volume 5m vs ritmo da hora", xr(g.volume_5m_vs_ritmo_1h)], ["Volume 1h vs ritmo 24h", xr(g.volume_1h_vs_ritmo_24h)],
        ["Compras 5m / 1h", `${pc(g.pressao_compra_5m)} / ${pc(g.pressao_compra_1h)}`], ["Transacoes 5m / 1h", `${num(g.transacoes_5m, 0)} / ${num(g.transacoes_1h, 0)}`],
        ["Variacao 5m / 1h", `${signed(g.var_5m_pct, 1)}% / ${signed(g.var_1h_pct, 1)}%`], ["Preco esticado", g.esticado ? "sim" : "nao", g.esticado ? "down" : ""]]);
    }
    if (an.reason) html += `<h4>Raciocinio do Grok</h4><p>${esc(an.reason)}</p>`;
    if (an.risks) html += `<h4>Riscos apontados</h4><p>${esc(an.risks)}</p>`;
    if (an.seguranca) {
      const sg = an.seguranca;
      html += `<h4>Seguranca</h4><div class="chips">${[["mint", sg.mint_authority], ["freeze", sg.freeze_authority], ["honeypot", sg.is_honeypot]]
        .map(([k, v]) => `<span class="chip">${k}: ${esc(v ?? "?")}</span>`).join("")}<span class="chip">dono ${sg.dev_holding_pct ?? "?"}%</span><span class="chip">top10 ${sg.top10_pct ?? "?"}%</span><span class="chip">holders ${sg.holders ?? "?"}</span></div>`;
    }
  }
  const anHtml = html;
  html = "";
  if (cl) {
    const costs = (cl.buy_cost_usd ?? 0) + (cl.sell_cost_usd ?? 0), hasBreak = cl.gross_usd != null;
    const priceMove = hasBreak ? cl.gross_usd - cl.tokens * cl.entry_price : null;
    html += `<h4>Operacao fechada (${when(cl.ts)})</h4>`;
    html += `<h4>Compra</h4>` + rows([["Data", when(cl.entry_ts)], ["Quantidade (tokens)", qty(cl.tokens)], ["Preco de entrada", fmtPrice(cl.entry_price)], ["Valor pago", money(cl.cost)],
      hasBreak && ["Comissao + impacto na compra", money(cl.buy_cost_usd), "down"], cl.entry_liq != null && ["Liquidez na entrada", `${usd(cl.entry_liq)} USD`],
      ["Confianca do Grok", cl.confidence != null ? `${Math.round(cl.confidence * 100)}%` : "-"]]);
    html += `<h4>Venda</h4>` + rows([["Data", when(cl.ts)], ["Tipo de saida", `${esc(cl.kind)}${cl.kind === "rug" ? " (!)" : ""}`], ["Preco de saida", fmtPrice(cl.exit_price)],
      hasBreak && ["Valor de mercado", money(cl.gross_usd)], hasBreak && ["Comissao + impacto + slippage", money(cl.sell_cost_usd), "down"], ["Recebido", money(cl.proceeds)],
      cl.exit_liq != null && ["Liquidez na saida", `${usd(cl.exit_liq)} USD`], ["Tempo em carteira", dur(cl.held_min)], ["Maximo atingido", `${signed(cl.peak_pnl_pct, 1)}%`],
      cl.target_pct != null && ["Alvo definido", `+${num(cl.target_pct, 0)}%`], cl.stop_pct != null && ["Stop definido", `-${num(cl.stop_pct, 1)}%${cl.conviction != null ? ` (conviccao ${Math.round(cl.conviction * 100)}%)` : ""}`]]);
    html += `<h4>Resultado</h4>` + rows([hasBreak && ["Ganho/perda de preco (bruto)", `${signed(priceMove)} USD`, cls(priceMove)],
      hasBreak && ["Custos totais", `-${num(costs)} USD`, "down"], ["Resultado liquido", `${signed(cl.pnl_usd)} USD (${signed(cl.pnl_pct, 1)}%)`, cls(cl.pnl_usd)]]);
    if (cl.detail) html += `<h4>Porque saiu</h4><p>${esc(cl.detail)}</p>`;
    if (cl.reason) html += `<h4>Porque comprou</h4><p>${esc(cl.reason)}</p>`;
    const tx = [txLink(cl.network, cl.buy_sig, "transacao de compra"), txLink(cl.network, cl.sell_sig, "transacao de venda")].filter(Boolean);
    if (tx.length) html += `<p>${tx.join(" | ")}</p>`;
  }
  html = head + html + anHtml;      // a operacao fechada primeiro, a analise do Grok depois
  setHtml(box, html || `<p class="muted">Sem dados guardados desta moeda.</p>`);
}

// ---------- separadores ----------
const q = () => $("search").value.trim().toLowerCase();
const hit = (o) => !q() || JSON.stringify(o).toLowerCase().includes(q());
const empty = (t) => `<div class="empty">${t}</div>`;

// Cabecalho clicavel: [chave, texto, classe]. Um clique ordena, outro inverte.
const th = (tabName, cols) => `<tr>${cols.map(([k, label, c]) => `<th class="sortable ${c || ""}" data-sort="${tabName}:${k}">${label}${SORT[tabName][0] === k ? (SORT[tabName][1] < 0 ? " ▼" : " ▲") : ""}</th>`).join("")}</tr>`;
const sortRows = (tabName, rows) => {
  const [k, d] = SORT[tabName];
  return rows.slice().sort((a, b) => (typeof a[k] === "string" ? String(a[k]).localeCompare(String(b[k])) * d : ((a[k] ?? -Infinity) - (b[k] ?? -Infinity)) * d));
};
const resOk = (o) => !F.res || (F.res === "win" ? o.pnl_pct > 0 : o.pnl_pct < 0);
const netOk = (o) => !F.net || o.network === F.net;
const sinceTs = () => { const now = Date.now() / 1000; return F.per === "today" ? new Date().setHours(0, 0, 0, 0) / 1000 : F.per === "24h" ? now - 86400 : F.per === "7d" ? now - 7 * 86400 : 0; };

function tablePositions() {
  const rows = sortRows("positions", S.positions.filter((p) => hit(p) && netOk(p) && resOk(p)));
  return rows.length ? `<table>` + th("positions", [["name", "Moeda"], ["network", "Rede"], ["cost", "Custo", "n"], ["value", "Valor", "n"], ["pnl_pct", "Resultado", "n"], ["peak_pct", "Maximo", "n"],
      ["target_pct", "Alvo", "n"], ["stop_pct", "Stop", "n"], ["liq", "Liquidez", "n"], ["held_min", "Tempo", "n"]]).replace("</tr>", `<th class="n">Vender</th></tr>`) +
    rows.map((p) => `<tr class="row ${sel && sel.id === p.id ? "sel" : ""}" data-id="${esc(p.id)}"><td><b>${esc(p.name)}</b></td><td>${esc(p.network)}</td><td class="n">${num(p.cost)}</td><td class="n">${num(p.value)}</td>
      <td class="n ${cls(p.pnl_pct)}">${signed(p.pnl_pct, 1)}%</td><td class="n">${signed(p.peak_pct, 1)}%</td><td class="n">+${num(p.target_pct, 0)}%</td><td class="n down">-${num(p.stop_pct, 1)}%</td><td class="n">${usd(p.liq)}</td><td class="n">${dur(p.held_min)}</td>
      <td class="n">${sellBtn(p.id)}</td></tr>`).join("") + "</table>"
    : empty(S.positions.length ? "Nenhuma posicao corresponde aos filtros." : "Sem posicoes abertas.");
}

function tableClosed() {
  const since = sinceTs();
  const rows = sortRows("closed", S.closed.map((r) => ({ ...r, costs: r.gross_usd != null ? r.buy_cost_usd + r.sell_cost_usd : null })).filter((r) => hit(r) && netOk(r) && resOk(r) && (!F.kind || r.kind === F.kind) && r.ts >= since));
  const total = rows.reduce((a, r) => a + r.pnl_usd, 0), wins = rows.filter((r) => r.pnl_usd > 0).length;
  const sum = rows.length ? `<div class="sect">${rows.length} operacoes | ${Math.round(100 * wins / rows.length)}% ganhas | resultado <span class="${cls(total)}">${signed(total)} USD</span></div>` : "";
  return rows.length ? sum + `<table>` + th("closed", [["name", "Moeda"], ["kind", "Saida"], ["pnl_pct", "Resultado", "n"], ["pnl_usd", "USD", "n"], ["cost", "Pago", "n"], ["proceeds", "Recebido", "n"], ["costs", "Custos", "n"], ["peak_pnl_pct", "Maximo", "n"],
      ["held_min", "Tempo", "n"], ["ts", "Fecho", "n"]]).replace("</tr>", `<th>Motivo da entrada</th></tr>`) +
    rows.map((r) => `<tr class="row ${sel && sel.id === r.id && sel.closedTs === r.ts ? "sel" : ""}" data-id="${esc(r.id)}" data-ts="${r.ts}"><td><b>${esc(r.name)}</b></td><td>${esc(r.kind)}${r.kind === "rug" ? " (!)" : ""}</td>
      <td class="n ${cls(r.pnl_pct)}">${signed(r.pnl_pct, 1)}%</td><td class="n ${cls(r.pnl_usd)}">${signed(r.pnl_usd)}</td><td class="n">${num(r.cost)}</td><td class="n">${num(r.proceeds)}</td><td class="n down">${r.costs ? "-" + num(r.costs) : "-"}</td><td class="n">${signed(r.peak_pnl_pct, 1)}%</td><td class="n">${dur(r.held_min)}</td>
      <td class="n muted">${esc(new Date(r.ts * 1000).toLocaleString("pt-PT", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" }))}</td><td class="why">${esc(r.reason)}</td></tr>`).join("") + "</table>"
    : empty(S.closed.length ? "Nenhuma operacao corresponde aos filtros." : "Sem operacoes fechadas.");
}

function tableAnalysed() {
  const d = $("decision").value;
  const rows = S.analysed.filter((a) => (!d || a.decision === d) && netOk(a) && hit(a));
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
  $("fNet").hidden = tab === "scans" || tab === "log";
  $("fRes").hidden = tab !== "positions" && tab !== "closed";
  $("fKind").hidden = tab !== "closed";
  $("fPer").hidden = tab !== "closed";
  const body = $("tabBody");
  const top = body.scrollTop;
  setHtml(body, { positions: tablePositions, closed: tableClosed, analysed: tableAnalysed, scans: tableScans, log: tableLog }[tab]());
  body.scrollTop = top;
}

// Redes e tipos de saida vem dos dados; o que o utilizador escolheu fica guardado no browser
function syncFilterOptions() {
  const fill = (id, values, first) => {
    const el = $(id), key = values.join("|");
    if (el._k === key) return;
    el._k = key;
    el.innerHTML = `<option value="">${first}</option>` + values.map((v) => `<option>${esc(v)}</option>`).join("");
    el.value = F[id === "fNet" ? "net" : "kind"];
  };
  fill("fNet", S.rules.networks, "Todas as redes");
  fill("fKind", [...new Set(S.closed.map((c) => c.kind))].sort(), "Qualquer saida");
}
function bindFilters() {
  [["fNet", "net"], ["fRes", "res"], ["fKind", "kind"], ["fPer", "per"]].forEach(([id, key]) => {
    $(id).value = F[key];
    $(id).addEventListener("input", () => { F[key] = $(id).value; store.set("dexF", JSON.stringify(F)); renderLists(); renderTab(); });
  });
}

// ---------- mascote ----------
const cut = (t, n = 90) => (String(t).length > n ? `${String(t).slice(0, n - 1)}…` : String(t));
const cap = (t) => t.charAt(0).toUpperCase() + t.slice(1);
let seenLog = null;
const logKey = (l) => `${l.t}|${l.kind}|${l.msg}`;

function mascotUpdate(s) {
  const act = s.activity || { kind: "idle", what: "" };
  if (!s.enabled) Mascot.set("sleep", "Parado. Carrega em LIGAR para me acordar.");
  else if (act.kind === "think") Mascot.set("think", `${cap(act.what || "a pensar")}...`);
  else if (act.kind === "scan") Mascot.set("scan", `${cap(act.what || "a procurar")}...`);
  else Mascot.set("idle", s.positions.length ? `A vigiar ${s.positions.length} posicao(oes).` : "Ligado. A espera de uma boa entrada.");
  // Reage ao que acabou de acontecer no registo. Na primeira leitura so memoriza, para nao reagir ao historico.
  if (seenLog === null || seenLog.size > 600) { seenLog = new Set(s.log.map(logKey)); return; }
  const fresh = s.log.filter((l) => !seenLog.has(logKey(l))).reverse();
  fresh.forEach((l) => seenLog.add(logKey(l)));
  const last = fresh.filter((l) => ["buy", "sell", "alert", "error"].includes(l.kind)).pop();
  if (!last) return;
  if (last.kind === "buy" || last.kind === "sell") Mascot.react("happy", cut(last.msg));
  else if (/^VENDA/.test(last.msg)) Mascot.react("sad", cut(last.msg));        // venda com perda
  else Mascot.react("alert", cut(last.msg));
}
Mascot.onClick(() => (S ? `${S.positions.length} posicao(oes) | hoje ${signed(S.today.pnl_usd)} USD | ${S.last_scan ? `ultima procura ${S.last_scan}` : "sem procuras ainda"}` : ""));

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
  $("disclaimer").textContent = `Regras: ordens de ${num(s.rules.size_min, 0)} a ${num(s.rules.size_max, 0)} EUR (1 EUR = ${num(s.rules.eurusd, 4)} USD), alvo entre +${s.rules.tp_min}% e +${s.rules.tp_max}%, stop-loss de ${s.rules.stop_min}% a ${s.rules.stop_max}% (ajustado a cada compra), comissao ${s.rules.fee}% por lado, maximo ${s.rules.max_hold_h} h por posicao, usa no maximo ${s.rules.wallet_use_pct}% da carteira (o resto fica para taxas), procura a cada ${s.scan_sec} s. Resultados simulados nao garantem resultados reais.`;

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

  syncFilterOptions();
  mascotUpdate(s);
  const pos = sel && s.positions.find((p) => p.id === sel.id);
  setLines(pos);
  if (pos) tickLast(pos.price);
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
  const sellEl = e.target.closest("[data-sell]");
  if (sellEl) { sellOne(sellEl.dataset.sell); return; }
  const sortEl = e.target.closest("th[data-sort]");
  if (sortEl) {
    const [tabName, k] = sortEl.dataset.sort.split(":");
    SORT[tabName] = [k, SORT[tabName][0] === k ? -SORT[tabName][1] : -1];
    store.set("dexSort", JSON.stringify(SORT));
    renderTab();
    return;
  }
  const row = e.target.closest("[data-id]");
  if (row && S) {
    const id = row.dataset.id;
    const ts = Number(row.dataset.ts) || null;          // linha de uma operacao fechada: mostra essa e nao a mais recente
    const item = S.positions.find((p) => p.id === id) || (ts ? S.closed.find((c) => c.id === id && c.ts === ts) : null) || S.analysed.find((a) => a.id === id) || S.closed.find((c) => c.id === id);
    if (item) { select(item); if (ts && sel) { sel.closedTs = ts; renderDetail(); renderTab(); } }
    return;
  }
  const t = e.target.closest(".tab");
  if (t) {
    tab = t.dataset.tab; store.set("dexTab", tab); renderTab();
    const body = $("tabBody"); body.classList.remove("fade"); void body.offsetWidth; body.classList.add("fade");
  }
});
$("search").addEventListener("input", renderTab);
$("decision").addEventListener("change", renderTab);
$("toggle").onclick = async () => { render(await api("/api/dex/toggle", { enabled: !on })); };
$("panic").onclick = async () => {
  if (!confirm("Vender TODAS as posicoes ja e parar o bot?")) return;
  render(await api("/api/dex/panic", {}));
};

initCharts();
bindFilters();
try { const saved = JSON.parse(store.get("dexSel") || "null"); if (saved && saved.id) sel = saved; } catch { /* ignora */ }
let inflight = false;
const tick = () => {
  if (inflight) return;      // nao empilha pedidos se o servidor demora
  inflight = true;
  api("/api/dex/status").then(render).catch((e) => { $("statusText").textContent = `sem ligacao (${e.message})`; }).finally(() => { inflight = false; });
};
tick();
setInterval(() => { if (!document.hidden) tick(); }, 2000);
(function pollCandles() {      // o ritmo depende do intervalo escolhido
  if (!document.hidden) loadCandles(false);
  setTimeout(pollCandles, TF_POLL[tf]);
})();
$("tfBar").addEventListener("click", (e) => { const b = e.target.closest("button[data-tf]"); if (b) setTf(b.dataset.tf); });
document.querySelectorAll("#tfBar button").forEach((b) => b.classList.toggle("on", b.dataset.tf === tf));
document.addEventListener("visibilitychange", () => { if (!document.hidden) { tick(); loadCandles(false); } });
if (sel) loadCandles(true);
