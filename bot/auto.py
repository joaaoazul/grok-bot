"""Modo automatico: loop em background que analisa, compra, vende e aplica stop-loss e perda diaria."""
import threading
import time
from collections import deque
from datetime import datetime

from . import analyst, config, ledger, market, risk, trader


class AutoTrader:
    def __init__(self, broker):
        self.broker = broker
        self.log = deque(maxlen=100)
        self.enabled = False
        self.halted_day = None
        self.last_tick = None
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
        self._say(f"Modo automatico ligado ({config.MODE}, a cada {config.AUTO_INTERVAL_SEC}s).", "system")

    def stop(self):
        self.enabled = False
        self._stop.set()
        self._say("Modo automatico desligado.", "system")

    def status(self):
        return {"enabled": self.enabled, "interval": config.AUTO_INTERVAL_SEC, "halted": self.halted_day == str(datetime.now().date()),
                "last_tick": self.last_tick, "log": list(self.log)}

    def _run(self):
        while not self._stop.is_set():
            try:
                self._tick()
            except Exception as exc:
                self._say(f"Erro no ciclo: {exc}", "error")
            self.last_tick = datetime.now().strftime("%H:%M:%S")
            self._stop.wait(config.AUTO_INTERVAL_SEC)

    def _tick(self):
        today = str(datetime.now().date())
        if self.halted_day == today:
            return

        # 1. Perda diaria: fecha tudo e pausa ate amanha
        loss = ledger.daily_loss(self.broker)
        if loss >= config.MAX_DAILY_LOSS_USDT:
            self._say(f"Perda diaria de {loss:.2f} USDT atingiu o limite ({config.MAX_DAILY_LOSS_USDT}). A fechar tudo e a pausar ate amanha.", "alert")
            for symbol in config.SYMBOLS:
                self._close(symbol, "limite de perda diaria")
            self.halted_day = today
            return

        for symbol in config.SYMBOLS:
            if not self.enabled:
                return
            try:
                self._handle(symbol)
            except Exception as exc:
                self._say(f"{symbol}: {exc}", "error")

    def _close(self, symbol, why):
        res = trader.close_position(self.broker, symbol)
        if res:
            self._say(f"VENDA {symbol} ({why}): {res['qty']:.6f} a {res['price']:.2f}, PnL {res['pnl']:+.2f} USDT.", "sell")

    def _handle(self, symbol):
        base = symbol.split("/")[0]
        held = self.broker.portfolio()["positions"].get(base, 0.0) > 0
        px = market.price(symbol)
        ent = ledger.entry(symbol) if held else None

        # 2. Stop-loss e take-profit sao deterministicos: nao dependem do Grok
        if ent:
            pnl_pct = (px / ent[0] - 1) * 100
            if pnl_pct <= -config.STOP_LOSS_PCT:
                return self._close(symbol, f"stop-loss {pnl_pct:.1f}%")
            if pnl_pct >= config.TAKE_PROFIT_PCT:
                return self._close(symbol, f"take-profit +{pnl_pct:.1f}%")

        # 3. Cooldown para nao entrar e sair em loop
        since = ledger.seconds_since_trade(symbol)
        if since is not None and since < config.COOLDOWN_SEC:
            return

        # 4. Decisao do Grok, filtrada pelo modulo de risco
        position = f"Tens posicao em {base} com entrada a {ent[0]:.2f}." if ent else f"Sem posicao em {base}."
        proposal = analyst.analyse(market.snapshot(symbol), self.broker.portfolio(), f"Modo automatico. {position} Decide agora.")
        action = proposal.get("action")
        conf = float(proposal.get("confidence") or 0)
        proposal["symbol"] = symbol  # so decide sobre o par que foi analisado

        if action == "hold":
            self._say(f"{symbol}: hold ({conf:.0%}). {proposal.get('reason', '')}")
            return
        if action == "buy" and conf < config.AUTO_MIN_CONFIDENCE:
            self._say(f"{symbol}: Grok quis comprar mas confianca {conf:.0%} < {config.AUTO_MIN_CONFIDENCE:.0%}. Ignorado.")
            return
        if action == "sell" and not held:
            self._say(f"{symbol}: Grok quis vender sem posicao. Ignorado.")
            return

        order, blocked = risk.validate(proposal, self.broker)
        if order is None:
            self._say(f"{symbol}: {action} bloqueado. {blocked}")
            return
        res = trader.execute(self.broker, order["action"], symbol, order["usdt"])
        pnl = f", PnL {res['pnl']:+.2f}" if order["action"] == "sell" else ""
        self._say(f"{order['action'].upper()} {symbol}: {res['usdt']} USDT a {res['price']:.2f}{pnl}. {proposal.get('reason', '')}", order["action"])
