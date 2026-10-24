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
5. Quando a simulação passar, `DEX_LIVE_DRY_RUN=false` e `DEX_LIVE_ARMED=true` passam a usar dinheiro de verdade. Define `DEX_BUDGET_EUR`, `DEX_MIN_SIZE_EUR` e `DEX_MAX_SIZE_EUR` pequenos no início.

O botão "Pânico" da página `/dex` vende tudo e para. Um ficheiro `data/KILL` bloqueia novas compras.

## Segurança

- O `.env` e a pasta `data/` não vão para o git. Não os partilhes.
- Se uma chave for exposta, apaga-a no serviço de origem e cria outra.
- O RPC público da Solana é lento e falha. Para uso a sério, define `DEX_RPC_URL` com um RPC próprio.

## Estrutura

```
app.py            servidor Flask e rotas da API
bot/              lógica do bot da Binance (broker, risco, scanner, journal)
bot/dex/          bot de DEX (dados, simulação, estratégia, execução real)
templates/ static/  interface web
```
