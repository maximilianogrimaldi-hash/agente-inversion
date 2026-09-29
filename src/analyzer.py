"""
Analyzer — Motor de señales técnicas.

Indicadores: RSI(14), EMA(9/21), SMA(50/200), MACD(12/26/9),
Bandas de Bollinger(20,2), ATR(14), momentum 5d/20d, soporte/resistencia,
pendiente de medias, volumen vs promedio y distancia desde máximos.

El puntaje es ponderado por confluencia: cada familia de indicadores
aporta como máximo su peso, así que FUERTE significa que varias
señales independientes coinciden, no que una sola se disparó.

Semáforo por familia (verde/amarillo/rojo) más condiciones explícitas
de confirmación para que el sistema distinga "corrección recuperable"
de "ruptura de estructura".
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
    # Tipo de alerta para distinguir corrección vs ruptura estructural
    tipo_senal: str = "tecnica"  # "tecnica" | "cartera"


# ─── Primitivas ──────────────────────────────────────────────────────────

def _sma(values: list[float], period: int) -> float | None:
    if len(values) < period:
        return None
    return sum(values[-period:]) / period


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


def _macd(closes: list[float], fast: int = 12, slow: int = 26, signal: int = 9):
    """Devuelve (macd, señal, histograma, histograma_previo) o None."""
    if len(closes) < slow + signal:
        return None
    ema_fast = _ema(closes, fast)
    ema_slow = _ema(closes, slow)
    if not ema_fast or not ema_slow:
        return None
    n = min(len(ema_fast), len(ema_slow))
    macd_line = [ema_fast[-n:][i] - ema_slow[-n:][i] for i in range(n)]
    signal_line = _ema(macd_line, signal)
    if len(signal_line) < 2:
        return None
    hist = macd_line[-1] - signal_line[-1]
    hist_prev = macd_line[-2] - signal_line[-2]
    return macd_line[-1], signal_line[-1], hist, hist_prev


def _bollinger(closes: list[float], period: int = 20, mult: float = 2.0):
    """Devuelve (banda_inferior, media, banda_superior, pct_b, ancho_pct)."""
    if len(closes) < period:
        return None
    window = closes[-period:]
    media = sum(window) / period
    var = sum((c - media) ** 2 for c in window) / period
    sd = var ** 0.5
    if sd == 0:
        return None
    upper = media + mult * sd
    lower = media - mult * sd
    precio = closes[-1]
    pct_b = (precio - lower) / (upper - lower) if upper != lower else 0.5
    ancho_pct = (upper - lower) / media * 100 if media else 0
    return lower, media, upper, pct_b, ancho_pct


def _atr(highs: list[float], lows: list[float], closes: list[float], period: int = 14):
    """Average True Range. Devuelve (atr, atr_pct_sobre_precio)."""
    n = min(len(highs), len(lows), len(closes))
    if n < period + 1:
        return None
    highs, lows, closes = highs[-n:], lows[-n:], closes[-n:]
    trs = []
    for i in range(1, n):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
        trs.append(tr)
    if len(trs) < period:
        return None
    atr = sum(trs[-period:]) / period
    precio = closes[-1]
    return atr, (atr / precio * 100 if precio else 0)


def _roc(closes: list[float], period: int) -> float | None:
    """Rate of change porcentual."""
    if len(closes) < period + 1:
        return None
    antes = closes[-(period + 1)]
    if antes == 0:
        return None
    return (closes[-1] - antes) / antes * 100


def _posicion_rango(closes: list[float], lookback: int = 252):
    """Dónde está el precio dentro del rango del período. 0 = mínimo, 100 = máximo."""
    window = closes[-lookback:] if len(closes) >= 20 else closes
    if not window:
        return None
    mx, mn = max(window), min(window)
    if mx == mn:
        return None
    precio = closes[-1]
    pos = (precio - mn) / (mx - mn) * 100
    return {
        "maximo": round(mx, 2),
        "minimo": round(mn, 2),
        "posicion_pct": round(pos, 1),
        "dist_maximo_pct": round((precio - mx) / mx * 100, 2) if mx else None,
        "dist_minimo_pct": round((precio - mn) / mn * 100, 2) if mn else None,
        "velas": len(window),
    }


def _soporte_resistencia(highs: list[float], lows: list[float], closes: list[float]):
    """Swing highs/lows recientes más cercanos al precio actual."""
    n = min(len(highs), len(lows))
    if n < 12:
        return None
    highs, lows = highs[-n:], lows[-n:]
    precio = closes[-1]
    pivots_alto, pivots_bajo = [], []
    for i in range(2, n - 2):
        if highs[i] == max(highs[i - 2:i + 3]):
            pivots_alto.append(highs[i])
        if lows[i] == min(lows[i - 2:i + 3]):
            pivots_bajo.append(lows[i])
    resistencia = min([p for p in pivots_alto if p > precio], default=None)
    soporte = max([p for p in pivots_bajo if p < precio], default=None)
    out = {}
    if resistencia:
        out["resistencia"] = round(resistencia, 2)
        out["dist_resistencia_pct"] = round((resistencia - precio) / precio * 100, 2)
    if soporte:
        out["soporte"] = round(soporte, 2)
        out["dist_soporte_pct"] = round((precio - soporte) / precio * 100, 2)
    return out or None


def _pendiente(values: list[float], period: int) -> float | None:
    """Pendiente lineal normalizada sobre el período (% por vela)."""
    if len(values) < period:
        return None
    seg = values[-period:]
    n = len(seg)
    x_mean = (n - 1) / 2
    y_mean = sum(seg) / n
    num = sum((i - x_mean) * (seg[i] - y_mean) for i in range(n))
    den = sum((i - x_mean) ** 2 for i in range(n))
    if den == 0 or y_mean == 0:
        return None
    return round(num / den / y_mean * 100, 3)  # %/vela


def _distancia_maximos(closes: list[float]):
    """Distancia desde el máximo en distintos períodos."""
    precio = closes[-1]
    if precio == 0:
        return {}
    out = {}
    for periodo, label in [(252, "52s"), (126, "6m"), (63, "3m")]:
        seg = closes[-periodo:] if len(closes) >= periodo else closes
        mx = max(seg)
        if mx > 0:
            dist = (precio - mx) / mx * 100
            out[f"dist_max_{label}"] = round(dist, 1)
    return out


def _semaforo_bloques(ind: dict, senal: str) -> dict:
    """
    Semáforo por familia de indicadores: verde/amarillo/rojo.
    Ayuda a ver de un vistazo cuántas familias coinciden.
    """
    s = {}

    # Tendencia
    tend = ind.get("tendencias", {})
    al = tend.get("alineacion", "")
    if al == "todo alcista":
        s["tendencia"] = "verde"
    elif al == "todo bajista":
        s["tendencia"] = "rojo"
    elif al == "mixta":
        s["tendencia"] = "amarillo"
    else:
        s["tendencia"] = "gris"

    # RSI
    rsi = ind.get("rsi")
    if rsi is not None:
        if rsi < 30:
            s["rsi"] = "verde"
        elif rsi > 70:
            s["rsi"] = "rojo"
        elif 40 <= rsi <= 60:
            s["rsi"] = "amarillo"
        else:
            s["rsi"] = "verde" if rsi < 50 else "rojo"

    # MACD
    hist = ind.get("macd_hist")
    if hist is not None:
        s["macd"] = "verde" if hist > 0 else "rojo"

    # Bollinger
    pct_b = ind.get("bb_pct")
    if pct_b is not None:
        if pct_b < 20:
            s["bollinger"] = "verde"
        elif pct_b > 80:
            s["bollinger"] = "rojo"
        else:
            s["bollinger"] = "amarillo"

    # Volumen
    vr = ind.get("vol_ratio")
    if vr is not None:
        s["volumen"] = "verde" if vr >= 1.5 else ("amarillo" if vr >= 0.8 else "rojo")

    # Soporte/resistencia
    soporte = ind.get("soporte")
    resistencia = ind.get("resistencia")
    if soporte or resistencia:
        dist_s = ind.get("dist_soporte_pct", 999)
        dist_r = ind.get("dist_resistencia_pct", 999)
        if dist_s < 2:
            s["soportes"] = "verde"   # muy cerca del soporte = oportunidad
        elif dist_r < 2:
            s["soportes"] = "rojo"    # muy cerca de resistencia = techo
        else:
            s["soportes"] = "amarillo"

    return s


def _condiciones_confirmacion(ind: dict, senal: str) -> list[str]:
    """
    Condiciones explícitas que, si se cumplen, confirmarían o invalidarían la señal.
    Cruciales para no entrar antes de tiempo.
    """
    conds = []
    tend = ind.get("tendencias", {})
    rsi = ind.get("rsi")
    macd_hist = ind.get("macd_hist")
    soporte = ind.get("soporte")
    resistencia = ind.get("resistencia")
    vr = ind.get("vol_ratio", 1)
    ema21 = ind.get("ema21")
    sma200 = ind.get("sma200")
    precio = ind.get("precio_actual")

    if senal == "BUY":
        if tend.get("corto") == "bajista":
            conds.append("⏳ Esperar cruce alcista EMA9/EMA21 en vela diaria")
        if rsi and rsi > 60:
            conds.append("⏳ RSI sobre 60 — esperar pullback antes de entrar")
        if macd_hist and macd_hist < 0:
            conds.append("⏳ MACD aún negativo — confirmar giro del histograma")
        if resistencia:
            dist_r = ind.get("dist_resistencia_pct", 0)
            conds.append(f"🎯 Resistencia en ${resistencia} ({dist_r:+.1f}%) — tomar ganancia ahí")
        if vr < 1.0:
            conds.append("⏳ Volumen bajo promedio — buscar confirmación con volumen")
        if not conds:
            conds.append("✅ Señal con múltiple confluencia — puede entrar con stop definido")

    elif senal == "SELL":
        if tend.get("corto") == "alcista":
            conds.append("⏳ Esperar confirmación bajista — EMA9 aún sobre EMA21")
        if rsi and rsi < 40:
            conds.append("⏳ RSI muy bajo — posible rebote técnico antes de continuar")
        if macd_hist and macd_hist > 0:
            conds.append("⏳ MACD aún positivo — confirmar cruce bajista")
        if soporte:
            dist_s = ind.get("dist_soporte_pct", 0)
            conds.append(f"🛡️ Soporte en ${soporte} ({dist_s:.1f}% abajo) — posible rebote")
        if not conds:
            conds.append("⚠️ Señal de venta confirmada — considerar reducir exposición")

    elif senal == "WATCH":
        conds.append("👀 Monitorear: todavía no hay señal clara")
        if tend.get("alineacion") == "mixta":
            conds.append("↔️ Tendencia mixta — esperar alineación de medias")

    return conds[:4]  # máximo 4 condiciones


# ─── Puntaje ─────────────────────────────────────────────────────────────

PESOS = {
    "rsi": 2.5,
    "macd": 2.0,
    "tendencia": 2.0,
    "bollinger": 1.5,
    "momentum": 1.5,
    "rango": 1.0,
    "volumen": 0.8,
    "variacion": 0.7,
}


def _tendencias_por_plazo(closes: list[float], precio: float) -> dict:
    """
    Separa la tendencia en tres horizontes e incluye la pendiente
    de cada media para saber si está acelerando o frenando.
    """
    out = {}
    ema9, ema21 = _ema(closes, 9), _ema(closes, 21)
    sma50, sma200 = _sma(closes, 50), _sma(closes, 200)

    if ema9 and ema21:
        out["corto"] = "alcista" if ema9[-1] > ema21[-1] else "bajista"
        out["ema9_v"] = round(ema9[-1], 2)
        out["ema21_v"] = round(ema21[-1], 2)

    if sma50:
        out["medio"] = "alcista" if precio > sma50 else "bajista"
        out["sma50_v"] = round(sma50, 2)
        pend50 = _pendiente([_sma(closes[:-i] if i else closes, 50) or 0 for i in range(10, -1, -1)], 10)
        if pend50 is not None:
            out["sma50_pendiente"] = pend50

    if sma200:
        out["largo"] = "alcista" if precio > sma200 else "bajista"
        out["sma200_v"] = round(sma200, 2)
        if sma50:
            out["cruce"] = "dorado" if sma50 > sma200 else "muerte"

    votos = [v for k, v in out.items() if k in ("corto", "medio", "largo")]
    if votos:
        alcistas = votos.count("alcista")
        if alcistas == len(votos):
            out["alineacion"] = "todo alcista"
        elif alcistas == 0:
            out["alineacion"] = "todo bajista"
        else:
            out["alineacion"] = "mixta"
    return out


def _caja_riesgo(precio: float, atr: float | None, soporte: float | None,
                 resistencia: float | None) -> dict:
    """
    Stop sugerido a 2 ATR (o bajo el soporte, lo que esté más cerca) y
    relación riesgo/beneficio hasta la resistencia.
    """
    if not precio or not atr:
        return {}
    stop_atr = precio - 2 * atr
    stop = max(stop_atr, soporte * 0.99) if soporte and soporte < precio else stop_atr
    if stop <= 0 or stop >= precio:
        return {}

    riesgo_pct = (precio - stop) / precio * 100
    out = {
        "stop_sugerido": round(stop, 2),
        "riesgo_pct": round(riesgo_pct, 2),
    }
    if resistencia and resistencia > precio:
        beneficio = resistencia - precio
        riesgo = precio - stop
        out["objetivo"] = round(resistencia, 2)
        out["beneficio_pct"] = round(beneficio / precio * 100, 2)
        if riesgo > 0:
            out["ratio_rb"] = round(beneficio / riesgo, 2)
    return out


def _es_senal_cartera(ind: dict, senal: str) -> bool:
    """
    Distingue 'señal técnica' (corrección recuperable) de 'señal de cartera'
    (ruptura estructural que requiere acción urgente en el portfolio).

    Una ruptura estructural requiere que MÚLTIPLES condiciones clave fallen
    simultáneamente, no que una sola señal sea negativa.
    """
    if senal not in ("BUY", "SELL"):
        return False

    tend = ind.get("tendencias", {})
    sma200 = ind.get("sma200")
    soporte = ind.get("soporte")
    resistencia = ind.get("resistencia")
    precio = ind.get("precio_actual", 0)
    vr = ind.get("vol_ratio", 1)
    rsi = ind.get("rsi", 50)

    if senal == "SELL":
        condiciones = 0
        # Rompió SMA200 (tendencia de fondo perdida)
        if sma200 and precio and precio < sma200 * 0.99:
            condiciones += 1
        # Rompió soporte importante
        if soporte and precio and precio < soporte * 0.98:
            condiciones += 1
        # Volumen elevado (la ruptura es real, no fake)
        if vr and vr >= 1.5:
            condiciones += 1
        # RSI saliendo de sobrecompra con momentum negativo
        if rsi and rsi < 45 and tend.get("alineacion") == "todo bajista":
            condiciones += 1
        return condiciones >= 2  # Al menos 2 condiciones = ruptura estructural

    elif senal == "BUY":
        condiciones = 0
        # Recuperó SMA200
        if sma200 and precio and precio > sma200 * 1.005:
            condiciones += 1
        # Rebotó en soporte con volumen
        if soporte and precio and abs(precio - soporte) / precio < 0.02:
            condiciones += 1
        # Volumen confirmando
        if vr and vr >= 1.5:
            condiciones += 1
        # RSI saliendo de sobreventa con momentum positivo
        if rsi and rsi < 40 and tend.get("alineacion") in ("todo alcista", "mixta"):
            condiciones += 1
        return condiciones >= 2

    return False


def _clasificar(score: float) -> tuple[str, str]:
    """Mapea el puntaje ponderado a señal y fuerza."""
    if score >= 4.5:
        return "BUY", "FUERTE"
    if score >= 2.5:
        return "BUY", "MODERADA"
    if score >= 1.2:
        return "WATCH", "DEBIL"
    if score <= -4.5:
        return "SELL", "FUERTE"
    if score <= -2.5:
        return "SELL", "MODERADA"
    if score <= -1.2:
        return "WATCH", "DEBIL"
    return "NEUTRAL", "DEBIL"


class Analyzer:
    def __init__(self, config: dict = None):
        cfg = config or {}
        self.rsi_oversold = float(cfg.get("rsi_oversold", 30))
        self.rsi_overbought = float(cfg.get("rsi_overbought", 70))
        self.price_change_alert = float(cfg.get("price_change_alert", 3.0))
        self.volume_spike_mult = float(cfg.get("volume_spike_mult", 2.0))

    # ─── Entradas ────────────────────────────────────────────────────────

    def analyze_cedear(self, ticker: str, quote: dict, history: list[dict]) -> Signal | None:
        try:
            precio = float(quote.get("ultimoPrecio") or quote.get("precio") or 0)
            variacion = float(quote.get("variacionPorcentual") or quote.get("variacion") or 0)
            volumen = float(quote.get("volumen") or quote.get("cantidadOperada") or 0)

            closes, highs, lows, volumes = [], [], [], []
            for h in history:
                c = h.get("ultimoPrecio") or h.get("cierre")
                if not c:
                    continue
                c = float(c)
                closes.append(c)
                highs.append(float(h.get("maximo") or c))
                lows.append(float(h.get("minimo") or c))
                volumes.append(float(h.get("volumen") or h.get("cantidadOperada") or 0))

            if len(closes) < 22:
                logger.warning(f"{ticker}: historial insuficiente ({len(closes)} velas)")
                return None

            return self._build_signal(
                ticker, "CEDEAR", precio, variacion, closes, highs, lows, volumes, volumen
            )
        except Exception as e:
            logger.error(f"Error analizando CEDEAR {ticker}: {e}")
            return None

    def analyze_crypto(self, symbol: str, ticker_24h: dict, klines: list[dict]) -> Signal | None:
        try:
            precio = ticker_24h["price"]
            variacion = ticker_24h["change_pct"]
            volumen = klines[-1]["volume"] if klines else 0

            closes = [k["close"] for k in klines]
            highs = [k.get("high", k["close"]) for k in klines]
            lows = [k.get("low", k["close"]) for k in klines]
            volumes = [k["volume"] for k in klines]

            if len(closes) < 22:
                return None

            return self._build_signal(
                symbol, "CRYPTO", precio, variacion, closes, highs, lows, volumes, volumen
            )
        except Exception as e:
            logger.error(f"Error analizando crypto {symbol}: {e}")
            return None

    # ─── Núcleo ──────────────────────────────────────────────────────────

    def _build_signal(
        self,
        ticker: str,
        tipo: str,
        precio: float,
        variacion: float,
        closes: list[float],
        highs: list[float],
        lows: list[float],
        volumes: list[float],
        vol_actual: float,
    ) -> Signal | None:
        score = 0.0
        motivos: list[str] = []
        ind: dict = {}

        # Guardamos el precio actual para funciones auxiliares
        ind["precio_actual"] = precio

        # ── RSI ──────────────────────────────────────────────────────────
        rsi = _rsi(closes)
        if rsi is not None:
            ind["rsi"] = round(rsi, 1)
            p = PESOS["rsi"]
            if rsi < 20:
                score += p
                motivos.append(f"RSI en zona extrema de sobreventa ({rsi:.0f})")
            elif rsi < self.rsi_oversold:
                score += p * 0.7
                motivos.append(f"RSI sobrevendido ({rsi:.0f})")
            elif rsi > 80:
                score -= p
                motivos.append(f"RSI en zona extrema de sobrecompra ({rsi:.0f})")
            elif rsi > self.rsi_overbought:
                score -= p * 0.7
                motivos.append(f"RSI sobrecomprado ({rsi:.0f})")

        # ── MACD ─────────────────────────────────────────────────────────
        macd = _macd(closes)
        if macd:
            macd_line, signal_line, hist, hist_prev = macd
            ind["macd"] = round(macd_line, 4)
            ind["macd_signal"] = round(signal_line, 4)
            ind["macd_hist"] = round(hist, 4)
            p = PESOS["macd"]
            if hist > 0 and hist_prev <= 0:
                score += p
                motivos.append("MACD cruzó al alza su señal")
            elif hist < 0 and hist_prev >= 0:
                score -= p
                motivos.append("MACD cruzó a la baja su señal")
            elif hist > 0:
                score += p * 0.4
                motivos.append("MACD sobre su señal (impulso comprador)")
            elif hist < 0:
                score -= p * 0.4
                motivos.append("MACD bajo su señal (impulso vendedor)")

        # ── Tendencia: EMA9/21 + SMA50/200 ───────────────────────────────
        p = PESOS["tendencia"]
        sub = 0.0
        ema9_v, ema21_v = _ema(closes, 9), _ema(closes, 21)
        if len(ema9_v) >= 2 and len(ema21_v) >= 2:
            ind["ema9"] = round(ema9_v[-1], 2)
            ind["ema21"] = round(ema21_v[-1], 2)
            if ema9_v[-1] > ema21_v[-1] and ema9_v[-2] <= ema21_v[-2]:
                sub += 0.6
                motivos.append("Cruce alcista EMA9/EMA21")
            elif ema9_v[-1] < ema21_v[-1] and ema9_v[-2] >= ema21_v[-2]:
                sub -= 0.6
                motivos.append("Cruce bajista EMA9/EMA21")
            elif ema9_v[-1] > ema21_v[-1]:
                sub += 0.25
            else:
                sub -= 0.25

        sma50, sma200 = _sma(closes, 50), _sma(closes, 200)
        if sma50:
            ind["sma50"] = round(sma50, 2)
        if sma200:
            ind["sma200"] = round(sma200, 2)
        if sma50 and sma200:
            if sma50 > sma200:
                sub += 0.4
                ind["tendencia_larga"] = "alcista"
                if precio > sma200:
                    motivos.append("Tendencia de fondo alcista (SMA50 > SMA200)")
            else:
                sub -= 0.4
                ind["tendencia_larga"] = "bajista"
                if precio < sma200:
                    motivos.append("Tendencia de fondo bajista (SMA50 < SMA200)")
        elif sma50:
            ind["tendencia_larga"] = "alcista" if precio > sma50 else "bajista"
            sub += 0.2 if precio > sma50 else -0.2

        score += max(-p, min(p, sub * p))

        # ── Bollinger ────────────────────────────────────────────────────
        bb = _bollinger(closes)
        if bb:
            lower, media, upper, pct_b, ancho = bb
            ind["bb_inferior"] = round(lower, 2)
            ind["bb_media"] = round(media, 2)
            ind["bb_superior"] = round(upper, 2)
            ind["bb_pct"] = round(pct_b * 100, 1)
            ind["bb_ancho_pct"] = round(ancho, 1)
            p = PESOS["bollinger"]
            if pct_b <= 0.05:
                score += p
                motivos.append("Precio tocando la banda inferior de Bollinger")
            elif pct_b < 0.2:
                score += p * 0.5
                motivos.append(f"En la zona baja del canal de Bollinger ({pct_b*100:.0f}%)")
            elif pct_b >= 0.95:
                score -= p
                motivos.append("Precio tocando la banda superior de Bollinger")
            elif pct_b > 0.8:
                score -= p * 0.5
                motivos.append(f"En la zona alta del canal de Bollinger ({pct_b*100:.0f}%)")
            if ancho < 6:
                ind["bb_squeeze"] = True
                motivos.append(f"Bandas comprimidas ({ancho:.1f}%): posible movimiento fuerte")

        # ── Momentum ─────────────────────────────────────────────────────
        roc5, roc20 = _roc(closes, 5), _roc(closes, 20)
        if roc5 is not None:
            ind["roc_5"] = round(roc5, 2)
        if roc20 is not None:
            ind["roc_20"] = round(roc20, 2)
        if roc5 is not None and roc20 is not None:
            p = PESOS["momentum"]
            if roc5 > 0 and roc20 > 0:
                score += p * 0.6
                motivos.append(f"Sube en 5 y 20 velas ({roc5:+.1f}% / {roc20:+.1f}%)")
            elif roc5 < 0 and roc20 < 0:
                score -= p * 0.6
                motivos.append(f"Baja en 5 y 20 velas ({roc5:+.1f}% / {roc20:+.1f}%)")
            elif roc5 > 0 and roc20 < 0:
                score += p * 0.3
                motivos.append(f"Momentum girando al alza ({roc5:+.1f}% en 5 velas)")
            elif roc5 < 0 and roc20 > 0:
                score -= p * 0.3
                motivos.append(f"Momentum girando a la baja ({roc5:+.1f}% en 5 velas)")

        # ── Posición en el rango ─────────────────────────────────────────
        rango = _posicion_rango(closes)
        if rango:
            ind["rango"] = rango
            p = PESOS["rango"]
            pos = rango["posicion_pct"]
            if pos <= 10:
                score += p
                motivos.append(f"Cerca del mínimo del período ({rango['dist_minimo_pct']:+.1f}%)")
            elif pos >= 90:
                score -= p
                motivos.append(f"Cerca del máximo del período ({rango['dist_maximo_pct']:+.1f}%)")

        # ── Volatilidad ──────────────────────────────────────────────────
        atr = _atr(highs, lows, closes)
        if atr:
            ind["atr"] = round(atr[0], 2)
            ind["atr_pct"] = round(atr[1], 2)

        # ── Soporte y resistencia ────────────────────────────────────────
        sr = _soporte_resistencia(highs, lows, closes)
        if sr:
            ind.update(sr)

        # ── Tendencia por plazo ──────────────────────────────────────────
        tend = _tendencias_por_plazo(closes, precio)
        if tend:
            ind["tendencias"] = tend
            if tend.get("alineacion") == "todo alcista":
                motivos.append("Tendencia alineada al alza en los tres plazos")
            elif tend.get("alineacion") == "todo bajista":
                motivos.append("Tendencia alineada a la baja en los tres plazos")
            elif tend.get("corto") == "alcista" and tend.get("largo") == "alcista" \
                    and tend.get("medio") == "bajista":
                motivos.append("Corrección dentro de una tendencia larga alcista")

        # ── Distancia desde máximos ──────────────────────────────────────
        dist_max = _distancia_maximos(closes)
        if dist_max:
            ind.update(dist_max)
            # Señalar oportunidades de caídas profundas
            d52s = dist_max.get("dist_max_52s")
            if d52s is not None and d52s <= -30:
                motivos.append(f"Cayó {abs(d52s):.0f}% desde máximo de 52 semanas")
            elif d52s is not None and -5 <= d52s <= 0:
                motivos.append(f"Cerca del máximo de 52 semanas ({d52s:+.1f}%)")

        # ── Caja de riesgo ───────────────────────────────────────────────
        riesgo = _caja_riesgo(
            precio,
            atr[0] if atr else None,
            ind.get("soporte"),
            ind.get("resistencia"),
        )
        if riesgo:
            ind["riesgo"] = riesgo
            rb = riesgo.get("ratio_rb")
            if rb and rb >= 2:
                motivos.append(f"Relación riesgo/beneficio favorable ({rb:.1f} a 1)")
            elif rb and rb < 1:
                motivos.append(f"Relación riesgo/beneficio pobre ({rb:.1f} a 1)")

        # ── Volumen ──────────────────────────────────────────────────────
        if volumes and len(volumes) >= 20:
            avg_vol = sum(volumes[-20:]) / 20
            if avg_vol > 0 and vol_actual > 0:
                ratio = vol_actual / avg_vol
                ind["vol_ratio"] = round(ratio, 1)
                if ratio > self.volume_spike_mult:
                    p = PESOS["volumen"]
                    motivos.append(f"Volumen {ratio:.1f}x el promedio de 20 velas")
                    score += p if score > 0 else (-p if score < 0 else 0)

        # ── Variación de la sesión ───────────────────────────────────────
        ind["variacion_pct"] = round(variacion, 2)
        if abs(variacion) >= self.price_change_alert:
            p = PESOS["variacion"]
            if variacion > 0:
                score += p
                motivos.append(f"Subió {variacion:.1f}% en la sesión")
            else:
                score -= p
                motivos.append(f"Bajó {abs(variacion):.1f}% en la sesión")

        # ── Cierre ───────────────────────────────────────────────────────
        score = max(-10.0, min(10.0, score))
        ind["score"] = round(score, 2)

        senal, fuerza = _clasificar(score)
        ind["senal"] = senal
        ind["fuerza"] = fuerza

        # ── Semáforo por familia ─────────────────────────────────────────
        ind["semaforo"] = _semaforo_bloques(ind, senal)

        # ── Condiciones de confirmación ───────────────────────────────────
        ind["confirmacion"] = _condiciones_confirmacion(ind, senal)

        # ── Tipo de señal: técnica vs cartera ────────────────────────────
        es_cartera = _es_senal_cartera(ind, senal)
        tipo_senal = "cartera" if es_cartera else "tecnica"
        ind["tipo_senal"] = tipo_senal

        if not motivos:
            motivos.append("Sin factores destacados")

        return Signal(
            ticker=ticker,
            tipo=tipo,
            precio=precio,
            variacion_pct=variacion,
            senal=senal,
            fuerza=fuerza,
            motivos=motivos,
            indicadores=ind,
            tipo_senal=tipo_senal,
        )
