import os

from dotenv import load_dotenv

load_dotenv()

# Onde ficam carteira virtual, custos de entrada e historico. Os testes apontam para outra pasta.
DATA_DIR = os.getenv("DATA_DIR") or os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")

XAI_API_KEY = os.getenv("XAI_API_KEY")
GROK_MODEL = os.getenv("GROK_MODEL", "grok-4.5")

MODE = os.getenv("TRADING_MODE", "paper").lower()
TESTNET = os.getenv("BINANCE_TESTNET", "true").lower() == "true"
BINANCE_KEY = os.getenv("BINANCE_API_KEY")
BINANCE_SECRET = os.getenv("BINANCE_API_SECRET")

SYMBOLS = [s.strip() for s in os.getenv("SYMBOLS", "BTC/USDT,ETH/USDT,SOL/USDT").split(",") if s.strip()]
MAX_ORDER_USDT = float(os.getenv("MAX_ORDER_USDT", "50"))
MAX_DAILY_LOSS_USDT = float(os.getenv("MAX_DAILY_LOSS_USDT", "100"))
PAPER_START_USDT = float(os.getenv("PAPER_START_USDT", "1000"))
MAX_EXPOSURE_USDT = float(os.getenv("MAX_EXPOSURE_USDT", "200"))

# Modo automatico
AUTO_INTERVAL_SEC = int(os.getenv("AUTO_INTERVAL_SEC", "900"))
AUTO_MIN_CONFIDENCE = float(os.getenv("AUTO_MIN_CONFIDENCE", "0.7"))
STOP_LOSS_PCT = float(os.getenv("STOP_LOSS_PCT", "5"))
TAKE_PROFIT_PCT = float(os.getenv("TAKE_PROFIT_PCT", "10"))
COOLDOWN_SEC = int(os.getenv("COOLDOWN_SEC", "3600"))
# Scanner: em vez de so SYMBOLS, procura as moedas USDT com mais momentum e liquidez
SCAN_ENABLED = os.getenv("SCAN_ENABLED", "true").lower() == "true"
SCAN_TOP_N = int(os.getenv("SCAN_TOP_N", "6"))
SCAN_MIN_VOLUME_USDT = float(os.getenv("SCAN_MIN_VOLUME_USDT", "20000000"))
SCAN_MAX_CHANGE_PCT = float(os.getenv("SCAN_MAX_CHANGE_PCT", "30"))
SCAN_REFRESH_SEC = int(os.getenv("SCAN_REFRESH_SEC", "600"))
# Venda por analise do Grok so com lucro acima disto (comissoes ida e volta ~0,2%)
MIN_SELL_PROFIT_PCT = float(os.getenv("MIN_SELL_PROFIT_PCT", "0.4"))
# Memecoins em DEX: SO simulacao com dinheiro virtual (nao ha carteira real nem chaves)
DEX_NETWORKS = [n.strip() for n in os.getenv("DEX_NETWORKS", "solana,base").split(",") if n.strip()]
DEX_START_USD = float(os.getenv("DEX_START_USD", "500"))
# Tamanho de cada compra: o Grok propoe, o codigo limita a [MIN, MAX] euros (e a 0,5% da liquidez da pool)
DEX_MIN_SIZE_EUR = float(os.getenv("DEX_MIN_SIZE_EUR", "1"))
DEX_MAX_SIZE_EUR = float(os.getenv("DEX_MAX_SIZE_EUR") or os.getenv("DEX_MAX_SIZE") or "25")   # aceita o nome curto
DEX_EURUSD = float(os.getenv("DEX_EURUSD", "1.10"))               # so se a taxa online falhar
DEX_MAX_POSITIONS = int(os.getenv("DEX_MAX_POSITIONS", "5"))
DEX_FEE_PCT = float(os.getenv("DEX_FEE_PCT", "1.0"))               # comissao por lado (conservadora)
DEX_MIN_LIQ_USD = float(os.getenv("DEX_MIN_LIQ_USD", "10000"))
DEX_MIN_AGE_MIN = float(os.getenv("DEX_MIN_AGE_MIN", "12"))         # espera que a pool "sobreviva" um pouco
DEX_MAX_AGE_H = float(os.getenv("DEX_MAX_AGE_H", "8760"))           # 1 ano: inclui altcoins com historia, nao so memecoins novas
DEX_ESTABLISHED = os.getenv("DEX_ESTABLISHED", "true").lower() == "true"   # procura tambem as pools mais negociadas
DEX_OLD_AFTER_H = float(os.getenv("DEX_OLD_AFTER_H", "48"))        # a partir daqui a moeda conta como "com historia"
DEX_MIN_LIQ_OLD_USD = float(os.getenv("DEX_MIN_LIQ_OLD_USD", "100000"))   # moedas com historia pedem mais liquidez
DEX_MAX_VOL_LIQ = float(os.getenv("DEX_MAX_VOL_LIQ", "60"))        # volume 24h / liquidez acima disto cheira a volume falso
DEX_MIN_VOL_H1 = float(os.getenv("DEX_MIN_VOL_H1", "5000"))
DEX_MIN_BUYERS_H1 = int(os.getenv("DEX_MIN_BUYERS_H1", "15"))
DEX_MIN_SELLERS_H1 = int(os.getenv("DEX_MIN_SELLERS_H1", "8"))      # vendedores a sair = a venda funciona
DEX_MAX_CHG_H1 = float(os.getenv("DEX_MAX_CHG_H1", "300"))          # nao persegue o que ja disparou
DEX_MAX_DEV_PCT = float(os.getenv("DEX_MAX_DEV_PCT", "25"))        # corte duro; entre 10% e isto o Grok ve o valor e decide
DEX_MAX_RUGCHECK_SCORE = float(os.getenv("DEX_MAX_RUGCHECK_SCORE", "60"))   # RugCheck: 0 = limpo, 100 = pessimo
DEX_MAX_BUY_SELL_RATIO = float(os.getenv("DEX_MAX_BUY_SELL_RATIO", "25"))   # compras por cada venda na ultima hora: acima disto parece que ninguem consegue vender
DEX_MAX_TOP10_PCT = float(os.getenv("DEX_MAX_TOP10_PCT", "60"))
DEX_STOP_PCT = float(os.getenv("DEX_STOP_PCT", "25"))
# Alvo de lucro por operacao: o Grok propoe, o codigo limita a [MIN, MAX] %. Nunca abaixo de 30%.
DEX_TP_MIN_PCT = float(os.getenv("DEX_TP_MIN_PCT", "10"))           # lucro minimo antes de o bot poder realizar
DEX_REVIEW_FROM_PCT = float(os.getenv("DEX_REVIEW_FROM_PCT", "10"))  # a partir deste lucro liquido o Grok reavalia a saida
DEX_REVIEW_SEC = int(os.getenv("DEX_REVIEW_SEC", "60"))              # de quanto em quanto tempo
DEX_TP_MAX_PCT = float(os.getenv("DEX_TP_MAX_PCT", "300"))
DEX_TP_DEFAULT_PCT = float(os.getenv("DEX_TP_DEFAULT_PCT", "60"))   # se o Grok nao disser
DEX_TRAIL_ACTIVATE_PCT = float(os.getenv("DEX_TRAIL_ACTIVATE_PCT", "40"))
DEX_TRAIL_PCT = float(os.getenv("DEX_TRAIL_PCT", "20"))
DEX_MAX_HOLD_H = float(os.getenv("DEX_MAX_HOLD_H", "6"))
DEX_CRASH_PCT = float(os.getenv("DEX_CRASH_PCT", "8"))             # queda brusca: pontos perdidos entre dois ciclos do vigilante
DEX_LIQ_DROP_PCT = float(os.getenv("DEX_LIQ_DROP_PCT", "25"))      # liquidez a cair tanto num ciclo = alguem esta a retirar
DEX_LIQ_FLOOR_PCT = float(os.getenv("DEX_LIQ_FLOOR_PCT", "60"))    # liquidez abaixo desta % da de entrada = sair
DEX_RECHECK_SEC = int(os.getenv("DEX_RECHECK_SEC", "90"))          # de quanto em quanto tempo volta a verificar a seguranca das posicoes
DEX_MIN_CONF = float(os.getenv("DEX_MIN_CONF", "0.6"))
DEX_SCAN_SEC = int(os.getenv("DEX_SCAN_SEC", "60"))
DEX_SOURCES = [x.strip() for x in os.getenv("DEX_SOURCES", "dexscreener,geckoterminal").split(",") if x.strip()]
DEX_GUARD_SEC = int(os.getenv("DEX_GUARD_SEC", "15"))
DEX_ANALYSE_PER_SCAN = int(os.getenv("DEX_ANALYSE_PER_SCAN", "5"))
DEX_REANALYSE_MIN = float(os.getenv("DEX_REANALYSE_MIN", "10"))   # minutos ate voltar a analisar uma moeda que o Grok ja viu
DEX_AUTO_START = os.getenv("DEX_AUTO_START", "false").lower() == "true"

# Vigilante: verifica stops e perda diaria sem chamar o Grok
GUARD_INTERVAL_SEC = int(os.getenv("GUARD_INTERVAL_SEC", "10"))
AUTO_TIMEFRAME = os.getenv("AUTO_TIMEFRAME", "1h")
# Trailing stop: depois de o ganho passar ACTIVATE %, vende se o preco recuar STOP % desde o maximo
TRAILING_ACTIVATE_PCT = float(os.getenv("TRAILING_ACTIVATE_PCT", "3"))
TRAILING_STOP_PCT = float(os.getenv("TRAILING_STOP_PCT", "2"))
AUTO_START = os.getenv("AUTO_START", "false").lower() == "true"
AUTO_LIVE_ALLOWED = os.getenv("AUTO_LIVE_ALLOWED", "false").lower() == "true"

# --- DEX em dinheiro REAL (Solana via Jupiter). Desligado por defeito: DEX_MODE=paper ---
DEX_MODE = os.getenv("DEX_MODE", "paper").lower()                       # paper | live
DEX_WALLET_KEY = os.getenv("DEX_WALLET_KEY")                            # chave da carteira DEDICADA ao bot (base58 ou lista JSON)
DEX_LIVE_ARMED = os.getenv("DEX_LIVE_ARMED", "false").lower() == "true"  # sem isto, o modo live nunca envia nada
DEX_LIVE_DRY_RUN = os.getenv("DEX_LIVE_DRY_RUN", "true").lower() == "true"  # true: cota e simula, nao envia
DEX_RPC_URL = os.getenv("DEX_RPC_URL", "https://api.mainnet-beta.solana.com")
JUPITER_URL = os.getenv("JUPITER_URL", "https://lite-api.jup.ag/swap/v1")
JUPITER_API_KEY = os.getenv("JUPITER_API_KEY")
DEX_BUDGET_EUR = float(os.getenv("DEX_BUDGET_EUR", "20"))              # maximo investido ao mesmo tempo
DEX_DAILY_LOSS_EUR = float(os.getenv("DEX_DAILY_LOSS_EUR", "10"))       # perda diaria que bloqueia novas compras
DEX_SOL_RESERVE = float(os.getenv("DEX_SOL_RESERVE", "0.02"))           # SOL que nunca se gasta (taxas e rendas)
DEX_BUY_SLIPPAGE_BPS = int(os.getenv("DEX_BUY_SLIPPAGE_BPS", "500"))
DEX_SELL_SLIPPAGE_BPS = [int(x) for x in os.getenv("DEX_SELL_SLIPPAGE_BPS", "500,1500,3000").split(",")]  # tentativas crescentes
DEX_MAX_IMPACT_PCT = float(os.getenv("DEX_MAX_IMPACT_PCT", "3"))        # impacto maximo cotado na compra
DEX_MAX_ROUNDTRIP_LOSS_PCT = float(os.getenv("DEX_MAX_ROUNDTRIP_LOSS_PCT", "15"))  # perda comprar+vender logo; acima disto e honeypot/taxa
DEX_PRIORITY_LAMPORTS = int(os.getenv("DEX_PRIORITY_LAMPORTS", "200000"))  # teto da taxa de prioridade por transacao
