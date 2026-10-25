"""Modo automatico: loop em background que analisa, compra, vende e aplica stop-loss e perda diaria."""
import threading
import time
from collections import deque
from datetime import datetime

from . import analyst, config, history, journal, ledger, market, risk, scanner, trader


class AutoTrader:
    def __init__(self, broker):
        self.broker = broker
        self.log = deque(maxlen=100)
        self.enabled = False
        self.halted_day = None
        self.last_tick = None
        self.cycles = 0
        self.activity = {"kind": "idle", "what": ""}   # idle | scan | think
        self.universe = []
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread = None

    def _say(self, msg, kind="info"):
        self.log.appendleft({"t": datetime.now().strftime("%H:%M:%S"), "kind": kind, "msg": msg})

    def start(self):
        if config.MODE == "live" and not config.TESTNET and not config.AUTO_LIVE_ALLOWED:
            raise RuntimeError("Modo automatico com dinheiro real esta bloqueado. Define AUTO_LIVE_ALLOWED=true no .env se tens a certeza.")
        if self.enabled:
            return
        self.enabled = True
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        threading.Thread(target=self._guard, daemon=True).start()
        self._say(f"Modo automatico ligado ({config.MODE}, ciclo de analise a cada {config.AUTO_INTERVAL_SEC}s, stops vigiados a cada {config.GUARD_INTERVAL_SEC}s).", "system")

    def stop(self):
        self.enabled = False
        self._stop.set()
        self._say("Modo automatico desligado.", "system")

    def status(self):
        return {"enabled": self.enabled, "interval": config.AUTO_INTERVAL_SEC, "halted": self.halted_day == str(datetime.now().date()),
                "last_tick": self.last_tick, "cycles": self.cycles, "activity": self.activity, "universe": self.universe, "log": list(self.log)}

    def _run(self):
        while not self._stop.is_set():
            self.activity = {"kind": "scan", "what": "a vigiar o mercado"}
            try:
                self._tick()
            except Exception as exc:
                self._say(f"Erro no ciclo: {exc}", "error")
            self.activity = {"kind": "idle", "what": ""}
            self.last_tick = datetime.now().strftime("%H:%M:%S")
            self.cycles += 1
            self._stop.wait(config.AUTO_INTERVAL_SEC)

    def _tick(self):
        today = str(datetime.now().date())
        if self.halted_day == today:
            return

        # 1. Perda diaria: fecha tudo e pausa ate amanha
        history.add(ledger.equity(self.broker), min_gap=120)
        if self._enforce_daily_loss():
            return

        try:
            lessons = journal.maybe_reflect(analyst.reflect)
            if lessons:
                self._say("Revisao do desempenho, licoes novas: " + " | ".join(lessons), "system")
        except Exception as exc:
            self._say(f"Revisao do desempenho falhou: {exc}", "error")

        self.universe = scanner.universe(self._held())
        self._say(f"A vigiar: {', '.join(s.split('/')[0] for s in self.universe)}")
        for symbol in self.universe:
            if not self.enabled:
                return
            try:
                self._handle(symbol)
            except Exception as exc:
                self._say(f"{symbol}: {exc}", "error")

    def _check_exits(self, symbol, px, ent):
        """Saidas automaticas. Devolve (fechou, ganho %, maximo desde a entrada)."""
        pnl_pct = (px / ent[0] - 1) * 100
        peak = ledger.update_peak(symbol, px)
        if pnl_pct <= -config.STOP_LOSS_PCT:
            self._close(symbol, f"stop-loss {pnl_pct:.1f}%")
        elif pnl_pct >= config.TAKE_PROFIT_PCT:
            self._close(symbol, f"take-profit +{pnl_pct:.1f}%")
        elif pnl_pct >= config.TRAILING_ACTIVATE_PCT and px <= peak * (1 - config.TRAILING_STOP_PCT / 100):
            self._close(symbol, f"trailing stop, recuou {(1 - px / peak) * 100:.1f}% do maximo, ganho {pnl_pct:+.1f}%")
        else:
            return False, pnl_pct, peak
        return True, pnl_pct, peak

    def _guard(self):
        """Vigilante rapido: stops e perda diaria a cada poucos segundos, sem chamar o Grok."""
        while not self._stop.wait(config.GUARD_INTERVAL_SEC):
            try:
                if self.halted_day == str(datetime.now().date()):
                    continue
                if self._enforce_daily_loss():
                    continue
                tickers = market.tickers(ttl=3)
                for symbol in self._held():
                    px = (tickers.get(symbol) or {}).get("last")
                    ent = ledger.entry(symbol)
                    if px and ent:
                        self._check_exits(symbol, px, ent)
            except Exception as exc:
                self._say(f"Vigilante: {exc}", "error")

    def _enforce_daily_loss(self):
        loss = ledger.daily_loss(self.broker)
        if loss < config.MAX_DAILY_LOSS_USDT:
            return False
        self._say(f"Perda diaria de {loss:.2f} USDT atingiu o limite ({config.MAX_DAILY_LOSS_USDT}). A fechar tudo e a pausar ate amanha.", "alert")
        for symbol in self._held():
            self._close(symbol, "limite de perda diaria")
        self.halted_day = str(datetime.now().date())
        return True

    def _held(self):
        tracked = ledger.tracked_symbols()
        return [f"{b}/USDT" for b, q in self.broker.portfolio()["positions"].items() if q > 0 and f"{b}/USDT" in tracked]

    def _close(self, symbol, why):
        with self._lock:  # o vigilante e o ciclo principal podem tentar fechar a mesma posicao
            res = trader.close_position(self.broker, symbol, why)
        if res:
            kind = next((k for k in ("stop-loss", "take-profit", "trailing", "limite") if why.startswith(k)), "analise")
            journal.close_entry(symbol, res["price"], kind)
            self._say(f"VENDA {symbol} ({why}): {res['qty']:.6f} a {res['price']:.2f}, PnL {res['pnl']:+.2f} USDT.", "sell")

    def _handle(self, symbol):
        base = symbol.split("/")[0]
        held = self.broker.portfolio()["positions"].get(base, 0.0) > 0
        px = market.price(symbol)
        ent = ledger.entry(symbol) if held else None
        pnl_pct = peak = None

        # 2. Stop-loss, take-profit e trailing sao deterministicos: nao dependem do Grok
        if ent:
            closed, pnl_pct, peak = self._check_exits(symbol, px, ent)
            if closed:
                return

        # 3. O cooldown so trava novas compras: posicoes abertas sao reavaliadas em todos os ciclos
        since = ledger.seconds_since_trade(symbol)
        if not held and since is not None and since < config.COOLDOWN_SEC:
            return

        # 4. Decisao do Grok, com o contexto completo da posicao para decidir quando realizar lucro
        if ent:
            position = (f"Tens posicao aberta em {base}: entrada {ent[0]:.6g}, preco atual {px:.6g}, resultado {pnl_pct:+.2f}%, "
                        f"maximo desde a entrada {peak:.6g} (recuou {(1 - px / peak) * 100:.1f}% do maximo). "
                        f"As comissoes custam cerca de 0,2% na ida e volta. Decide se vendes agora para realizar lucro ou se manténs.")
        elif held:
            position = f"Tens {base} na carteira mas sem preco de entrada registado."
        else:
            position = f"Sem posicao em {base}."
        snap = market.snapshot(symbol, config.AUTO_TIMEFRAME)
        self.activity = {"kind": "think", "what": f"a analisar {symbol} com o Grok"}
        try:
            proposal = analyst.analyse(snap, self.broker.portfolio(), f"Modo automatico agressivo. {position} Decide agora.",
                                       memory=journal.memory())
        finally:
            self.activity = {"kind": "scan", "what": "a vigiar o mercado"}
        action = proposal.get("action")
        conf = float(proposal.get("confidence") or 0)
        proposal["symbol"] = symbol  # so decide sobre o par que foi analisado

        if action == "hold":
            self._say(f"{symbol}: hold ({conf:.0%}). {proposal.get('reason', '')}")
            return
        # O limiar sobe sozinho se as faixas de confianca baixas estiverem a perder dinheiro (com amostra minima)
        min_conf = journal.min_confidence(config.AUTO_MIN_CONFIDENCE)
        if action == "buy" and conf < min_conf:
            raised = f" (subiu de {config.AUTO_MIN_CONFIDENCE:.0%} porque as faixas baixas perderam)" if min_conf > config.AUTO_MIN_CONFIDENCE else ""
            self._say(f"{symbol}: Grok quis comprar mas confianca {conf:.0%} < {min_conf:.0%}{raised}. Ignorado.")
            return
        if action == "sell" and not held:
            self._say(f"{symbol}: Grok quis vender sem posicao. Ignorado.")
            return
        if action == "buy" and held:
            self._say(f"{symbol}: ja tens posicao, nao reforca. A gerir a saida.")
            return

        if action == "sell":
            # Vende a posicao inteira (sem o teto por ordem), mas so se o lucro cobrir as comissoes.
            # Prejuizos sao tratados pelo stop-loss e pelo trailing, nao por ruido de analise.
            if ent and pnl_pct < config.MIN_SELL_PROFIT_PCT:
                self._say(f"{symbol}: Grok quis vender mas o resultado ({pnl_pct:+.2f}%) nao cobre as comissoes (minimo {config.MIN_SELL_PROFIT_PCT}%). Mantem.")
                return
            return self._close(symbol, f"Grok {conf:.0%}: {str(proposal.get('reason', ''))[:140]}")

        if action == "buy":
            # Aposta proporcional a confianca: entradas fracas ficam pequenas
            proposal["usdt"] = min(float(proposal.get("usdt") or 0), config.MAX_ORDER_USDT * conf)
        order, blocked = risk.validate(proposal, self.broker)
        if order is None:
            self._say(f"{symbol}: {action} bloqueado. {blocked}")
            return
        with self._lock:
            res = trader.execute(self.broker, order["action"], symbol, order["usdt"], str(proposal.get("reason", ""))[:160])
        journal.open_entry(symbol, snap, conf, str(proposal.get("reason", "")), res["price"])
        pnl = f", PnL {res['pnl']:+.2f}" if order["action"] == "sell" else ""
        self._say(f"{order['action'].upper()} {symbol}: {res['usdt']} USDT a {res['price']:.2f}{pnl}. {proposal.get('reason', '')}", order["action"])
