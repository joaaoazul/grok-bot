from . import config, ledger


def validate(proposal, broker):
    """Devolve (ordem_ajustada, None) ou (None, motivo). Corre sempre antes de enviar qualquer ordem."""
    side = proposal.get("action")
    symbol = proposal.get("symbol")
    if side not in ("buy", "sell"):
        return None, "Sem ordem (hold)."
    if symbol not in config.SYMBOLS:
        return None, f"{symbol} nao esta na lista permitida."
    try:
        usdt = float(proposal.get("usdt", 0))
    except (TypeError, ValueError):
        return None, "Valor invalido."
    if usdt <= 0:
        return None, "Valor tem de ser positivo."
    usdt = min(usdt, config.MAX_ORDER_USDT)
    if side == "buy":
        if ledger.daily_loss(broker) >= config.MAX_DAILY_LOSS_USDT:
            return None, "Limite de perda diaria atingido: compras bloqueadas ate amanha."
        usdt = min(usdt, broker.balance_usdt(), config.MAX_EXPOSURE_USDT - ledger.exposure(broker))
        if usdt < 5:
            return None, "Sem saldo ou limite de exposicao total atingido."
    return {"action": side, "symbol": symbol, "usdt": round(usdt, 2)}, None
