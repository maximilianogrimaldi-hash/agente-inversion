"""
Telegram Bot - Alertas de inversion
v2: agrega formatters para resumen diario, noticias, screener, SEC, portfolio, backtesting, dólar
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

    # ─── Nuevos formatters v2 ─────────────────────────────────────────────

    def send_daily_summary(
        self,
        cedears_count: int,
        cryptos_count: int,
        fg_msg: str = "",
        dollar_msg: str = "",
        commentary: str = "",
        top_signals: list = None,
        news_preview: list = None,
    ) -> bool:
        """Resumen matutino completo a las 9hs."""
        now_str = datetime.utcnow().strftime("%d/%m/%Y")
        lines = [
            f"🌅 <b>RESUMEN DIARIO — {now_str}</b>",
            f"━━━━━━━━━━━━━━━━━━━━",
        ]

        if commentary:
            lines.append(f"\n📝 {commentary}")

        if fg_msg:
            lines.append(f"\n{fg_msg}")

        if dollar_msg:
            lines.append(f"\n{dollar_msg}")

        lines.append(f"\n📊 Monitoreando: {cedears_count} CEDEARs | {cryptos_count} Cryptos")

        if top_signals:
            lines.append("\n🔔 <b>Señales del ciclo:</b>")
            for sig in top_signals[:3]:
                emoji = self._emoji_senal(sig.senal, sig.fuerza)
                lines.append(f"  {emoji} {sig.ticker}: {sig.senal} {sig.fuerza}")

        if news_preview:
            lines.append("\n📰 <b>Noticias destacadas:</b>")
            for n in news_preview[:3]:
                title = n.get("title", "")[:80]
                ticker = n.get("ticker", "")
                lines.append(f"  [{ticker}] {title}")

        lines.append(f"\n━━━━━━━━━━━━━━━━━━━━")
        lines.append(f"🕘 {datetime.utcnow().strftime('%H:%M UTC')} · <i>Solo informativo</i>")

        return self._send("\n".join(lines))

    def send_news_alert(self, news_items: list[dict], sentiment_data: dict = None) -> bool:
        """Envía resumen de noticias relevantes con sentimiento."""
        if not news_items:
            return False

        lines = [f"📰 <b>NOTICIAS RELEVANTES</b> — {datetime.utcnow().strftime('%H:%M UTC')}\n"]

        market_sentiment = sentiment_data.get("sentimiento_mercado", "") if sentiment_data else ""
        if market_sentiment:
            s_emoji = {"POSITIVO": "📈", "NEGATIVO": "📉", "NEUTRO": "📊"}.get(market_sentiment, "📊")
            lines.append(f"{s_emoji} Sentimiento: <b>{market_sentiment}</b>\n")

        for item in news_items[:8]:
            ticker = item.get("ticker", "")
            title = item.get("title", "")[:100]
            # Sentimiento por ticker si está disponible
            ticker_sentiment = ""
            if sentiment_data and "tickers" in sentiment_data:
                td = sentiment_data["tickers"].get(ticker, {})
                if td.get("sentiment"):
                    s_map = {"POSITIVO": "📈", "NEGATIVO": "📉", "NEUTRO": "•"}
                    ticker_sentiment = f" {s_map.get(td['sentiment'], '')} <i>{td.get('razon', '')}</i>"
            lines.append(f"[<b>{ticker}</b>] {title}{ticker_sentiment}")

        return self._send("\n".join(lines))

    def send_screener_results(self, results: list) -> bool:
        """Envía resultados del screener de oportunidades."""
        if not results:
            return False

        lines = [
            f"🔍 <b>SCREENER — Candidatos de entrada</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━"
        ]

        for r in results[:8]:
            rsi_str = f"RSI: {r.rsi}" if r.rsi else ""
            var_str = f"{r.variacion_pct:+.1f}%" if r.variacion_pct else ""
            score_str = f"Score: {r.score_oportunidad}"
            lines.append(
                f"\n🎯 <b>{r.ticker}</b> — ${r.precio:,.2f} ({var_str})\n"
                f"   {rsi_str} · {score_str}\n"
                f"   <i>{r.razon}</i>"
            )

        lines.append(f"\n━━━━━━━━━━━━━━━━━━━━\n⚠️ <i>Solo informativo. No es asesoramiento financiero.</i>")
        return self._send("\n".join(lines))

    def send_sec_filings(self, filings: list[dict]) -> bool:
        """Envía alertas de nuevos filings SEC."""
        if not filings:
            return False

        lines = [f"📋 <b>FILINGS SEC — Últimos 7 días</b>\n"]

        for f in filings[:10]:
            ticker = f.get("ticker", "")
            form = f.get("form", "")
            date = f.get("date", "")
            desc = f.get("description", form)
            url = f.get("url", "")
            lines.append(f"{desc} <b>{ticker}</b> ({form}) — {date}")
            if url:
                lines.append(f"  <a href='{url}'>Ver en EDGAR →</a>")

        return self._send("\n".join(lines))

    def send_portfolio(self, portfolio_msg: str) -> bool:
        """Envía resumen del portfolio."""
        return self._send(portfolio_msg)

    def send_backtesting(self, backtest_msg: str) -> bool:
        """Envía estadísticas de backtesting."""
        return self._send(backtest_msg)

    def send_dollar_alert(self, dollar_msg: str, correlation_alerts: list[str]) -> bool:
        """Envía alerta de tipo de cambio y correlación CEDEAR."""
        if not dollar_msg and not correlation_alerts:
            return False
        lines = [dollar_msg] if dollar_msg else []
        if correlation_alerts:
            lines.append("\n<b>Correlación dólar-CEDEAR:</b>")
            for alert in correlation_alerts:
                lines.append(f"  {alert}")
        return self._send("\n".join(lines))
