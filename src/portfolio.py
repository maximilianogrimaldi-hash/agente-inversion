"""
portfolio.py — Tracker de portfolio con P&L.
Las posiciones se guardan en Supabase tabla 'portfolio'.
Estructura tabla: id, ticker, tipo, cantidad, precio_entrada, fecha_entrada, notas
"""

import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


class PortfolioTracker:
    def __init__(self, db):
        self.db = db

    def get_positions(self) -> list[dict]:
        """Retorna todas las posiciones abiertas del portfolio."""
        try:
            return self.db.get_portfolio() or []
        except Exception as e:
            logger.error(f"Error obteniendo portfolio: {e}")
            return []

    def calculate_pnl(self, positions: list[dict], current_prices: dict) -> list[dict]:
        """
        Calcula P&L para cada posición.
        current_prices: {ticker: float}
        Retorna lista con P&L calculado.
        """
        results = []
        for pos in positions:
            ticker = pos.get("ticker", "")
            cantidad = float(pos.get("cantidad", 0))
            precio_entrada = float(pos.get("precio_entrada", 0))
            moneda = pos.get("moneda", "ARS")

            # Snapshot tiene precios en ARS — no cruzar con posiciones en USD
            if moneda == "USD":
                results.append({**pos, "precio_actual": None, "pnl_pct": None, "pnl_abs": None})
                continue

            precio_actual = current_prices.get(ticker)

            if precio_actual is None or precio_entrada == 0:
                results.append({**pos, "precio_actual": None, "pnl_pct": None, "pnl_abs": None})
                continue

            pnl_pct = ((precio_actual - precio_entrada) / precio_entrada) * 100
            pnl_abs = (precio_actual - precio_entrada) * cantidad

            results.append({
                **pos,
                "precio_actual": precio_actual,
                "pnl_pct": round(pnl_pct, 2),
                "pnl_abs": round(pnl_abs, 2),
            })

        return results

    def format_portfolio_message(self, pnl_data: list[dict]) -> str:
        """Formatea el resumen del portfolio para Telegram."""
        if not pnl_data:
            return "📂 <b>Portfolio vacío</b>\nAgregá posiciones en Supabase (tabla portfolio)."

        total_invertido = sum(
            float(p.get("cantidad", 0)) * float(p.get("precio_entrada", 0))
            for p in pnl_data if p.get("precio_entrada")
        )
        total_actual = sum(
            float(p.get("cantidad", 0)) * float(p.get("precio_actual", 0))
            for p in pnl_data if p.get("precio_actual")
        )
        total_pnl = total_actual - total_invertido

        lines = ["📂 <b>PORTFOLIO — P&L Actual</b>\n━━━━━━━━━━━━━━━━━━━━"]

        for pos in pnl_data:
            ticker = pos.get("ticker", "?")
            pnl_pct = pos.get("pnl_pct")
            pnl_abs = pos.get("pnl_abs")
            precio_actual = pos.get("precio_actual")
            precio_entrada = float(pos.get("precio_entrada", 0))

            if pnl_pct is None:
                lines.append(f"  {ticker}: sin precio actual")
                continue

            emoji = "🟢" if pnl_pct >= 0 else "🔴"
            pnl_str = f"{pnl_pct:+.2f}% (${pnl_abs:+,.2f})" if pnl_abs is not None else f"{pnl_pct:+.2f}%"
            lines.append(f"  {emoji} <b>{ticker}</b>: entrada ${precio_entrada:,.2f} → actual ${precio_actual:,.2f} → {pnl_str}")

        lines.append("━━━━━━━━━━━━━━━━━━━━")
        if total_invertido > 0:
            total_emoji = "🟢" if total_pnl >= 0 else "🔴"
            pnl_total_pct = (total_pnl / total_invertido) * 100
            lines.append(f"{total_emoji} <b>TOTAL: ${total_actual:,.2f}</b> ({pnl_total_pct:+.2f}%)")

        return "\n".join(lines)
