import json

from openai import OpenAI

from . import config

# A API da xAI e compativel com o SDK da OpenAI
client = OpenAI(api_key=config.XAI_API_KEY, base_url="https://api.x.ai/v1") if config.XAI_API_KEY else None

SYSTEM = f"""Es um analista de trading de crypto. Recebes dados de mercado reais (preco, RSI, EMAs) e a carteira atual.
Responde APENAS com JSON neste formato:
{{"action": "buy" | "sell" | "hold", "symbol": "BTC/USDT", "usdt": <valor em USDT>, "confidence": <0 a 1>, "reason": "<2 a 4 frases em portugues>", "risks": "<principais riscos>"}}
Regras: so podes usar os simbolos {config.SYMBOLS}; o maximo por ordem e {config.MAX_ORDER_USDT} USDT; prefere "hold" quando o sinal for fraco; nunca prometas lucros."""


def analyse(snapshot, portfolio, question=""):
    if client is None:
        raise RuntimeError("XAI_API_KEY em falta. Copia .env.example para .env e preenche.")
    user = {"market": snapshot, "portfolio": portfolio, "question": question or "Devo agir agora?"}
    res = client.chat.completions.create(
        model=config.GROK_MODEL,
        messages=[{"role": "system", "content": SYSTEM}, {"role": "user", "content": json.dumps(user)}],
        response_format={"type": "json_object"},
    )
    return json.loads(res.choices[0].message.content)
