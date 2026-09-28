"""
Scheduler - Cron interno para Railway
v2: agrega screener (1x/día 10:00), backtesting (lunes 08:00), portfolio (diario 09:30)
"""

import logging
import os
import sys
import time
from datetime import datetime, timezone

import schedule

from main import run_cycle, run_heartbeat, run_screener, run_backtesting, run_portfolio

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


def safe(fn, name: str):
    """Wrapper de error para cualquier job."""
    def wrapper():
        try:
            fn()
        except Exception as e:
            logger.exception(f"Error no capturado en {name}: {e}")
            try:
                from telegram_bot import TelegramBot
                TelegramBot().send_error(name, str(e))
            except Exception:
                pass
    return wrapper


def main():
    logger.info("Agente de Inversion v2 iniciado")
    logger.info(
        "Jobs: ciclo cada 15min | heartbeat 09:00 | portfolio 09:30 | screener 10:00 | backtesting lunes 08:30"
    )

    # Panel web en un thread aparte (no debe tumbar el scheduler si falla)
    try:
        import threading
        from web import serve as serve_panel
        threading.Thread(target=serve_panel, daemon=True, name="panel").start()
    except Exception as e:
        logger.error(f"No se pudo levantar el panel web: {e}")

    # Sonda de diagnóstico IOL (solo con IOL_DIAG=1)
    if os.environ.get("IOL_DIAG") == "1":
        try:
            import iol_probe
            from iol_client import IOLClient
            iol_probe.run(IOLClient()._headers())
        except Exception as e:
            logger.error(f"Sonda IOL fallo: {e}")

    # Análisis técnico cada 15 minutos
    schedule.every(15).minutes.do(safe(run_cycle, "ciclo"))

    # Resumen diario completo (Fear&Greed + dólar + noticias + SEC filings)
    schedule.every().day.at("09:00").do(safe(run_heartbeat, "heartbeat"))

    # Portfolio P&L (diario, después del resumen)
    schedule.every().day.at("09:30").do(safe(run_portfolio, "portfolio"))

    # Screener de oportunidades (diario al medio día NY)
    schedule.every().day.at("14:00").do(safe(run_screener, "screener"))

    # Backtesting (lunes a las 08:30 UTC)
    schedule.every().monday.at("08:30").do(safe(run_backtesting, "backtesting"))

    # Ejecutar ciclo inicial al arrancar
    safe(run_cycle, "ciclo_inicial")()

    while True:
        schedule.run_pending()
        time.sleep(30)


if __name__ == "__main__":
    main()
