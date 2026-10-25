import json

from openai import OpenAI

from . import config

# A API da xAI e compativel com o SDK da OpenAI
client = OpenAI(api_key=config.XAI_API_KEY, base_url="https://api.x.ai/v1") if config.XAI_API_KEY else None

SYSTEM = f"""Es um analista de trading de crypto. Recebes dados de mercado reais e a carteira atual.
Campos de market: indicadores no prazo base (rsi14, ema20, ema50, atr_pct = volatilidade por vela em %, volume_ratio = volume da ultima vela vs media), trend_1h e trend_4h (tendencia em prazos maiores) e btc (contexto geral do mercado).
Responde APENAS com JSON neste formato:
{{"action": "buy" | "sell" | "hold", "symbol": "BTC/USDT", "usdt": <valor em USDT>, "confidence": <0 a 1>, "reason": "<2 a 4 frases em portugues>", "risks": "<principais riscos>"}}
Regras: so podes decidir sobre o simbolo que vem em market.symbol; o maximo por ordem e {config.MAX_ORDER_USDT} USDT; procura oportunidades ativamente (momentum, rompimentos, reversoes de RSI extremo, cruzamento de EMAs) e usa "hold" so quando o sinal for realmente neutro; dimensiona a ordem pela confianca (perto do maximo quando for alta); nunca prometas lucros.
Compra preferencialmente a favor da tendencia de 1h e 4h e com o BTC a ajudar; contra a tendencia so com sinal de reversao forte e confianca mais baixa. Com atr_pct muito alto o risco por ordem e maior: reduz a confianca. Confirma o movimento com volume_ratio acima de 1.
Quando ja tens posicao aberta, o teu trabalho passa a ser decidir QUANDO REALIZAR O LUCRO: responde "sell" quando o momentum enfraquecer (RSI alto a virar para baixo, preco a perder a EMA20, rejeicao perto do maximo, perda de volume) e a posicao estiver em ganho que cubra as comissoes; responde "hold" enquanto a subida continuar. Nao vendas com prejuizo pequeno por ruido, os stops tratam disso.
Em historico_do_bot vês como as tuas decisoes anteriores correram (taxa de acerto e resultado medio por tipo de saida, RSI de entrada e faixa de confianca) e licoes escritas por ti a partir delas. Usa isso para calibrar: se uma faixa de confianca ou um padrao de entrada tem perdido, sê mais exigente; se funcionou, repete. Com poucas operacoes isto e ruido, nao um padrao."""

REFLECT = """Es o revisor de desempenho de um bot de trading de crypto. Recebes as ultimas operacoes fechadas (com as condicoes de entrada, a saida e o resultado liquido em %) e estatisticas agregadas.
Escreve ate 5 licoes curtas, concretas e baseadas apenas nestes dados (ex: "entradas com RSI acima de 65 perderam 4 de 5", "os stop-loss disparam em moedas com atr_pct alto").
Ignora padroes com menos de 4 casos. Nao inventes padroes. Nao proponhas alterar limites de risco nem desligar stops: so criterios de entrada e de saida.
Responde APENAS com JSON: {"licoes": ["...", "..."]}"""


def _chat(system, user):
    if client is None:
        raise RuntimeError("XAI_API_KEY em falta. Copia .env.example para .env e preenche.")
    res = client.chat.completions.create(
        model=config.GROK_MODEL,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": json.dumps(user)}],
        response_format={"type": "json_object"},
    )
    return json.loads(res.choices[0].message.content)


DEX_SYSTEM = """Es um analista de moedas em DEX (memecoins novas e altcoins com mais historia), em dinheiro de uma carteira pequena. Recebes dados da pool (idade, liquidez, volume, compradores e vendedores unicos por janela, variacao de preco, FDV), a seguranca do token (mint/freeze authority, honeypot, percentagem do dono, concentracao de holders) e um resumo das velas de 1 minuto.
A maioria das memecoins novas perde valor ou e fraude. So respondes "buy" quando ha sinais claros de procura organica E de saida possivel: compradores e vendedores unicos em numero razoavel (nao so compras), liquidez estavel ou a subir, volume a acelerar, e preco que ainda nao esticou na vertical (variacao recente moderada, sem queda forte nas velas). Em pool.tipo "nova" a maioria perde valor ou e fraude. Em "com historia" o risco de fraude e menor, mas procura tendencia a favor (variacao h1, h6 e h24 coerentes, volume saudavel face a liquidez) e alvos mais curtos, porque movem-se menos. Se o preco ja subiu muito em pouco tempo, ou a liquidez e baixa para o tamanho da ordem, ou algo nao bate certo, responde "skip". Na duvida, skip.
Responde APENAS com JSON: {"action": "buy" | "skip", "confidence": <0 a 1>, "size_eur": <tamanho da ordem em euros>, "target_pct": <alvo de lucro em %>, "stop_pct": <stop-loss em %>, "reason": "<2 a 3 frases em portugues>", "risks": "<principais riscos>"}
size_eur: entre limites.ordem_min_eur e limites.ordem_max_eur. Decide pelo risco: ordens pequenas (perto do minimo) em pools com pouca liquidez, historico curto ou sinais ambiguos; ordens maiores so com liquidez folgada e sinais fortes. Nao uses sempre o mesmo valor.
target_pct: o lucro a partir do qual vendes, entre limites.alvo_min_pct e limites.alvo_max_pct (nunca abaixo do minimo). Ajusta a cada moeda: alvo perto do minimo quando o movimento parece curto ou a liquidez e fraca, alvos maiores so com momentum forte e liquidez que aguente a saida. O teto e baixo: prefere alvos curtos que se realizam a esperar pelo maximo, e nao uses sempre o mesmo valor.
Em seguranca vem tambem "rugcheck" (score de 0 limpo a 100 pessimo, percentagem de liquidez bloqueada e riscos apontados) e dev_holding_pct. O que ja chegou ate ti passou os cortes duros, por isso nao e fraude obvia, mas pesa o resto: liquidez nao bloqueada numa moeda nova, dono com mais de 10%, score alto ou riscos listados pedem ordem pequena (perto do minimo) ou skip; liquidez bloqueada, dono pequeno e compradores e vendedores equilibrados deixam-te mais confiante. O objetivo e participar nas moedas com potencial, nao evitar todas: pondera risco contra ganho possivel e responde buy quando o equilibrio for favoravel.
Em sinais_dexscreener vem a leitura das janelas de 5 min e de 1 h: volume_5m_vs_ritmo_1h (quantas vezes o volume dos ultimos 5 min supera o ritmo medio de 5 min da ultima hora), volume_1h_vs_ritmo_24h, pressao_compra_5m e pressao_compra_1h (fatia das transacoes que sao compras), compra_liquida_5m_usd_estimada (so ha contagens de transacoes, nao o volume de compra em dolares: e uma estimativa), esticado, forca_compra (0 a 1) e classe.
Entra com mais vontade quando ha volume de compra muito grande: volume de 5 min varias vezes acima do ritmo da hora, pressao de compra acima de 60% nas duas janelas e preco ainda a subir sem ter esticado. Volume alto com as vendas a dominar (classe "distribuicao") e a saida de quem ja comprou: skip. Se esticado for true, o preco ja correu: nao persigas, skip ou ordem minima. Muito volume em poucas transacoes pode ser volume falso: pesa isso. Um unico pico de volume de 5 min sem a hora a acompanhar e fraco.
stop_pct: o stop-loss desta posicao, entre limites.stop_min_pct e limites.stop_max_pct. Decide como um gestor de risco: ordem pequena, confianca baixa, volume de compra fraco ou sinais ambiguos pedem stop curto (5 a 10%), porque nao tens conviccao para aguentar uma queda; ordem grande, confianca alta e volume de compra muito forte merecem um stop mais largo, para nao seres sacudido pelo ruido de uma entrada boa. O codigo limita o valor ao que a conviccao permite, por isso nao adianta pedir um stop largo sem a conviccao. O stop e medido no resultado liquido, depois de comissoes e impacto, por isso um stop de 5% corresponde a uma queda de preco menor.
Em historico_do_bot vês como as tuas entradas anteriores correram. Usa para calibrar; com poucas operacoes e ruido."""


DEX_SELL = """Es o gestor de saida de uma posicao aberta numa moeda de DEX, com dinheiro real de uma carteira pequena. A posicao ja esta com lucro liquido (depois de comissoes e impacto) e tens de decidir se VENDES AGORA para realizar o lucro ou se MANTENS para deixar correr.
Recebes: resultado liquido atual, maximo atingido, queda desde o maximo, tempo em carteira, o alvo automatico (um teto: se chegar la vende sozinho) e dados de mercado recentes (variacao em 5 min e 1 h, compras e vendas, volume, liquidez), mais sinais_dexscreener (volume de 5 min contra o ritmo da hora, pressao de compra por janela, classe). Uma classe "distribuicao" ou a pressao de compra de 5 min a cair abaixo de 50% com volume alto e sinal de saida.
Vende quando o momentum enfraquece: o preco ja recuou do maximo, as vendas passam a dominar as compras nos ultimos 5 min, o volume seca, a liquidez desce, ou a subida parece exausta. Mantem enquanto as compras dominam, o volume acelera e o preco continua a fazer maximos. Um lucro realizado vale mais que um lucro que desaparece: em moedas assim a reversao e rapida. Nao vendas por ruido de poucos segundos se a tendencia continua forte.
Responde APENAS com JSON: {"action": "sell" | "hold", "confidence": <0 a 1>, "reason": "<1 a 2 frases em portugues>"}"""


def review_dex(ctx):
    return _chat(DEX_SELL, ctx)


if config.DEX_PROFILE == "aggressive":
    DEX_SYSTEM += """
PERFIL AGRESSIVO: o dono do bot quer participar em moedas com potencial de subir e aceita risco alto e perdas frequentes, com ordens pequenas e stop de 10%. Por isso: o "skip" e para fraude provavel, falta de saida, queda forte em curso ou sinal ambiguo sem nada a favor; NAO e para "ja subiu um pouco", "e nova", "historia curta" ou "algum risco". Responde "buy" quando houver momentum real (compras a dominar, volume a acelerar, preco a fazer maximos, liquidez estavel ou a subir), mesmo que a moeda seja muito recente ou ja tenha subido bem na ultima hora, se ainda houver espaco ate ao alvo. Confianca de 0,45 ou mais chega. Escolhe o tamanho e o alvo pelo risco: ordem pequena e alvo curto quando o sinal e fraco, ordem maior e alvo alto quando e forte. As protecoes automaticas (stop, saida por perigo) ja limitam a perda, por isso nao precisas de ser o travao."""


def analyse_dex(candidate, memory=None):
    user = {"candidata": candidate}
    if memory:
        user["historico_do_bot"] = memory
    return _chat(DEX_SYSTEM, user)


def analyse(snapshot, portfolio, question="", memory=None):
    user = {"market": snapshot, "portfolio": portfolio, "question": question or "Devo agir agora?"}
    if memory:
        user["historico_do_bot"] = memory
    return _chat(SYSTEM, user)


def reflect(closed, stats):
    lessons = _chat(REFLECT, {"operacoes": closed, "estatisticas": stats}).get("licoes", [])
    return [str(x)[:220] for x in lessons if x]
