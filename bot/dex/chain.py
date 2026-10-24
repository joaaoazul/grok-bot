"""Ligacao a Solana (RPC) e a Jupiter. Sem estado: so pedidos e assinatura. A chave nunca e escrita em log."""
import base64
import json
import time

import requests

from .. import config

SOL = "So11111111111111111111111111111111111111112"
USDC = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
TOKEN_PROGRAM = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
TOKEN_2022 = "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"


class ChainError(Exception):
    pass


def _rpc(method, params):
    r = requests.post(config.DEX_RPC_URL, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params}, timeout=20)
    r.raise_for_status()
    j = r.json()
    if "error" in j:
        raise ChainError(f"{method}: {j['error'].get('message', j['error'])}")
    return j["result"]


def keypair():
    """Carteira dedicada do bot. Aceita a chave em base58 ou como lista JSON de 64 numeros."""
    from solders.keypair import Keypair
    raw = (config.DEX_WALLET_KEY or "").strip()
    if not raw:
        raise ChainError("DEX_WALLET_KEY em falta no .env")
    try:
        return Keypair.from_bytes(bytes(json.loads(raw))) if raw.startswith("[") else Keypair.from_base58_string(raw)
    except Exception:
        raise ChainError("DEX_WALLET_KEY invalida (nao mostro o valor)")


# ---------- leitura ----------
def sol_balance(owner):
    return _rpc("getBalance", [owner, {"commitment": "confirmed"}])["value"]  # lamports


def token_balance(owner, mint):
    """Saldo bruto (unidades inteiras) do token na carteira. 0 se nao tem conta."""
    # A rede so aceita um filtro de cada vez: por token apanha as contas dos dois programas (Token e Token-2022)
    res = _rpc("getTokenAccountsByOwner", [owner, {"mint": mint}, {"encoding": "jsonParsed", "commitment": "confirmed"}])
    return sum(int(acc["account"]["data"]["parsed"]["info"]["tokenAmount"]["amount"]) for acc in res["value"])


def mint_info(mint):
    """Dados on-chain do token: decimais e se o dono ainda pode criar ou congelar. Independente de sites terceiros."""
    res = _rpc("getAccountInfo", [mint, {"encoding": "jsonParsed", "commitment": "confirmed"}])["value"]
    if not res:
        raise ChainError("token inexistente on-chain")
    if not isinstance(res["data"], dict) or res["data"].get("parsed", {}).get("type") != "mint":
        raise ChainError("o endereco nao e um token")
    info = res["data"]["parsed"]["info"]
    exts = info.get("extensions") or []
    return {"decimals": int(info["decimals"]), "mint_authority": info.get("mintAuthority"), "freeze_authority": info.get("freezeAuthority"),
            "token_2022": res["owner"] == TOKEN_2022, "extensions": [e["extension"] for e in exts], "t22_problem": _t22_problem(exts)}


MAX_TRANSFER_FEE_BPS = 300   # taxa de transferencia maxima aceite (3%): paga-se em cada compra e venda


def _t22_problem(exts):
    """Token-2022 so e recusado por extensoes que dao poder ao dono sobre o teu saldo ou taxam a saida. As inofensivas (metadados, etc.) passam."""
    for e in exts:
        name, st = e["extension"], e.get("state") or {}
        if name == "permanentDelegate" and st.get("delegate"):
            return "o dono tem delegado permanente (pode tirar tokens da tua carteira)"
        if name == "transferHook" and st.get("programId"):
            return "transfer hook com programa proprio (codigo arbitrario em cada transferencia)"
        if name == "nonTransferable":
            return "token nao transferivel"
        if name == "pausableConfig":
            return "o dono pode pausar as transferencias"
        if name == "defaultAccountState" and str(st.get("state")).lower() == "frozen":
            return "contas novas nascem congeladas"
        if name == "transferFeeConfig":
            bps = max(((st.get(k) or {}).get("transferFeeBasisPoints") or 0) for k in ("newerTransferFee", "olderTransferFee"))
            if bps > MAX_TRANSFER_FEE_BPS:
                return f"taxa de transferencia de {bps / 100:.1f}% (limite {MAX_TRANSFER_FEE_BPS / 100:.0f}%)"
    return None


# ---------- Jupiter ----------
def _jup_headers():
    return {"x-api-key": config.JUPITER_API_KEY} if config.JUPITER_API_KEY else {}


def quote(in_mint, out_mint, amount, slippage_bps):
    r = requests.get(f"{config.JUPITER_URL}/quote", headers=_jup_headers(), timeout=15,
                     params={"inputMint": in_mint, "outputMint": out_mint, "amount": int(amount), "slippageBps": int(slippage_bps),
                             "restrictIntermediateTokens": "true"})
    if r.status_code != 200:
        raise ChainError(f"cotacao recusada ({r.status_code}): {r.text[:120]}")
    return r.json()


def sol_price_usd(_cache={}):
    if _cache.get("t", 0) > time.time() - 30:
        return _cache["p"]
    q = quote(SOL, USDC, 10**9, 50)
    _cache.update(t=time.time(), p=int(q["outAmount"]) / 1e6)
    return _cache["p"]


def build_swap(owner, quote_resp):
    r = requests.post(f"{config.JUPITER_URL}/swap", headers=_jup_headers(), timeout=20,
                      json={"quoteResponse": quote_resp, "userPublicKey": owner, "dynamicComputeUnitLimit": True,
                            "prioritizationFeeLamports": {"priorityLevelWithMaxLamports": {"maxLamports": config.DEX_PRIORITY_LAMPORTS, "priorityLevel": "high"}}})
    if r.status_code != 200:
        raise ChainError(f"swap recusado ({r.status_code}): {r.text[:120]}")
    j = r.json()
    return j["swapTransaction"], j.get("lastValidBlockHeight")


def _sign(kp, tx_b64):
    from solders.transaction import VersionedTransaction
    tx = VersionedTransaction.from_bytes(base64.b64decode(tx_b64))
    return VersionedTransaction(tx.message, [kp])


def simulate(kp, tx_b64):
    """Corre a transacao sem a enviar. Devolve (ok, erro)."""
    signed = _sign(kp, tx_b64)
    res = _rpc("simulateTransaction", [base64.b64encode(bytes(signed)).decode(), {"encoding": "base64", "commitment": "confirmed", "sigVerify": False}])
    err = res["value"].get("err")
    return err is None, (None if err is None else str(err)[:160])


def send_and_confirm(kp, tx_b64, last_valid_height=None, timeout=75):
    """Envia e espera. Devolve a assinatura se confirmada, senao levanta ChainError. So desiste depois de o blockhash expirar,
    porque antes disso a transacao ainda pode entrar e nao queremos tokens que o bot nao sabe que tem."""
    signed = _sign(kp, tx_b64)
    sig = _rpc("sendTransaction", [base64.b64encode(bytes(signed)).decode(), {"encoding": "base64", "skipPreflight": False, "maxRetries": 3, "preflightCommitment": "confirmed"}])
    t0 = time.time()
    while time.time() - t0 < timeout + 60:
        st = _rpc("getSignatureStatuses", [[sig], {"searchTransactionHistory": True}])["value"][0]
        if st:
            if st.get("err"):
                raise ChainError(f"transacao falhou on-chain: {str(st['err'])[:120]}")
            if st.get("confirmationStatus") in ("confirmed", "finalized"):
                return sig
        expired = time.time() - t0 > timeout and (last_valid_height is None or _rpc("getBlockHeight", [{"commitment": "confirmed"}]) > last_valid_height)
        if expired:
            raise ChainError("transacao nao confirmou e o blockhash expirou")
        time.sleep(1.5)
    raise ChainError("transacao nao confirmou a tempo")
