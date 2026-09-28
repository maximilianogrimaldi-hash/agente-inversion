"""
screener.py — Screener de oportunidades de inversión.
Escanea un universo ampliado de CEDEARs buscando candidatos de entrada.
"""

import logging
from dataclasses import dataclass

from analyzer import Analyzer, Signal, _rsi, _ema

logger = logging.getLogger(__name__)

# Top 50 CEDEARs por volumen en Argentina (ampliado del watchlist principal)
SCREENER_UNIVERSE = [
    # Watchlist principal (18)
    "AAPL", "ABBV", "AMZN", "AVGO", "BRK", "GLOB", "GOOGL", "KO",
    "MELI", "META", "MSFT", "NVDA", "ORCL", "TSLA", "TSM", "UNH", "XOM", "YPFD",
    # Adicionales populares en CEDEAR (32 más)
    "JPM", "BAC", "C", "WFC", "GS", "MS", "V", "MA", "PYPL",
    "NFLX", "DIS", "CMCSA", "T", "VZ",
    "JNJ", "PFE", "MRK", "LLY",
    "WMT", "HD", "COST", "TGT",
    "BA", "CAT", "DE", "GE",
    "BABA", "NIO", "INTC", "AMD", "QCOM",
]


@dataclass
class ScreenerResult:
    ticker: str
    rsi: float | None
    ema9: float | None
    ema21: float | None
    precio: float
    variacion_pct: float
    score_oportunidad: float
    razon: str
    tipo_senal: str  # "ENTRADA_POTENCIAL" | "SOBRECOMPRADO"


class Screener:
    def __init__(self, config: dict = None):
        self.analyzer = Analyzer(config)

    def scan_cedear(self, iol_client, watchlist_actual: list[str]) -> list[ScreenerResult]:
        """
        Escanea el universo ampliado de CEDEARs buscando candidatos de entrada.
        Retorna los top candidatos que NO están ya en la watchlist principal.
        """
        results = []

        # También re-analiza watchlist principal con criterios más estrictos
        universe = list(set(SCREENER_UNIVERSE))

        for ticker in universe:
            try:
                quote = iol_client.get_cedear_quote(ticker)
                history = iol_client.get_cedear_history(ticker, days=50)

                precio = float(quote.get("ultimoPrecio") or quote.get("precio") or 0)
                variacion = float(quote.get("variacionPorcentual") or quote.get("variacion") or 0)
                closes = [float(h.get("ultimoPrecio") or h.get("cierre") or 0) for h in history if h.get("ultimoPrecio") or h.get("cierre")]

                if len(closes) < 22 or precio <= 0:
                    continue

                rsi = _rsi(closes)
                ema9_vals = _ema(closes, 9)
                ema21_vals = _ema(closes, 21)
                ema9 = ema9_vals[-1] if ema9_vals else None
                ema21 = ema21_vals[-1] if ema21_vals else None

                score = 0.0
                razones = []

                # RSI extremo bajo = oportunidad de entrada
                if rsi is not None:
                    if rsi < 25:
                        score += 3.0
                        razones.append(f"RSI muy sobrevendido ({rsi:.1f})")
                    elif rsi < 35:
                        score += 1.5
                        razones.append(f"RSI sobrevendido ({rsi:.1f})")
                    elif rsi > 75:
                        score -= 2.0
                        razones.append(f"RSI sobrecomprado ({rsi:.1f})")

                # EMA setup alcista
                if ema9 and ema21:
                    if ema9 > ema21:
                        score += 1.0
                        razones.append("EMA alcista")
                    elif ema9 < ema21 and rsi and rsi < 35:
                        score += 0.5  # sobrevendido pero tendencia baja = oportunidad contraria

                # Caída reciente grande = posible rebote
                if variacion < -5:
                    score += 1.5
                    razones.append(f"Caída {variacion:.1f}% (posible rebote)")
                elif variacion < -3:
                    score += 0.5
                    razones.append(f"Caída {variacion:.1f}%")

                if score >= 1.5:
                    tipo = "ENTRADA_POTENCIAL" if score >= 0 else "SOBRECOMPRADO"
                    results.append(ScreenerResult(
                        ticker=ticker,
                        rsi=round(rsi, 1) if rsi else None,
                        ema9=round(ema9, 2) if ema9 else None,
                        ema21=round(ema21, 2) if ema21 else None,
                        precio=precio,
                        variacion_pct=variacion,
                        score_oportunidad=round(score, 1),
                        razon=" · ".join(razones),
                        tipo_senal=tipo,
                    ))

            except Exception as e:
                logger.debug(f"Screener skip {ticker}: {e}")

        # Ordenar por score descendente
        results.sort(key=lambda r: r.score_oportunidad, reverse=True)
        return results[:10]  # top 10
