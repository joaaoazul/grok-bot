"""Sinais de volume e de pressao de compra a partir das janelas de 5 min e 1 h do DexScreener, e a regra do stop por posicao.

Tudo aqui e calculo puro, sem rede, para poder ser testado. So ha contagens de transacoes (compras e vendas), nao o volume de
compra em dolares: a "pressao de compra" e a fatia de transacoes que sao compras e o volume comprado e uma estimativa."""
from .. import config


def _f(x):
    try:
        return float(x or 0)
    except (TypeError, ValueError):
        return 0.0


def _clamp(x, lo=0.0, hi=1.0):
    return max(lo, min(hi, x))


def _counts(tx):
    """(compras, vendas) de uma janela. A GeckoTerminal e o DexScreener usam chaves ligeiramente diferentes."""
    tx = tx or {}
    return _f(tx.get("buys") or tx.get("buyers")), _f(tx.get("sells") or tx.get("sellers"))


def compute(p):
    """Le as janelas m5 e h1 da pool `p` e devolve os racios, a forca de compra (0 a 1) e a classe."""
    vol, tx, chg = p.get("vol") or {}, p.get("tx") or {}, p.get("chg") or {}
    v5, v1, v24 = _f(vol.get("m5")), _f(vol.get("h1")), _f(vol.get("h24"))
    b5, s5 = _counts(tx.get("m5"))
    b1, s1 = _counts(tx.get("h1"))
    n5, n1 = b5 + s5, b1 + s1
    share5 = b5 / n5 if n5 else None
    share1 = b1 / n1 if n1 else None
    ratio5 = v5 / (v1 / 12) if v1 > 0 else None            # ultimos 5 min contra o ritmo medio de 5 min da ultima hora
    ratio1 = v1 / (v24 / 24) if v24 > 0 else None          # ultima hora contra o ritmo medio horario das 24 h
    c5, c1 = chg.get("m5"), chg.get("h1")
    c5, c1 = (_f(c5) if c5 is not None else None), (_f(c1) if c1 is not None else None)

    accel5 = _clamp(((ratio5 or 1) - 1) / 3)               # 4 vezes o ritmo da hora = maximo
    accel1 = _clamp(((ratio1 or 1) - 1) / 3)
    pres5 = _clamp(((share5 if share5 is not None else 0.5) - 0.5) / 0.3)    # 80% de compras = maximo
    pres1 = _clamp(((share1 if share1 is not None else 0.5) - 0.5) / 0.3)
    forca = 0.3 * accel5 + 0.2 * accel1 + 0.3 * pres5 + 0.2 * pres1
    forca *= min(1.0, n5 / 15)                              # poucas transacoes em 5 min: o racio nao merece confianca

    esticado = (c5 is not None and c5 > config.DEX_SURGE_MAX_M5_PCT) or (c1 is not None and c1 > config.DEX_SURGE_MAX_H1_PCT)
    distribuicao = (ratio5 or 0) >= 2 and share5 is not None and share5 < 0.45     # volume alto mas a vender: saida de quem ja comprou
    if esticado:
        forca *= 0.5                                        # o preco ja correu: seria perseguir
    if c5 is not None and c5 < -3:
        forca *= 0.5                                        # a cair agora, mesmo com volume
    if distribuicao:
        forca = min(forca, 0.15)
    classe = "distribuicao" if distribuicao else "muito_forte" if forca >= 0.7 else "forte" if forca >= 0.5 else "moderada" if forca >= 0.3 else "fraca"

    r = lambda x, d=2: None if x is None else round(x, d)
    return {
        "volume_5m_usd": round(v5), "volume_1h_usd": round(v1),
        "volume_5m_vs_ritmo_1h": r(ratio5), "volume_1h_vs_ritmo_24h": r(ratio1),
        "transacoes_5m": int(n5), "transacoes_1h": int(n1),
        "pressao_compra_5m": r(share5), "pressao_compra_1h": r(share1),
        "compra_liquida_5m_usd_estimada": round(v5 * (2 * share5 - 1)) if share5 is not None else None,
        "var_5m_pct": c5, "var_1h_pct": c1,
        "esticado": esticado, "forca_compra": round(forca, 2), "classe": classe,
    }


def surge(p):
    """So a forca de compra (0 a 1), para ordenar candidatas."""
    return compute(p)["forca_compra"]


def conviction(conf, size_eur, lo_eur, hi_eur, forca):
    """Conviccao (0 a 1) = confianca do Grok, tamanho da ordem dentro do intervalo permitido e forca do volume de compra.
    Se o intervalo de tamanhos e minusculo (ex: orcamento quase igual ao minimo), o tamanho nao distingue nada e sai da conta."""
    floor = config.DEX_MIN_CONF
    c = _clamp((conf - floor) / (1 - floor)) if conf is not None else 0.0
    if hi_eur - lo_eur >= 0.25 * lo_eur:
        s = _clamp((size_eur - lo_eur) / (hi_eur - lo_eur))
        return round(0.4 * c + 0.3 * s + 0.3 * forca, 3)
    return round(0.55 * c + 0.45 * forca, 3)


def stop_limits(conv):
    """(minimo, teto) do stop em %. Conviccao baixa nunca passa dos 10%; so a conviccao maxima chega ao teto."""
    cap = config.DEX_STOP_SMALL_MAX_PCT + _clamp(conv) * (config.DEX_STOP_MAX_PCT - config.DEX_STOP_SMALL_MAX_PCT)
    return config.DEX_STOP_MIN_PCT, round(cap, 1)


def stop_pct(proposed, conv):
    """Stop final: o que o Grok propoe, limitado ao que a conviccao permite. Sem proposta, o codigo calcula-o."""
    lo, cap = stop_limits(conv)
    value = proposed if proposed and proposed > 0 else lo + _clamp(conv) * (cap - lo)
    return round(min(max(value, lo), cap), 1)
