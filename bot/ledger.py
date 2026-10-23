"""Estado persistente do bot: custo medio por posicao, equity de inicio de dia e cooldowns."""
import json
import os
import threading
import time
from datetime import date

from . import config, market

_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "state.json")
_lock = threading.RLock()


def _load():
    if os.path.exists(_PATH):
        with open(_PATH, encoding="utf-8") as f:
            return json.load(f)
    return {"day": None, "day_start_equity": 0.0, "cost": {}, "last_trade": {}, "realized_today": 0.0}


def _save(s):
    os.makedirs(os.path.dirname(_PATH), exist_ok=True)
    with open(_PATH, "w", encoding="utf-8") as f:
        json.dump(s, f, indent=2)


def equity(broker):
    """USDT livre + valor de mercado das posicoes nos pares permitidos."""
    p = broker.portfolio()
    total = p["USDT"]
    for base, qty in p["positions"].items():
        symbol = f"{base}/USDT"
        if symbol in config.SYMBOLS:
            total += qty * market.price(symbol)
    return total


def exposure(broker):
    return equity(broker) - broker.portfolio()["USDT"]


def daily_loss(broker):
    """Perda do dia em USDT (0 se estiver em ganho). Inclui perdas ainda nao realizadas."""
    with _lock:
        s = _load()
        today = str(date.today())
        eq = equity(broker)
        if s["day"] != today:
            s.update(day=today, day_start_equity=eq, realized_today=0.0)
            _save(s)
        return max(0.0, s["day_start_equity"] - eq)


def entry(symbol):
    """(preco medio de entrada, quantidade) registados pelo bot, ou None."""
    with _lock:
        pos = _load()["cost"].get(symbol)
    return (pos["avg"], pos["qty"]) if pos and pos["qty"] > 0 else None


def seconds_since_trade(symbol):
    with _lock:
        ts = _load()["last_trade"].get(symbol)
    return None if ts is None else time.time() - ts


def record(side, symbol, qty, price):
    """Atualiza custo medio e PnL realizado. Devolve o PnL realizado desta ordem (0 nas compras)."""
    with _lock:
        s = _load()
        pos = s["cost"].get(symbol, {"qty": 0.0, "avg": 0.0})
        pnl = 0.0
        if side == "buy":
            total = pos["qty"] + qty
            pos["avg"] = (pos["avg"] * pos["qty"] + price * qty) / total
            pos["qty"] = total
        else:
            sold = min(qty, pos["qty"])
            pnl = (price - pos["avg"]) * sold
            pos["qty"] -= sold
            s["realized_today"] = s.get("realized_today", 0.0) + pnl
        s["cost"][symbol] = pos
        s["last_trade"][symbol] = time.time()
        _save(s)
        return pnl
