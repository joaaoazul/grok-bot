# Grok Trader

Bot de trading de crypto com decisões do Grok (xAI) e uma interface web em Flask.

- **Binance** (página `/`): analisa várias moedas, compra e vende sozinho, com stop-loss, trailing e limite de perda diária.
- **DEX** (página `/dex`): memecoins e altcoins na Solana e na Base. Por defeito é simulação com dinheiro virtual. Pode operar com dinheiro real na Solana via Jupiter (ver abaixo).

Nenhum resultado, simulado ou real, garante lucro. Memecoins perdem valor na maioria dos casos. Usa só dinheiro que aceitas perder.

## Instalar

Precisa de Python 3.10 ou superior.

```
git clone https://github.com/joaaoazul/grok-bot.git
cd grok-bot
python -m venv .venv
.venv\Scripts\activate        # Windows (em Linux/Mac: source .venv/bin/activate)
pip install -r requirements.txt
copy .env.example .env        # em Linux/Mac: cp .env.example .env
```

Abre o `.env` e preenche **as tuas** chaves:

- `XAI_API_KEY`: chave da xAI (https://console.x.ai).
- `BINANCE_API_KEY` e `BINANCE_API_SECRET`: só se fores usar a Binance. Sem chaves, o bot da Binance corre em modo `paper` (virtual).

Depois:

```
python app.py
```

e abre http://127.0.0.1:5000 (Binance) ou http://127.0.0.1:5000/dex (DEX).

Se o browser der **403** ou "sem autorização" em `localhost:5000`, a porta 5000 está ocupada por outro programa (no Mac é o AirPlay Receiver). Usa outra porta, por exemplo `PORT=5001 python app.py` (no Windows PowerShell: `$env:PORT=5001; python app.py`) e abre http://127.0.0.1:5001.

## Modos

| Variável | Valor | O que faz |
|---|---|---|
| `TRADING_MODE` | `paper` | Binance com dinheiro virtual (por defeito) |
| `DEX_MODE` | `paper` | DEX com dinheiro virtual (por defeito) |
| `DEX_MODE` | `live` | DEX com carteira real na Solana |

### DEX com dinheiro real

1. Cria uma conta **nova** só para o bot (por exemplo na Phantom, com "Add account"). Nunca uses a conta onde tens o resto dos fundos.
2. Exporta a chave privada dessa conta e põe-na em `DEX_WALLET_KEY` no `.env`. Nunca a partilhes nem a coloques no git.
3. Envia uma quantia pequena de SOL para essa conta (por exemplo 0,2 a 0,3).
4. Começa em teste: `DEX_MODE=live`, `DEX_LIVE_DRY_RUN=true`, `DEX_LIVE_ARMED=false`. O bot cota e simula as transações, mas não envia nada.
5. Quando a simulação passar, `DEX_LIVE_DRY_RUN=false` e `DEX_LIVE_ARMED=true` passam a usar dinheiro de verdade. Define `DEX_MIN_SIZE_EUR` e `DEX_MAX_SIZE_EUR` pequenos no início (o orçamento é 95% do saldo da carteira).

O botão "Pânico" da página `/dex` vende tudo e para. Um ficheiro `data/KILL` bloqueia novas compras.

## Interface

- **Vender cada posição**: botões por posição (Binance: 25%, 50%, tudo; DEX: posição inteira), sempre com confirmação. Com `DEX_MODE=live` e `DEX_LIVE_ARMED=true` vende de verdade.
- **Filtros e ordenação** nas tabelas (guardados no browser): moeda, resultado, rede, tipo de saída, período e pesquisa. Clica num cabeçalho para ordenar.
- **Gráficos**: na Binance as velas atualizam a cada negócio; na DEX escolhes o intervalo (1m, 5m, 15m, 1h, 4h, 1d). As velas de 4h e 1d podem demorar quando a GeckoTerminal limita os pedidos.
- **Detalhe de cada operação**: clica numa posição ou numa linha de "Operações" para ver a quantidade, as comissões e o impacto, o resultado bruto e líquido, o motivo da saída e as transações.
- **Bit, a mascote**: mostra o que o bot está a fazer (dorme com o bot parado, passeia e procura, pensa enquanto espera pelo Grok, reage a compras e vendas). Clica nela para ver um resumo, arrasta-a para mudar de sítio, `⇄` pára o passeio e `×` oculta-a. As imagens estão em `static/mascot/` e podem ser trocadas por outras com o mesmo nome.

## Entrada por volume e stop por posição (DEX)

O Grok recebe os sinais das janelas de 5 min e de 1 h do DexScreener: volume contra o ritmo da hora, pressão de compra, preço esticado e distribuição (volume alto com vendas a dominar). Entra com mais vontade quando há volume de compra muito grande, e não persegue preços já esticados.

Cada compra tem o seu stop: o Grok propõe e o código limita-o pela convicção (confiança, tamanho da ordem e força do volume). Convicção baixa fica entre 5% e 10%, e só a máxima chega a 15%. Os limites estão no `.env.example` (`DEX_STOP_*`). **Muda o comportamento de compra e de saída**, por isso convém testar em `paper` ou em dry-run antes de usar dinheiro real.

## Reserva para taxas

O bot só usa **95% da carteira** (`WALLET_USE_PCT`, na Binance e na DEX). Os outros 5% ficam livres para taxas da rede e outros custos. Na DEX o **orçamento é 95% do saldo da carteira** (saldo de SOL mais o valor das posições abertas), e acompanha o saldo real: já não há um orçamento fixo (`DEX_BUDGET_EUR` foi retirado). Em modo real a caixa é lida da carteira a cada ciclo, já sem as taxas pagas. Se não conseguir ler o saldo, não compra. O que continua a limitar o risco é o tamanho de cada compra (`DEX_MAX_SIZE_EUR`), o número máximo de posições (`DEX_MAX_POSITIONS`) e o limite de perda diária (`DEX_DAILY_LOSS_EUR`).

Isto afeta o tamanho das ordens: com uma carteira de 5€ só se podem gastar 4,75€, por isso `DEX_MIN_SIZE_EUR` tem de ser 4,75 ou menos, senão o bot nunca compra (e avisa no registo).

## Segurança

- O `.env` e a pasta `data/` não vão para o git. Não os partilhes.
- Se uma chave for exposta, apaga-a no serviço de origem e cria outra.
- O RPC público da Solana é lento e falha. Para uso a sério, define `DEX_RPC_URL` com um RPC próprio.

## Estrutura

```
app.py            servidor Flask e rotas da API
bot/              lógica do bot da Binance (broker, risco, scanner, journal)
bot/dex/          bot de DEX (dados, simulação, estratégia, sinais de volume, execução real)
templates/ static/  interface web (theme.css, mascot.js, static/mascot/)
```
