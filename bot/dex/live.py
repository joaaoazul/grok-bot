"""Execucao real na Solana via Jupiter. Cada passo e uma barreira: se algo nao bate certo, levanta ChainError e NAO compra.
Usa so a carteira dedicada do bot (DEX_WALLET_KEY). Em dry-run cota e simula, mas nunca envia."""
import time

from .. import config
from . import chain
from .chain import ChainError


class LiveSolana:
    def __init__(self):
        self.kp = chain.keypair()
        self.owner = str(self.kp.pubkey())
        self.dry = config.DEX_LIVE_DRY_RUN or not config.DEX_LIVE_ARMED

    def wallet_usd(self):
        return chain.sol_balance(self.owner) / 1e9 * chain.sol_price_usd()

    # ---------- compra ----------
    def buy(self, mint, usd):
        info = chain.mint_info(mint)
        if info["mint_authority"]:
            raise ChainError("o dono ainda pode criar mais tokens")
        if info["freeze_authority"]:
            raise ChainError("o dono pode congelar carteiras")
        if info["t22_problem"]:
            raise ChainError(f"Token-2022 recusado: {info['t22_problem']}")
        price = chain.sol_price_usd()
        lamports = int(usd / price * 1e9)
        if chain.sol_balance(self.owner) - lamports < config.DEX_SOL_RESERVE * 1e9 and not self.dry:
            raise ChainError("SOL insuficiente (reserva para taxas)")
        q = chain.quote(chain.SOL, mint, lamports, config.DEX_BUY_SLIPPAGE_BPS)
        impact = abs(float(q.get("priceImpactPct") or 0)) * 100
        if impact > config.DEX_MAX_IMPACT_PCT:
            raise ChainError(f"impacto de {impact:.1f}% acima do limite")
        out = int(q["outAmount"])
        # Teste de venda: se comprar e vender logo ja perde muito, ha taxa escondida, honeypot ou liquidez falsa
        back = chain.quote(mint, chain.SOL, int(q["otherAmountThreshold"]), config.DEX_SELL_SLIPPAGE_BPS[0])
        loss = (1 - int(back["outAmount"]) / lamports) * 100
        if loss > config.DEX_MAX_ROUNDTRIP_LOSS_PCT:
            raise ChainError(f"comprar e vender logo perde {loss:.0f}% (limite {config.DEX_MAX_ROUNDTRIP_LOSS_PCT:.0f}%)")
        tx, last_valid = chain.build_swap(self.owner, q)
        if self.dry:
            ok, err = chain.simulate(self.kp, tx)
            return {"dry": True, "sim_ok": ok, "sim_err": err, "tokens": out / 10 ** info["decimals"], "impact": impact, "roundtrip_loss": loss}
        pre = chain.token_balance(self.owner, mint)
        sig = chain.send_and_confirm(self.kp, tx, last_valid)
        got = 0
        for _ in range(6):
            got = chain.token_balance(self.owner, mint) - pre
            if got > 0:
                break
            time.sleep(1.5)
        if got <= 0:
            raise ChainError(f"transacao {sig} confirmada mas sem tokens na carteira: verificar a mao")
        return {"dry": False, "tokens": got / 10 ** info["decimals"], "raw": got, "decimals": info["decimals"], "usd": lamports / 1e9 * price,
                "sig": sig, "impact": impact, "roundtrip_loss": loss}

    # ---------- venda ----------
    def sell(self, mint, urgent=False):
        raw = chain.token_balance(self.owner, mint)
        if raw <= 0:
            return {"gone": True, "usd": 0.0}
        pre = chain.sol_balance(self.owner)
        last = None
        slips = config.DEX_SELL_SLIPPAGE_BPS
        if urgent and len(slips) > 1:
            slips = slips[1:]   # perigo: nao perde tempo com a tentativa de slippage baixo
        for slip in slips:
            try:
                q = chain.quote(mint, chain.SOL, raw, slip)
                tx, last_valid = chain.build_swap(self.owner, q)
                if self.dry:
                    ok, err = chain.simulate(self.kp, tx)
                    return {"dry": True, "sim_ok": ok, "sim_err": err, "usd": int(q["outAmount"]) / 1e9 * chain.sol_price_usd()}
                sig = chain.send_and_confirm(self.kp, tx, last_valid)
                time.sleep(1.5)
                post = chain.sol_balance(self.owner)
                return {"dry": False, "usd": (post - pre) / 1e9 * chain.sol_price_usd(), "sig": sig, "slippage_bps": slip}
            except ChainError as exc:
                last = exc
        raise ChainError(f"venda falhou em todas as tentativas: {last}")
