"""Orcamento diario de chamadas ao Grok: o Python vigia de graca, a IA so entra nos momentos que contam."""
import json
import os
import threading
from datetime import date

from . import config

_PATH = os.path.join(config.DATA_DIR, "grok_usage.json")
_lock = threading.Lock()


class BudgetExceeded(RuntimeError):
    pass


def _load():
    try:
        with open(_PATH, encoding="utf-8") as f:
            s = json.load(f)
    except (OSError, ValueError):
        s = {}
    if s.get("day") != str(date.today()):
        s = {"day": str(date.today()), "calls": 0, "exits": 0, "tokens_in": 0, "tokens_out": 0, "by_kind": {}}
    return s


def _save(s):
    os.makedirs(os.path.dirname(_PATH), exist_ok=True)
    with open(_PATH, "w", encoding="utf-8") as f:
        json.dump(s, f, indent=2)


def reserve(kind):
    """Conta uma chamada. Entradas param no teto; saidas (realizar lucro) tem uma reserva extra para nunca ficarem sem IA."""
    with _lock:
        s = _load()
        exit_kind = kind == "exit"
        if exit_kind:
            if s["exits"] >= config.GROK_EXIT_RESERVE_CALLS:
                raise BudgetExceeded(f"reserva de saidas esgotada ({config.GROK_EXIT_RESERVE_CALLS}/dia)")
        elif s["calls"] - s["exits"] >= config.GROK_MAX_CALLS_PER_DAY:
            raise BudgetExceeded(f"orcamento diario do Grok esgotado ({config.GROK_MAX_CALLS_PER_DAY} chamadas), volta amanha")
        s["calls"] += 1
        s["exits"] += exit_kind
        s["by_kind"][kind] = s["by_kind"].get(kind, 0) + 1
        _save(s)


def record_tokens(tokens_in, tokens_out):
    with _lock:
        s = _load()
        s["tokens_in"] += tokens_in or 0
        s["tokens_out"] += tokens_out or 0
        _save(s)


def usage():
    with _lock:
        return _load()


def exhausted():
    """True se ja nao ha chamadas para analisar entradas hoje (as saidas tem reserva propria)."""
    with _lock:
        s = _load()
        return s["calls"] - s["exits"] >= config.GROK_MAX_CALLS_PER_DAY
