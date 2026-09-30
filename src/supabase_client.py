"""
SupabaseClient — Conexión a Supabase REST API
v2: agrega get_recent_alerts, get_portfolio, upsert_portfolio
"""

import os
import logging
from datetime import datetime, timezone, timedelta

import requests

logger = logging.getLogger(__name__)


class SupabaseClient:
    def __init__(self):
        self.url = os.environ["SUPABASE_URL"].rstrip("/")
        self.key = (
            os.environ.get("SUPABASE_KEY")
            or os.environ.get("SUPABASE_SERVICE_KEY")
            or os.environ["SUPABASE_ANON_KEY"]
        )
        self.headers = {
            "apikey": self.key,
            "Authorization": f"Bearer {self.key}",
            "Content-Type": "application/json",
            "Prefer": "return=representation",
        }

    def _get(self, table: str, params: dict = None) -> list:
        try:
            resp = requests.get(
                f"{self.url}/rest/v1/{table}",
                headers=self.headers,
                params=params or {},
                timeout=10,
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.error(f"Supabase GET {table}: {e}")
            return []

    def _post(self, table: str, data: dict) -> dict | None:
        try:
            resp = requests.post(
                f"{self.url}/rest/v1/{table}",
                headers=self.headers,
                json=data,
                timeout=10,
            )
            resp.raise_for_status()
            result = resp.json()
            return result[0] if isinstance(result, list) and result else result
        except Exception as e:
            logger.error(f"Supabase POST {table}: {e}")
            return None

    def _upsert(self, table: str, data: dict, on_conflict: str = "id") -> dict | None:
        try:
            headers = {**self.headers, "Prefer": f"resolution=merge-duplicates,return=representation"}
            resp = requests.post(
                f"{self.url}/rest/v1/{table}",
                headers=headers,
                json=data,
                params={"on_conflict": on_conflict},
                timeout=10,
            )
            resp.raise_for_status()
            result = resp.json()
            return result[0] if isinstance(result, list) and result else result
        except Exception as e:
            logger.error(f"Supabase UPSERT {table}: {e}")
            return None

    def _patch(self, table: str, params: dict, data: dict) -> dict | None:
        try:
            resp = requests.patch(
                f"{self.url}/rest/v1/{table}",
                headers=self.headers,
                params=params,
                json=data,
                timeout=10,
            )
            resp.raise_for_status()
            result = resp.json()
            return result[0] if isinstance(result, list) and result else (result or {})
        except Exception as e:
            logger.error(f"Supabase PATCH {table}: {e}")
            return None

    def _delete(self, table: str, params: dict) -> dict | None:
        try:
            resp = requests.delete(
                f"{self.url}/rest/v1/{table}",
                headers=self.headers,
                params=params,
                timeout=10,
            )
            resp.raise_for_status()
            return {}
        except Exception as e:
            logger.error(f"Supabase DELETE {table}: {e}")
            return None

    # ─── Snapshot (estado actual de cada instrumento) ────────────────────────

    def save_snapshot(self, sig_dict: dict) -> dict | None:
        ind = sig_dict.get("indicadores", {}) or {}
        # Nombre de empresa: puede venir en el sig_dict o en indicadores.fundamentales
        nombre = sig_dict.get("nombre") or (ind.get("fundamentales") or {}).get("nombre") or ""
        payload = {
            "ticker": sig_dict.get("ticker"),
            "tipo": sig_dict.get("tipo"),
            "precio": sig_dict.get("precio"),
            "variacion_pct": sig_dict.get("variacion_pct"),
            "senal": sig_dict.get("senal"),
            "fuerza": sig_dict.get("fuerza"),
            "score": ind.get("score"),
            "motivos": sig_dict.get("motivos", []),
            "indicadores": ind,
            "nombre": nombre,
            "actualizado_en": datetime.now(timezone.utc).isoformat(),
        }
        return self._upsert("snapshot", payload, on_conflict="ticker")

    def get_snapshots(self) -> list[dict]:
        return self._get("snapshot", {"select": "*", "order": "score.desc"})

    # ─── Watchlist ───────────────────────────────────────────────────────────

    def get_watchlist(self) -> list[dict]:
        return self._get("watchlist", {"select": "*", "activo": "eq.true"})

    def get_cedears(self) -> list[str]:
        rows = self._get("watchlist", {"select": "ticker", "tipo": "eq.CEDEAR", "activo": "eq.true"})
        return [r["ticker"] for r in rows]

    def get_cryptos(self) -> list[str]:
        rows = self._get("watchlist", {"select": "ticker", "tipo": "eq.CRYPTO", "activo": "eq.true"})
        return [r["ticker"] for r in rows]

    # ─── Alertas ─────────────────────────────────────────────────────────────

    def save_alert(self, data: dict) -> dict | None:
        payload = {
            "ticker": data.get("ticker"),
            "tipo": data.get("tipo"),
            "senal": data.get("senal"),
            "fuerza": data.get("fuerza"),
            "precio": data.get("precio"),
            "variacion_pct": data.get("variacion_pct"),
            "motivos": data.get("motivos", []),
            "indicadores": data.get("indicadores", {}),
            "creado_en": datetime.now(timezone.utc).isoformat(),
        }
        return self._post("alertas", payload)

    def alert_already_sent(self, ticker: str, senal: str, within_minutes: int = 60) -> bool:
        cutoff = (datetime.now(timezone.utc) - timedelta(minutes=within_minutes)).isoformat()
        rows = self._get("alertas", {
            "ticker": f"eq.{ticker}",
            "senal": f"eq.{senal}",
            "creado_en": f"gte.{cutoff}",
            "select": "id",
            "limit": "1",
        })
        return len(rows) > 0

    def get_recent_alerts(self, days_back: int = 30) -> list[dict]:
        """Retorna alertas de los últimos N días para backtesting."""
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days_back)).isoformat()
        return self._get("alertas", {
            "select": "*",
            "creado_en": f"gte.{cutoff}",
            "order": "creado_en.desc",
            "limit": "200",
        })

    # ─── Config ──────────────────────────────────────────────────────────────

    def get_config(self, key: str):
        rows = self._get("config", {"select": "value", "key": f"eq.{key}"})
        if rows:
            return rows[0].get("value")
        return None

    # ─── Portfolio ───────────────────────────────────────────────────────────

    def get_portfolio(self) -> list[dict]:
        """Retorna todas las posiciones del portfolio."""
        return self._get("portfolio", {"select": "*", "activo": "eq.true"})

    def upsert_portfolio(self, ticker: str, tipo: str, cantidad: float, precio_entrada: float, notas: str = "") -> dict | None:
        """Agrega o actualiza una posición del portfolio."""
        return self._upsert("portfolio", {
            "ticker": ticker,
            "tipo": tipo,
            "cantidad": cantidad,
            "precio_entrada": precio_entrada,
            "notas": notas,
            "activo": True,
            "fecha_entrada": datetime.now(timezone.utc).isoformat(),
        }, on_conflict="ticker")
