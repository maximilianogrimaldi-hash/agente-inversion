"""
backtesting.py — Backtesting de señales pasadas contra precios históricos.
Analiza señales guardadas en Supabase y calcula su efectividad.
"""

import logging
from datetime import datetime, timezone, timedelta
from collections import defaultdict

logger = logging.getLogger(__name__)


class Backtester:
    def __init__(self, db):
        self.db = db

    def get_past_signals(self, days_back: int = 30) -> list[dict]:
        """Obtiene señales de los últimos N días de Supabase."""
        try:
            return self.db.get_recent_alerts(days_back=days_back) or []
        except Exception as e:
            logger.error(f"Error obteniendo señales históricas: {e}")
            return []

    def analyze_signal_accuracy(self, signals: list[dict], binance_client=None, iol_client=None) -> dict:
        """
        Para cada señal pasada, estima si fue correcta basándose en precios posteriores.
        Retorna estadísticas de efectividad.
        Solo funciona para señales que tienen precio_entrada y podemos comparar.
        """
        if not signals:
            return {}

        # Agrupar por ticker y tipo de señal
        by_senal = defaultdict(lambda: {"correcto": 0, "incorrecto": 0, "total": 0})
        by_ticker = defaultdict(lambda: {"correcto": 0, "incorrecto": 0, "total": 0})
        results_detail = []

        for sig in signals:
            ticker = sig.get("ticker", "")
            senal = sig.get("senal", "")
            precio_entrada = float(sig.get("precio", 0) or 0)

            if precio_entrada <= 0 or senal not in ("BUY", "SELL"):
                continue

            # Obtener precio actual para comparar
            precio_actual = None
            try:
                tipo = sig.get("tipo", "CEDEAR")
                if tipo == "CRYPTO" and binance_client:
                    td = binance_client.get_ticker_24h(ticker)
                    precio_actual = td.get("price")
                elif tipo == "CEDEAR" and iol_client:
                    quote = iol_client.get_cedear_quote(ticker)
                    precio_actual = float(quote.get("ultimoPrecio") or 0) or None
            except Exception:
                pass

            if precio_actual is None:
                continue

            cambio_pct = ((precio_actual - precio_entrada) / precio_entrada) * 100

            # BUY es correcto si el precio subió, SELL si bajó
            es_correcto = (senal == "BUY" and cambio_pct > 1.0) or (senal == "SELL" and cambio_pct < -1.0)

            resultado = "✅" if es_correcto else "❌"
            by_senal[senal]["total"] += 1
            by_ticker[ticker]["total"] += 1
            if es_correcto:
                by_senal[senal]["correcto"] += 1
                by_ticker[ticker]["correcto"] += 1
            else:
                by_senal[senal]["incorrecto"] += 1
                by_ticker[ticker]["incorrecto"] += 1

            results_detail.append({
                "ticker": ticker,
                "senal": senal,
                "precio_entrada": precio_entrada,
                "precio_actual": precio_actual,
                "cambio_pct": round(cambio_pct, 2),
                "correcto": es_correcto,
                "resultado": resultado,
            })

        total = sum(v["total"] for v in by_senal.values())
        correctos = sum(v["correcto"] for v in by_senal.values())
        accuracy_global = (correctos / total * 100) if total > 0 else 0

        return {
            "total_analizadas": total,
            "correctas": correctos,
            "accuracy_pct": round(accuracy_global, 1),
            "por_senal": dict(by_senal),
            "por_ticker": dict(by_ticker),
            "detalle": results_detail[:20],  # máximo 20 detalles
        }

    def format_backtest_message(self, stats: dict) -> str:
        """Formatea estadísticas de backtesting para Telegram."""
        if not stats or stats.get("total_analizadas", 0) == 0:
            return "📉 <b>Backtesting:</b> Sin datos suficientes aún."

        total = stats["total_analizadas"]
        acc = stats["accuracy_pct"]
        correctas = stats["correctas"]

        emoji = "🎯" if acc >= 60 else "⚠️" if acc >= 45 else "🔴"

        lines = [
            f"📉 <b>BACKTESTING — Últimas {total} señales</b>",
            f"{emoji} Efectividad: <b>{acc:.1f}%</b> ({correctas}/{total} correctas)",
        ]

        por_senal = stats.get("por_senal", {})
        for senal, data in por_senal.items():
            if data["total"] > 0:
                acc_senal = data["correcto"] / data["total"] * 100
                lines.append(f"  {senal}: {acc_senal:.0f}% ({data['correcto']}/{data['total']})")

        # Top tickers por rendimiento
        por_ticker = stats.get("por_ticker", {})
        buenos = [(t, d) for t, d in por_ticker.items() if d["total"] >= 2 and d["correcto"] / d["total"] >= 0.6]
        buenos.sort(key=lambda x: x[1]["correcto"] / x[1]["total"], reverse=True)
        if buenos:
            top = ", ".join([f"{t} ({d['correcto']}/{d['total']})" for t, d in buenos[:3]])
            lines.append(f"🏆 Mejores: {top}")

        return "\n".join(lines)
