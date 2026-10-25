from . import ledger, market


def execute(broker, side, symbol, usdt, why=""):
    """Unico ponto por onde passam ordens (manuais e automaticas): executa e regista no ledger."""
    res = broker.order(side, symbol, usdt)
    res["pnl"] = round(ledger.record(side, symbol, res["qty"], res["price"], why, res.get("fee_usdt", 0.0)), 2)
    return res


def close_position(broker, symbol, why=""):
    """Vende tudo o que existe de um simbolo. Ignora o limite por ordem: e uma saida protetora."""
    base = symbol.split("/")[0]
    qty = broker.portfolio()["positions"].get(base, 0.0)
    if qty <= 0:
        return None
    return execute(broker, "sell", symbol, qty * market.price(symbol), why)
