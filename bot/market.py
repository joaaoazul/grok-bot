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


def price(symbol):
    return _public.fetch_ticker(symbol)["last"]


def snapshot(symbol, timeframe="1h", limit=100):
    """Preco, variacao 24h e indicadores simples para dar contexto ao Grok."""
    ohlcv = _public.fetch_ohlcv(symbol, timeframe, limit=limit)
    closes = [c[4] for c in ohlcv]
    ticker = _public.fetch_ticker(symbol)
    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "price": ticker["last"],
        "change_24h_pct": ticker.get("percentage"),
        "volume_24h": ticker.get("quoteVolume"),
        "rsi14": round(_rsi(closes), 1),
        "ema20": round(_ema(closes[-40:], 20), 2),
        "ema50": round(_ema(closes, 50), 2),
        "high_100": max(c[2] for c in ohlcv),
        "low_100": min(c[3] for c in ohlcv),
        "last_closes": [round(c, 2) for c in closes[-12:]],
    }
