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

    @staticmethod
    def _semaforo_str(bloque: dict) -> str:
        """Convierte dict semaforo en string visual."""
        SEM = {"verde": "🟢", "amarillo": "🟡", "rojo": "🔴"}
        parts = []
        labels = {
            "tendencia": "Tend",
            "rsi": "RSI",
            "macd": "MACD",
            "bollinger": "BB",
            "volumen": "Vol",
            "soportes": "Sop",
        }
        for k, label in labels.items():
            v = bloque.get(k)
            if v:
                parts.append(f"{SEM.get(v, '⚪')} {label}")
        return "  ".join(parts) if parts else ""

    def format_signal(self, sig: Signal) -> str:
        emoji = self._emoji_senal(sig.senal, sig.fuerza)
        tipo_emoji = self._emoji_tipo(sig.tipo)
        precio_str = self._format_price(sig.precio, sig.tipo)
        var_str = f"{sig.variacion_pct:+.2f}%" if sig.variacion_pct else "N/A"
        ind = sig.indicadores

        # Tipo de señal
        tipo_senal = getattr(sig, "tipo_senal", "tecnica")
        if tipo_senal == "cartera":
            badge = "🚨 <b>SEÑAL DE CARTERA</b> (ruptura estructural)"
        else:
            badge = "📡 Señal técnica"

        # Header
        lines = [
            f"{emoji} <b>{sig.senal} {sig.fuerza}</b> — {tipo_emoji} <b>{sig.ticker}</b>",
            f"{badge}",
            f"━━━━━━━━━━━━━━━━━━━━",
        ]

        # Bloque 1: Precio
        lines.append(f"💰 Precio: <b>{precio_str}</b>  ({var_str})")

        # Bloque 2: Tendencia de fondo
        td = ind.get("tendencia_diaria") or {}
        ts = ind.get("tendencia_semanal") or {}
        if td or ts:
            lines.append("\n📈 <b>TENDENCIA</b>")
            if td:
                alin = td.get("alineacion", "")
                sma50 = td.get("sma50_v")
                sma200 = td.get("sma200_v")
                pend = td.get("sma50_pendiente")
                partes = [f"1D: {alin}"]
                if sma50:
                    partes.append(f"SMA50=${sma50:.2f}")
                if sma200:
                    partes.append(f"SMA200=${sma200:.2f}")
                if pend is not None:
                    partes.append(f"pend={pend:+.2f}%/v")
                lines.append("  " + " · ".join(partes))
            if ts:
                alin_w = ts.get("alineacion", "")
                lines.append(f"  1W: {alin_w}")

        # Bloque 3: Niveles clave
        sop = ind.get("soporte")
        res = ind.get("resistencia")
        p = sig.precio
        if sop or res:
            lines.append("\n🎯 <b>NIVELES CLAVE</b>")
            if sop and p:
                dist_s = (p / sop - 1) * 100
                lines.append(f"  Soporte:     ${sop:.2f}  ({dist_s:+.1f}% desde precio)")
            if res and p:
                dist_r = (res / p - 1) * 100
                lines.append(f"  Resistencia: ${res:.2f}  ({dist_r:+.1f}% desde precio)")

        # Bloque 4: Volumen
        vr = ind.get("vol_ratio")
        if vr is not None:
            vol_desc = "🔥 alto" if vr >= 1.5 else ("normal" if vr >= 0.8 else "⚠️ bajo")
            lines.append(f"\n📊 <b>VOLUMEN</b>: x{vr:.1f} vs 20D  ({vol_desc})")

        # Bloque 5: Distancia desde máximos
        d52 = ind.get("dist_max_52s")
        d6m = ind.get("dist_max_6m")
        d3m = ind.get("dist_max_3m")
        if d52 is not None:
            lines.append(f"\n📉 <b>DESDE MÁXIMOS</b>: 52S={d52:+.1f}%"
                         + (f"  6M={d6m:+.1f}%" if d6m is not None else "")
                         + (f"  3M={d3m:+.1f}%" if d3m is not None else ""))

        # Bloque 6: Semáforo por familia
        sem = ind.get("semaforo") or {}
        if sem:
            lines.append(f"\n🚦 <b>SEMÁFORO</b>")
            lines.append(f"  {self._semaforo_str(sem)}")

        # Motivos detectados
        if sig.motivos:
            lines.append(f"\n🔍 <b>Señales detectadas:</b>")
            for m in sig.motivos:
                lines.append(f"  • {m}")

        # Condiciones de confirmación
        conf = ind.get("confirmacion") or []
        if conf:
            lines.append(f"\n✅ <b>Condiciones de confirmación:</b>")
            for c in conf:
                lines.append(f"  {c}")

        lines.append(f"\n━━━━━━━━━━━━━━━━━━━━")
        lines.append(f"🕐 {datetime.utcnow().strftime('%H:%M UTC')} · <i>Solo informativo</i>")

        return "\n".join(lines)

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
