"""Curva de equity: um ponto por minuto, no maximo, guardada em data/equity.json."""
import json
import os
import threading
import time

from . import config

_PATH = os.path.join(config.DATA_DIR, "equity.json")
_lock = threading.Lock()


def _load():
    if os.path.exists(_PATH):
        with open(_PATH, encoding="utf-8") as f:
            return json.load(f)
    return []


def add(value, min_gap=60):
    with _lock:
        points = _load()
        now = int(time.time())
        if points and now - points[-1][0] < min_gap:
            return
        points.append([now, round(value, 2)])
        os.makedirs(os.path.dirname(_PATH), exist_ok=True)
        with open(_PATH, "w", encoding="utf-8") as f:
            json.dump(points[-4000:], f)


def series():
    with _lock:
        return _load()
