"""Clasificacion ABC de las TIENDAS por venta (valor neto sin IVA) de los ultimos meses cerrados de la ventana.
A = las tiendas que juntan hasta el corte A (80 % por defecto) de la venta total, B = hasta el corte B (95 %), C = el resto.
La tienda que cruza el corte se queda en la clase mejor. Sin venta = C. Se puede fijar a mano (clase_manual) y manda sobre la calculada.
Se usa de desempate en el reparto del CEDI (regla 5: A primero) y se muestra en los reportes y filtros."""
from sqlalchemy import text

RANGO = {"A": 0, "B": 1, "C": 2}
SIN_CLASE = 3


def rango(clase: str | None) -> int:
    return RANGO.get((clase or "").upper(), SIN_CLASE)


def clasificar(ventas: list[tuple], corte_a: float = 80.0, corte_b: float = 95.0) -> dict:
    """ventas = [(clave, venta)] -> {clave: (clase, venta, pct_acumulado)}. Ordena de mayor a menor venta (a igualdad, por clave)."""
    corte_a = min(max(corte_a, 0.0), 100.0); corte_b = min(max(corte_b, corte_a), 100.0)
    total = sum(v for _, v in ventas if v and v > 0)
    out, acum = {}, 0.0
    for k, v in sorted(ventas, key=lambda x: (-(x[1] or 0.0), str(x[0]))):
        v = float(v or 0.0)
        if total <= 0 or v <= 0:
            out[k] = ("C", v, 100.0 if total > 0 else 0.0); continue
        antes = 100.0 * acum / total          # % acumulado ANTES de esta tienda: si aun no llega al corte, entra en la clase
        acum += v
        clase = "A" if antes < corte_a - 1e-9 else ("B" if antes < corte_b - 1e-9 else "C")
        out[k] = (clase, v, 100.0 * acum / total)
    return out


def _param(c, clave: str, defecto: float) -> float:
    v = c.execute(text("SELECT valor FROM ddmrp.parametro WHERE clave = :k"), {"k": clave}).scalar()
    return float(v) if v is not None else defecto


def recalcular(c) -> dict:
    """Recalcula la clase de cada tienda de la Bitacora (activa, sin CEDI) con la venta de los ultimos N meses cerrados. Conserva la clase manual."""
    meses = int(_param(c, "clase_tienda_meses", 6)); ca = _param(c, "clase_tienda_corte_a", 80); cb = _param(c, "clase_tienda_corte_b", 95)
    filas = c.execute(text("""
        SELECT b.empresa, b.bodega_id, COALESCE(sum(v.valor), 0)::float8
        FROM ddmrp.abast_bitacora b
        LEFT JOIN ddmrp.ventas_mensual v ON v.empresa = b.empresa AND v.bodega_id = b.bodega_id
             AND v.mes >= to_char(date_trunc('month', current_date) - make_interval(months => :m), 'YYYYMM')
             AND v.mes <  to_char(date_trunc('month', current_date), 'YYYYMM')
        WHERE COALESCE(b.activa, 1) = 1
          AND NOT EXISTS (SELECT 1 FROM ddmrp.maestro_cedi mc WHERE mc.bodega_id = b.bodega_id)
        GROUP BY b.empresa, b.bodega_id"""), {"m": meses}).all()
    res = {}
    for emp in {f[0] for f in filas}:             # el ABC es por empresa: cada una se mide contra sus propias tiendas
        res.update({(emp, k): v for k, v in clasificar([(f[1], f[2]) for f in filas if f[0] == emp], ca, cb).items()})
    c.execute(text("DELETE FROM ddmrp.tienda_clase t WHERE t.clase_manual IS NULL AND NOT EXISTS "
                   "(SELECT 1 FROM ddmrp.abast_bitacora b WHERE b.empresa = t.empresa AND b.bodega_id = t.bodega_id AND COALESCE(b.activa, 1) = 1)"))
    if res:
        c.execute(text("""INSERT INTO ddmrp.tienda_clase (empresa, bodega_id, clase_calc, venta, pct_acum, calculada)
                          VALUES (:e, :b, :c, :v, :p, now())
                          ON CONFLICT (empresa, bodega_id) DO UPDATE SET clase_calc = EXCLUDED.clase_calc, venta = EXCLUDED.venta,
                                pct_acum = EXCLUDED.pct_acum, calculada = EXCLUDED.calculada"""),
                  [{"e": e, "b": b, "c": cl, "v": v, "p": p} for (e, b), (cl, v, p) in res.items()])
    return {"tiendas": len(res), "A": sum(1 for x in res.values() if x[0] == "A"), "B": sum(1 for x in res.values() if x[0] == "B"),
            "C": sum(1 for x in res.values() if x[0] == "C"), "meses": meses}
