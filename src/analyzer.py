"""
Analyzer — Motor de senales tecnicas
RSI(14), EMA(9/21), volumen spike, variacion de precio
"""

import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class Signal:
    ticker: str
    tipo: str           # CEDEAR | CRYPTO
    precio: float
    variacion_pct: float
    senal: str          # BUY | SELL | NEUTRAL | WATCH
    fuerza: str         # FUERTE | MODERADA | DEBIL
    motivos: list[str] = field(default_factory=list)
    indicadores: dict = field(default_factory=dict)


def _ema(values: list[float], period: int) -> list[float]:
    if len(values) < period:
        return []
    k = 2 / (period + 1)
    ema = [sum(values[:period]) / period]
    for v in values[period:]:
        ema.append(v * k + ema[-1] * (1 - k))
    return ema


def _rsi(closes: list[float], period: int = 14) -> float | None:
    if len(closes) < period + 1:
        return None
    gains, losses = [], []
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i - 1]
        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def _score_to_signal(score: int) -> tuple[str, str]:
    if score >= 3:
        return "BUY", "FUERTE"
    elif score == 2:
        return "BUY", "MODERADA"
    elif score == 1:
        return "WATCH", "DEBIL"
    elif score == -1:
        return "WATCH", "DEBIL"
    elif score == -2:
        return "SELL", "MODERADA"
    elif score <= -3:
        return "SELL", "FUERTE"
    return "NEUTRAL", "DEBIL"


class Analyzer:
    def __init__(self, config: dict = None):
        cfg = config or {}
        self.rsi_oversold = float(cfg.get("rsi_oversold", 30))
        self.rsi_overbought = float(cfg.get("rsi_overbought", 70))
        self.price_change_alert = float(cfg.get("price_change_alert", 3.0))
        self.volume_spike_mult = float(cfg.get("volume_spike_mult", 2.0))

    def analyze_cedear(self, ticker: str, quote: dict, history: list[dict]) -> Signal | None:
        try:
            precio = float(quote.get("ultimoPrecio") or quote.get("precio") or 0)
            variacion = float(quote.get("variacionPorcentual") or quote.get("variacion") or 0)
            volumen = float(quote.get("volumen") or quote.get("cantidadOperada") or 0)

            closes = [float(h.get("ultimoPrecio") or h.get("cierre") or 0) for h in history if h.get("ultimoPrecio") or h.get("cierre")]
            volumes = [float(h.get("volumen") or h.get("cantidadOperada") or 0) for h in history if h.get("volumen") or h.get("cantidadOperada")]

            if len(closes) < 22:
                logger.warning(f"{ticker}: historial insuficiente ({len(closes)} velas)")
                return None

            return self._build_signal(ticker, "CEDEAR", precio, variacion, closes, volumes, volumen)
        except Exception as e:
            logger.error(f"Error analizando CEDEAR {ticker}: {e}")
            return None

    def analyze_crypto(self, symbol: str, ticker_24h: dict, klines: list[dict]) -> Signal | None:
        try:
            precio = ticker_24h["price"]
            variacion = ticker_24h["change_pct"]
            volumen = klines[-1]["volume"] if klines else 0

            closes = [k["close"] for k in klines]
            volumes = [k["volume"] for k in klines]

            if len(closes) < 22:
                return None

            return self._build_signal(symbol, "CRYPTO", precio, variacion, closes, volumes, volumen)
        except Exception as e:
            logger.error(f"Error analizando crypto {symbol}: {e}")
            return None

    def _build_signal(
        self,
        ticker: str,
        tipo: str,
        precio: float,
        variacion: float,
        closes: list[float],
        volumes: list[float],
        vol_actual: float,
    ) -> Signal | None:
        score = 0
        motivos = []
        indicadores = {}

        # RSI
        rsi = _rsi(closes)
        if rsi is not None:
            indicadores["rsi"] = round(rsi, 2)
            if rsi < self.rsi_oversold:
                score += 2
                motivos.append(f"RSI sobrevendido ({rsi:.1f})")
            elif rsi > self.rsi_overbought:
                score -= 2
                motivos.append(f"RSI sobrecomprado ({rsi:.1f})")

        # EMA crossover
        ema9 = _ema(closes, 9)
        ema21 = _ema(closes, 21)
        if len(ema9) >= 2 and len(ema21) >= 2:
            indicadores["ema_short"] = round(ema9[-1], 4)
            indicadores["ema_long"] = round(ema21[-1], 4)
            if ema9[-1] > ema21[-1] and ema9[-2] <= ema21[-2]:
                score += 2
                motivos.append("Cruce alcista EMA9 > EMA21")
            elif ema9[-1] < ema21[-1] and ema9[-2] >= ema21[-2]:
                score -= 2
                motivos.append("Cruce bajista EMA9 < EMA21")
            elif ema9[-1] > ema21[-1]:
                score += 1
                motivos.append("EMA9 sobre EMA21 (tendencia alcista)")
            elif ema9[-1] < ema21[-1]:
                score -= 1
                motivos.append("EMA9 bajo EMA21 (tendencia bajista)")

        # Volumen spike
        if volumes and len(volumes) >= 20:
            avg_vol = sum(volumes[-20:]) / 20
            if avg_vol > 0 and vol_actual > avg_vol * self.volume_spike_mult:
                vol_ratio = round(vol_actual / avg_vol, 1)
                indicadores["vol_ratio"] = vol_ratio
                motivos.append(f"Volumen {vol_ratio}x el promedio")
                score += 1 if score > 0 else -1

        # Variacion de precio
        abs_var = abs(variacion)
        if abs_var >= self.price_change_alert:
            indicadores["cambio_ultima_vela"] = round(variacion, 2)
            if variacion > 0:
                score += 1
                motivos.append(f"Subio {variacion:.1f}% en la sesion")
            else:
                score -= 1
                motivos.append(f"Bajo {abs(variacion):.1f}% en la sesion")

        if score == 0 and not motivos:
            return None

        senal, fuerza = _score_to_signal(score)
        return Signal(
            ticker=ticker,
            tipo=tipo,
            precio=precio,
            variacion_pct=variacion,
            senal=senal,
            fuerza=fuerza,
            motivos=motivos,
            indicadores=indicadores,
        )
