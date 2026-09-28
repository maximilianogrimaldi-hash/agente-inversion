"""
dollar_monitor.py — Monitor de tipos de cambio USD y correlación con CEDEARs.
Usa APIs públicas de dólares argentinos.
"""

import logging
import requests

logger = logging.getLogger(__name__)

BLUELYTICS_URL = "https://api.bluelytics.com.ar/v2/latest"
TIMEOUT = 10


def get_dollar_rates() -> dict | None:
    """
    Retorna tipos de cambio actuales.
    {oficial, blue, mep, ccl, cripto, spread_blue_pct}
    """
    try:
        resp = requests.get(BLUELYTICS_URL, timeout=TIMEOUT)
        if resp.status_code != 200:
            return None

        data = resp.json()
        oficial = data.get("oficial", {})
        blue = data.get("blue", {})

        oficial_venta = float(oficial.get("value_sell", 0))
        blue_venta = float(blue.get("value_sell", 0))
        spread_pct = ((blue_venta / oficial_venta) - 1) * 100 if oficial_venta > 0 else 0

        return {
            "oficial": oficial_venta,
            "blue": blue_venta,
            "spread_blue_pct": round(spread_pct, 1),
            "fecha": data.get("last_update", ""),
        }

    except Exception as e:
        logger.warning(f"Error obteniendo tipos de cambio: {e}")
        return None


def get_dolar_mep_ccl() -> dict | None:
    """MEP y CCL aproximados via API pública."""
    try:
        # Usar ambito.com o dolarito.ar
        resp = requests.get(
            "https://dolarito.ar/api/latest",
            timeout=TIMEOUT,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        if resp.status_code == 200:
            data = resp.json()
            return {
                "mep": float(data.get("mep", {}).get("ask", 0) or 0),
                "ccl": float(data.get("ccl", {}).get("ask", 0) or 0),
            }
    except Exception:
        pass
    return None


def analyze_dollar_cedear_correlation(dollar_rates: dict, cedear_signals: list) -> list[str]:
    """
    Detecta alertas de correlación dólar → CEDEAR.
    Los CEDEARs cotizan en ARS y siguen al dólar CCL.
    Si el CCL sube mucho, los CEDEARs ARS deberían subir también.
    """
    alerts = []
    if not dollar_rates:
        return alerts

    spread = dollar_rates.get("spread_blue_pct", 0)

    # Spread muy alto = presión sobre CEDEARs
    if spread > 150:
        alerts.append(f"⚡ Brecha cambiaria alta ({spread:.0f}%) — CEDEARs pueden subir en ARS por cobertura")
    elif spread > 100:
        alerts.append(f"📊 Brecha cambiaria moderada ({spread:.0f}%)")

    # Si CEDEARs están cayendo pero dólar sube = señal de compra técnica
    cedear_negativos = [s for s in cedear_signals if getattr(s, "tipo", "") == "CEDEAR" and getattr(s, "senal", "") == "SELL"]
    if cedear_negativos and spread > 80:
        tickers = ", ".join([s.ticker for s in cedear_negativos[:3]])
        alerts.append(f"🔄 CEDEARs bajando ({tickers}) con brecha alta — posible desacople temporal vs USD")

    return alerts


def format_dollar_message(rates: dict) -> str:
    if not rates:
        return ""
    return (
        f"💵 <b>Tipos de cambio:</b>\n"
        f"  Oficial: ${rates['oficial']:,.0f} | Blue: ${rates['blue']:,.0f}\n"
        f"  Brecha blue: {rates['spread_blue_pct']:.1f}%"
    )
