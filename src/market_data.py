"""
market_data.py — Fundamentales y series de precio desde Yahoo Finance.

Gratuito y sin API key. Los CEDEARs cotizan en pesos en bCBA, pero el
subyacente es el papel en Nueva York: los fundamentales (P/E, balance,
precio objetivo) salen de ahí, no de la cotización local.

Todo cachea en memoria: los fundamentales cambian de a días, no de a
minutos, y así el ciclo de 15 minutos no golpea la API 23 veces.
"""

import logging
import time
from datetime import datetime, timezone

import requests

logger = logging.getLogger(__name__)

CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
SUMMARY_URL = "https://query2.finance.yahoo.com/v10/finance/quoteSummary/{symbol}"
TIMEOUT = 12
UA = {"User-Agent": "Mozilla/5.0 (compatible; agente-inversion/1.0)"}

# Tickers locales cuyo subyacente en Nueva York se llama distinto
ALIAS = {
    "YPFD": "YPF",
    "BRKB": "BRK-B",
    "BRK": "BRK-B",
}

# Índice de referencia por tipo de activo
BENCHMARK = {"CEDEAR": "^GSPC", "CRYPTO": "BTC-USD"}

_cache: dict = {}


def _cached(clave: str, ttl: int, productor):
    ahora = time.time()
    hit = _cache.get(clave)
    if hit and ahora - hit[0] < ttl:
        return hit[1]
    try:
        valor = productor()
        if valor is not None:
            _cache[clave] = (ahora, valor)
        return valor
    except Exception as e:
        logger.debug(f"market_data {clave}: {e}")
        return hit[1] if hit else None


def _symbol(ticker: str, tipo: str) -> str:
    if tipo == "CRYPTO":
        # BTCUSDT -> BTC-USD
        base = ticker.replace("USDT", "").replace("USD", "")
        return f"{base}-USD"
    return ALIAS.get(ticker, ticker)


# ─── Serie de precios ────────────────────────────────────────────────────

def get_series(ticker: str, tipo: str = "CEDEAR", rango: str = "1y", intervalo: str = "1d"):
    """
    Serie histórica del subyacente. Devuelve
    {closes, highs, lows, volumes, timestamps, moneda} o None.
    """
    sym = _symbol(ticker, tipo)

    def traer():
        r = requests.get(
            CHART_URL.format(symbol=sym),
            params={"range": rango, "interval": intervalo},
            headers=UA, timeout=TIMEOUT,
        )
        if r.status_code != 200:
            logger.debug(f"Yahoo chart {sym}: HTTP {r.status_code}")
            return None
        res = (r.json().get("chart") or {}).get("result") or []
        if not res:
            return None
        d = res[0]
        q = (d.get("indicators", {}).get("quote") or [{}])[0]
        meta = d.get("meta", {})
        closes = [c for c in (q.get("close") or []) if c is not None]
        if len(closes) < 30:
            return None
        return {
            "closes": closes,
            "highs": [h for h in (q.get("high") or []) if h is not None],
            "lows": [l for l in (q.get("low") or []) if l is not None],
            "volumes": [v for v in (q.get("volume") or []) if v is not None],
            "timestamps": d.get("timestamp") or [],
            "moneda": meta.get("currency", ""),
            "simbolo": sym,
        }

    return _cached(f"serie:{sym}:{rango}:{intervalo}", 1800, traer)


# ─── Fundamentales ───────────────────────────────────────────────────────

MODULOS = "summaryDetail,defaultKeyStatistics,financialData,calendarEvents,price"


def get_fundamentals(ticker: str, tipo: str = "CEDEAR") -> dict | None:
    """P/E, capitalización, dividendos, próximo balance, precio objetivo, consenso."""
    if tipo == "CRYPTO":
        return None
    sym = _symbol(ticker, tipo)

    def traer():
        r = requests.get(
            SUMMARY_URL.format(symbol=sym),
            params={"modules": MODULOS}, headers=UA, timeout=TIMEOUT,
        )
        if r.status_code != 200:
            logger.debug(f"Yahoo summary {sym}: HTTP {r.status_code}")
            return None
        res = (r.json().get("quoteSummary") or {}).get("result") or []
        if not res:
            return None
        d = res[0]
        sd = d.get("summaryDetail") or {}
        ks = d.get("defaultKeyStatistics") or {}
        fd = d.get("financialData") or {}
        ce = d.get("calendarEvents") or {}
        px = d.get("price") or {}

        def val(obj, key):
            v = (obj or {}).get(key)
            if isinstance(v, dict):
                return v.get("raw")
            return v if isinstance(v, (int, float)) else None

        out = {
            "nombre": px.get("longName") or px.get("shortName") or "",
            "moneda": px.get("currency", ""),
            "precio_usd": val(px, "regularMarketPrice"),
            "per": val(sd, "trailingPE"),
            "per_futuro": val(sd, "forwardPE"),
            "capitalizacion": val(px, "marketCap") or val(sd, "marketCap"),
            "dividendo_pct": (val(sd, "dividendYield") or 0) * 100 or None,
            "beta": val(ks, "beta"),
            "max_52s": val(sd, "fiftyTwoWeekHigh"),
            "min_52s": val(sd, "fiftyTwoWeekLow"),
            "precio_objetivo": val(fd, "targetMeanPrice"),
            "recomendacion": (fd or {}).get("recommendationKey"),
            "analistas": val(fd, "numberOfAnalystOpinions"),
            "margen_pct": (val(fd, "profitMargins") or 0) * 100 or None,
            "crecimiento_ventas_pct": (val(fd, "revenueGrowth") or 0) * 100 or None,
            "deuda_capital": val(fd, "debtToEquity"),
        }

        # Próximo balance: dato clave para decidir entradas
        try:
            fechas = ((ce.get("earnings") or {}).get("earningsDate") or [])
            if fechas:
                ts = fechas[0].get("raw") if isinstance(fechas[0], dict) else fechas[0]
                if ts:
                    fecha = datetime.fromtimestamp(ts, tz=timezone.utc)
                    out["proximo_balance"] = fecha.strftime("%Y-%m-%d")
                    dias = (fecha - datetime.now(timezone.utc)).days
                    out["dias_al_balance"] = dias
        except Exception:
            pass

        # Potencial hasta el precio objetivo de los analistas
        if out.get("precio_objetivo") and out.get("precio_usd"):
            out["potencial_pct"] = round(
                (out["precio_objetivo"] / out["precio_usd"] - 1) * 100, 1
            )
        return {k: v for k, v in out.items() if v not in (None, "", 0)}

    return _cached(f"fund:{sym}", 21600, traer)  # 6 horas


# ─── Fuerza relativa ─────────────────────────────────────────────────────

def fuerza_relativa(ticker: str, tipo: str, periodos=(21, 63)) -> dict | None:
    """
    Compara el rendimiento del papel contra su índice.
    Positivo = le está ganando al mercado.
    """
    serie = get_series(ticker, tipo)
    bench_sym = BENCHMARK.get(tipo, "^GSPC")
    bench = _cached(
        f"bench:{bench_sym}", 1800,
        lambda: _serie_simbolo(bench_sym),
    )
    if not serie or not bench:
        return None

    out = {}
    for p in periodos:
        a, b = serie["closes"], bench["closes"]
        if len(a) < p + 1 or len(b) < p + 1:
            continue
        try:
            r_papel = (a[-1] / a[-(p + 1)] - 1) * 100
            r_bench = (b[-1] / b[-(p + 1)] - 1) * 100
            out[f"rs_{p}"] = round(r_papel - r_bench, 1)
            out[f"ret_{p}"] = round(r_papel, 1)
        except Exception:
            pass
    return out or None


def _serie_simbolo(sym: str):
    r = requests.get(
        CHART_URL.format(symbol=sym),
        params={"range": "1y", "interval": "1d"}, headers=UA, timeout=TIMEOUT,
    )
    if r.status_code != 200:
        return None
    res = (r.json().get("chart") or {}).get("result") or []
    if not res:
        return None
    q = (res[0].get("indicators", {}).get("quote") or [{}])[0]
    closes = [c for c in (q.get("close") or []) if c is not None]
    return {"closes": closes} if len(closes) >= 30 else None


# ─── Verificación al arranque ────────────────────────────────────────────

def autotest() -> bool:
    """Confirma que Yahoo es alcanzable desde este contenedor."""
    s = get_series("AAPL", "CEDEAR")
    f = get_fundamentals("AAPL", "CEDEAR")
    ok_s, ok_f = bool(s and s.get("closes")), bool(f)
    logger.info(
        f"[market_data] Yahoo alcanzable: serie={'si' if ok_s else 'NO'} "
        f"({len(s['closes']) if ok_s else 0} velas) · fundamentales={'si' if ok_f else 'NO'}"
        + (f" · P/E={f.get('per')} objetivo={f.get('precio_objetivo')}" if ok_f else "")
    )
    return ok_s
