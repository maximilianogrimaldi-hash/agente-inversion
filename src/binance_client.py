"""
Binance API Client (Public — sin firma para datos de mercado)
"""

import logging
import requests

logger = logging.getLogger(__name__)

BINANCE_BASE = "https://api.binance.com/api/v3"


class BinanceClient:
    def __init__(self):
        self.session = requests.Session()

    def _get(self, endpoint: str, params: dict = None) -> dict | list:
        url = f"{BINANCE_BASE}/{endpoint}"
        resp = self.session.get(url, params=params, timeout=10)
        resp.raise_for_status()
        return resp.json()

    def get_price(self, symbol: str) -> float:
        data = self._get("ticker/price", {"symbol": symbol.upper()})
        return float(data["price"])

    def get_ticker_24h(self, symbol: str) -> dict:
        data = self._get("ticker/24hr", {"symbol": symbol.upper()})
        return {
            "symbol": data["symbol"],
            "price": float(data["lastPrice"]),
            "change_pct": float(data["priceChangePercent"]),
            "volume": float(data["volume"]),
            "quote_volume": float(data["quoteVolume"]),
            "high": float(data["highPrice"]),
            "low": float(data["lowPrice"]),
        }

    def get_klines(self, symbol: str, interval: str = "15m", limit: int = 50) -> list[dict]:
        raw = self._get("klines", {
            "symbol": symbol.upper(),
            "interval": interval,
            "limit": limit,
        })
        return [
            {
                "open_time": k[0],
                "open": float(k[1]),
                "high": float(k[2]),
                "low": float(k[3]),
                "close": float(k[4]),
                "volume": float(k[5]),
            }
            for k in raw
        ]

    def get_order_book_depth(self, symbol: str, limit: int = 5) -> dict:
        data = self._get("depth", {"symbol": symbol.upper(), "limit": limit})
        bids = [(float(p), float(q)) for p, q in data["bids"]]
        asks = [(float(p), float(q)) for p, q in data["asks"]]
        return {"bids": bids, "asks": asks}

    def get_multiple_tickers(self, symbols: list[str]) -> dict[str, dict]:
        results = {}
        for symbol in symbols:
            try:
                results[symbol] = self.get_ticker_24h(symbol)
            except Exception as e:
                logger.error(f"Error obteniendo ticker {symbol}: {e}")
        return results
