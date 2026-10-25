import json
import os
import threading
from datetime import date

import ccxt

from . import config, market

_lock = threading.Lock()
_STATE = os.path.join(config.DATA_DIR, "paper.json")


class PaperBroker:
    """Carteira virtual guardada em data/paper.json."""

    def __init__(self):
        os.makedirs(os.path.dirname(_STATE), exist_ok=True)
        if os.path.exists(_STATE):
            with open(_STATE, encoding="utf-8") as f:
                self.s = json.load(f)
        else:
            self.s = {"USDT": config.PAPER_START_USDT, "positions": {}, "trades": []}
            self._save()

    def _save(self):
        with open(_STATE, "w", encoding="utf-8") as f:
            json.dump(self.s, f, indent=2)

    def balance_usdt(self):
        return self.s["USDT"]

    def portfolio(self):
        return {"mode": "paper", "USDT": round(self.s["USDT"], 2), "positions": self.s["positions"], "trades": self.s["trades"][-20:]}

    def order(self, side, symbol, usdt):
        px = market.price(symbol)
        base = symbol.split("/")[0]
        qty = usdt / px
        with _lock:
            pos = self.s["positions"].get(base, 0.0)
            if side == "buy":
                if usdt > self.s["USDT"]:
                    raise ValueError("Saldo USDT insuficiente.")
                self.s["USDT"] -= usdt
                self.s["positions"][base] = pos + qty
            else:
                qty = min(qty, pos)
                if qty <= 0:
                    raise ValueError(f"Sem posicao em {base} para vender.")
                self.s["USDT"] += qty * px
                self.s["positions"][base] = pos - qty
            self.s["trades"].append({"day": str(date.today()), "side": side, "symbol": symbol, "price": px, "qty": qty, "usdt": qty * px})
            self._save()
        return {"side": side, "symbol": symbol, "price": px, "qty": qty, "usdt": round(qty * px, 2), "mode": "paper", "fee_usdt": 0.0}   # simulacao sem comissoes


class LiveBroker:
    """Ordens reais na Binance (ou na testnet se BINANCE_TESTNET=true)."""

    def __init__(self):
        if not (config.BINANCE_KEY and config.BINANCE_SECRET):
            raise RuntimeError("BINANCE_API_KEY/SECRET em falta para TRADING_MODE=live.")
        # adjustForTimeDifference sincroniza com o relogio da Binance (erro -1021 quando o PC esta desfasado)
        self.ex = ccxt.binance({
            "apiKey": config.BINANCE_KEY,
            "secret": config.BINANCE_SECRET,
            "enableRateLimit": True,
            "options": {"adjustForTimeDifference": True, "recvWindow": 10000},
        })
        if config.TESTNET:
            self.ex.set_sandbox_mode(True)
        # A Binance rejeita timestamps adiantados em mais de 1s (recvWindow so cobre atrasos),
        # por isso mede o desfasamento ja e recua o relogio 1s a mais como margem.
        self.ex.load_time_difference()
        self.ex.options["timeDifference"] = (self.ex.options.get("timeDifference") or 0) + 1000

    def balance_usdt(self):
        return self.ex.fetch_balance()["free"].get("USDT", 0.0)

    def portfolio(self):
        bal = self.ex.fetch_balance()
        label = "live-testnet" if config.TESTNET else "live"
        return {"mode": label, "USDT": round(bal["free"].get("USDT", 0.0), 2), "positions": {k: v for k, v in bal["total"].items() if v and k != "USDT"}, "trades": []}

    def order(self, side, symbol, usdt):
        px = market.price(symbol)
        amount = float(self.ex.amount_to_precision(symbol, usdt / px))
        res = self.ex.create_order(symbol, "market", side, amount)
        fill = res.get("average") or px
        base = symbol.split("/")[0]
        fee = 0.0
        for f in (res.get("fees") or ([res["fee"]] if res.get("fee") else [])):   # comissao na moeda em que foi cobrada, convertida para USDT
            cost = f.get("cost") or 0.0
            fee += cost * (fill if f.get("currency") == base else 1.0 if f.get("currency") == "USDT" else 0.0)
        return {"side": side, "symbol": symbol, "price": fill, "qty": amount, "usdt": round(amount * px, 2), "mode": "live-testnet" if config.TESTNET else "live", "id": res.get("id"), "fee_usdt": round(fee, 6)}


def get_broker():
    return LiveBroker() if config.MODE == "live" else PaperBroker()
