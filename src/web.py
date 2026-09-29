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
        # Para rutas /api/, devolver JSON sin WWW-Authenticate
        # para que el browser no muestre el diálogo nativo de auth
        if request.path.startswith("/api/"):
            return jsonify({"error": "No autorizado"}), 401
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
    """Fear & Greed + tipos de cambio + VIX."""
    from fear_greed import get_fear_greed
    from dollar_monitor import get_dollar_rates, get_dolar_mep_ccl

    fg = cached("fg", 900, get_fear_greed)
    dolar = cached("dolar", 600, get_dollar_rates) or {}
    mep_ccl = cached("mep_ccl", 600, get_dolar_mep_ccl) or {}

    # VIX: índice de volatilidad del mercado
    def traer_vix():
        try:
            from market_data import get_series
            serie = get_series("^VIX", "CEDEAR", "5d", "1d")
            if serie and len(serie) > 0:
                return float(serie[-1])
        except Exception as e:
            logger.warning(f"VIX: {e}")
        return None

    vix = cached("vix", 1800, traer_vix)

    return jsonify({
        "fear_greed": fg,
        "dolar": {**dolar, **{k: v for k, v in mep_ccl.items() if v}},
        "vix": vix,
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


@app.get("/api/screener")
@require_auth
def get_screener():
    """Oportunidades en 50 CEDEARs que no estás mirando."""
    from iol_client import IOLClient
    from screener import Screener

    def correr():
        d = db()
        res = Screener({}).scan_cedear(IOLClient(), d.get_cedears())
        return [r.__dict__ for r in res]

    return jsonify(cached("screener", 3600, correr) or [])


@app.get("/api/portfolio")
@require_auth
def get_portfolio_api():
    """Posiciones con P&L calculado contra el precio actual."""
    from portfolio import PortfolioTracker

    d = db()
    tracker = PortfolioTracker(d)
    posiciones = tracker.get_positions()
    if not posiciones:
        return jsonify({"posiciones": [], "total": None})

    # Reusa los precios del snapshot en vez de volver a pedirlos
    precios = {s["ticker"]: float(s["precio"]) for s in (d.get_snapshots() or [])
               if s.get("precio")}
    pnl = tracker.calculate_pnl(posiciones, precios)

    invertido = sum(float(p.get("cantidad", 0)) * float(p.get("precio_entrada", 0))
                    for p in pnl if p.get("precio_entrada"))
    actual = sum(float(p.get("cantidad", 0)) * float(p.get("precio_actual", 0))
                 for p in pnl if p.get("precio_actual"))
    total = None
    if invertido > 0:
        total = {
            "invertido": round(invertido, 2),
            "actual": round(actual, 2),
            "pnl_abs": round(actual - invertido, 2),
            "pnl_pct": round((actual / invertido - 1) * 100, 2),
        }
    return jsonify({"posiciones": pnl, "total": total})


@app.post("/api/portfolio/import")
@require_auth
def import_portfolio():
    """
    Importa posiciones desde Excel de Balanz (multipart/form-data, campo 'file').
    Hace upsert de cada ticker; devuelve resumen {ok, errores}.
    """
    import io
    import openpyxl

    if "file" not in request.files:
        return jsonify({"error": "Falta el archivo"}), 400

    f = request.files["file"]
    if not f.filename.endswith((".xlsx", ".xls")):
        return jsonify({"error": "Solo se aceptan archivos .xlsx"}), 400

    TIPO_MAP = {"acciones": "CEDEAR", "cedears": "CEDEAR", "crypto": "CRYPTO"}

    try:
        wb = openpyxl.load_workbook(io.BytesIO(f.read()))
        ws = wb.active
        rows = list(ws.iter_rows(values_only=True))
        if not rows:
            return jsonify({"error": "Archivo vacío"}), 400

        header = [str(h).strip().lower() if h else "" for h in rows[0]]

        def col(row, name):
            try:
                return row[header.index(name)]
            except (ValueError, IndexError):
                return None

        ok_list, err_list = [], []

        for row in rows[1:]:
            ticker = col(row, "ticker")
            if not ticker:
                continue
            ticker = str(ticker).strip().upper()
            tipo_raw = str(col(row, "tipo de instrumento") or "").strip().lower()
            cantidad = col(row, "nominales")
            precio_prom = col(row, "precio promedio de compra")
            precio_actual = col(row, "precio")
            valor_actual = col(row, "valor actual")
            rendimiento_pct = col(row, "porcentaje de rendimiento")
            dias_tenencia = col(row, "días promedio de tenencia")

            if not cantidad:
                continue

            tipo = TIPO_MAP.get(tipo_raw, "CEDEAR")

            # Limpiar rendimiento_pct (puede venir como "125.24%" string)
            if isinstance(rendimiento_pct, str):
                try:
                    rendimiento_pct = float(rendimiento_pct.replace("%", "").replace(",", ".").strip())
                except Exception:
                    rendimiento_pct = None

            res = db()._upsert("portfolio", {
                "ticker": ticker,
                "tipo": tipo,
                "cantidad": float(cantidad),
                "precio_entrada": float(precio_prom) if precio_prom else None,
                "activo": True,
                "notas": f"Balanz import | rendimiento: {rendimiento_pct}% | días: {dias_tenencia}",
            }, on_conflict="ticker")

            if res is not None:
                ok_list.append(ticker)
            else:
                err_list.append(ticker)

        return jsonify({
            "ok": len(ok_list),
            "errores": len(err_list),
            "importados": ok_list,
            "fallidos": err_list,
        })

    except Exception as e:
        logger.error(f"import_portfolio: {e}")
        return jsonify({"error": str(e)}), 500


@app.get("/api/fundamentals/<ticker>")
@require_auth
def get_fundamentals_api(ticker: str):
    """
    Devuelve fundamentales completos de un ticker + análisis técnico del snapshot.
    Incluye recomendación de entrada/salida basada en indicadores.
    """
    from market_data import get_fundamentals, get_series, fuerza_relativa

    ticker = ticker.upper().strip()
    snap = None

    # Buscar snapshot del ticker para indicadores técnicos
    snaps = db().get_snapshots() or []
    for s in snaps:
        if s.get("ticker") == ticker:
            snap = s
            break

    tipo = (snap or {}).get("tipo", "CEDEAR")

    # Fundamentales desde Yahoo
    fund = cached(f"fund_api:{ticker}", 3600, lambda: get_fundamentals(ticker, tipo))

    # Fuerza relativa
    rs = cached(f"rs_api:{ticker}", 3600, lambda: fuerza_relativa(ticker, tipo))

    # Serie de precios (últimos 30 cierres para mini-chart)
    serie_data = cached(f"serie_api:{ticker}", 1800, lambda: get_series(ticker, tipo))
    serie = []
    if serie_data and serie_data.get("closes"):
        serie = [round(c, 4) for c in serie_data["closes"][-60:]]

    # Construir análisis de recomendación
    recomendacion = _build_recomendacion(snap, fund, rs)

    return jsonify({
        "ticker": ticker,
        "tipo": tipo,
        "fundamentales": fund or {},
        "fuerza_relativa": rs or {},
        "serie_30d": serie,
        "snapshot": snap or {},
        "recomendacion": recomendacion,
    })


def _build_recomendacion(snap: dict, fund: dict, rs: dict) -> dict:
    """
    Genera una recomendación textual basada en indicadores técnicos + fundamentales.
    Retorna {nivel: COMPRA|ESPERAR|VENTA, puntuacion: int, razones: list, riesgos: list}
    """
    razones = []
    riesgos = []
    score = 50  # Neutro

    if not snap:
        return {"nivel": "SIN_DATOS", "puntuacion": score, "razones": [], "riesgos": []}

    ind = snap.get("indicadores") or {}

    # ── Tendencia ──────────────────────────────────────────────────────
    td = ind.get("tendencia_diaria") or {}
    alin = td.get("alineacion", "")
    if "alcista" in alin.lower():
        score += 10
        razones.append("✅ Tendencia diaria alcista — precio sobre SMA50 y SMA200")
    elif "bajista" in alin.lower():
        score -= 10
        riesgos.append("⚠️ Tendencia diaria bajista — precio bajo medias")

    # ── RSI ────────────────────────────────────────────────────────────
    rsi = ind.get("rsi")
    if rsi:
        if rsi < 35:
            score += 12
            razones.append(f"✅ RSI sobrevendido ({rsi:.0f}) — potencial rebote técnico")
        elif rsi < 45:
            score += 5
            razones.append(f"✅ RSI en zona neutra-baja ({rsi:.0f}) — margen de entrada")
        elif rsi > 70:
            score -= 10
            riesgos.append(f"⚠️ RSI sobrecomprado ({rsi:.0f}) — riesgo de corrección")
        elif rsi > 60:
            score -= 3
            riesgos.append(f"⚠️ RSI elevado ({rsi:.0f}) — entrar con cautela")

    # ── MACD ───────────────────────────────────────────────────────────
    macd = ind.get("macd")
    macd_sig = ind.get("macd_signal")
    if macd is not None and macd_sig is not None:
        if macd > macd_sig:
            score += 8
            razones.append("✅ MACD sobre señal — momentum positivo")
        else:
            score -= 5
            riesgos.append("⚠️ MACD bajo señal — momentum negativo")

    # ── Volumen ────────────────────────────────────────────────────────
    vr = ind.get("vol_ratio")
    if vr and vr >= 1.5:
        score += 5
        razones.append(f"✅ Volumen alto (x{vr:.1f}) — confirma movimiento")

    # ── Fuerza relativa ────────────────────────────────────────────────
    if rs:
        r21 = rs.get("rs_21")
        if r21 is not None:
            if r21 > 5:
                score += 8
                razones.append(f"✅ Supera al índice en {r21:+.1f}% (21d) — momentum relativo fuerte")
            elif r21 < -8:
                score -= 8
                riesgos.append(f"⚠️ Pierde contra el índice por {r21:+.1f}% (21d) — rezagado")

    # ── Fundamentales ──────────────────────────────────────────────────
    if fund:
        per = fund.get("per")
        if per:
            if per < 15:
                score += 8
                razones.append(f"✅ P/E bajo ({per:.1f}x) — valuación atractiva")
            elif per > 40:
                score -= 5
                riesgos.append(f"⚠️ P/E alto ({per:.1f}x) — exige crecimiento fuerte")

        potencial = fund.get("potencial_pct")
        if potencial:
            if potencial > 20:
                score += 10
                razones.append(f"✅ Potencial {potencial:+.1f}% según analistas (consenso: {fund.get('recomendacion','?')})")
            elif potencial < -10:
                score -= 8
                riesgos.append(f"⚠️ Precio sobre objetivo de analistas ({potencial:+.1f}%)")

        dias_balance = fund.get("dias_al_balance")
        if dias_balance is not None and 0 <= dias_balance <= 10:
            riesgos.append(f"⚠️ Balance en {dias_balance} días — alta volatilidad esperada")

        div = fund.get("dividendo_pct")
        if div and div > 2:
            score += 4
            razones.append(f"✅ Dividendo {div:.1f}% anual — ingreso pasivo")

    # ── Soporte / resistencia ──────────────────────────────────────────
    sop = ind.get("soporte")
    precio = snap.get("precio")
    if sop and precio:
        dist_s = (precio / sop - 1) * 100
        if 0 < dist_s < 5:
            score += 6
            razones.append(f"✅ Cerca del soporte (${sop:.2f}) — riesgo/beneficio favorable")

    # ── Clasificación final ────────────────────────────────────────────
    score = max(0, min(100, score))
    if score >= 65:
        nivel = "COMPRA"
    elif score >= 45:
        nivel = "ESPERAR"
    else:
        nivel = "VENTA"

    return {
        "nivel": nivel,
        "puntuacion": score,
        "razones": razones,
        "riesgos": riesgos,
    }


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
