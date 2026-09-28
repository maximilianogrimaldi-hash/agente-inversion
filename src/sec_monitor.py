"""
sec_monitor.py — Monitor de filings SEC y eventos corporativos para watchlist.
Usa SEC EDGAR API (gratuita, no requiere key).
"""

import logging
import time
from datetime import datetime, timezone, timedelta

import requests

logger = logging.getLogger(__name__)

SEC_CIK_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
SEC_SEARCH_URL = "https://efts.sec.gov/LATEST/search-index?q=%22{ticker}%22&dateRange=custom&startdt={start}&enddt={end}&forms=8-K,10-Q,10-K,DEF%2014A,SC%2013G"
EDGAR_COMPANY_URL = "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&company={ticker}&type=8-K&dateb=&owner=include&count=5&search_text=&output=atom"
TIMEOUT = 10

# Mapeo ticker → CIK (los más usados en CEDEARs)
TICKER_CIK = {
    "AAPL": 320193,
    "MSFT": 789019,
    "AMZN": 1018724,
    "GOOGL": 1652044,
    "META": 1326801,
    "TSLA": 1318605,
    "NVDA": 1045810,
    "AVGO": 1730168,
    "TSM": 1046179,
    "ORCL": 1341439,
    "ABBV": 1551152,
    "UNH": 72971,
    "KO": 21344,
    "XOM": 34088,
    "MELI": 1373670,
    "GLOB": 1557860,
    "BRK": 1067983,
}

FORM_DESCRIPTIONS = {
    "8-K": "📋 Evento material",
    "10-Q": "📊 Reporte trimestral",
    "10-K": "📅 Reporte anual",
    "DEF 14A": "🗳️ Proxy / Junta accionistas",
    "SC 13G": "🏦 Gran accionista",
    "SC 13D": "🏦 Gran accionista (activista)",
}


class SECMonitor:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Agente-Inversion contact@example.com",
            "Accept-Encoding": "gzip, deflate",
        })

    def get_recent_filings(self, ticker: str, days_back: int = 7) -> list[dict]:
        """Retorna filings recientes para un ticker. Máximo 5 por ticker."""
        cik = TICKER_CIK.get(ticker)
        if not cik:
            return []

        results = []
        try:
            url = SEC_CIK_URL.format(cik=cik)
            resp = self.session.get(url, timeout=TIMEOUT)
            if resp.status_code != 200:
                return []

            data = resp.json()
            filings = data.get("filings", {}).get("recent", {})
            forms = filings.get("form", [])
            dates = filings.get("filingDate", [])
            descriptions = filings.get("primaryDocument", [])
            accessions = filings.get("accessionNumber", [])

            cutoff = datetime.now(timezone.utc) - timedelta(days=days_back)

            for i, (form, date_str, doc, acc) in enumerate(zip(forms, dates, descriptions, accessions)):
                try:
                    filing_date = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                    if filing_date < cutoff:
                        break  # ya están ordenados desc
                    if form in ("8-K", "10-Q", "10-K", "DEF 14A", "SC 13G", "SC 13D"):
                        acc_clean = acc.replace("-", "")
                        url_filing = f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc_clean}/{doc}"
                        results.append({
                            "ticker": ticker,
                            "form": form,
                            "date": date_str,
                            "description": FORM_DESCRIPTIONS.get(form, form),
                            "url": f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}&type={form}&dateb=&owner=include&count=5",
                        })
                        if len(results) >= 3:
                            break
                except Exception:
                    pass

        except Exception as e:
            logger.debug(f"SEC error {ticker}: {e}")

        return results

    def scan_watchlist(self, tickers: list[str], days_back: int = 7) -> list[dict]:
        """Escanea toda la watchlist. Retorna filings recientes ordenados por fecha."""
        all_filings = []
        for ticker in tickers:
            if ticker not in TICKER_CIK:
                continue
            filings = self.get_recent_filings(ticker, days_back)
            all_filings.extend(filings)
            time.sleep(0.3)  # EDGAR rate limit

        # Ordenar por fecha desc
        all_filings.sort(key=lambda f: f["date"], reverse=True)
        return all_filings
