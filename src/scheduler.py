"""
Scheduler - Cron interno para Railway
"""

import logging
import sys
import time
from datetime import datetime, timezone

import schedule

from main import run_cycle, run_heartbeat

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


def safe_run_cycle():
    try:
        run_cycle()
    except Exception as e:
        logger.exception(f"Error no capturado en ciclo: {e}")
        try:
            from telegram_bot import TelegramBot
            TelegramBot().send_error("scheduler", str(e))
        except Exception:
            pass


def safe_heartbeat():
    try:
        run_heartbeat()
    except Exception as e:
        logger.exception(f"Error en heartbeat: {e}")


def main():
    logger.info("Agente de Inversion iniciado")
    logger.info("Ciclo: cada 15 minutos | Heartbeat: 09:00 UTC diario")
    schedule.every(15).minutes.do(safe_run_cycle)
    schedule.every().day.at("09:00").do(safe_heartbeat)
    safe_run_cycle()
    while True:
        schedule.run_pending()
        time.sleep(30)


if __name__ == "__main__":
    main()
