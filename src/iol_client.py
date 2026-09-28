"""
IOL (InvertirOnline) API Client
Autenticacion OAuth2 + consulta de cotizaciones CEDEARs
"""

import os
import time
import logging
from typing import Optional
from datetime import datetime, timedelta

import requests

logger = logging.getLogger(__name__)

IOL_BASE_URL = "https://api.invertironline.com"
TOKEN_URL = f"{IOL_BASE_URL}/token"
API_V2_URL = f"{IOL_BASE_URL}/api/v2"
MERCADO = "bCBA"


def _raise_with_body(resp, contexto: str) -> None:
    """Como raise_for_status, pero deja el cuerpo del error en el log."""
    if resp.status_code >= 400:
        body = (resp.text or "")[:200].replace("\n", " ")
        logger.error(f"IOL {resp.status_code} en {contexto}: {body}")
    resp.raise_for_status()


class IOLClient:
    def __init__(self):
        self.username = os.environ["IOL_USERNAME"]
        self.password = os.environ["IOL_PASSWORD"]
        self._access_token: Optional[str] = None
        self._refresh_token: Optional[str] = None
        self._token_expires_at: float = 0

    def _fetch_token(self) -> None:
        resp = requests.post(
            TOKEN_URL,
            data={
                "username": self.username,
                "password": self.password,
                "grant_type": "password",
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        self._access_token = data["access_token"]
        self._refresh_token = data.get("refresh_token")
        expires_in = int(data.get("expires_in", 1800))
        self._token_expires_at = time.time() + expires_in - 60

    def _refresh_access_token(self) -> None:
        if not self._refresh_token:
            self._fetch_token()
            return
        resp = requests.post(
            TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "refresh_token": self._refresh_token,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=10,
        )
        if resp.status_code != 200:
            self._fetch_token()
            return
        data = resp.json()
        self._access_token = data["access_token"]
        self._refresh_token = data.get("refresh_token", self._refresh_token)
        expires_in = int(data.get("expires_in", 1800))
        self._token_expires_at = time.time() + expires_in - 60

    def _ensure_token(self) -> str:
        if not self._access_token or time.time() >= self._token_expires_at:
            if self._refresh_token:
                self._refresh_access_token()
            else:
                self._fetch_token()
        return self._access_token

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self._ensure_token()}"}

    def get_cedear_quote(self, ticker: str) -> dict:
        url = f"{API_V2_URL}/{MERCADO}/Titulos/{ticker}/Cotizacion"
        resp = requests.get(url, headers=self._headers(), timeout=10)
        _raise_with_body(resp, f"cotizacion {ticker}")
        return resp.json()

    def get_cedear_history(self, ticker: str, days: int = 50) -> list[dict]:
        date_from = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        date_to = datetime.now().strftime("%Y-%m-%d")
        url = (
            f"{API_V2_URL}/{MERCADO}/Titulos/{ticker}/Cotizacion/seriehistorica"
            f"/{date_from}/{date_to}/sinAjustar"
        )
        resp = requests.get(url, headers=self._headers(), timeout=15)
        _raise_with_body(resp, f"historico {ticker}")
        data = resp.json()
        return data if isinstance(data, list) else []

    def get_multiple_cedears(self, tickers: list[str]) -> dict[str, dict]:
        results = {}
        for ticker in tickers:
            try:
                results[ticker] = self.get_cedear_quote(ticker)
            except Exception as e:
                logger.error(f"Error obteniendo CEDEAR {ticker}: {e}")
        return results

    def get_portfolio(self) -> dict:
        url = f"{API_V2_URL}/portafolio/argentina"
        resp = requests.get(url, headers=self._headers(), timeout=10)
        resp.raise_for_status()
        return resp.json()
