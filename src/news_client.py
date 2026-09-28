"""
news_client.py — Noticias relevantes filtradas por watchlist.
Usa Yahoo Finance RSS (no requiere API key) + análisis de relevancia.
"""

import logging
import re
import time
from datetime import datetime, timezone, timedelta
from urllib.parse import quote

import requests

logger = logging.getLogger(__name__)

# Tickers CEDEAR → nombre empresa para búsqueda
CEDEAR_NAMES = {
    "AAPL": "Apple",
    "ABBV": "AbbVie",
    "AMZN": "Amazon",
    "AVGO": "Broadcom",
    "BRK": "Berkshire Hathaway",
    "GLOB": "Globant",
    "GOOGL": "Alphabet Google",
    "KO": "Coca-Cola",
    "MELI": "MercadoLibre",
    "META": "Meta Facebook",
    "MSFT": "Microsoft",
    "NVDA": "Nvidia",
    "ORCL": "Oracle",
    "TSLA": "Tesla",
    "TSM": "TSMC Taiwan Semiconductor",
    "UNH": "UnitedHealth",
    "XOM": "ExxonMobil",
    "YPFD": "YPF",
}

CRYPTO_NAMES = {
    "BTCUSDT": "Bitcoin BTC",
    "ETHUSDT": "Ethereum ETH",
    "XRPUSDT": "XRP Ripple",
    "UNIUSDT": "Uniswap UNI",
    "LINKUSDT": "Chainlink LINK",
    "HYPEUSDT": "Hyperliquid HYPE",
}


class NewsClient:
    YAHOO_RSS = "https://feeds.finance.yahoo.com/rss/2.0/headline?s={ticker}&region=US&lang=en-US"
    GF_URL = "https://finviz.com/news.ashx"  # fallback
    TIMEOUT = 10

    def get_ticker_news(self, ticker: str, tipo: str = "CEDEAR", max_items: int = 3) -> list[dict]:
        """Busca noticias recientes para un ticker. Retorna lista de {title, url, published}."""
        results = []
        try:
            if tipo == "CRYPTO":
                # Para crypto: buscar por nombre en Yahoo Finance news
                name_parts = CRYPTO_NAMES.get(ticker, ticker.replace("USDT", "")).split()
                search_ticker = name_parts[0] if name_parts else ticker
            else:
                search_ticker = ticker

            url = self.YAHOO_RSS.format(ticker=quote(search_ticker))
            resp = requests.get(url, timeout=self.TIMEOUT, headers={"User-Agent": "Mozilla/5.0"})
            if resp.status_code != 200:
                return results

            # Parse RSS sin lxml
            text = resp.text
            items = re.findall(r"<item>(.*?)</item>", text, re.DOTALL)
            for item in items[:max_items]:
                title_m = re.search(r"<title><!\[CDATA\[(.*?)\]\]></title>", item)
                link_m = re.search(r"<link>(.*?)</link>", item, re.DOTALL)
                pub_m = re.search(r"<pubDate>(.*?)</pubDate>", item)
                if title_m:
                    title = title_m.group(1).strip()
                    link = link_m.group(1).strip() if link_m else ""
                    pub = pub_m.group(1).strip() if pub_m else ""
                    results.append({"title": title, "url": link, "published": pub, "ticker": ticker})

        except Exception as e:
            logger.warning(f"Error obteniendo noticias para {ticker}: {e}")

        return results

    def get_watchlist_news(self, cedears: list[str], cryptos: list[str], max_per_ticker: int = 2) -> list[dict]:
        """Obtiene noticias para toda la watchlist. Prioriza los más relevantes."""
        all_news = []
        priority_tickers = cedears[:5] + ["BTCUSDT", "ETHUSDT"]  # los más importantes primero

        for ticker in priority_tickers:
            tipo = "CEDEAR" if ticker in cedears else "CRYPTO"
            news = self.get_ticker_news(ticker, tipo, max_per_ticker)
            all_news.extend(news)
            time.sleep(0.3)  # rate limiting cortés

        return all_news[:15]  # máximo 15 noticias totales

    def get_macro_news(self) -> list[dict]:
        """Noticias macro: S&P500, tasas, economía global."""
        results = []
        macro_tickers = ["^GSPC", "^TNX", "DXY"]  # S&P500, US10Y, DXY
        for t in macro_tickers:
            news = self.get_ticker_news(t, "CEDEAR", 2)
            results.extend(news)
            time.sleep(0.3)
        return results[:6]
