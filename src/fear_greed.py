"""
fear_greed.py — Fear & Greed Index (CNN Money) + VIX aproximado.
"""

import logging
import requests

logger = logging.getLogger(__name__)

CNN_FG_URL = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata/previous-close"
TIMEOUT = 10


def get_fear_greed() -> dict | None:
    """
    Retorna {value, rating, prev_close, prev_week, prev_month, prev_year} o None.
    value: 0-100 (0=extremo miedo, 100=extrema codicia)
    rating: 'Extreme Fear' | 'Fear' | 'Neutral' | 'Greed' | 'Extreme Greed'
    """
    try:
        resp = requests.get(
            CNN_FG_URL,
            timeout=TIMEOUT,
            headers={
                "User-Agent": "Mozilla/5.0",
                "Referer": "https://edition.cnn.com/markets/fear-and-greed",
            },
        )
        if resp.status_code != 200:
            logger.warning(f"Fear & Greed HTTP {resp.status_code}")
            return None

        data = resp.json()
        fg = data.get("fear_and_greed", {})
        score = fg.get("score")
        rating = fg.get("rating", "Unknown")

        if score is None:
            return None

        return {
            "value": round(float(score), 1),
            "rating": rating,
            "prev_close": round(float(fg.get("previous_close", score)), 1),
            "prev_week": round(float(fg.get("previous_1_week", score)), 1),
            "prev_month": round(float(fg.get("previous_1_month", score)), 1),
        }

    except Exception as e:
        logger.warning(f"Error obteniendo Fear & Greed: {e}")
        return None


def fg_emoji(value: float) -> str:
    if value <= 20:
        return "😱"
    elif value <= 40:
        return "😨"
    elif value <= 60:
        return "😐"
    elif value <= 80:
        return "😄"
    return "🤑"


def format_fg_message(fg: dict) -> str:
    if not fg:
        return ""
    emoji = fg_emoji(fg["value"])
    return (
        f"{emoji} <b>Fear & Greed:</b> {fg['value']} — <i>{fg['rating']}</i>\n"
        f"  Ayer: {fg['prev_close']} | Semana pasada: {fg['prev_week']} | Mes pasado: {fg['prev_month']}"
    )
