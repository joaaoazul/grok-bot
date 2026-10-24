"""Taxa EUR/USD (a simulacao trabalha em dolares, os limites de ordem sao em euros)."""
import time

import requests

from .. import config

_cache = {"t": 0.0, "rate": None}


def eur_usd():
    if time.time() - _cache["t"] > 3600:
        try:
            rate = requests.get("https://api.frankfurter.app/latest", params={"from": "EUR", "to": "USD"}, timeout=10).json()["rates"]["USD"]
            _cache.update(t=time.time(), rate=float(rate))
        except Exception:
            _cache["t"] = time.time() - 3000  # volta a tentar daqui a ~10 min; entretanto usa o ultimo valor ou o por defeito
    return _cache["rate"] or config.DEX_EURUSD
