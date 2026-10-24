import time
from flask import Flask, jsonify, render_template, request

from bot import analyst, config, history, ledger, market, risk, scanner, trader
from bot.auto import AutoTrader
from bot.broker import get_broker
from bot.dex.strategy import DexBot

app = Flask(__name__)
broker = get_broker()
auto = AutoTrader(broker)
dex = DexBot()  # memecoins em DEX: so simulacao


def _held():
    tracked = ledger.tracked_symbols()
    return [f"{b}/USDT" for b, q in broker.portfolio()["positions"].items() if q > 0 and f"{b}/USDT" in tracked]


def _allowed(symbol):
    return scanner.is_allowed(symbol) or symbol in _held()


@app.get("/")
def index():
    return render_template("index.html", model=config.GROK_MODEL, max_order=config.MAX_ORDER_USDT,
                           interval=config.AUTO_INTERVAL_SEC, stop_loss=config.STOP_LOSS_PCT,
                           take_profit=config.TAKE_PROFIT_PCT, max_loss=config.MAX_DAILY_LOSS_USDT)


@app.get("/api/symbols")
def symbols():
    return jsonify(scanner.universe(_held()) + [s for s in config.SYMBOLS if s not in scanner.universe(_held())])


@app.get("/api/summary")
def summary():
    p = broker.portfolio()
    eq = ledger.equity(broker)
    loss = ledger.daily_loss(broker)  # fixa tambem o equity de inicio de dia
    st = ledger.state()
    history.add(eq)
    tickers = market.tickers()
    tracked = ledger.tracked_symbols()
    positions = []
    for base, qty in p["positions"].items():
        symbol = f"{base}/USDT"
        last = (tickers.get(symbol) or {}).get("last")
        if qty <= 0 or symbol not in tracked or not last:
            continue
        cost = st["cost"].get(symbol) or {}
        avg = cost.get("avg") if cost.get("qty", 0) > 0 else None
        value = qty * last
        positions.append({
            "symbol": symbol, "qty": qty, "price": last, "value": round(value, 2), "avg": avg,
            "pnl": round((last - avg) * qty, 2) if avg else None,
            "pnl_pct": round((last / avg - 1) * 100, 2) if avg else None,
            "stop": round(avg * (1 - config.STOP_LOSS_PCT / 100), 6) if avg else None,
            "peak": cost.get("peak"),
        })
    exposure = sum(x["value"] for x in positions)
    day_start = st.get("day_start_equity") or eq
    return jsonify(
        mode=p["mode"], day_start=round(day_start, 2), equity=round(eq, 2), usdt=p["USDT"], exposure=round(exposure, 2), max_exposure=config.MAX_EXPOSURE_USDT,
        day_pnl=round(eq - day_start, 2), day_pnl_pct=round((eq / day_start - 1) * 100, 2) if day_start else 0,
        daily_loss=round(loss, 2), max_daily_loss=config.MAX_DAILY_LOSS_USDT,
        realized_today=round(st.get("realized_today", 0.0), 2), positions=sorted(positions, key=lambda x: -x["value"]),
    )


@app.get("/api/equity")
def equity_series():
    return jsonify(history.series())


@app.get("/api/trades")
def trades():
    return jsonify(list(reversed(ledger.state().get("trades", [])[-100:])))


@app.get("/api/candles/<base>/<quote>")
def candles(base, quote):
    symbol = f"{base}/{quote}"
    if not _allowed(symbol):
        return jsonify(error="Simbolo nao permitido."), 400
    tf = request.args.get("tf", "15m")
    if tf not in ("5m", "15m", "1h", "4h"):
        return jsonify(error="Intervalo invalido."), 400
    own = [t for t in ledger.state().get("trades", []) if t["symbol"] == symbol]
    return jsonify(candles=market.candles(symbol, tf), trades=own)


@app.get("/api/market/<base>/<quote>")
def market_snapshot(base, quote):
    symbol = f"{base}/{quote}"
    if not _allowed(symbol):
        return jsonify(error="Simbolo nao permitido."), 400
    return jsonify(market.snapshot(symbol))


@app.post("/api/analyse")
def analyse():
    body = request.get_json(silent=True) or {}
    symbol = body.get("symbol")
    if not _allowed(symbol):
        return jsonify(error="Simbolo nao permitido."), 400
    try:
        proposal = analyst.analyse(market.snapshot(symbol), broker.portfolio(), body.get("question", ""))
    except Exception as exc:
        return jsonify(error=str(exc)), 500
    # O risco e avaliado ja aqui para o utilizador ver a ordem final antes de confirmar
    order, reason = risk.validate(proposal, broker)
    return jsonify(proposal=proposal, order=order, blocked=reason)


@app.post("/api/execute")
def execute():
    """So corre quando o utilizador carrega em Confirmar. Revalida sempre os limites."""
    order, reason = risk.validate(request.get_json(silent=True) or {}, broker)
    if order is None:
        return jsonify(error=reason), 400
    try:
        return jsonify(trader.execute(broker, order["action"], order["symbol"], order["usdt"], "manual"))
    except Exception as exc:
        return jsonify(error=str(exc)), 500


@app.get("/api/auto")
def auto_status():
    return jsonify(auto.status())


@app.post("/api/auto")
def auto_toggle():
    try:
        auto.start() if (request.get_json(silent=True) or {}).get("enabled") else auto.stop()
    except RuntimeError as exc:
        return jsonify(error=str(exc)), 400
    return jsonify(auto.status())


@app.get("/dex")
def dex_page():
    return render_template("dex.html")


@app.get("/api/dex/status")
def dex_status():
    return jsonify(dex.status())


_dex_candle_cache = {}


@app.get("/api/dex/candles")
def dex_candles():
    net, pool = request.args.get("network", ""), request.args.get("pool", "")
    if not net.isalnum() or not pool.isalnum():
        return jsonify({"error": "parametros invalidos"}), 400
    hit = _dex_candle_cache.get((net, pool))
    if hit and time.time() - hit[0] < 12:
        return jsonify(hit[1])
    from bot.dex import data as dex_data
    try:
        rows = dex_data.candles(net, pool, limit=120)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 502
    out = [{"time": int(r[0]), "open": r[1], "high": r[2], "low": r[3], "close": r[4], "volume": r[5]} for r in rows]
    _dex_candle_cache[(net, pool)] = (time.time(), out)
    return jsonify(out)


@app.post("/api/dex/panic")
def dex_panic():
    dex.panic()
    return jsonify(dex.status())


@app.post("/api/dex/toggle")
def dex_toggle():
    dex.start() if (request.get_json(silent=True) or {}).get("enabled") else dex.stop()
    return jsonify(dex.status())


if __name__ == "__main__":
    if config.DEX_AUTO_START:
        dex.start()
    if config.AUTO_START:
        try:
            auto.start()
        except RuntimeError as exc:
            print(f"Modo automatico nao arrancou: {exc}")
    app.run(host="127.0.0.1", port=5000, debug=False)
