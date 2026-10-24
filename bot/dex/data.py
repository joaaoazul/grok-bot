"""Dados de DEX via GeckoTerminal (API publica, sem chave, ~30 pedidos por minuto)."""
import threading
import time
from datetime import datetime

import requests

G = "https://api.geckoterminal.com/api/v2"
_HEADERS = {"Accept": "application/json;version=20230302"}
_MIN_GAP = 3.0  # segundos entre pedidos: o limite gratuito e partilhado por IP e 2,2 s chegou a dar 429
_lock = threading.Lock()
_last = [0.0]


def _get(path, **params):
    with _lock:
        wait = _MIN_GAP - (time.time() - _last[0])
        if wait > 0:
            time.sleep(wait)
        _last[0] = time.time()
    for attempt in range(4):
        r = requests.get(G + path, headers=_HEADERS, params=params, timeout=20)
        if r.status_code == 429:
            time.sleep(8 * (attempt + 1))
            continue
        r.raise_for_status()
        return r.json()
    raise RuntimeError("GeckoTerminal: limite de pedidos atingido")


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _pool(p):
    a, rel = p["attributes"], p["relationships"]
    network = p["id"].split("_", 1)[0]
    created = datetime.fromisoformat(a["pool_created_at"].replace("Z", "+00:00")).timestamp()
    return {
        "id": f"{network}:{a['address']}", "network": network, "pool": a["address"],
        "token": rel["base_token"]["data"]["id"].split("_", 1)[1],
        "name": a["name"], "dex": ((rel.get("dex") or {}).get("data") or {}).get("id"),
        "created": created, "age_min": (time.time() - created) / 60,
        "price": _f(a["base_token_price_usd"]), "liq": _f(a.get("reserve_in_usd")), "fdv": _f(a.get("fdv_usd")),
        "vol": {k: _f(a["volume_usd"].get(k)) for k in ("m5", "h1", "h24")},
        "tx": {k: a["transactions"].get(k) for k in ("m5", "h1", "h24")},
        "chg": {k: _f(a["price_change_percentage"].get(k)) for k in ("m5", "h1", "h6", "h24")},
    }


def new_pools(network):
    return [_pool(p) for p in _get(f"/networks/{network}/new_pools")["data"]]


def trending_pools(network):
    return [_pool(p) for p in _get(f"/networks/{network}/trending_pools")["data"]]


def pools_multi(network, addresses):
    """Atualiza ate 30 pools de uma vez."""
    out = []
    for i in range(0, len(addresses), 30):
        out += [_pool(p) for p in _get(f"/networks/{network}/pools/multi/{','.join(addresses[i:i + 30])}")["data"]]
    return out


def token_info(network, token):
    a = _get(f"/networks/{network}/tokens/{token}/info")["data"]["attributes"]
    holders = a.get("holders") or {}
    return {
        "mint_authority": a.get("mint_authority"), "freeze_authority": a.get("freeze_authority"),
        "is_honeypot": a.get("is_honeypot"), "dev_holding_pct": _f(a.get("developer_holding_percentage")),
        "holders": holders.get("count"), "top10_pct": _f(((holders.get("distribution_percentage") or {}).get("top_10"))),
        "gt_score": _f(a.get("gt_score")), "has_socials": bool(a.get("twitter_handle") or a.get("telegram_handle") or a.get("websites")),
        "launchpad_progress": (a.get("launchpad_details") or {}).get("graduation_percentage"),
    }


def candles(network, pool, limit=60):
    """Velas de 1 minuto, da mais antiga para a mais recente: [t, o, h, l, c, v]."""
    rows = _get(f"/networks/{network}/pools/{pool}/ohlcv/minute", aggregate=1, limit=limit)["data"]["attributes"]["ohlcv_list"]
    return sorted(rows, key=lambda r: r[0])


# ---------- DexScreener (API publica, sem chave; ~300 pedidos/min nos pares, 60/min nos perfis) ----------
DS = "https://api.dexscreener.com"


def _ds(path):
    for attempt in range(3):
        r = requests.get(DS + path, timeout=15)
        if r.status_code == 429:
            time.sleep(5 * (attempt + 1))
            continue
        r.raise_for_status()
        return r.json()
    raise RuntimeError("DexScreener: limite de pedidos atingido")


def _ds_pool(p):
    """Converte um par do DexScreener para o mesmo formato das pools da GeckoTerminal. Aqui buyers/sellers
    sao contagens de transacoes (a API nao da compradores unicos)."""
    network, tx = p["chainId"], p.get("txns") or {}
    created = (p.get("pairCreatedAt") or 0) / 1000
    vol, chg = p.get("volume") or {}, p.get("priceChange") or {}
    base, quote = p.get("baseToken") or {}, p.get("quoteToken") or {}
    return {
        "id": f"{network}:{p['pairAddress']}", "network": network, "pool": p["pairAddress"], "token": base.get("address"),
        "name": f"{base.get('symbol', '?')} / {quote.get('symbol', '?')}", "dex": p.get("dexId"),
        "created": created, "age_min": (time.time() - created) / 60 if created else 0,
        "price": _f(p.get("priceUsd")), "liq": _f((p.get("liquidity") or {}).get("usd")), "fdv": _f(p.get("fdv")),
        "vol": {k: _f(vol.get(k)) for k in ("m5", "h1", "h24")},
        "tx": {k: {"buys": (tx.get(k) or {}).get("buys"), "sells": (tx.get(k) or {}).get("sells"),
                   "buyers": (tx.get(k) or {}).get("buys"), "sellers": (tx.get(k) or {}).get("sells")} for k in ("m5", "h1", "h24")},
        "chg": {k: _f(chg.get(k)) for k in ("m5", "h1", "h6", "h24")},
    }


def ds_discover(network):
    """Tokens novos com perfil ou impulso (boost) no DexScreener, passados ao melhor par de cada um."""
    tokens = []
    for path in ("/token-profiles/latest/v1", "/token-boosts/latest/v1", "/token-boosts/top/v1"):
        try:
            tokens += [x["tokenAddress"] for x in _ds(path) if x.get("chainId") == network]
        except Exception:
            continue
    tokens = list(dict.fromkeys(tokens))[:60]
    best = {}
    for i in range(0, len(tokens), 30):
        for p in _ds(f"/tokens/v1/{network}/{','.join(tokens[i:i + 30])}"):
            pool = _ds_pool(p)
            if pool["token"] in tokens[i:i + 30] and pool["liq"] and pool["liq"] > (best.get(pool["token"], {}).get("liq") or 0):
                best[pool["token"]] = pool
    return list(best.values())


def ds_pools_multi(network, addresses):
    out = []
    for i in range(0, len(addresses), 30):
        res = _ds(f"/latest/dex/pairs/{network}/{','.join(addresses[i:i + 30])}")
        out += [_ds_pool(p) for p in (res.get("pairs") or [])]
    return out


def top_pools(network):
    """Pools mais negociadas nas ultimas 24h: apanha altcoins com mais historia, nao so pools novas."""
    return [_pool(p) for p in _get(f"/networks/{network}/pools", sort="h24_volume_usd_desc", page=1)["data"]]


def rugcheck(token):
    """Resumo de risco do RugCheck (so Solana, API publica). Devolve None se nao responder: nesse caso decidem os outros filtros."""
    try:
        r = requests.get(f"https://api.rugcheck.xyz/v1/tokens/{token}/report/summary", timeout=12)
        if r.status_code != 200:
            return None
        j = r.json()
    except (requests.RequestException, ValueError):
        return None
    risks = j.get("risks") or []
    return {"score": j.get("score_normalised"), "lp_bloqueada_pct": round(j.get("lpLockedPct") or 0),
            "riscos": [f"{x.get('name')} ({x.get('level')})" for x in risks][:8],
            "graves": [x.get("name", "") for x in risks if x.get("level") == "danger"]}
