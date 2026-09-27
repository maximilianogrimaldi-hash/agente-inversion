"""
Telegram Bot - Alertas de inversion
"""

import os
import logging
from datetime import datetime

import requests

from analyzer import Signal

logger = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org/bot{token}/{method}"


class TelegramBot:
    def __init__(self):
        self.token = os.environ["TELEGRAM_BOT_TOKEN"]
        self.chat_id = os.environ["TELEGRAM_CHAT_ID"]

    def _send(self, text: str, parse_mode: str = "HTML") -> bool:
        url = TELEGRAM_API.format(token=self.token, method="sendMessage")
        try:
            resp = requests.post(
                url,
                json={
                    "chat_id": self.chat_id,
                    "text": text,
                    "parse_mode": parse_mode,
                    "disable_web_page_preview": True,
                },
                timeout=10,
            )
            resp.raise_for_status()
            return True
        except Exception as e:
            logger.error(f"Error enviando mensaje Telegram: {e}")
            return False

    @staticmethod
    def _emoji_senal(senal: str, fuerza: str) -> str:
        if senal == "BUY":
            return "\U0001f7e2\U0001f7e2" if fuerza == "FUERTE" else "\U0001f7e2"
        elif senal == "SELL":
            return "\U0001f534\U0001f534" if fuerza == "FUERTE" else "\U0001f534"
        return "\U0001f7e1"

    @staticmethod
    def _emoji_tipo(tipo: str) -> str:
        return "\U0001f4c8" if tipo == "CEDEAR" else "₿"

    @staticmethod
    def _format_price(precio: float, tipo: str) -> str:
        if tipo == "CRYPTO":
            if precio >= 1000:
                return f"${precio:,.2f}"
            elif precio >= 1:
                return f"${precio:.4f}"
            else:
                return f"${precio:.6f}"
        return f"${precio:,.2f}"

    def format_signal(self, sig: Signal) -> str:
        emoji = self._emoji_senal(sig.senal, sig.fuerza)
        tipo_emoji = self._emoji_tipo(sig.tipo)
        precio_str = self._format_price(sig.precio, sig.tipo)
        var_str = f"{sig.variacion_pct:+.2f}%" if sig.variacion_pct else "N/A"
        motivos_str = "\n".join(f"  • {m}" for m in sig.motivos)
        indicadores_parts = []
        ind = sig.indicadores
        if "rsi" in ind:
            indicadores_parts.append(f"RSI: {ind['rsi']}")
        if "ema_short" in ind and "ema_long" in ind:
            indicadores_parts.append(f"EMA9: {ind['ema_short']} | EMA21: {ind['ema_long']}")
        if "vol_ratio" in ind:
            indicadores_parts.append(f"Vol ratio: x{ind['vol_ratio']}")
        if "cambio_ultima_vela" in ind:
            indicadores_parts.append(f"Ultima vela: {ind['cambio_ultima_vela']:+.2f}%")
        indicadores_str = " · ".join(indicadores_parts)
        msg = (
            f"{emoji} <b>{sig.senal} {sig.fuerza}</b> - {tipo_emoji} {sig.ticker}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"\U0001f4b0 Precio: <b>{precio_str}</b>  ({var_str})\n"
            f"\U0001f4ca Tipo: {sig.tipo}\n\n"
            f"<b>Senales detectadas:</b>\n{motivos_str}\n\n"
            f"<i>{indicadores_str}</i>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"\U0001f550 {datetime.utcnow().strftime('%H:%M UTC')} · <i>Solo informativo</i>"
        )
        return msg

    def send_signal(self, sig: Signal) -> bool:
        msg = self.format_signal(sig)
        return self._send(msg)

    def send_signals_batch(self, signals: list[Signal]) -> None:
        if not signals:
            logger.info("Sin senales relevantes en este ciclo.")
            return
        header = (
            f"⚡ <b>AGENTE DE INVERSION - {len(signals)} senal{'es' if len(signals) > 1 else ''}</b>\n"
            f"\U0001f5d3 {datetime.utcnow().strftime('%d/%m/%Y %H:%M UTC')}"
        )
        self._send(header)
        for sig in signals:
            self.send_signal(sig)

    def send_heartbeat(self, cedears_monitored: int, cryptos_monitored: int) -> bool:
        msg = (
            f"\U0001f49a <b>Agente activo</b>\n"
            f"\U0001f4c8 CEDEARs monitoreados: {cedears_monitored}\n"
            f"₿ Cryptos monitoreadas: {cryptos_monitored}\n"
            f"\U0001f550 {datetime.utcnow().strftime('%d/%m/%Y %H:%M UTC')}"
        )
        return self._send(msg)

    def send_error(self, context: str, error: str) -> bool:
        msg = (
            f"⚠️ <b>Error en el agente</b>\n"
            f"<b>Contexto:</b> {context}\n"
            f"<b>Error:</b> <code>{error[:300]}</code>\n"
            f"\U0001f550 {datetime.utcnow().strftime('%H:%M UTC')}"
        )
        return self._send(msg)
