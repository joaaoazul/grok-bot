"""Corre o bot em modo autonomo, sem interface web. Ctrl+C para parar."""
import time

from bot import config
from bot.auto import AutoTrader
from bot.broker import get_broker

bot = AutoTrader(get_broker())
bot.start()
print(f"Bot autonomo a correr ({config.MODE}{', testnet' if config.MODE == 'live' and config.TESTNET else ''}). Ctrl+C para parar.")

seen = set()
try:
    while True:
        for entry in reversed(bot.log):
            key = (entry["t"], entry["msg"])
            if key not in seen:
                seen.add(key)
                print(f"[{entry['t']}] {entry['msg']}", flush=True)
        time.sleep(2)
except KeyboardInterrupt:
    bot.stop()
