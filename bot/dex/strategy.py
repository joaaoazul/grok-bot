"""Bot de memecoins em DEX. Descobre pools novas, filtra fraudes obvias, pede decisao ao Grok e gere as saidas com stops
proprios. Por defeito e simulacao (dinheiro virtual). Com DEX_MODE=live, DEX_LIVE_ARMED=true e uma carteira dedicada,
executa swaps reais na Solana via Jupiter (ver live.py); com DEX_LIVE_DRY_RUN=true so cota e simula."""
import json
import os
import threading
import time
from collections import Counter, deque
from datetime import datetime

from .. import analyst, budget, config
from . import data, fx, signals
from .sim import DexPaper, net_value, _lock as _sim_lock


# Saidas por perigo: vende ja, com slippage mais alto
URGENT = {"perigo", "queda_brusca", "pressao_venda", "liquidez", "rug"}

# Moedas base que nao interessam: stablecoins e as grandes (nao dao os movimentos que o bot procura)
MAJORS = {"SOL", "WSOL", "USDC", "USDT", "USDG", "USDS", "PYUSD", "DAI", "ETH", "WETH", "BTC", "WBTC", "CBBTC", "JITOSOL", "MSOL", "BSOL"}


def _momentum(p):
    """Pontuacao de impulso so para ORDENAR candidatas (nao decide nada): preco a subir, volume da ultima hora acima do ritmo
    diario e mais compras que vendas. As melhores vao primeiro ao Grok."""
    chg = max(-20.0, min(60.0, (p["chg"].get("h1") or 0))) / 20
    day_rate = (p["vol"].get("h24") or 0) / 24
    accel = min(5.0, (p["vol"].get("h1") or 0) / day_rate) / 2 if day_rate else 0
    h1 = (p.get("tx") or {}).get("h1") or {}
    b, s = h1.get("buyers") or 0, h1.get("sellers") or 0
    pressure = ((b / (b + s)) - 0.5) * 4 if b + s else 0
    m5 = max(-5.0, min(5.0, (p["chg"].get("m5") or 0))) / 5
    return chg + accel + pressure + m5 + 2 * signals.surge(p)    # volume de compra a acelerar em 5 min e 1 h sobe a candidata na fila


def _num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


class DexBot:
    def __init__(self):
        self.live = None
        if config.DEX_MODE == "live":
            from .live import LiveSolana
            self.live = LiveSolana()   # levanta erro se a chave falta ou e invalida: nao arranca a meio gas
            self.sim = DexPaper("dex_live.json", 0.01)   # a caixa e o saldo real da carteira: sincroniza-se a cada ciclo (_sync_wallet)
            self.networks = ["solana"]
        else:
            self.sim = DexPaper()
            self.networks = config.DEX_NETWORKS
        self.enabled = False
        self.cycles = 0
        self.activity = {"kind": "idle", "what": ""}   # idle | scan | think
        self._scanning = False
        self.log = deque(maxlen=150)
        self.funnel = {}
        self.last_scan = None
        self._stop = threading.Event()
        self.scans = deque(maxlen=60)          # resumo de cada procura (funil)
        self._an_path = os.path.join(config.DATA_DIR, "dex_analysed.json")
        try:
            with open(self._an_path, encoding="utf-8") as f:
                self.analysed = deque(json.load(f), maxlen=200)   # decisoes do Grok e rejeicoes, mais recente primeiro
        except (OSError, ValueError):
            self.analysed = deque(maxlen=200)
        self._wallet = {"t": 0}
        self._prev = {}      # id -> (resultado %, liquidez) do ciclo anterior do vigilante
        self._chk = {}       # id -> ultima verificacao de seguranca
        self._fresh = {}     # id -> ultimos dados da pool
        self._reviewed = {}  # id -> ultima reavaliacao de saida pelo Grok
        self._reviewing = set()
        if self.live:
            self._sync_wallet()   # tenta ja; se o RPC falhar, fica a espera do primeiro ciclo
        self._exit_lock = threading.RLock()   # evita vender a mesma posicao duas vezes (vigilante + botao)

    def _note(self, p, decision, reason="", **extra):
        """Guarda cada moeda analisada com a decisao e os numeros que a justificam, para a pagina de pesquisas."""
        h1 = (p.get("tx") or {}).get("h1") or {}
        entry = {"ts": int(time.time()), "t": datetime.now().strftime("%H:%M:%S"), "id": p["id"], "name": p["name"], "network": p["network"],
                 "pool": p["pool"], "token": p["token"], "decision": decision, "reason": str(reason)[:400],
                 "price": p["price"], "liq": p["liq"], "fdv": p.get("fdv"), "vol_h1": (p.get("vol") or {}).get("h1"),
                 "chg_h1": (p.get("chg") or {}).get("h1"), "chg_h24": (p.get("chg") or {}).get("h24"), "age_min": round(p["age_min"]),
                 "buyers": h1.get("buyers"), "sellers": h1.get("sellers"), **extra}
        self.analysed.appendleft(entry)
        try:
            os.makedirs(config.DATA_DIR, exist_ok=True)
            with open(self._an_path, "w", encoding="utf-8") as f:
                json.dump(list(self.analysed), f)
        except OSError:
            pass

    def _wallet_info(self):
        if not self.live:
            return None
        if time.time() - self._wallet["t"] > 20:
            try:
                from . import chain
                sol = chain.sol_balance(self.live.owner) / 1e9
                self._wallet = {"t": time.time(), "address": self.live.owner, "sol": round(sol, 4), "usd": round(sol * chain.sol_price_usd(), 2)}
            except Exception:
                self._wallet["t"] = time.time() - 10   # tenta de novo daqui a 10 s
        return {k: v for k, v in self._wallet.items() if k != "t"} or {"address": self.live.owner}

    def _set(self, kind, what=""):
        self.activity = {"kind": kind, "what": what}

    def _rest(self):
        """Volta ao estado de fundo: a procurar se houver uma procura a decorrer, senao em repouso."""
        self._set("scan", "a procurar pools") if self._scanning else self._set("idle")

    def _say(self, msg, kind="info"):
        self.log.appendleft({"t": datetime.now().strftime("%H:%M:%S"), "kind": kind, "msg": msg})

    # ---------- ciclo de vida ----------
    def start(self):
        if self.enabled:
            return
        self.enabled = True
        self._stop.clear()
        if self.live:
            self._reconcile()
            if os.getenv("DEX_BUDGET_EUR"):
                self._say("DEX_BUDGET_EUR ja nao se usa: o orcamento e agora "
                          f"{config.WALLET_USE_PCT:g}% do saldo da carteira. Podes apagar essa linha do .env.", "alert")
        threading.Thread(target=self._scan_loop, daemon=True).start()
        threading.Thread(target=self._guard_loop, daemon=True).start()
        if self.live:
            how = "SO COTA E SIMULA (dry-run, nada e enviado)" if self.live.dry else "DINHEIRO REAL"
            self._say(f"Modo live ligado: {how}. Carteira {self.live.owner}.", "system")
        else:
            self._say(f"Simulacao de memecoins ligada ({', '.join(self.networks)}). Dinheiro virtual.", "system")

    def stop(self):
        self.enabled = False
        self._stop.set()
        self._say("Memecoins desligado (as posicoes abertas continuam guardadas; usa o botao de panico para vender tudo).", "system")

    def _scan_loop(self):
        while not self._stop.is_set():
            self._scanning = True
            self._set("scan", "a procurar pools")
            try:
                self.scan()
            except Exception as exc:
                self._say(f"Erro na procura: {exc}", "error")
            finally:
                self._scanning = False
                self._rest()
            self.last_scan = datetime.now().strftime("%H:%M:%S")
            self.cycles += 1
            self._stop.wait(config.DEX_SCAN_SEC)

    def _guard_loop(self):
        while not self._stop.wait(config.DEX_GUARD_SEC):
            try:
                self.guard()
            except Exception as exc:
                self._say(f"Vigilante: {exc}", "error")

    def _reconcile(self):
        """Antes de operar, confirma on-chain que cada posicao ainda existe na carteira."""
        from . import chain
        for pos in list(self.sim.s["positions"].values()):
            try:
                if chain.token_balance(self.live.owner, pos["token"]) <= 0:
                    self.sim.sell(pos["id"], "perdido", proceeds=0.0)
                    self._say(f"{pos['name']}: sem saldo na carteira, fechada como perdida.", "alert")
            except Exception as exc:
                self._say(f"Reconciliacao de {pos['name']}: {exc}", "error")

    def _live_blocked(self):
        """Travoes do modo real. Devolve o motivo, ou None se pode comprar."""
        if os.path.exists(os.path.join(config.DATA_DIR, "KILL")):
            return "ficheiro KILL presente"
        day = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        lost = -sum(r["pnl_usd"] for r in self.sim.s["closed"] if r["ts"] >= day)
        if lost >= config.DEX_DAILY_LOSS_EUR * fx.eur_usd():
            return f"perda do dia de {lost / fx.eur_usd():.2f} EUR atingiu o limite"
        return None

    def _sync_wallet(self):
        """Modo real: a caixa e o saldo de SOL da carteira, ja sem as taxas pagas. Sem operacoes ainda, o capital inicial acompanha
        o saldo. Devolve (saldo_em_usd, None) ou (None, motivo)."""
        try:
            sol_usd = self.live.wallet_usd()
        except Exception as exc:
            return None, f"nao consegui ler o saldo da carteira ({exc})"
        with _sim_lock:
            s = self.sim.s
            s["cash"] = sol_usd
            if not s["positions"] and not s["closed"]:
                s["start"] = sol_usd
            elif not s.get("wallet_budget"):
                # Migracao unica de um estado antigo (orcamento fixo): o capital inicial passa a ser o que a carteira tem agora mais o custo
                # das posicoes abertas, menos o que ja se ganhou ou perdeu. Assim o "resultado total" nao conta a diferenca como lucro.
                realized = sum(r.get("pnl_usd", 0.0) for r in s["closed"])
                s["start"] = sol_usd + sum(p["cost"] for p in s["positions"].values()) - realized
            s["wallet_budget"] = True
            self.sim._save()
        return sol_usd, None

    def _room(self):
        """Dolares que ainda se podem gastar numa compra nova. O orcamento e WALLET_USE_PCT% da carteira (saldo + posicoes abertas):
        os outros (100 - WALLET_USE_PCT)% ficam livres para taxas da rede e outros custos. Devolve (dolares, motivo_se_nao_conseguiu_ler)."""
        keep = 1 - config.WALLET_USE_PCT / 100
        if self.live:
            sol_usd, why = self._sync_wallet()
            if why:
                return 0.0, why
        return max(self.sim.s["cash"] - keep * self.sim.equity(), 0.0), None

    @staticmethod
    def _target(pos):
        """Alvo de lucro da posicao, nunca acima do teto atual: tambem encolhe os alvos de posicoes abertas antes de o teto baixar."""
        return min(pos.get("target_pct") or config.DEX_TP_DEFAULT_PCT, config.DEX_TP_MAX_PCT)

    def _today(self):
        day = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        rows = [r for r in self.sim.s["closed"] if r["ts"] >= day]
        return {"n": len(rows), "pnl_usd": round(sum(r["pnl_usd"] for r in rows), 2), "wins": sum(r["pnl_usd"] > 0 for r in rows)}

    def panic(self):
        """Vende tudo e para. Tenta cada posicao ate ao fim, mesmo que uma falhe."""
        self.stop()
        for pid in list(self.sim.s["positions"]):
            self._exit(pid, "panico", "botao de panico")
        left = len(self.sim.s["positions"])
        self._say("Panico concluido." if not left else f"Panico: {left} posicao(oes) nao venderam, verificar a carteira.", "alert")

    # ---------- entradas ----------
    def _reject(self, p):
        """Filtros baratos, sem chamar o Grok. Devolve o motivo curto da rejeicao, ou None se passa."""
        s = self.sim.s
        h1 = p["tx"].get("h1") or {}
        if not p["price"] or p["price"] <= 0:
            return "sem_preco"
        if p["id"] in s["positions"]:
            return "ja_tenho"
        if self.sim.seen(p["id"], config.DEX_REANALYSE_MIN):
            return "ja_analisada"
        if not p["liq"] or p["liq"] < config.DEX_MIN_LIQ_USD:
            return "pouca_liquidez"
        if p["age_min"] < config.DEX_MIN_AGE_MIN:
            return "muito_nova"
        if p["age_min"] > config.DEX_MAX_AGE_H * 60:
            return "muito_velha"
        if p["name"].split(" / ")[0].strip().upper() in MAJORS:
            return "moeda_grande_ou_stable"
        old = p["age_min"] > config.DEX_OLD_AFTER_H * 60
        if old and p["liq"] < config.DEX_MIN_LIQ_OLD_USD:
            return "pouca_liquidez_p_antiga"
        if (p["vol"]["h24"] or 0) > config.DEX_MAX_VOL_LIQ * p["liq"]:
            return "volume_suspeito"
        if (p["vol"]["h1"] or 0) < config.DEX_MIN_VOL_H1:
            return "pouco_volume"
        if (h1.get("buyers") or 0) < config.DEX_MIN_BUYERS_H1:
            return "poucos_compradores"
        if (h1.get("sellers") or 0) < config.DEX_MIN_SELLERS_H1:
            return "poucos_vendedores"
        if (h1.get("buyers") or 0) >= 30 and (h1.get("sellers") or 0) * config.DEX_MAX_BUY_SELL_RATIO < (h1.get("buyers") or 0):
            return "vendas_bloqueadas"   # muitas compras e quase nenhuma venda: padrao de quem nao consegue sair
        if (p["chg"]["h1"] or 0) > config.DEX_MAX_CHG_H1:
            return "ja_disparou"
        return None

    @staticmethod
    def _rc_bad(rc):
        blocking = ("mint authority", "freeze authority", "rug", "honeypot", "creator")
        if any(k in g.lower() for g in rc["graves"] for k in blocking):
            return "seguranca:rugcheck_grave"
        if (rc["score"] or 0) > config.DEX_MAX_RUGCHECK_SCORE:
            return "seguranca:rugcheck_score"
        return None

    def _unsafe(self, info):
        rc = info.get("rugcheck")
        if rc and self._rc_bad(rc):
            return self._rc_bad(rc)
        if info["mint_authority"] == "yes":
            return "seguranca:mint_ativo"
        if info["freeze_authority"] == "yes":
            return "seguranca:freeze_ativo"
        if info["is_honeypot"] == "yes":
            return "seguranca:honeypot"
        if info["dev_holding_pct"] is not None and info["dev_holding_pct"] > config.DEX_MAX_DEV_PCT:
            return "seguranca:dono_com_muito"
        if info["top10_pct"] is not None and info["top10_pct"] > config.DEX_MAX_TOP10_PCT:
            return "seguranca:holders_concentrados"
        return None

    def scan(self):
        s = self.sim.s
        if self.live:
            why = self._live_blocked()
            if why:
                self._say(f"Compras bloqueadas: {why}.", "alert")
                return
        room, why = self._room()
        if why:
            self._say(f"Compras em pausa: {why}.", "alert")
            return
        if len(s["positions"]) >= config.DEX_MAX_POSITIONS or room < config.DEX_MIN_SIZE_EUR * fx.eur_usd():
            self._say(f"Sem vaga ou sem saldo livre (a carteira guarda {100 - config.WALLET_USE_PCT:g}% para taxas): a esperar que as posicoes fechem.")
            return
        if budget.exhausted():
            self._say(f"Orcamento diario do Grok esgotado ({config.GROK_MAX_CALLS_PER_DAY} chamadas): sem novas entradas ate amanha, os stops continuam.", "alert")
            return
        pools = {}
        fns = []
        if "dexscreener" in config.DEX_SOURCES:
            fns.append(data.ds_discover)
        if "geckoterminal" in config.DEX_SOURCES:
            fns += [data.new_pools, data.trending_pools]
            if config.DEX_ESTABLISHED:
                fns.append(data.top_pools)
        for net in self.networks:
            for fn in fns:
                try:
                    for p in fn(net):
                        pools.setdefault(p["id"], p)   # a primeira fonte que ve a pool fica com ela
                except Exception as exc:
                    self._say(f"{net} ({fn.__name__}): {exc}", "error")
        funnel = Counter(vistas=len(pools))
        cands = []
        for p in pools.values():
            why = self._reject(p)
            if why:
                funnel[why] += 1
            else:
                cands.append(p)
        funnel["passam_filtros"] = len(cands)
        self.funnel = dict(funnel)
        self.scans.appendleft({"t": datetime.now().strftime("%H:%M:%S"), "ts": int(time.time()), "vistas": funnel["vistas"],
                               "passam": len(cands), "funnel": {k: v for k, v in funnel.items() if k not in ("vistas", "passam_filtros")}})
        rejected = ", ".join(f"{k} {v}" for k, v in funnel.most_common() if k not in ("vistas", "passam_filtros"))[:150]
        self._say(f"Procura: {funnel['vistas']} pools, {len(cands)} passam os filtros. Rejeitadas: {rejected or 'nenhuma'}")
        for p in sorted(cands, key=_momentum, reverse=True)[:config.DEX_ANALYSE_PER_SCAN]:
            if not self.enabled or budget.exhausted():
                return
            try:
                self._evaluate(p)
            except Exception as exc:
                self._say(f"{p['name']}: {exc}", "error")

    def _memory(self):
        c = self.sim.s["closed"]
        if len(c) < 3:
            return {"nota": "Ainda quase sem operacoes fechadas."}
        keep = ("kind", "pnl_pct", "peak_pnl_pct", "held_min", "confidence")
        return {"estatisticas": self.sim.stats(), "ultimas_operacoes": [{k: r[k] for k in keep} for r in c[-8:]],
                "aviso": "Amostra pequena: usa para calibrar, nao como regra."}

    def _evaluate(self, p):
        self.sim.mark_seen(p["id"])
        info = data.token_info(p["network"], p["token"])
        if p["network"] == "solana":
            info["rugcheck"] = data.rugcheck(p["token"])
        unsafe = self._unsafe(info)
        if unsafe:
            self.funnel[unsafe] = self.funnel.get(unsafe, 0) + 1
            self._say(f"{p['name']}: rejeitada ({unsafe.split(':')[1]}).")
            self._note(p, "rejeitada", unsafe.split(":")[1], seguranca=info)
            return
        rows = data.candles(p["network"], p["pool"])
        closes = [r[4] for r in rows]
        if len(closes) < 10:
            self._say(f"{p['name']}: poucas velas ({len(closes)}), ignorada.")
            self._note(p, "ignorada", f"so {len(closes)} velas de 1 minuto")
            return
        peak, max_dd = closes[0], 0.0
        for c in closes:
            peak = max(peak, c)
            max_dd = max(max_dd, (1 - c / peak) * 100)
        candle_summary = {"velas": len(closes), "var_total_pct": round((closes[-1] / closes[0] - 1) * 100, 1),
                          "var_ultimos_5m_pct": round((closes[-1] / closes[-6] - 1) * 100, 1), "queda_maxima_pct": round(max_dd, 1),
                          "volume_ultimos_10m_usd": round(sum(r[5] for r in rows[-10:]))}
        sig = signals.compute(p)
        feat = {"pool": {k: p[k] for k in ("name", "network", "dex", "price", "liq", "fdv", "vol", "tx", "chg")} | {"idade_min": round(p["age_min"]),
                                                                                    "tipo": "com historia" if p["age_min"] > config.DEX_OLD_AFTER_H * 60 else "nova"},
                "seguranca": info, "velas_1m": candle_summary, "sinais_dexscreener": sig,
                "limites": {"ordem_min_eur": config.DEX_MIN_SIZE_EUR, "ordem_max_eur": config.DEX_MAX_SIZE_EUR,
                            "alvo_min_pct": config.DEX_TP_MIN_PCT, "alvo_max_pct": config.DEX_TP_MAX_PCT,
                            "stop_min_pct": config.DEX_STOP_MIN_PCT, "stop_max_pct": config.DEX_STOP_MAX_PCT}}
        self._set("think", f"a analisar {p['name']} com o Grok")
        try:
            proposal = analyst.analyse_dex(feat, self._memory())
        finally:
            self._rest()
        conf = float(proposal.get("confidence") or 0)
        reason = str(proposal.get("reason", ""))
        if proposal.get("action") != "buy" or conf < config.DEX_MIN_CONF:
            self._say(f"{p['name']}: skip ({conf:.0%}). {reason}")
            self._note(p, "skip", reason, confidence=conf, risks=str(proposal.get("risks", ""))[:300], seguranca=info, velas=candle_summary)
            return

        # Tamanho e alvo: o Grok propoe, o codigo limita. O alvo nunca fica abaixo do minimo (30%).
        rate = fx.eur_usd()
        lo, hi = config.DEX_MIN_SIZE_EUR * rate, config.DEX_MAX_SIZE_EUR * rate
        want = _num(proposal.get("size_eur")) * rate or hi * conf
        room, why = self._room()
        if why:
            self._say(f"{p['name']}: {why}.", "alert")
            return
        size = min(max(want, lo), hi, p["liq"] * 0.005, room)  # no maximo 0,5% da liquidez (impacto pequeno) e so o que a carteira deixa gastar
        if size < lo:
            self._say(f"{p['name']}: sem saldo livre para a ordem minima de {config.DEX_MIN_SIZE_EUR:g} EUR (a carteira guarda {100 - config.WALLET_USE_PCT:g}% para taxas).")
            return
        target = min(max(_num(proposal.get("target_pct")) or config.DEX_TP_DEFAULT_PCT, config.DEX_TP_MIN_PCT), config.DEX_TP_MAX_PCT)
        # Stop proprio desta compra: o Grok propoe, a conviccao (confianca, tamanho, volume de compra) limita
        hi_eur = min(config.DEX_MAX_SIZE_EUR, room / rate)          # o intervalo de tamanhos e o que a carteira deixa gastar
        conv = signals.conviction(conf, size / rate, config.DEX_MIN_SIZE_EUR, hi_eur, sig["forca_compra"])
        stop = signals.stop_pct(_num(proposal.get("stop_pct")), conv)
        feats = {**feat["pool"], "seguranca": info, "velas_1m": candle_summary, "sinais": sig}
        fill = None
        if self.live:
            if self._live_blocked():
                return
            try:
                fill = self.live.buy(p["token"], size)
            except Exception as exc:
                self._say(f"{p['name']}: compra recusada ({exc})", "alert")
                self._note(p, "recusada", f"Grok quis comprar, a execucao recusou: {exc}", confidence=conf, seguranca=info)
                return
            if fill.get("dry"):
                sim_txt = "OK" if fill["sim_ok"] else "FALHOU: " + str(fill["sim_err"])
                self._say(f"[DRY-RUN] {p['name']}: {size / rate:.2f} EUR -> ~{fill['tokens']:.4g} tokens, impacto {fill['impact']:.1f}%, "
                          f"ida e volta perde {fill['roundtrip_loss']:.1f}%, simulacao {sim_txt}. Nada enviado.", "buy")
                self._note(p, "dry-run", reason, confidence=conf, size_eur=round(size / rate, 2), target_pct=target, stop_pct=stop, conviction=conv,
                           sinais=sig, seguranca=info, velas=candle_summary)
                return
        pos = self.sim.buy(p, size, feats, conf, reason, target, fill=fill, stop_pct=stop, conviction=conv)
        self._note(p, "compra" if pos else "sem_saldo", reason, confidence=conf, size_eur=round(size / rate, 2), target_pct=target, stop_pct=stop, conviction=conv, sinais=sig,
                   risks=str(proposal.get("risks", ""))[:300], seguranca=info, velas=candle_summary)
        if pos:
            self._say(f"COMPRA {p['name']} ({p['network']}): {size / rate:.2f} EUR ({size:.2f} USD) virtuais, alvo +{target:.0f}%, stop -{stop:.1f}% (conviccao {conv:.0%}, volume de compra {sig['classe']}), idade {p['age_min']:.0f} min, liquidez {p['liq']:,.0f} USD. {reason}", "buy")

    # ---------- saidas ----------
    def guard(self):
        """Atualiza precos das posicoes e aplica as saidas. Um pedido por rede."""
        positions = list(self.sim.s["positions"].values())
        for net in {p["network"] for p in positions}:
            mine = [p for p in positions if p["network"] == net]
            addrs = [p["pool"] for p in mine]
            fresh = {}
            if "dexscreener" in config.DEX_SOURCES:      # mais rapido e com mais pedidos por minuto
                try:
                    fresh = {x["id"]: x for x in data.ds_pools_multi(net, addrs)}
                except Exception as exc:
                    self._say(f"DexScreener: {exc}", "error")
            lacking = [a for a in addrs if f"{net}:{a}" not in fresh]
            if lacking and "geckoterminal" in config.DEX_SOURCES:
                fresh.update({x["id"]: x for x in data.pools_multi(net, lacking)})
            for pos in mine:
                f = fresh.get(pos["id"])
                if f and f["price"]:
                    self._fresh[pos["id"]] = f
                    self.sim.update_mark(pos["id"], f["price"], f["liq"])
                elif self.sim.mark_missing(pos["id"])["miss"] >= 3:
                    self._exit(pos["id"], "rug", "a pool deixou de existir nos dados")
        for pos in list(self.sim.s["positions"].values()):
            danger = self._danger(pos, self._fresh.get(pos["id"]))
            if danger:
                self._exit(pos["id"], danger[0], danger[1])
                continue
            self._check_exits(pos)
            if pos["id"] in self.sim.s["positions"]:
                self._maybe_review(pos, self._fresh.get(pos["id"]))
        self.sim.snapshot_equity()

    def _maybe_review(self, pos, fresh):
        """Com lucro liquido a partir do minimo, o Grok decide se realiza ja ou deixa correr. Corre noutro fio para nao atrasar os stops."""
        pid, pnl = pos["id"], self.sim.pnl_pct(pos)
        if pnl < config.DEX_REVIEW_FROM_PCT or pid in self._reviewing or time.time() - self._reviewed.get(pid, 0) < config.DEX_REVIEW_SEC:
            return
        self._reviewed[pid] = time.time()
        self._reviewing.add(pid)
        f = fresh or {}
        tx, vol, chg = f.get("tx") or {}, f.get("vol") or {}, f.get("chg") or {}
        ctx = {"posicao": {"nome": pos["name"], "resultado_liquido_pct": round(pnl, 1), "maximo_pct": round(pos["peak_pnl_pct"], 1),
                           "queda_desde_maximo_pct": round(max(0.0, pos["peak_pnl_pct"] - pnl), 1),
                           "minutos_em_carteira": round((time.time() - pos["ts"]) / 60), "alvo_automatico_pct": self._target(pos)},
               "mercado": {"var_5m_pct": chg.get("m5"), "var_1h_pct": chg.get("h1"), "var_6h_pct": chg.get("h6"),
                           "compras_vendas_5m": [(tx.get("m5") or {}).get("buyers"), (tx.get("m5") or {}).get("sellers")],
                           "compras_vendas_1h": [(tx.get("h1") or {}).get("buyers"), (tx.get("h1") or {}).get("sellers")],
                           "volume_5m": vol.get("m5"), "volume_1h": vol.get("h1"),
                           "liquidez_atual": pos["last_liq"], "liquidez_na_entrada": pos["entry_liq"]},
               "sinais_dexscreener": signals.compute(f) if f else None}
        threading.Thread(target=self._review, args=(pid, ctx), daemon=True).start()

    def _review(self, pid, ctx):
        self._set("think", "a reavaliar a saida de uma posicao")
        try:
            r = analyst.review_dex(ctx)
            if pid in self.sim.s["positions"] and r.get("action") == "sell" and float(r.get("confidence") or 0) >= 0.5:
                self._exit(pid, "analise", str(r.get("reason", ""))[:200])
        except Exception as exc:
            self._say(f"Reavaliacao de saida: {exc}", "error")
        finally:
            self._reviewing.discard(pid)
            self._rest()

    def _danger(self, pos, fresh):
        """Sinais de problema numa posicao aberta. Se houver um, o bot vende logo em vez de esperar pelo stop."""
        pid, now = pos["id"], time.time()
        pnl, liq, entry_liq = self.sim.pnl_pct(pos), pos["last_liq"], pos["entry_liq"]
        prev = self._prev.get(pid)
        self._prev[pid] = (pnl, liq)
        if prev and pnl <= prev[0] - config.DEX_CRASH_PCT:
            return "queda_brusca", f"de {prev[0]:+.0f}% para {pnl:+.0f}% num ciclo"
        if prev and prev[1] and liq and liq < prev[1] * (1 - config.DEX_LIQ_DROP_PCT / 100):
            return "liquidez", f"liquidez caiu de {prev[1]:,.0f} para {liq:,.0f} USD num ciclo (retirada?)"
        if entry_liq and liq and liq < entry_liq * config.DEX_LIQ_FLOOR_PCT / 100:
            return "liquidez", f"liquidez em {liq / entry_liq:.0%} da entrada"
        m5 = ((fresh or {}).get("tx") or {}).get("m5") or {}
        b, s = m5.get("buyers") or 0, m5.get("sellers") or 0
        if s >= 20 and s > 3 * b and ((fresh or {}).get("chg", {}).get("m5") or 0) < -5:
            return "pressao_venda", f"{s} vendas contra {b} compras nos ultimos 5 min e preco a cair"
        if now - self._chk.get(pid, 0) >= config.DEX_RECHECK_SEC:
            self._chk[pid] = now
            if self.live:
                from . import chain
                try:
                    info = chain.mint_info(pos["token"])
                    if info["mint_authority"] or info["freeze_authority"] or info["t22_problem"]:
                        return "perigo", "o token passou a ter autoridade de criar/congelar ou extensao perigosa"
                except Exception:
                    pass
            if pos["network"] == "solana":
                rc = data.rugcheck(pos["token"])
                bad = self._rc_bad(rc) if rc else None
                if bad:
                    return "perigo", f"RugCheck passou a apontar risco ({bad.split(':')[1]}, score {rc['score']})"
        return None

    def _check_exits(self, pos):
        pnl, peak = self.sim.pnl_pct(pos), pos["peak_pnl_pct"]
        held_h = (time.time() - pos["ts"]) / 3600
        if pos["entry_liq"] and pos["last_liq"] and pos["last_liq"] < 0.3 * pos["entry_liq"]:
            return self._exit(pos["id"], "liquidez", f"a liquidez caiu para {pos['last_liq'] / pos['entry_liq']:.0%} da entrada")
        stop = pos.get("stop_pct") or config.DEX_STOP_PCT
        if pnl <= -stop:
            return self._exit(pos["id"], "stop-loss", f"{pnl:+.1f}% (stop -{stop:.1f}%)")
        target = self._target(pos)
        if pnl >= target:
            return self._exit(pos["id"], "take-profit", f"{pnl:+.0f}% (alvo +{target:.0f}%)")
        # O trailing arma a meio do caminho para o alvo, para um alvo de 30% nao ficar sem protecao de lucro
        trail = min(config.DEX_TRAIL_PCT, max(6.0, target * 0.5))   # alvos curtos guardam o lucro com folga menor
        if peak >= max(8.0, min(config.DEX_TRAIL_ACTIVATE_PCT, target * 0.5)) and (1 + pnl / 100) <= (1 + peak / 100) * (1 - trail / 100):
            return self._exit(pos["id"], "trailing", f"maximo {peak:+.0f}%, agora {pnl:+.0f}%")
        if held_h >= config.DEX_MAX_HOLD_H:
            return self._exit(pos["id"], "tempo", f"{held_h:.1f}h em carteira, {pnl:+.0f}%")

    def _exit(self, pos_id, kind, detail):
        with self._exit_lock:
            return self._exit_locked(pos_id, kind, detail)

    def _exit_locked(self, pos_id, kind, detail):
        proceeds = sig = None
        if self.live:
            pos = self.sim.s["positions"].get(pos_id)
            if not pos:
                return
            try:
                res = self.live.sell(pos["token"], urgent=kind in URGENT)
                if res.get("dry"):
                    sim_txt = "OK" if res["sim_ok"] else "FALHOU: " + str(res["sim_err"])
                    self._say(f"[DRY-RUN] venda de {pos['name']} ({kind}): receberia ~{res['usd']:.2f} USD, simulacao {sim_txt}. Nada enviado.", "sell")
                    return
                proceeds, sig = res["usd"], res.get("sig")
            except Exception as exc:
                if kind == "rug" and pos["miss"] >= 6:
                    proceeds = 0.0   # a pool sumiu e a venda nao passa: dar como perdido
                else:
                    self._say(f"{pos['name']}: venda ({kind}) falhou, tento outra vez no proximo ciclo. {exc}", "error")
                    return
        rec = self.sim.sell(pos_id, kind, proceeds, detail=detail, sig=sig)
        if rec:
            self._say(f"VENDA {rec['name']} ({kind}: {detail}): {rec['pnl_usd']:+.2f} USD ({rec['pnl_pct']:+.0f}%)", "sell" if rec["pnl_usd"] > 0 else "alert")

    def sell_one(self, pos_id):
        """Venda manual de uma so posicao. Devolve (vendida, mensagem)."""
        pos = self.sim.s["positions"].get(pos_id)
        if not pos:
            return False, "Posicao ja nao existe."
        self._exit(pos_id, "manual", "venda manual")
        if pos_id in self.sim.s["positions"]:
            return False, "Nao vendeu (dry-run ou erro). Ver o registo."
        return True, f"{pos['name']} vendida."

    # ---------- vista para a interface ----------
    def status(self):
        s = self.sim.s
        positions = []
        for p in s["positions"].values():
            nv = net_value(p["tokens"], p["last_price"], p["last_liq"])
            positions.append({"id": p["id"], "name": p["name"], "network": p["network"], "pool": p["pool"], "token": p["token"],
                              "entry_price": p["entry_price"], "price": p["last_price"], "sig": p.get("sig"), "reason": p.get("reason"),
                              "stop_price": self.sim.price_for_pnl(p, -(p.get("stop_pct") or config.DEX_STOP_PCT)),
                              "stop_pct": p.get("stop_pct") or config.DEX_STOP_PCT, "conviction": p.get("conviction"),
                              "target_price": self.sim.price_for_pnl(p, self._target(p)),
                              "cost": round(p["cost"], 2), "value": round(nv, 2),
                              "pnl_pct": round(self.sim.pnl_pct(p), 1), "peak_pct": round(p["peak_pnl_pct"], 1),
                              "held_min": round((time.time() - p["ts"]) / 60), "liq": p["last_liq"], "confidence": p["confidence"],
                              "target_pct": self._target(p),
                              "tokens": p["tokens"], "entry_ts": p["ts"], "entry_liq": p.get("entry_liq"), "real": bool(p.get("real")),
                              "buy_cost_usd": round(p["cost"] - p["tokens"] * p["entry_price"], 4),      # comissao + impacto pagos a comprar
                              "gross": round(p["tokens"] * p["last_price"], 4), "exit_cost": round(p["tokens"] * p["last_price"] - nv, 4)})  # o que custaria sair agora
        eq = self.sim.equity()
        return {"enabled": self.enabled, "activity": self.activity, "cash": round(s["cash"], 2), "equity": round(eq, 2), "start": s["start"],
                "pnl_usd": round(eq - s["start"], 2), "positions": positions, "max_positions": config.DEX_MAX_POSITIONS,
                "closed": [{k: v for k, v in r.items() if k != "features"} for r in reversed(s["closed"][-200:])], "stats": self.sim.stats(), "funnel": self.funnel, "last_scan": self.last_scan,
                "equity_curve": s["equity"][-300:], "log": list(self.log)[:120],
                "analysed": [{k: v for k, v in a.items() if k != "velas"} for a in list(self.analysed)[:150]], "scans": list(self.scans)[:40], "wallet": self._wallet_info(),
                "today": self._today(), "scan_sec": config.DEX_SCAN_SEC,
                "mode": "live" if self.live else "paper", "dry_run": bool(self.live and self.live.dry),
                "rules": {"size_min": config.DEX_MIN_SIZE_EUR, "size_max": config.DEX_MAX_SIZE_EUR, "eurusd": round(fx.eur_usd(), 4),
                          "tp_min": config.DEX_TP_MIN_PCT, "tp_max": config.DEX_TP_MAX_PCT, "wallet_use_pct": config.WALLET_USE_PCT, "budget_usd": round(config.WALLET_USE_PCT / 100 * eq, 2), "stop": config.DEX_STOP_PCT, "stop_min": config.DEX_STOP_MIN_PCT, "stop_max": config.DEX_STOP_MAX_PCT, "fee": config.DEX_FEE_PCT,
                          "min_liq": config.DEX_MIN_LIQ_USD, "max_hold_h": config.DEX_MAX_HOLD_H, "networks": self.networks}}
