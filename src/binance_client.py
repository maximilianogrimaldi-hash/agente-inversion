"""
CoinGecko client — reemplaza Binance (bloqueado en Railway us-west2 con error 451).
Mantiene la misma interfaz que el cliente Binance anterior para que
analyzer.py y main.py no necesiten cambios.
"""
import requests
import time
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# Mapa de símbolos estilo Binance → IDs de CoinGecko
SYMBOL_TO_COINGECKO = {
    "BTCUSDT":  "bitcoin",
    "ETHUSDT":  "ethereum",
    "SOLUSDT":  "solana",
    "BNBUSDT":  "binancecoin",
    "XRPUSDT":  "ripple",
    "ADAUSDT":  "cardano",
    "DOGEUSDT": "dogecoin",
    "DOTUSDT":  "polkadot",
    "MATICUSDT":"matic-network",
    "AVAXUSDT": "avalanche-2",
    "LINKUSDT": "chainlink",
    "LTCUSDT":  "litecoin",
    "UNIUSDT":  "uniswap",
    "ATOMUSDT": "cosmos",
}

BASE_URL = "https://api.coingecko.com/api/v3"
RATE_LIMIT_DELAY = 1.2  # segundos entre requests (límite free: ~30/min)


def _symbol_to_id(symbol: str) -> str:
    """Convierte BTCUSDT → bitcoin. Lanza ValueError si no está mapeado."""
    sid = SYMBOL_TO_COINGECKO.get(symbol.upper())
    if not sid:
        raise ValueError(f"Símbolo no mapeado a CoinGecko: {symbol}")
    return sid


def _get(path: str, params: dict = None, retries: int = 3) -> dict | list:
    url = BASE_URL + path
    for attempt in range(retries):
        try:
            resp = requests.get(url, params=params, timeout=15)
            if resp.status_code == 429:
                wait = 60
                logger.warning("CoinGecko rate limit — esperando %ds", wait)
                time.sleep(wait)
                continue
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
            else:
                raise
    raise RuntimeError(f"Fallo tras {retries} intentos: {path}")


# ──────────────────────────────────────────────────────────────────────────────
# Interfaz pública (misma que binance_client.py original)
# ──────────────────────────────────────────────────────────────────────────────

def get_ticker_24h(symbol: str) -> dict:
    """
    Retorna datos de precio/volumen para un símbolo.
    Estructura de retorno idéntica a la del cliente Binance:
    {
        "symbol": str,
        "price": float,
        "change_pct": float,    # variación 24h en %
        "volume": float,        # volumen en USD
        "high": float,
        "low": float,
        "volume_quote": float,  # alias de volume para compatibilidad
    }
    """
    cg_id = _symbol_to_id(symbol)
    data = _get("/coins/markets", params={
        "vs_currency": "usd",
        "ids": cg_id,
        "price_change_percentage": "24h",
    })
    if not data:
        raise ValueError(f"CoinGecko no devolvió datos para {cg_id}")
    coin = data[0]
    time.sleep(RATE_LIMIT_DELAY)
    return {
        "symbol":       symbol.upper(),
        "price":        float(coin.get("current_price") or 0),
        "change_pct":   float(coin.get("price_change_percentage_24h") or 0),
        "volume":       float(coin.get("total_volume") or 0),
        "volume_quote": float(coin.get("total_volume") or 0),
        "high":         float(coin.get("high_24h") or 0),
        "low":          float(coin.get("low_24h") or 0),
    }


def get_klines(symbol: str, interval: str = "1h", limit: int = 50) -> list[dict]:
    """
    Retorna velas OHLC.  CoinGecko /coins/{id}/ohlc devuelve datos
    diarios con granularidad fija según el parámetro 'days'.
    Mapeo de intervalos Binance → days:
      1m/5m/15m/30m/1h → 1 día (máximo de granularidad free)
      4h/1d            → 7 días
      1w               → 30 días

    Estructura de cada vela:
    {
        "open_time": int (ms epoch),
        "open":  float,
        "high":  float,
        "low":   float,
        "close": float,
        "volume": float,   # CoinGecko OHLC no incluye volumen; se usa 0
    }
    """
    cg_id = _symbol_to_id(symbol)

    interval_to_days = {
        "1m": 1, "3m": 1, "5m": 1, "15m": 1, "30m": 1,
        "1h": 1, "2h": 1, "4h": 7,
        "6h": 7, "8h": 7, "12h": 7,
        "1d": 7, "3d": 14, "1w": 30, "1M": 90,
    }
    days = interval_to_days.get(interval, 1)

    raw = _get(f"/coins/{cg_id}/ohlc", params={
        "vs_currency": "usd",
        "days": days,
    })
    # raw = [[timestamp_ms, open, high, low, close], ...]
    klines = []
    for candle in raw[-limit:]:   # tomar solo las últimas `limit` velas
        ts, o, h, l, c = candle
        klines.append({
            "open_time": int(ts),
            "open":      float(o),
            "high":      float(h),
            "low":       float(l),
            "close":     float(c),
            "volume":    0.0,   # OHLC endpoint no provee volumen
        })
    time.sleep(RATE_LIMIT_DELAY)
    return klines


def get_multiple_tickers(symbols: list[str]) -> dict[str, dict]:
    """
    Obtiene datos de múltiples símbolos en una sola request.
    Retorna {symbol: ticker_dict, ...}
    """
    ids_map = {}
    for s in symbols:
        try:
            ids_map[_symbol_to_id(s)] = s.upper()
        except ValueError as e:
            logger.warning(str(e))

    if not ids_map:
        return {}

    data = _get("/coins/markets", params={
        "vs_currency": "usd",
        "ids": ",".join(ids_map.keys()),
        "price_change_percentage": "24h",
    })
    time.sleep(RATE_LIMIT_DELAY)

    result = {}
    for coin in data:
        original_symbol = ids_map.get(coin["id"])
        if original_symbol:
            result[original_symbol] = {
                "symbol":       original_symbol,
                "price":        float(coin.get("current_price") or 0),
                "change_pct":   float(coin.get("price_change_percentage_24h") or 0),
                "volume":       float(coin.get("total_volume") or 0),
                "volume_quote": float(coin.get("total_volume") or 0),
                "high":         float(coin.get("high_24h") or 0),
                "low":          float(coin.get("low_24h") or 0),
            }
    return result
