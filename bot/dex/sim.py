"""Carteira virtual para DEX. Modela o que torna o DEX diferente de uma exchange: impacto no preco
(pool de produto constante), comissoes altas e posicoes que podem ficar sem saida.

Tudo com dinheiro virtual. Nao ha carteira real nem chaves.
"""
import json
import os
import threading
import time

from .. import config

_lock = threading.RLock()


def reserve(liq):
    """Lado em USD da pool (metade da liquidez total)."""
    return max(liq or 0.0, 1.0) / 2


def net_value(tokens, price, liq):
    """O que receberias hoje se vendesses tudo: preco de mercado menos impacto na pool e comissao."""
    v = tokens * price
    rq = reserve(liq)
    return v * rq / (rq + v) * (1 - config.DEX_FEE_PCT / 100)


class DexPaper:
    def __init__(self, name="dex.json", start=None):
        self.path = os.path.join(config.DATA_DIR, name)
        if os.path.exists(self.path):
            with open(self.path, encoding="utf-8") as f:
                self.s = json.load(f)
        else:
            start = start or config.DEX_START_USD
            self.s = {"cash": start, "start": start, "positions": {}, "closed": [], "equity": [], "seen": {}}
            self._save()

    def _save(self):
        os.makedirs(config.DATA_DIR, exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self.s, f, indent=1)

    # --- compra e venda ---
    def buy(self, pool, usd, features, conf, reason, target_pct=None, fill=None):
        """fill: execucao real {tokens, usd, ...}. Sem fill, calcula o que a pool daria (simulacao)."""
        with _lock:
            if usd > self.s["cash"] or pool["id"] in self.s["positions"]:
                return None
            if fill:
                tokens, usd = fill["tokens"], fill["usd"]
            else:
                eff = pool["price"] * (1 + usd / reserve(pool["liq"]))      # impacto de comprar `usd` na pool
                tokens = usd * (1 - config.DEX_FEE_PCT / 100) / eff
            self.s["cash"] -= usd
            pos = {"id": pool["id"], "name": pool["name"], "network": pool["network"], "pool": pool["pool"], "token": pool["token"],
                   "tokens": tokens, "cost": usd, "entry_price": pool["price"], "entry_liq": pool["liq"], "ts": int(time.time()),
                   "last_price": pool["price"], "last_liq": pool["liq"], "peak_pnl_pct": 0.0, "miss": 0,
                   "target_pct": target_pct or config.DEX_TP_DEFAULT_PCT,
                   "features": features, "confidence": conf, "reason": reason[:200]}
            if fill:
                pos.update(real=True, sig=fill.get("sig"))
            self.s["positions"][pool["id"]] = pos
            self._save()
            return pos

    def pnl_pct(self, pos):
        return (net_value(pos["tokens"], pos["last_price"], pos["last_liq"]) / pos["cost"] - 1) * 100

    def price_for_pnl(self, pos, pct):
        """Preco de mercado a que a posicao teria o resultado liquido `pct` (para as linhas do grafico). Bissecao: o valor so sobe com o preco."""
        lo, hi = 0.0, pos["entry_price"] * 1000
        for _ in range(60):
            mid = (lo + hi) / 2
            if (net_value(pos["tokens"], mid, pos["last_liq"]) / pos["cost"] - 1) * 100 < pct:
                lo = mid
            else:
                hi = mid
        return hi

    def update_mark(self, pos_id, price, liq):
        with _lock:
            pos = self.s["positions"].get(pos_id)
            if not pos:
                return None
            pos.update(last_price=price, last_liq=liq or pos["last_liq"], miss=0)
            pos["peak_pnl_pct"] = max(pos["peak_pnl_pct"], self.pnl_pct(pos))
            self._save()
            return pos

    def mark_missing(self, pos_id):
        with _lock:
            pos = self.s["positions"].get(pos_id)
            if pos:
                pos["miss"] += 1
                self._save()
            return pos

    def sell(self, pos_id, kind, proceeds=None, detail="", sig=None):
        """Vende tudo ao preco da ultima observacao. Se a pool desapareceu (kind rug), recebe 0."""
        with _lock:
            pos = self.s["positions"].pop(pos_id, None)
            if not pos:
                return None
            if proceeds is None:   # simulacao: calcula; real: vem do que a carteira recebeu
                proceeds = 0.0 if kind == "rug" else net_value(pos["tokens"], pos["last_price"], pos["last_liq"])
            self.s["cash"] += proceeds
            gross = pos["tokens"] * pos["last_price"]          # valor de mercado da saida, antes de impacto e comissao
            rec = {**{k: pos[k] for k in ("id", "name", "network", "cost", "entry_price", "confidence", "reason", "features")},
                   "target_pct": pos.get("target_pct"),
                   "exit_price": pos["last_price"], "proceeds": round(proceeds, 2), "kind": kind,
                   "pnl_usd": round(proceeds - pos["cost"], 2), "pnl_pct": round((proceeds / pos["cost"] - 1) * 100, 1),
                   "peak_pnl_pct": round(pos["peak_pnl_pct"], 1), "held_min": round((time.time() - pos["ts"]) / 60), "ts": int(time.time()),
                   # detalhe: quantidade, de onde vem o resultado e quanto se perdeu em comissoes, impacto no preco e slippage
                   "tokens": pos["tokens"], "entry_ts": pos["ts"], "entry_liq": pos.get("entry_liq"), "exit_liq": pos.get("last_liq"),
                   "gross_usd": round(gross, 4), "buy_cost_usd": round(pos["cost"] - pos["tokens"] * pos["entry_price"], 4),
                   "sell_cost_usd": round(gross - proceeds, 4), "detail": str(detail)[:200], "real": bool(pos.get("real")),
                   "buy_sig": pos.get("sig"), "sell_sig": sig,
                   "stop_pct": pos.get("stop_pct"), "conviction": pos.get("conviction")}
            self.s["closed"] = (self.s["closed"] + [rec])[-300:]
            self._save()
            return rec

    # --- vistas ---
    def equity(self):
        return self.s["cash"] + sum(net_value(p["tokens"], p["last_price"], p["last_liq"]) for p in self.s["positions"].values())

    def snapshot_equity(self, min_gap=60):
        with _lock:
            now = int(time.time())
            if not self.s["equity"] or now - self.s["equity"][-1][0] >= min_gap:
                self.s["equity"] = (self.s["equity"] + [[now, round(self.equity(), 2)]])[-2000:]
                self._save()

    def stats(self):
        c = self.s["closed"]
        if not c:
            return None
        kinds = {}
        for r in c:
            kinds.setdefault(r["kind"], []).append(r["pnl_pct"])
        return {"n": len(c), "win_rate_pct": round(100 * sum(r["pnl_usd"] > 0 for r in c) / len(c)),
                "avg_pnl_pct": round(sum(r["pnl_pct"] for r in c) / len(c), 1), "total_pnl_usd": round(sum(r["pnl_usd"] for r in c), 2),
                "rugs": sum(r["kind"] == "rug" for r in c),
                "por_saida": {k: {"n": len(v), "avg_pnl_pct": round(sum(v) / len(v), 1)} for k, v in kinds.items()}}

    def seen(self, pid, within_min):
        t = self.s["seen"].get(pid)
        return t is not None and time.time() - t < within_min * 60

    def mark_seen(self, pid):
        with _lock:
            self.s["seen"][pid] = int(time.time())
            if len(self.s["seen"]) > 2000:  # limpa os mais antigos
                self.s["seen"] = dict(sorted(self.s["seen"].items(), key=lambda kv: kv[1])[-1000:])
            self._save()
