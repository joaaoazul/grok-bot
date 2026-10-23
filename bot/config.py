import os

from dotenv import load_dotenv

load_dotenv()

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
AUTO_START = os.getenv("AUTO_START", "false").lower() == "true"
AUTO_LIVE_ALLOWED = os.getenv("AUTO_LIVE_ALLOWED", "false").lower() == "true"
