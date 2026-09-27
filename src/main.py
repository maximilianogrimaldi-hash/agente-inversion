"""
Main — Orquestador del ciclo de analisis
"""

import logging
import sys

from iol_client import IOLClient
from binance_client import BinanceClient
from analyzer import Analyzer, Signal
from telegram_bot import TelegramBot
from supabase_client import SupabaseClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


def _load_config(db: SupabaseClient) -> dict:
    keys = ["rsi_oversold", "rsi_overbought", "price_change_alert", "volume_spike_mult", "dedup_minutes"]
    config = {}
    for k in keys:
        val = db.get_config(k)
        if val is not None:
            config[k] = val
    return config


def run_cycle():
    logger.info("=== Iniciando ciclo de analisis ===")
    db = SupabaseClient()
    config = _load_config(db)
    dedup_minutes = int(config.get("dedup_minutes", 60))
    analyzer = Analyzer(config)
    telegram = TelegramBot()
    signals_to_send: list[Signal] = []

    # --- CEDEARs ---
    cedears = db.get_cedears()
    if cedears:
        try:
            iol = IOLClient()
            for ticker in cedears:
                try:
                    quote = iol.get_cedear_quote(ticker)
                    history = iol.get_cedear_history(ticker, days=50)
                    sig = analyzer.analyze_cedear(ticker, quote, history)
                    if sig and sig.senal not in ("NEUTRAL",):
                        if db.alert_already_sent(ticker, sig.senal, dedup_minutes):
                            logger.info(f"Duplicado ignorado: {sig.ticker} {sig.senal}")
                            continue
                        db.save_alert(sig.__dict__)
                        signals_to_send.append(sig)
                except Exception as e:
                    logger.error(f"Error procesando CEDEAR {ticker}: {e}")
        except Exception as e:
            logger.error(f"Error inicializando IOL: {e}")
    else:
        logger.info("Sin CEDEARs en watchlist")

    # --- Crypto ---
    cryptos = db.get_cryptos()
    if cryptos:
        try:
            binance = BinanceClient()
            for symbol in cryptos:
                try:
                    ticker_24h = binance.get_ticker_24h(symbol)
                    klines = binance.get_klines(symbol, interval="15m", limit=50)
                    sig = analyzer.analyze_crypto(symbol, ticker_24h, klines)
                    if sig and sig.senal not in ("NEUTRAL",):
                        if db.alert_already_sent(symbol, sig.senal, dedup_minutes):
                            logger.info(f"Duplicado ignorado: {sig.ticker} {sig.senal}")
                            continue
                        db.save_alert(sig.__dict__)
                        signals_to_send.append(sig)
                except Exception as e:
                    logger.error(f"Error procesando crypto {symbol}: {e}")
        except Exception as e:
            logger.error(f"Error inicializando Binance: {e}")
    else:
        logger.info("Sin cryptos en watchlist")

    # Ordenar: FUERTE primero
    fuerza_order = {"FUERTE": 0, "MODERADA": 1, "DEBIL": 2}
    signals_to_send.sort(key=lambda s: fuerza_order.get(s.fuerza, 3))

    telegram.send_signals_batch(signals_to_send)
    logger.info(f"=== Ciclo completado: {len(signals_to_send)} senales enviadas ===")


def run_heartbeat():
    db = SupabaseClient()
    telegram = TelegramBot()
    cedears = db.get_cedears()
    cryptos = db.get_cryptos()
    telegram.send_heartbeat(len(cedears), len(cryptos))
    logger.info("Heartbeat enviado")
