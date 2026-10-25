"""Estado persistente do bot: custo medio por posicao, equity de inicio de dia e cooldowns."""
import json
import os
import threading
import time
from datetime import date

from . import config, market

_PATH = os.path.join(config.DATA_DIR, "state.json")
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
    tracked = tracked_symbols()
    for base, qty in p["positions"].items():
        symbol = f"{base}/USDT"
        last = (market.tickers().get(symbol) or {}).get("last")
        if symbol in tracked and last:
            total += qty * last
    return total


def tracked_symbols():
    """Pares que o bot opera: os que ja comprou e os da lista base. Ignora o resto da carteira (ex: BNB)."""
    with _lock:
        return set(_load()["cost"]) | set(config.SYMBOLS)


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


def update_peak(symbol, price):
    """Maximo atingido desde a entrada (base do trailing stop)."""
    with _lock:
        s = _load()
        pos = s["cost"].get(symbol)
        if not pos or pos["qty"] <= 0:
            return price
        pos["peak"] = max(pos.get("peak", price), price)
        _save(s)
        return pos["peak"]


def seconds_since_trade(symbol):
    with _lock:
        ts = _load()["last_trade"].get(symbol)
    return None if ts is None else time.time() - ts


def state():
    with _lock:
        return _load()


def record(side, symbol, qty, price, why="", fee=0.0):
    """Atualiza custo medio e PnL realizado. Devolve o PnL realizado desta ordem (0 nas compras)."""
    with _lock:
        s = _load()
        pos = s["cost"].get(symbol, {"qty": 0.0, "avg": 0.0})
        pnl = 0.0
        if side == "buy":
            pos["peak"] = price if pos["qty"] <= 0 else max(pos.get("peak", price), price)
            total = pos["qty"] + qty
            pos["avg"] = (pos["avg"] * pos["qty"] + price * qty) / total
            pos["qty"] = total
        else:
            sold = min(qty, pos["qty"])
            pnl = (price - pos["avg"]) * sold
            pos["qty"] -= sold
            s["realized_today"] = s.get("realized_today", 0.0) + pnl
        s["cost"][symbol] = pos
        entry_avg = pos["avg"]
        s["last_trade"][symbol] = time.time()
        trades = s.setdefault("trades", [])
        trades.append({"ts": int(time.time()), "side": side, "symbol": symbol, "price": price, "qty": qty,
                       "usdt": round(qty * price, 2), "pnl": round(pnl, 2), "why": why,
                       "fee": round(fee, 6), "left": round(pos["qty"], 8),
                       "avg": round(entry_avg, 8) if side == "sell" and entry_avg else None,
                       "pnl_pct": round((price / entry_avg - 1) * 100, 2) if side == "sell" and entry_avg else None})
        s["trades"] = trades[-500:]
        _save(s)
        return pnl
