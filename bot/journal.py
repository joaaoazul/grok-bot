"""Diario do bot: cada compra com as condicoes em que foi feita, e o resultado quando a posicao fecha.

E daqui que sai a "aprendizagem": o Grok nao muda, mas passa a ver como as suas decisoes correram
e a receber licoes escritas a partir dessas operacoes.
"""
import json
import os
import threading
import time

from . import config

_PATH = os.path.join(config.DATA_DIR, "journal.json")
_lock = threading.RLock()
FEE_PCT = 0.2  # ida e volta
MIN_BUCKET_SAMPLE = 8  # abaixo disto uma media nao quer dizer nada
CONF_BUCKETS = [(0.5, 0.6), (0.6, 0.7), (0.7, 0.8), (0.8, 1.01)]
RSI_BUCKETS = [(0, 35), (35, 50), (50, 65), (65, 101)]


def _load():
    if os.path.exists(_PATH):
        with open(_PATH, encoding="utf-8") as f:
            return json.load(f)
    return {"open": {}, "closed": [], "lessons": [], "lessons_at": 0}


def _save(s):
    os.makedirs(os.path.dirname(_PATH), exist_ok=True)
    with open(_PATH, "w", encoding="utf-8") as f:
        json.dump(s, f, indent=2)


def open_entry(symbol, snap, confidence, reason, price):
    e20, e50 = snap.get("ema20"), snap.get("ema50")
    with _lock:
        s = _load()
        s["open"][symbol] = {
            "symbol": symbol, "ts": int(time.time()), "price": price, "confidence": round(confidence, 2), "reason": reason[:200],
            "rsi": snap.get("rsi14"), "change_24h": snap.get("change_24h_pct"), "atr_pct": snap.get("atr_pct"),
            "trend_4h": (snap.get("trend_4h") or {}).get("ema20_vs_ema50"), "trend_1h": (snap.get("trend_1h") or {}).get("ema20_vs_ema50"),
            "vs_ema20_pct": round((price / e20 - 1) * 100, 2) if e20 else None,
            "btc_24h": (snap.get("btc") or {}).get("change_24h_pct"), "tf_trend": "alta" if e20 and e50 and e20 > e50 else "baixa",
        }
        _save(s)


def close_entry(symbol, price, kind):
    """kind: stop-loss | take-profit | trailing | limite | analise. Devolve o registo fechado (ou None se o bot nao a abriu)."""
    with _lock:
        s = _load()
        e = s["open"].pop(symbol, None)
        if not e:
            return None
        now = int(time.time())
        rec = {**e, "exit_price": price, "exit_ts": now, "kind": kind, "held_min": round((now - e["ts"]) / 60),
               "pnl_pct": round((price / e["price"] - 1) * 100 - FEE_PCT, 2)}
        s["closed"] = (s["closed"] + [rec])[-300:]
        _save(s)
        return rec


def _agg(rows):
    if not rows:
        return None
    return {"n": len(rows), "win_rate_pct": round(100 * sum(r["pnl_pct"] > 0 for r in rows) / len(rows)),
            "avg_pnl_pct": round(sum(r["pnl_pct"] for r in rows) / len(rows), 2)}


def _bucketed(closed, key, buckets):
    out = {}
    for lo, hi in buckets:
        agg = _agg([r for r in closed if r.get(key) is not None and lo <= r[key] < hi])
        if agg:
            out[f"{lo}-{hi if hi < 100 else ''}"] = agg
    return out


def stats():
    closed = _load()["closed"]
    kinds = {}
    for r in closed:
        kinds.setdefault(r["kind"], []).append(r)
    return {"total": _agg(closed), "por_tipo_de_saida": {k: _agg(v) for k, v in kinds.items()},
            "por_RSI_na_entrada": _bucketed(closed, "rsi", RSI_BUCKETS),
            "por_confianca": _bucketed(closed, "confidence", CONF_BUCKETS)}


def memory():
    """O que o Grok ve sobre o seu proprio historico, em cada analise."""
    with _lock:
        s = _load()
    if len(s["closed"]) < 3:
        return {"nota": "Ainda quase sem operacoes fechadas: decide so pelos dados de mercado."}
    keep = ("symbol", "confidence", "rsi", "trend_4h", "trend_1h", "vs_ema20_pct", "btc_24h", "kind", "held_min", "pnl_pct")
    return {
        "estatisticas": stats(),
        "ultimas_operacoes": [{k: r.get(k) for k in keep} for r in s["closed"][-8:]],
        "licoes": s["lessons"],
        "aviso": "Amostra pequena: usa isto para calibrar, nao como regra absoluta. Ignora padroes com menos de 5 casos.",
    }


def min_confidence(base):
    """Sobe o limiar de entrada se as faixas de confianca mais baixas estao a perder dinheiro (com amostra minima)."""
    closed = _load()["closed"]
    threshold = base
    for lo, hi in CONF_BUCKETS:
        if hi <= threshold:
            continue
        agg = _agg([r for r in closed if lo <= r["confidence"] < hi])
        if agg and agg["n"] >= MIN_BUCKET_SAMPLE and agg["avg_pnl_pct"] < 0:
            threshold = hi
        else:
            break
    return min(threshold, 0.9)


def maybe_reflect(reflect_fn, every=5):
    """A cada `every` operacoes fechadas, o Grok revê-as e escreve licoes que passam a ir em todas as analises."""
    with _lock:
        s = _load()
        if len(s["closed"]) - s["lessons_at"] < every:
            return None
        recent, summary = s["closed"][-30:], stats()
    lessons = reflect_fn(recent, summary)
    with _lock:
        s = _load()
        s["lessons"] = lessons[:5]
        s["lessons_at"] = len(s["closed"])
        _save(s)
    return lessons[:5]
