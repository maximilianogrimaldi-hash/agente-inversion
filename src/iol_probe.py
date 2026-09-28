"""
iol_probe.py — Sonda de diagnóstico para la API de IOL.

Corre solo si IOL_DIAG=1. Prueba variantes de endpoint y registra
status + cuerpo de la respuesta, para identificar el formato correcto
sin adivinar. Una vez resuelto, apagar la variable.
"""

import logging
from datetime import datetime, timedelta

import requests

logger = logging.getLogger(__name__)

BASE = "https://api.invertironline.com"
TICKER = "AAPL"


def _try(session_headers: dict, label: str, url: str, params: dict = None):
    try:
        r = requests.get(url, headers=session_headers, params=params or {}, timeout=15)
        body = (r.text or "")[:220].replace("\n", " ")
        logger.info(f"[IOL-DIAG] {r.status_code:3d} {label} -> {url}")
        if r.status_code != 200:
            logger.info(f"[IOL-DIAG]      body: {body}")
        else:
            logger.info(f"[IOL-DIAG]      OK: {body}")
        return r.status_code == 200
    except Exception as e:
        logger.info(f"[IOL-DIAG] ERR {label} -> {url} :: {e}")
        return False


def run(headers: dict):
    """headers debe traer el Authorization Bearer ya resuelto."""
    logger.info("[IOL-DIAG] ===== inicio sonda IOL =====")

    desde = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
    hasta = datetime.now().strftime("%Y-%m-%d")

    # Cotización actual — variantes de orden de segmentos y capitalización
    quote_variants = [
        ("v2 mercado/Titulos/simbolo/Cotizacion", f"{BASE}/api/v2/bCBA/Titulos/{TICKER}/Cotizacion"),
        ("v2 minuscula bcba",                      f"{BASE}/api/v2/bcba/Titulos/{TICKER}/Cotizacion"),
        ("v2 cotizacion minuscula",                f"{BASE}/api/v2/bCBA/Titulos/{TICKER}/cotizacion"),
        ("v1 sin version",                         f"{BASE}/api/bCBA/Titulos/{TICKER}/Cotizacion"),
        ("ACTUAL (el que falla hoy)",              f"{BASE}/api/v2/cotizaciones/bCBA/{TICKER}/actual"),
    ]
    for label, url in quote_variants:
        _try(headers, label, url)

    # Serie histórica
    hist_variants = [
        ("hist seriehistorica minuscula",
         f"{BASE}/api/v2/bCBA/Titulos/{TICKER}/Cotizacion/seriehistorica/{desde}/{hasta}/sinAjustar"),
        ("hist serieHistorica camel",
         f"{BASE}/api/v2/bCBA/Titulos/{TICKER}/Cotizacion/serieHistorica/{desde}/{hasta}/SinAjustar"),
        ("hist ajustada",
         f"{BASE}/api/v2/bCBA/Titulos/{TICKER}/Cotizacion/seriehistorica/{desde}/{hasta}/Ajustada"),
    ]
    for label, url in hist_variants:
        _try(headers, label, url)

    # Panel completo de CEDEARs: alternativa si lo individual no sirve
    panel_variants = [
        ("panel cedears",
         f"{BASE}/api/v2/Cotizaciones/cedears/argentina/Todos"),
        ("panel acciones merval",
         f"{BASE}/api/v2/Cotizaciones/acciones/merval/argentina"),
    ]
    for label, url in panel_variants:
        _try(headers, label, url)

    logger.info("[IOL-DIAG] ===== fin sonda IOL =====")
