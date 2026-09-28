"""
sentiment.py — Análisis de sentimiento de noticias via Claude API.
Analiza titulares y los clasifica como positivo/negativo/neutro con impacto estimado.
"""

import logging
import os
import json

import requests

logger = logging.getLogger(__name__)

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
SENTIMENT_MODEL = "claude-haiku-4-5-20251001"  # Rápido y barato para sentiment


class SentimentAnalyzer:
    def __init__(self):
        self.api_key = os.environ.get("ANTHROPIC_API_KEY", "")

    def _call_claude(self, prompt: str, max_tokens: int = 300) -> str | None:
        if not self.api_key:
            logger.warning("ANTHROPIC_API_KEY no configurada")
            return None
        try:
            resp = requests.post(
                ANTHROPIC_API_URL,
                headers={
                    "x-api-key": self.api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": SENTIMENT_MODEL,
                    "max_tokens": max_tokens,
                    "messages": [{"role": "user", "content": prompt}],
                },
                timeout=20,
            )
            resp.raise_for_status()
            return resp.json()["content"][0]["text"]
        except Exception as e:
            logger.error(f"Error Claude API: {e}")
            return None

    def analyze_news_batch(self, news_items: list[dict]) -> dict:
        """
        Analiza un batch de noticias y retorna resumen de sentimiento por ticker.
        Input: lista de {ticker, title, url}
        Output: {ticker: {sentiment, score, summary}}
        """
        if not news_items or not self.api_key:
            return {}

        # Agrupar por ticker
        by_ticker: dict[str, list[str]] = {}
        for item in news_items:
            t = item.get("ticker", "GENERAL")
            by_ticker.setdefault(t, []).append(item.get("title", ""))

        # Un solo llamado para todos los tickers
        news_text = "\n".join([
            f"[{ticker}]: {'; '.join(titles[:3])}"
            for ticker, titles in by_ticker.items()
        ])

        prompt = f"""Eres un analista financiero experto. Analiza el sentimiento de estas noticias para traders argentinos que invierten en CEDEARs y crypto.

NOTICIAS:
{news_text}

Responde SOLO con JSON válido (sin markdown), con este formato exacto:
{{
  "resumen_general": "una frase del clima del mercado",
  "sentimiento_mercado": "POSITIVO|NEGATIVO|NEUTRO",
  "tickers": {{
    "TICKER": {{"sentiment": "POSITIVO|NEGATIVO|NEUTRO", "impacto": "ALTO|MEDIO|BAJO", "razon": "una frase corta"}}
  }}
}}"""

        result_text = self._call_claude(prompt, max_tokens=400)
        if not result_text:
            return {}

        try:
            # Limpiar posible markdown
            clean = result_text.strip()
            if clean.startswith("```"):
                clean = "\n".join(clean.split("\n")[1:-1])
            return json.loads(clean)
        except Exception as e:
            logger.error(f"Error parsing sentiment JSON: {e} — {result_text[:200]}")
            return {}

    def generate_market_commentary(self, fg_data: dict | None, top_signals: list, news_summary: dict) -> str:
        """
        Genera un comentario de mercado para el resumen diario.
        Retorna texto listo para Telegram.
        """
        if not self.api_key:
            return ""

        fg_str = f"Fear & Greed: {fg_data['value']} ({fg_data['rating']})" if fg_data else "Fear & Greed: N/A"
        signals_str = ", ".join([f"{s.ticker} {s.senal} {s.fuerza}" for s in top_signals[:5]]) or "Sin señales destacadas"
        market_sentiment = news_summary.get("sentimiento_mercado", "NEUTRO")
        market_summary = news_summary.get("resumen_general", "")

        prompt = f"""Eres el agente de inversión personal de un trader argentino.
Escribe UN párrafo corto (máximo 3 oraciones) como apertura del resumen diario de mercados.
Sé directo, concreto y útil. Sin saludos ni cierres.

Datos:
- {fg_str}
- Sentimiento noticias: {market_sentiment} — {market_summary}
- Señales del ciclo: {signals_str}

Escribe solo el párrafo, en español, sin formato markdown."""

        result = self._call_claude(prompt, max_tokens=150)
        return result.strip() if result else ""
