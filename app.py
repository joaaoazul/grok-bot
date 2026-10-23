from flask import Flask, jsonify, render_template, request

from bot import analyst, config, market, risk, trader
from bot.auto import AutoTrader
from bot.broker import get_broker

app = Flask(__name__)
broker = get_broker()
auto = AutoTrader(broker)


@app.get("/")
def index():
    return render_template("index.html", symbols=config.SYMBOLS, model=config.GROK_MODEL, max_order=config.MAX_ORDER_USDT,
                           interval=config.AUTO_INTERVAL_SEC, stop_loss=config.STOP_LOSS_PCT, take_profit=config.TAKE_PROFIT_PCT, max_loss=config.MAX_DAILY_LOSS_USDT)


@app.get("/api/portfolio")
def portfolio():
    return jsonify(broker.portfolio())


@app.get("/api/market/<base>/<quote>")
def market_snapshot(base, quote):
    symbol = f"{base}/{quote}"
    if symbol not in config.SYMBOLS:
        return jsonify(error="Simbolo nao permitido."), 400
    return jsonify(market.snapshot(symbol))


@app.post("/api/analyse")
def analyse():
    body = request.get_json(silent=True) or {}
    symbol = body.get("symbol")
    if symbol not in config.SYMBOLS:
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
        return jsonify(trader.execute(broker, order["action"], order["symbol"], order["usdt"]))
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


if __name__ == "__main__":
    if config.AUTO_START:
        try:
            auto.start()
        except RuntimeError as exc:
            print(f"Modo automatico nao arrancou: {exc}")
    app.run(host="127.0.0.1", port=5000, debug=False)
