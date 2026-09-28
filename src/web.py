"""
web.py — Panel web del agente, servido desde el mismo contenedor.

Protegido con HTTP Basic Auth (PANEL_USER / PANEL_PASS).
Las claves de Supabase nunca salen al navegador: el panel habla con
/api/* y este servidor hace las llamadas con la service key.
"""

import base64
import hmac
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from functools import wraps
from pathlib import Path

from flask import Flask, Response, jsonify, request

from supabase_client import SupabaseClient

logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config["JSON_AS_ASCII"] = False

PANEL_USER = os.environ.get("PANEL_USER", "")
PANEL_PASS = os.environ.get("PANEL_PASS", "")
PANEL_HTML = Path(__file__).with_name("panel.html")

_db = None


def db() -> SupabaseClient:
    global _db
    if _db is None:
        _db = SupabaseClient()
    return _db


def _check(user: str, pw: str) -> bool:
    if not PANEL_USER or not PANEL_PASS:
        return False
    return hmac.compare_digest(user, PANEL_USER) and hmac.compare_digest(pw, PANEL_PASS)


def require_auth(fn):
    @wraps(fn)
    def wrapper(*a, **kw):
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Basic "):
            try:
                raw = base64.b64decode(auth[6:]).decode("utf-8")
                user, _, pw = raw.partition(":")
                if _check(user, pw):
                    return fn(*a, **kw)
            except Exception:
                pass
        return Response(
            "Acceso restringido.",
            401,
            {"WWW-Authenticate": 'Basic realm="Mesa de Operaciones"'},
        )

    return wrapper


# ─── Panel ───────────────────────────────────────────────────────────────

@app.get("/")
@require_auth
def panel():
    if not PANEL_HTML.exists():
        return Response("panel.html no encontrado", 500)
    return Response(PANEL_HTML.read_text(encoding="utf-8"), mimetype="text/html")


@app.get("/health")
def health():
    return jsonify({"ok": True})


# ─── API ─────────────────────────────────────────────────────────────────

@app.get("/api/watchlist")
@require_auth
def get_watchlist():
    rows = db()._get("watchlist", {"select": "*", "order": "tipo.asc,ticker.asc"})
    return jsonify(rows or [])


@app.post("/api/watchlist")
@require_auth
def add_watchlist():
    body = request.get_json(silent=True) or {}
    ticker = str(body.get("ticker", "")).strip().upper()
    tipo = body.get("tipo", "CEDEAR")
    if not ticker:
        return jsonify({"error": "Falta el ticker"}), 400
    if tipo not in ("CEDEAR", "CRYPTO"):
        return jsonify({"error": "Tipo invalido"}), 400
    if len(ticker) > 20 or not ticker.replace(".", "").replace("-", "").isalnum():
        return jsonify({"error": "Ticker invalido"}), 400
    res = db()._post("watchlist", {"ticker": ticker, "tipo": tipo, "activo": True, "notas": ""})
    if res is None:
        return jsonify({"error": "No se pudo agregar (¿ya existe?)"}), 409
    return jsonify(res)


@app.patch("/api/watchlist/<int:row_id>")
@require_auth
def toggle_watchlist(row_id: int):
    body = request.get_json(silent=True) or {}
    activo = bool(body.get("activo"))
    ok = db()._patch("watchlist", {"id": f"eq.{row_id}"}, {"activo": activo})
    if ok is None:
        return jsonify({"error": "No se pudo actualizar"}), 500
    return jsonify({"ok": True, "activo": activo})


@app.delete("/api/watchlist/<int:row_id>")
@require_auth
def del_watchlist(row_id: int):
    ok = db()._delete("watchlist", {"id": f"eq.{row_id}"})
    if ok is None:
        return jsonify({"error": "No se pudo borrar"}), 500
    return jsonify({"ok": True})


@app.get("/api/alertas")
@require_auth
def get_alertas():
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()
    rows = db()._get("alertas", {
        "select": "*",
        "creado_en": f"gte.{cutoff}",
        "order": "creado_en.desc",
        "limit": "60",
    })
    return jsonify(rows or [])


@app.get("/api/snapshot")
@require_auth
def get_snapshot():
    """Estado actual de todos los instrumentos, con todos los indicadores."""
    return jsonify(db().get_snapshots() or [])


# ─── Caché simple en memoria para APIs externas ──────────────────────────

_cache: dict = {}


def cached(clave: str, segundos: int, productor):
    ahora = time.time()
    hit = _cache.get(clave)
    if hit and ahora - hit[0] < segundos:
        return hit[1]
    try:
        valor = productor()
        _cache[clave] = (ahora, valor)
        return valor
    except Exception as e:
        logger.warning(f"cache {clave}: {e}")
        return hit[1] if hit else None


@app.get("/api/contexto")
@require_auth
def get_contexto():
    """Fear & Greed + tipos de cambio. Lo que hoy solo iba al resumen de Telegram."""
    from fear_greed import get_fear_greed
    from dollar_monitor import get_dollar_rates, get_dolar_mep_ccl

    fg = cached("fg", 900, get_fear_greed)
    dolar = cached("dolar", 600, get_dollar_rates) or {}
    mep_ccl = cached("mep_ccl", 600, get_dolar_mep_ccl) or {}

    return jsonify({
        "fear_greed": fg,
        "dolar": {**dolar, **{k: v for k, v in mep_ccl.items() if v}},
    })


@app.get("/api/noticias")
@require_auth
def get_noticias():
    """Titulares de la watchlist, agrupados por ticker."""
    from news_client import NewsClient

    def traer():
        d = db()
        nc = NewsClient()
        return nc.get_watchlist_news(d.get_cedears(), d.get_cryptos(), max_per_ticker=3)

    return jsonify(cached("noticias", 900, traer) or [])


# ─── Arranque ────────────────────────────────────────────────────────────

def serve():
    """Levanta el servidor. Pensado para correr en un thread daemon."""
    port = int(os.environ.get("PORT", "8080"))
    if not PANEL_USER or not PANEL_PASS:
        logger.warning("PANEL_USER/PANEL_PASS sin configurar: el panel rechaza todo acceso")
    logger.info(f"Panel web escuchando en :{port}")
    from waitress import serve as waitress_serve
    waitress_serve(app, host="0.0.0.0", port=port, threads=4, _quiet=True)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    serve()
