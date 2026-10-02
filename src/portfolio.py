"""
portfolio.py — Tracker de portfolio con P&L.
Las posiciones se guardan en Supabase tabla 'portfolio'.
Estructura tabla: id, ticker, tipo, cantidad, precio_entrada, moneda, fecha_entrada, notas

Una misma tenencia puede estar cargada dos veces: una fila en ARS y otra en USD
(dos importaciones de Balanz). Son dos formas de medir la misma posición, no
dos posiciones.
"""

import logging
import re

logger = logging.getLogger(__name__)

_RENDIMIENTO_RE = re.compile(r"rendimiento:\s*([-\d.]+)%")


def _moneda(pos: dict) -> str:
    """Crypto cotiza en USDT; el resto usa la moneda de la fila (ARS por defecto)."""
    if pos.get("tipo") == "CRYPTO":
        return "USD"
    return (pos.get("moneda") or "ARS").upper()


def _una_por_ticker(positions: list[dict]) -> list[dict]:
    """Deja una fila por ticker, prefiriendo la cargada en USD."""
    elegidas: dict[str, dict] = {}
    for pos in positions:
        ticker = pos.get("ticker", "")
        actual = elegidas.get(ticker)
        if actual is None or (_moneda(pos) == "USD" and _moneda(actual) != "USD"):
            elegidas[ticker] = pos
    return list(elegidas.values())


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

    def calculate_pnl(
        self,
        positions: list[dict],
        current_prices: dict,
        mep: float | None = None,
        una_por_ticker: bool = False,
    ) -> list[dict]:
        """
        Calcula P&L para cada posición.
        current_prices: {ticker: float} — CEDEARs en ARS (IOL), crypto en USD.
        mep: pesos por dólar. Con él, las posiciones en USD se valúan a precio
             de hoy; sin él quedan sin precio actual (el panel las completa con
             el rendimiento importado de Balanz).
        una_por_ticker: descarta la fila ARS cuando el ticker también está en USD.
        """
        if una_por_ticker:
            positions = _una_por_ticker(positions)

        results = []
        for pos in positions:
            ticker = pos.get("ticker", "")
            cantidad = float(pos.get("cantidad", 0))
            precio_entrada = float(pos.get("precio_entrada", 0))
            moneda = _moneda(pos)
            precio_actual = current_prices.get(ticker)
            fuente = "mercado"

            if precio_actual and moneda == "USD" and pos.get("tipo") != "CRYPTO":
                # El precio de IOL está en pesos: pasarlo a dólares
                precio_actual = precio_actual / mep if mep else None

            if not precio_actual and moneda == "USD" and una_por_ticker:
                # Sin cotización de hoy: último rendimiento informado por Balanz
                m = _RENDIMIENTO_RE.search(pos.get("notas") or "")
                if m and precio_entrada:
                    precio_actual = precio_entrada * (1 + float(m.group(1)) / 100)
                    fuente = "balanz"

            if not precio_actual or precio_entrada == 0:
                results.append({**pos, "moneda": moneda, "precio_actual": None, "pnl_pct": None, "pnl_abs": None})
                continue

            pnl_pct = ((precio_actual - precio_entrada) / precio_entrada) * 100
            pnl_abs = (precio_actual - precio_entrada) * cantidad

            results.append({
                **pos,
                "moneda": moneda,
                "precio_actual": round(precio_actual, 4),
                "pnl_pct": round(pnl_pct, 2),
                "pnl_abs": round(pnl_abs, 2),
                "pnl_fuente": fuente,
            })

        return results

    def format_portfolio_message(self, pnl_data: list[dict], mep: float | None = None) -> str:
        """Formatea el resumen del portfolio para Telegram, separado por moneda."""
        if not pnl_data:
            return "📂 <b>Portfolio vacío</b>\nAgregá posiciones en Supabase (tabla portfolio)."

        lines = ["📂 <b>PORTFOLIO — P&L Actual</b>\n━━━━━━━━━━━━━━━━━━━━"]
        simbolos = {"USD": "US$", "ARS": "AR$"}
        hay_estimado = False

        for moneda in ("USD", "ARS"):
            grupo = [p for p in pnl_data if p.get("moneda", "ARS") == moneda]
            if not grupo:
                continue
            sim = simbolos[moneda]

            def valor(p):
                precio = p.get("precio_actual") or p.get("precio_entrada") or 0
                return float(p.get("cantidad", 0)) * float(precio)

            invertido = actual = 0.0
            for pos in sorted(grupo, key=valor, reverse=True):
                ticker = pos.get("ticker", "?")
                pnl_pct = pos.get("pnl_pct")
                if pnl_pct is None:
                    lines.append(f"  ⚪ <b>{ticker}</b>: sin precio actual")
                    continue

                cantidad = float(pos.get("cantidad", 0))
                invertido += cantidad * float(pos.get("precio_entrada", 0))
                actual += cantidad * float(pos["precio_actual"])

                marca = ""
                if pos.get("pnl_fuente") == "balanz":
                    marca = " *"
                    hay_estimado = True
                emoji = "🟢" if pnl_pct >= 0 else "🔴"
                lines.append(
                    f"  {emoji} <b>{ticker}</b>: {sim} {valor(pos):,.0f} · "
                    f"{pnl_pct:+.2f}% ({sim} {pos['pnl_abs']:+,.0f}){marca}"
                )

            lines.append("━━━━━━━━━━━━━━━━━━━━")
            if invertido > 0:
                pnl = actual - invertido
                emoji = "🟢" if pnl >= 0 else "🔴"
                lines.append(
                    f"{emoji} <b>TOTAL {moneda}: {sim} {actual:,.0f}</b> "
                    f"({pnl / invertido * 100:+.2f}%, {sim} {pnl:+,.0f})"
                )

        if mep:
            lines.append(f"<i>Dólar MEP usado: AR$ {mep:,.0f}</i>")
        if hay_estimado:
            lines.append("<i>* Sin cotización de hoy: último rendimiento de Balanz</i>")

        return "\n".join(lines)
