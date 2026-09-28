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
