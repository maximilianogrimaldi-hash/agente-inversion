"""
Carga las posiciones reales del Excel de Balanz a Supabase.
Uso: python scripts/cargar_portfolio_balanz.py

Extrae ticker, tipo, cantidad y precio_promedio_compra del Excel.
Limpia las posiciones previas marcadas como activo=False antes de insertar.
"""

import os
import sys
import openpyxl
import requests

SUPABASE_URL = os.environ["SUPABASE_URL"].rstrip("/")
SUPABASE_KEY = (
    os.environ.get("SUPABASE_KEY")
    or os.environ.get("SUPABASE_SERVICE_KEY")
    or os.environ["SUPABASE_ANON_KEY"]
)

HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
    "Prefer": "return=representation",
}

# Mapa de tipo Balanz → tipo interno
TIPO_MAP = {
    "acciones": "CEDEAR",   # YPFD cotiza en pesos, tratado igual
    "cedears": "CEDEAR",
    "crypto": "CRYPTO",
}

XLSX = os.path.join(os.path.dirname(__file__), "..", "data", "portfolio_balanz.xlsx")


def cargar_desde_xlsx(path: str) -> list[dict]:
    wb = openpyxl.load_workbook(path)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    header = [str(h).strip().lower() if h else "" for h in rows[0]]

    def col(row, name):
        try:
            return row[header.index(name)]
        except (ValueError, IndexError):
            return None

    posiciones = []
    for row in rows[1:]:
        ticker = col(row, "ticker")
        tipo_raw = str(col(row, "tipo de instrumento") or "").strip().lower()
        cantidad = col(row, "nominales")
        precio_prom = col(row, "precio promedio de compra")
        precio_actual = col(row, "precio")
        valor_actual = col(row, "valor actual")
        rendimiento_pct = col(row, "variación (%)")

        if not ticker or not cantidad:
            continue

        tipo = TIPO_MAP.get(tipo_raw, "CEDEAR")

        posiciones.append({
            "ticker": str(ticker).strip().upper(),
            "tipo": tipo,
            "cantidad": float(cantidad),
            "precio_entrada": float(precio_prom) if precio_prom else None,
            "precio_actual_ars": float(precio_actual) if precio_actual else None,
            "valor_actual_ars": float(valor_actual) if valor_actual else None,
            "rendimiento_pct": float(rendimiento_pct) if isinstance(rendimiento_pct, (int, float)) else None,
            "activo": True,
            "notas": "Importado desde Balanz 27/09/2026",
        })

    return posiciones


def upsert_posicion(p: dict) -> bool:
    # Upsert por ticker (on_conflict=ticker)
    resp = requests.post(
        f"{SUPABASE_URL}/rest/v1/portfolio",
        headers={**HEADERS, "Prefer": "resolution=merge-duplicates,return=representation"},
        json=p,
        timeout=10,
    )
    if resp.status_code in (200, 201):
        print(f"  ✓ {p['ticker']} — {p['cantidad']} u. @ ${p['precio_entrada']:,.0f} ARS")
        return True
    else:
        print(f"  ✗ {p['ticker']}: {resp.status_code} {resp.text[:120]}")
        return False


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--xlsx", default=XLSX, help="Ruta al Excel de Balanz")
    args = parser.parse_args()

    path = args.xlsx
    if not os.path.exists(path):
        # Buscar en uploads si se pasa la ruta directa
        if os.path.exists(sys.argv[-1]) and sys.argv[-1].endswith(".xlsx"):
            path = sys.argv[-1]
        else:
            print(f"ERROR: no encontré {path}")
            print("Uso: python scripts/cargar_portfolio_balanz.py --xlsx /ruta/al/archivo.xlsx")
            sys.exit(1)

    print(f"Leyendo {path}...")
    posiciones = cargar_desde_xlsx(path)
    print(f"Encontré {len(posiciones)} posiciones:")

    ok = 0
    for p in posiciones:
        if upsert_posicion(p):
            ok += 1

    print(f"\n{ok}/{len(posiciones)} posiciones cargadas en Supabase.")
    if ok == len(posiciones):
        print("✅ Portfolio sincronizado correctamente.")
    else:
        print("⚠️ Algunas posiciones no se pudieron cargar.")


if __name__ == "__main__":
    main()
