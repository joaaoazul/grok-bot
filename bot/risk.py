from . import config, ledger, scanner


def validate(proposal, broker):
    """Devolve (ordem_ajustada, None) ou (None, motivo). Corre sempre antes de enviar qualquer ordem."""
    side = proposal.get("action")
    symbol = proposal.get("symbol")
    if side not in ("buy", "sell"):
        return None, "Sem ordem (hold)."
    held = broker.portfolio()["positions"].get(str(symbol).split("/")[0], 0.0) > 0
    # Vender o que ja se tem e sempre permitido, mesmo que a moeda ja nao esteja no scanner
    if not scanner.is_allowed(symbol) and not (side == "sell" and held):
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
        exposure = ledger.exposure(broker)
        room = config.WALLET_USE_PCT / 100 * ledger.equity(broker) - exposure      # o resto da carteira fica livre para taxas
        usdt = min(usdt, broker.balance_usdt(), config.MAX_EXPOSURE_USDT - exposure, room)
        if usdt < 5:
            return None, f"Sem saldo, limite de exposicao total ou reserva de {100 - config.WALLET_USE_PCT:g}% da carteira atingidos."
    return {"action": side, "symbol": symbol, "usdt": round(usdt, 2)}, None
