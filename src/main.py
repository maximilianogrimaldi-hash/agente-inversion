"""
Main — Orquestador del ciclo de analisis
v2: integra news, screener, fear&greed, sentiment, portfolio, SEC, dólar, backtesting
"""

import logging
import sys

from iol_client import IOLClient
from binance_client import BinanceClient
from analyzer import Analyzer, Signal
from telegram_bot import TelegramBot
from supabase_client import SupabaseClient
from news_client import NewsClient
from fear_greed import get_fear_greed, format_fg_message
from dollar_monitor import get_dollar_rates, format_dollar_message, analyze_dollar_cedear_correlation
from sentiment import SentimentAnalyzer
from screener import Screener
from sec_monitor import SECMonitor
from backtesting import Backtester
from portfolio import PortfolioTracker

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


def _load_config(db: SupabaseClient) -> dict:
    keys = [
        "rsi_oversold", "rsi_overbought", "rsi_extreme_oversold", "rsi_extreme_overbought",
        "price_change_alert", "volume_spike_mult", "dedup_minutes"
    ]
    config = {}
    for k in keys:
        val = db.get_config(k)
        if val is not None:
            config[k] = val
    return config


def _enriquecer(sig, tipo: str) -> None:
    """
    Suma al snapshot lo que el análisis técnico no ve: fundamentales del
    subyacente, fuerza relativa contra el índice y la serie para graficar.
    Si Yahoo no responde, la señal técnica sigue sirviendo igual.
    """
    if sig is None:
        return
    try:
        import market_data as md

        fund = md.get_fundamentals(sig.ticker, tipo)
        if fund:
            sig.indicadores["fundamentales"] = fund
            # Un balance inminente cambia el riesgo de cualquier entrada
            dias = fund.get("dias_al_balance")
            if dias is not None and 0 <= dias <= 7:
                sig.motivos.append(f"Presenta balance en {dias} días")

        rs = md.fuerza_relativa(sig.ticker, tipo)
        if rs:
            sig.indicadores["fuerza_relativa"] = rs
            r21 = rs.get("rs_21")
            if r21 is not None:
                if r21 > 5:
                    sig.motivos.append(f"Le gana al índice por {r21:+.1f}% en un mes")
                elif r21 < -5:
                    sig.motivos.append(f"Pierde contra el índice por {r21:+.1f}% en un mes")

        serie = md.get_series(sig.ticker, tipo)
        if serie and serie.get("closes"):
            # Solo lo necesario para dibujar: 120 cierres
            sig.indicadores["serie"] = [round(c, 4) for c in serie["closes"][-120:]]
    except Exception as e:
        logger.debug(f"Enriquecimiento {sig.ticker}: {e}")


def run_cycle():
    logger.info("=== Iniciando ciclo de analisis ===")
    db = SupabaseClient()
    config = _load_config(db)
    dedup_minutes = int(config.get("dedup_minutes", 60))
    analyzer = Analyzer(config)
    telegram = TelegramBot()
    signals_to_send: list[Signal] = []
    current_prices: dict = {}

    # --- CEDEARs ---
    cedears = db.get_cedears()
    iol = None
    if cedears:
        try:
            iol = IOLClient()
            for ticker in cedears:
                try:
                    quote = iol.get_cedear_quote(ticker)
                    history = iol.get_cedear_history(ticker, days=300)
                    sig = analyzer.analyze_cedear(ticker, quote, history)
                    precio = float(quote.get("ultimoPrecio") or quote.get("precio") or 0)
                    if precio > 0:
                        current_prices[ticker] = precio
                    if sig:
                        _enriquecer(sig, "CEDEAR")
                        db.save_snapshot(sig.__dict__)
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
    binance = None
    if cryptos:
        try:
            binance = BinanceClient()
            for symbol in cryptos:
                try:
                    ticker_24h = binance.get_ticker_24h(symbol)
                    klines = binance.get_klines(symbol, interval="1h", limit=250)
                    sig = analyzer.analyze_crypto(symbol, ticker_24h, klines)
                    if ticker_24h.get("price"):
                        current_prices[symbol] = ticker_24h["price"]
                    if sig:
                        _enriquecer(sig, "CRYPTO")
                        db.save_snapshot(sig.__dict__)
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

    # Enviar señales técnicas
    telegram.send_signals_batch(signals_to_send)

    # Noticias (cada ciclo, solo si hay señales o cada hora)
    _run_news_check(telegram, cedears, cryptos)

    logger.info(f"=== Ciclo completado: {len(signals_to_send)} senales enviadas ===")
    return signals_to_send, current_prices


def _run_news_check(telegram: TelegramBot, cedears: list, cryptos: list):
    """Chequeo de noticias — solo informa si hay algo relevante."""
    try:
        news_client = NewsClient()
        news = news_client.get_watchlist_news(cedears, cryptos, max_per_ticker=2)

        if not news:
            return

        # Análisis de sentimiento (si hay API key)
        sentiment_data = {}
        try:
            sa = SentimentAnalyzer()
            sentiment_data = sa.analyze_news_batch(news)
        except Exception as e:
            logger.debug(f"Sentiment skip: {e}")

        # Solo enviar si hay noticias con sentimiento negativo fuerte o positivo fuerte
        if sentiment_data.get("sentimiento_mercado") in ("POSITIVO", "NEGATIVO"):
            telegram.send_news_alert(news, sentiment_data)
        elif len(news) >= 3:
            # De todas formas, cada hora aprox enviar algunas noticias
            telegram.send_news_alert(news[:5], sentiment_data)

    except Exception as e:
        logger.error(f"Error en news check: {e}")


def run_heartbeat():
    """Resumen diario a las 09:00 UTC — solo señales nuevas del día."""
    logger.info("=== Iniciando heartbeat diario ===")
    db = SupabaseClient()
    telegram = TelegramBot()

    # Solo señales de las últimas 24hs
    recent_signals = []
    try:
        recent_alerts = db.get_recent_alerts(days_back=1)

        class SigProxy:
            def __init__(self, d):
                self.ticker = d.get("ticker", "")
                self.senal = d.get("senal", "")
                self.fuerza = d.get("fuerza", "")

        recent_signals = [SigProxy(a) for a in recent_alerts]
    except Exception as e:
        logger.warning(f"Recent signals error: {e}")

    if not recent_signals:
        logger.info("Heartbeat: sin señales nuevas, no se envía mensaje")
        return

    # Armar mensaje compacto
    from datetime import datetime as _dt
    now_str = _dt.utcnow().strftime("%d/%m/%Y")
    lines = [
        f"📋 <b>SEÑALES DEL DÍA — {now_str}</b>",
        f"━━━━━━━━━━━━━━━━━━━━",
    ]
    fuerza_order = {"FUERTE": 0, "MODERADA": 1, "DEBIL": 2}
    recent_signals.sort(key=lambda s: fuerza_order.get(s.fuerza, 3))
    for sig in recent_signals[:10]:
        emoji_map = {
            ("COMPRA", "FUERTE"): "🟢🔥", ("COMPRA", "MODERADA"): "🟢",
            ("VENTA", "FUERTE"): "🔴🔥", ("VENTA", "MODERADA"): "🔴",
        }
        emoji = emoji_map.get((sig.senal, sig.fuerza), "🔔")
        lines.append(f"  {emoji} <b>{sig.ticker}</b>: {sig.senal} {sig.fuerza}")

    if len(recent_signals) > 10:
        lines.append(f"  ... y {len(recent_signals) - 10} señales más")

    lines.append(f"\n━━━━━━━━━━━━━━━━━━━━")
    lines.append(f"🕘 {_dt.utcnow().strftime('%H:%M UTC')} · <i>Solo informativo</i>")

    telegram._send("\n".join(lines))
    logger.info(f"Heartbeat: {len(recent_signals)} señales enviadas")


def run_screener():
    """Screener de oportunidades — se ejecuta 1 vez por día."""
    logger.info("=== Ejecutando screener ===")
    db = SupabaseClient()
    telegram = TelegramBot()
    config = _load_config(db)

    try:
        iol = IOLClient()
        screener = Screener(config)
        cedears = db.get_cedears()
        results = screener.scan_cedear(iol, cedears)
        if results:
            telegram.send_screener_results(results)
            logger.info(f"Screener: {len(results)} candidatos enviados")
        else:
            logger.info("Screener: sin candidatos destacados")
    except Exception as e:
        logger.error(f"Screener error: {e}")


def run_backtesting():
    """Backtesting semanal de señales pasadas."""
    logger.info("=== Ejecutando backtesting ===")
    db = SupabaseClient()
    telegram = TelegramBot()

    try:
        backtester = Backtester(db)
        signals = backtester.get_past_signals(days_back=30)

        binance = BinanceClient()
        iol = IOLClient()
        stats = backtester.analyze_signal_accuracy(signals, binance, iol)
        msg = backtester.format_backtest_message(stats)
        telegram.send_backtesting(msg)
        logger.info(f"Backtesting: {stats.get('total_analizadas', 0)} señales analizadas")
    except Exception as e:
        logger.error(f"Backtesting error: {e}")


def run_portfolio():
    """Actualiza y envía resumen del portfolio."""
    logger.info("=== Actualizando portfolio ===")
    db = SupabaseClient()
    telegram = TelegramBot()

    try:
        tracker = PortfolioTracker(db)
        positions = tracker.get_positions()

        if not positions:
            logger.info("Portfolio vacío")
            return

        # Obtener precios actuales
        current_prices = {}
        binance = BinanceClient()
        iol = IOLClient()

        for pos in positions:
            ticker = pos.get("ticker", "")
            tipo = pos.get("tipo", "CEDEAR")
            try:
                if tipo == "CRYPTO":
                    td = binance.get_ticker_24h(ticker)
                    current_prices[ticker] = td.get("price", 0)
                else:
                    quote = iol.get_cedear_quote(ticker)
                    current_prices[ticker] = float(quote.get("ultimoPrecio") or 0)
            except Exception as e:
                logger.warning(f"Precio no disponible para {ticker}: {e}")

        pnl_data = tracker.calculate_pnl(positions, current_prices)
        msg = tracker.format_portfolio_message(pnl_data)
        telegram.send_portfolio(msg)

    except Exception as e:
        logger.error(f"Portfolio error: {e}")
