import time

import ccxt

# Dados publicos: nao precisam de chave
_public = ccxt.binance({"enableRateLimit": True})


def _ema(values, period):
    k = 2 / (period + 1)
    ema = values[0]
    for v in values[1:]:
        ema = v * k + ema * (1 - k)
    return ema


def _rsi(closes, period=14):
    gains, losses = [], []
    for a, b in zip(closes[-period - 1:-1], closes[-period:]):
        d = b - a
        gains.append(max(d, 0))
        losses.append(max(-d, 0))
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        return 100.0
    rs = (sum(gains) / period) / avg_loss
    return 100 - 100 / (1 + rs)


_cache = {"t": 0.0, "data": {}}


def tickers(ttl=10):
    """Todos os tickers num so pedido, com cache curta."""
    if time.time() - _cache["t"] > ttl:
        _cache.update(t=time.time(), data=_public.fetch_tickers())
    return _cache["data"]


def price(symbol):
    return _public.fetch_ticker(symbol)["last"]


def candles(symbol, timeframe="15m", limit=120):
    """[[timestamp_ms, fecho], ...] para o grafico de preco."""
    return [[c[0], c[4]] for c in _public.fetch_ohlcv(symbol, timeframe, limit=limit)]


def _r(x):
    """6 algarismos significativos: nao zera precos minusculos (PEPE ~ 0.0000046)."""
    return float(f"{x:.6g}")


def _atr_pct(ohlcv, period=14):
    """Amplitude media por vela em % do preco: mede a volatilidade."""
    rows = ohlcv[-period - 1:]
    trs = [max(cur[2] - cur[3], abs(cur[2] - prev[4]), abs(cur[3] - prev[4])) for prev, cur in zip(rows[:-1], rows[1:])]
    return round(sum(trs) / len(trs) / ohlcv[-1][4] * 100, 2)


def _trend(symbol, timeframe):
    """Tendencia num prazo maior, para o Grok nao comprar contra a corrente."""
    closes = [c[4] for c in _public.fetch_ohlcv(symbol, timeframe, limit=60)]
    e20, e50 = _ema(closes[-40:], 20), _ema(closes, 50)
    return {"rsi14": round(_rsi(closes), 1), "price_vs_ema20_pct": round((closes[-1] / e20 - 1) * 100, 2),
            "ema20_vs_ema50": "alta" if e20 > e50 else "baixa"}


_btc = {"t": 0.0, "data": None}


def _btc_context():
    """O BTC puxa o mercado inteiro: o Grok ve se o contexto geral esta a favor ou contra."""
    if time.time() - _btc["t"] > 300:
        t = tickers().get("BTC/USDT") or {}
        _btc.update(t=time.time(), data={"change_24h_pct": t.get("percentage"), "trend_1h": _trend("BTC/USDT", "1h")})
    return _btc["data"]


def snapshot(symbol, timeframe="1h", limit=100, context=True):
    """Preco, indicadores, volatilidade, tendencias de prazos maiores e contexto do BTC."""
    ohlcv = _public.fetch_ohlcv(symbol, timeframe, limit=limit)
    closes = [c[4] for c in ohlcv]
    ticker = _public.fetch_ticker(symbol)
    vols = [c[5] for c in ohlcv]
    snap = {
        "symbol": symbol,
        "timeframe": timeframe,
        "price": _r(ticker["last"]),
        "change_24h_pct": ticker.get("percentage"),
        "volume_24h": ticker.get("quoteVolume"),
        "rsi14": round(_rsi(closes), 1),
        "ema20": _r(_ema(closes[-40:], 20)),
        "ema50": _r(_ema(closes, 50)),
        "atr_pct": _atr_pct(ohlcv),
        "volume_ratio": round(vols[-2] / (sum(vols[-22:-2]) / 20), 2) if sum(vols[-22:-2]) else None,
        "high_100": _r(max(c[2] for c in ohlcv)),
        "low_100": _r(min(c[3] for c in ohlcv)),
        "last_closes": [_r(c) for c in closes[-12:]],
    }
    if context:
        try:
            snap["trend_1h"] = _trend(symbol, "1h")
            snap["trend_4h"] = _trend(symbol, "4h")
            if symbol != "BTC/USDT":
                snap["btc"] = _btc_context()
        except Exception:
            pass  # o contexto e um extra: sem ele a analise continua
    return snap
