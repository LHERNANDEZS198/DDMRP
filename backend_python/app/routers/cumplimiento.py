"""Cumplimiento de los proveedores (surtido y plazo) y configuración sugerida para el buffer del CEDI.
Lee el historial de OC de Siesa (cantidad pedida vs recibida y plazo pactado) y propone, por proveedor: lead time, colchón de la zona roja (factor_tor) y si
conviene pedir también en zona verde. Es solo una sugerencia: no se aplica nada hasta que compras lo confirma en la pantalla (POST /aplicar).
Se mide con la entrada REAL de cada OC: el documento de compras (t451, que apunta a la OC por f451_rowid_oc_docto) y su fecha (t350.f350_fecha):
  - lead time real = de la fecha de la OC a su PRIMERA entrada; las OC que se montaron el mismo dia de la entrada (regularizaciones) no cuentan
  - a tiempo = la primera entrada llego a mas tardar 1 dia despues de la fecha pactada en la OC
  - surtido = lo recibido contra lo pedido en las OC cuya fecha pactada ya paso hace mas de DIAS_MADURA dias
  - OTIF = % de OC maduras que llegaron a tiempo Y completas (98% o mas de lo pedido)
Si el enlace con las entradas falla en alguna base, se cae al plazo pactado y se avisa."""
import math
from datetime import date, timedelta
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import bindparam, text
from ..config import settings
from ..db import pg, siesa_engine
from ..security import requiere

router = APIRouter(prefix="/compras/cumplimiento", tags=["compras"], dependencies=[Depends(requiere("cargar_maestros_compras"))])

SQL_OC = """
SELECT RTRIM(t.f200_id) AS nit,
       RTRIM(d.f420_id_tipo_docto) + '-' + RTRIM(d.f420_consec_docto) AS oc,
       CONVERT(date, d.f420_fecha) AS fecha_oc,
       CONVERT(date, MIN(m.f421_fecha_entrega)) AS entrega,
       CONVERT(float, SUM(m.f421_cant_pedida_base)) AS pedida,
       CONVERT(float, SUM(m.f421_cant_entrada)) AS recibida
FROM t420_cm_oc_docto d
JOIN t200_mm_terceros t ON t.f200_rowid = d.f420_rowid_tercero_prov
JOIN t421_cm_oc_movto m ON m.f421_rowid_oc_docto = d.f420_rowid
WHERE d.f420_id_cia = :cia AND d.f420_ind_estado <> 9 AND m.f421_ind_estado IN (1, 2, 3)
  AND d.f420_fecha >= :desde AND RTRIM(t.f200_id) IN :nits
GROUP BY t.f200_id, d.f420_id_tipo_docto, d.f420_consec_docto, d.f420_fecha
"""
# misma consulta + la primera entrada de cada OC (documento de compras t451 -> su fecha en t350). La subconsulta evita multiplicar las sumas por el numero de entradas.
SQL_OC_ENTRADAS = SQL_OC.replace("""       CONVERT(float, SUM(m.f421_cant_entrada)) AS recibida
FROM t420_cm_oc_docto d""", """       CONVERT(float, SUM(m.f421_cant_entrada)) AS recibida,
       CONVERT(date, MIN(en.primera)) AS primera_entrada
FROM t420_cm_oc_docto d""").replace("""JOIN t421_cm_oc_movto m ON m.f421_rowid_oc_docto = d.f420_rowid
WHERE""", """JOIN t421_cm_oc_movto m ON m.f421_rowid_oc_docto = d.f420_rowid
LEFT JOIN (SELECT c.f451_rowid_oc_docto AS rowid_oc, MIN(e.f350_fecha) AS primera
           FROM t451_cm_docto_compras c JOIN t350_co_docto_contable e ON e.f350_rowid = c.f451_rowid_docto
           WHERE c.f451_id_cia = :cia AND e.f350_ind_estado = 1 AND c.f451_rowid_oc_docto IS NOT NULL
           GROUP BY c.f451_rowid_oc_docto) en ON en.rowid_oc = d.f420_rowid
WHERE""")
MIN_OC = 5            # menos OC maduras que esto = muestra chica: no se sugiere nada
DIAS_MADURA = 7       # una OC cuenta para el surtido cuando su fecha pactada pasó hace más de estos días (si no, aún puede estar llegando)


class Prov(BaseModel):
    empresa: str
    proveedor_id: str
    sucursal: str = "001"


class AnalisisIn(BaseModel):
    proveedores: list[Prov]
    meses: int = 12


class Aplicar1(BaseModel):
    empresa: str
    proveedor_id: str
    sucursal: str = "001"
    leadtime: float | None = None
    factor_tor: float | None = None
    pedir_verde: int | None = None


class AplicarIn(BaseModel):
    items: list[Aplicar1]


def _pct(xs: list[float], q: float) -> float:
    xs = sorted(xs)
    if not xs:
        return 0.0
    k = (len(xs) - 1) * q
    lo, hi = math.floor(k), math.ceil(k)
    return xs[lo] + (xs[hi] - xs[lo]) * (k - lo)


def evaluar(filas: list[tuple], hoy: date) -> dict:
    """Metricas y sugerencia de UN proveedor a partir de sus OC: (nit, oc, fecha_oc, entrega_pactada, pedida, recibida[, primera_entrada])."""
    plazos_pact, lt_real, atrasos, maduras, abiertas_viejas = [], [], [], [], []
    regularizadas = 0
    for f in filas:
        _nit, oc, f_oc, f_ent, pedida, recibida = f[:6]
        f_prim = f[6] if len(f) > 6 else None
        pedida, recibida = float(pedida or 0), float(recibida or 0)
        if pedida <= 0 or not f_oc:
            continue
        dias_real = (f_prim - f_oc).days if f_prim else None
        regulariza = dias_real is not None and dias_real <= 0      # OC montada el mismo dia (o despues) de la entrada: no mide al proveedor
        regularizadas += 1 if regulariza else 0
        if f_ent:
            plazo = (f_ent - f_oc).days
            if 0 < plazo <= 120:
                plazos_pact.append(plazo)
        a_tiempo = None
        if f_prim and f_ent and not regulariza:
            a_tiempo = (f_prim - f_ent).days <= 1
            atrasos.append((f_prim - f_ent).days)
        if dias_real is not None and 0 < dias_real <= 120:
            lt_real.append(dias_real)
        if f_ent and f_ent + timedelta(days=DIAS_MADURA) <= hoy:
            maduras.append((oc, pedida, min(recibida, pedida), a_tiempo, regulariza))
            if f_ent + timedelta(days=15) <= hoy and recibida < pedida * 0.98:
                abiertas_viejas.append((oc, pedida - recibida))
    ped = sum(x[1] for x in maduras)
    rec = sum(x[2] for x in maduras)
    surtido = rec / ped if ped > 0 else None
    completas = sum(1 for x in maduras if x[2] >= x[1] * 0.98) / len(maduras) if maduras else None
    medibles = [x for x in maduras if x[3] is not None]
    a_tiempo_pct = sum(1 for x in medibles if x[3]) / len(medibles) if medibles else None
    otif = sum(1 for x in medibles if x[3] and x[2] >= x[1] * 0.98) / len(medibles) if medibles else None
    r1 = lambda v: None if v is None else round(v * 100, 1)
    m = {"oc_total": len(filas), "oc_maduras": len(maduras), "oc_regularizadas": regularizadas, "surtido_pct": r1(surtido), "oc_completas_pct": r1(completas),
         "a_tiempo_pct": r1(a_tiempo_pct), "otif_pct": r1(otif), "oc_medibles": len(medibles),
         "plazo_p50": round(_pct(plazos_pact, .5), 1) if plazos_pact else None, "plazo_p75": round(_pct(plazos_pact, .75), 1) if plazos_pact else None,
         "lt_real_p50": round(_pct(lt_real, .5), 1) if lt_real else None, "lt_real_p75": round(_pct(lt_real, .75), 1) if lt_real else None, "lt_real_n": len(lt_real),
         "atraso_p50": round(_pct(atrasos, .5), 1) if atrasos else None,
         "saldos_viejos_oc": len(abiertas_viejas), "saldos_viejos_u": round(sum(x[1] for x in abiertas_viejas))}
    sug: dict = {"leadtime": None, "factor_tor": None, "pedir_verde": None}
    motivos: list[str] = []
    if len(maduras) < MIN_OC:
        motivos.append(f"Pocas OC con plazo cumplido en la ventana ({len(maduras)}, se piden al menos {MIN_OC}): no hay base para sugerir.")
        return {"metricas": m, "sugerido": sug, "motivos": motivos}
    if len(lt_real) >= MIN_OC:
        sug["leadtime"] = float(max(1, math.ceil(_pct(lt_real, .75))))
        motivos.append(f"Lead time = lo que realmente demoró en el 75% de las OC ({m['lt_real_p75']} d; mediana {m['lt_real_p50']} d; pactado {m['plazo_p75']} d).")
    elif len(plazos_pact) >= MIN_OC:
        sug["leadtime"] = float(max(1, math.ceil(_pct(plazos_pact, .75))))
        motivos.append(f"Lead time = plazo pactado en la OC del 75% de los casos ({m['plazo_p75']} d); no hay entradas suficientes para medir el real.")
    if a_tiempo_pct is not None:
        motivos.append(f"Llega a tiempo el {m['a_tiempo_pct']}% de las OC (retraso mediano {m['atraso_p50']} d frente a la fecha pactada); OTIF {m['otif_pct']}%.")
    if surtido is not None and surtido < 0.98:
        sug["factor_tor"] = float(min(2.0, max(1.0, math.ceil(100 / surtido / 5) * 5 / 100)))
        motivos.append(f"Surte el {m['surtido_pct']}% de lo pedido: se sube la zona roja x{sug['factor_tor']:.2f} para cubrir lo que no llega.")
    else:
        sug["factor_tor"] = 1.0
        motivos.append("Surte casi todo lo pedido: sin colchón extra.")
    if (surtido is not None and surtido < 0.95) or (completas is not None and completas < 0.7):
        sug["pedir_verde"] = 1
        motivos.append(f"Solo el {m['oc_completas_pct']}% de las OC llega completa: conviene pedir también en zona verde.")
    else:
        sug["pedir_verde"] = 0
        motivos.append("Cumple bien: no hace falta pedir en zona verde.")
    if m["saldos_viejos_oc"]:
        motivos.append(f"{m['saldos_viejos_oc']} OC con saldo vencido hace más de 15 días ({m['saldos_viejos_u']:,} u): ciérralas en Siesa o déjalas fuera del tránsito (regla «Ignorar tránsito de OC con atraso»).".replace(",", "."))
    return {"metricas": m, "sugerido": sug, "motivos": motivos}


@router.post("/analizar")
def analizar(b: AnalisisIn):
    if not b.proveedores:
        raise HTTPException(400, "Elige al menos un proveedor")
    if len(b.proveedores) > 2000:
        raise HTTPException(400, "Máximo 2000 proveedores por análisis")
    meses = min(max(int(b.meses or 12), 3), 36)
    hoy = date.today()
    desde = hoy - timedelta(days=30 * meses)
    por_emp: dict[str, list[Prov]] = {}
    for p in b.proveedores:
        por_emp.setdefault(p.empresa, []).append(p)
    with pg.connect() as c:
        actual = {(r[0], r[1], r[2]): r[3:] for r in c.execute(text(
            "SELECT empresa, proveedor_id, sucursal, nombre, leadtime::float8, factor_tor::float8, pedir_verde FROM ddmrp.proveedor")).all()}
    out, avisos = [], []
    for emp, provs in por_emp.items():
        db = settings.siesa_db if emp == "05" else settings.siesa_db_s if emp == "21" else ""
        if not db:
            avisos.append(f"Empresa {emp}: sin base de Siesa configurada")
            continue
        nits = sorted({p.proveedor_id.strip() for p in provs})
        try:
            filas = []
            sql = SQL_OC_ENTRADAS
            with siesa_engine(db).connect() as cx:
                for i in range(0, len(nits), 500):   # SQL Server admite ~2100 parametros por consulta: se va por tandas
                    prm = {"cia": settings.siesa_cia, "desde": desde, "nits": nits[i:i + 500]}
                    try:
                        filas += cx.execute(text(sql).bindparams(bindparam("nits", expanding=True)), prm).all()
                    except Exception as e1:   # sin el enlace con las entradas: se cae al plazo pactado (sin lead time real ni % a tiempo)
                        if sql is SQL_OC:
                            raise
                        cx.rollback()
                        sql = SQL_OC
                        avisos.append(f"Empresa {emp}: no se pudieron leer las entradas de mercancía ({str(e1).splitlines()[0][:120]}); se usa el plazo pactado en la OC")
                        filas += cx.execute(text(sql).bindparams(bindparam("nits", expanding=True)), prm).all()
        except Exception as e:
            avisos.append(f"Empresa {emp}: no se pudo leer Siesa ({str(e).splitlines()[0][:160]})")
            continue
        por_nit: dict[str, list[tuple]] = {}
        for r in filas:
            por_nit.setdefault(str(r[0]).strip(), []).append(tuple(r))
        for p in provs:
            ev = evaluar(por_nit.get(p.proveedor_id.strip(), []), hoy)
            a = actual.get((p.empresa, p.proveedor_id, p.sucursal), (None, None, None, None))
            out.append({"empresa": p.empresa, "proveedor_id": p.proveedor_id, "sucursal": p.sucursal, "nombre": a[0],
                        "actual": {"leadtime": a[1], "factor_tor": a[2], "pedir_verde": a[3]}, **ev})
    return {"desde": desde.isoformat(), "meses": meses, "resultados": out, "avisos": avisos}


@router.post("/aplicar")
def aplicar(b: AplicarIn):
    n = 0
    with pg.begin() as c:
        for it in b.items:
            sets, prm = [], {"e": it.empresa, "p": it.proveedor_id, "s": it.sucursal}
            if it.leadtime is not None:
                if it.leadtime < 0:
                    raise HTTPException(400, "El lead time no puede ser negativo")
                sets.append("leadtime = :lt"); prm["lt"] = it.leadtime
            if it.factor_tor is not None:
                if it.factor_tor < 1 or it.factor_tor > 5:
                    raise HTTPException(400, "El colchón (factor de la zona roja) va entre 1 y 5")
                sets.append("factor_tor = :ft"); prm["ft"] = None if it.factor_tor == 1 else it.factor_tor
            if it.pedir_verde is not None:
                sets.append("pedir_verde = :pv"); prm["pv"] = 1 if it.pedir_verde else 0
            if not sets:
                continue
            r = c.execute(text(f"UPDATE ddmrp.proveedor SET {', '.join(sets)} WHERE empresa = :e AND proveedor_id = :p AND sucursal = :s"), prm)
            n += r.rowcount or 0
    return {"actualizados": n}
