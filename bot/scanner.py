"""Escolhe as moedas a vigiar: as USDT liquidas com mais momentum nas ultimas 24h."""
import time

from . import config, market

STABLES = {"USDC", "FDUSD", "TUSD", "USDP", "DAI", "BUSD", "EUR", "USDE", "USD1", "XUSD", "AEUR", "PYUSD", "GBP", "TRY", "BRL"}
LEVERAGED = ("UP", "DOWN", "BULL", "BEAR")

_cache = {"t": 0.0, "top": []}


def _eligible(symbol, t):
    if not symbol.endswith("/USDT") or ":" in symbol:
        return False
    base = symbol.split("/")[0]
    if base in STABLES or base.endswith(LEVERAGED):
        return False
    vol, chg, last = t.get("quoteVolume"), t.get("percentage"), t.get("last")
    if not vol or chg is None or not last:
        return False
    # Liquidez minima e sem moedas que ja explodiram (entrar depois do pico e a forma classica de perder)
    return vol >= config.SCAN_MIN_VOLUME_USDT and chg <= config.SCAN_MAX_CHANGE_PCT


def top_movers():
    if time.time() - _cache["t"] > config.SCAN_REFRESH_SEC or not _cache["top"]:
        ranked = sorted(((s, t) for s, t in market.tickers().items() if _eligible(s, t)),
                        key=lambda st: st[1]["percentage"], reverse=True)
        _cache.update(t=time.time(), top=[s for s, _ in ranked[:config.SCAN_TOP_N]])
    return _cache["top"]


def universe(held=()):
    """Posicoes abertas primeiro (para as gerir sempre), depois as candidatas novas."""
    base = top_movers() if config.SCAN_ENABLED else list(config.SYMBOLS)
    return list(dict.fromkeys([*held, *base]))


def is_allowed(symbol):
    return symbol in config.SYMBOLS or symbol in _cache["top"]
