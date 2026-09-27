"""
Supabase Client - Watchlist e historial de alertas
"""

import os
import logging
from datetime import datetime
from typing import Optional

import requests

logger = logging.getLogger(__name__)


class SupabaseClient:
    def __init__(self):
        self.url = os.environ["SUPABASE_URL"].rstrip("/")
        self.key = os.environ.get("SUPABASE_SERVICE_KEY") or os.environ["SUPABASE_ANON_KEY"]
        self.headers = {
            "apikey": self.key,
            "Authorization": f"Bearer {self.key}",
            "Content-Type": "application/json",
            "Prefer": "return=representation",
        }

    def _rest(self, method: str, table: str, data: dict = None, params: dict = None) -> list | dict:
        url = f"{self.url}/rest/v1/{table}"
        resp = requests.request(
            method, url, headers=self.headers, json=data, params=params, timeout=10
        )
        resp.raise_for_status()
        return resp.json() if resp.text else []

    def get_watchlist(self) -> list[dict]:
        try:
            rows = self._rest("GET", "watchlist", params={"activo": "eq.true", "select": "*"})
            return rows if isinstance(rows, list) else []
        except Exception as e:
            logger.error(f"Error obteniendo watchlist: {e}")
            return []

    def get_cedears(self) -> list[str]:
        rows = self.get_watchlist()
        return [r["ticker"] for r in rows if r.get("tipo") == "CEDEAR"]

    def get_cryptos(self) -> list[str]:
        rows = self.get_watchlist()
        return [r["ticker"] for r in rows if r.get("tipo") == "CRYPTO"]

    def add_to_watchlist(self, ticker: str, tipo: str, notas: str = "") -> bool:
        try:
            self._rest("POST", "watchlist", data={
                "ticker": ticker.upper(),
                "tipo": tipo.upper(),
                "notas": notas,
                "activo": True,
                "creado_en": datetime.utcnow().isoformat(),
            })
            return True
        except Exception as e:
            logger.error(f"Error agregando {ticker} a watchlist: {e}")
            return False

    def remove_from_watchlist(self, ticker: str) -> bool:
        try:
            self._rest("PATCH", "watchlist",
                       data={"activo": False},
                       params={"ticker": f"eq.{ticker.upper()}"})
            return True
        except Exception as e:
            logger.error(f"Error removiendo {ticker} de watchlist: {e}")
            return False

    def save_alert(self, signal_dict: dict) -> bool:
        try:
            self._rest("POST", "alertas", data={
                "ticker": signal_dict.get("ticker"),
                "tipo": signal_dict.get("tipo"),
                "precio": signal_dict.get("precio"),
                "variacion_pct": signal_dict.get("variacion_pct"),
                "senal": signal_dict.get("senal"),
                "fuerza": signal_dict.get("fuerza"),
                "motivos": signal_dict.get("motivos", []),
                "indicadores": signal_dict.get("indicadores", {}),
                "creado_en": datetime.utcnow().isoformat(),
            })
            return True
        except Exception as e:
            logger.error(f"Error guardando alerta: {e}")
            return False

    def get_recent_alerts(self, limit: int = 50) -> list[dict]:
        try:
            rows = self._rest("GET", "alertas", params={
                "select": "*",
                "order": "creado_en.desc",
                "limit": limit,
            })
            return rows if isinstance(rows, list) else []
        except Exception as e:
            logger.error(f"Error obteniendo alertas recientes: {e}")
            return []

    def alert_already_sent(self, ticker: str, senal: str, minutes: int = 60) -> bool:
        from datetime import timedelta
        cutoff = (datetime.utcnow() - timedelta(minutes=minutes)).isoformat()
        try:
            rows = self._rest("GET", "alertas", params={
                "ticker": f"eq.{ticker}",
                "senal": f"eq.{senal}",
                "creado_en": f"gte.{cutoff}",
                "select": "id",
                "limit": 1,
            })
            return len(rows) > 0
        except Exception as e:
            logger.error(f"Error verificando duplicado: {e}")
            return False

    def get_config(self, key: str, default=None):
        try:
            rows = self._rest("GET", "config", params={
                "key": f"eq.{key}",
                "select": "value",
                "limit": 1,
            })
            if rows:
                return rows[0]["value"]
            return default
        except Exception as e:
            logger.error(f"Error obteniendo config {key}: {e}")
            return default

    def set_config(self, key: str, value) -> bool:
        try:
            self._rest("POST", "config",
                       data={"key": key, "value": str(value)})
            return True
        except Exception as e:
            logger.error(f"Error seteando config {key}: {e}")
            return False
