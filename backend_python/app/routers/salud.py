"""Salud del inventario: por tienda x item cruza el estado del buffer de hoy (zona) con la importancia del item (clase ABC x XYZ)
y su rotacion, para decidir que atender primero. Usa la misma clasificacion de /clasificacion (mismos filtros y ventana)."""
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from .. import clasificacion as cl, excel
from ..security import usuario_actual, requiere
from .clasificacion import _calcular
from .control import ZONAS, _csv

router = APIRouter(prefix="/salud", tags=["salud"], dependencies=[Depends(requiere("ver_control"))])
ORDEN_DIAG = ["prioridad", "reponer", "vigilar", "exceso_clave", "exceso", "dormido", "ok"]


def _datos(user, criterio, meses, empresa, bodegas, labs, crit, q, zonas, diag):
    items, meta = _calcular(user, "tienda_item", criterio, meses, 80, 95, empresa, bodegas, labs, crit, q)
    for i in items:
        i["diag"] = cl.diagnostico(i)
    resumen = {k: {"diag": k, "etiqueta": cl.DIAGNOSTICOS[k][0], "color": cl.DIAGNOSTICOS[k][1], "ayuda": cl.DIAGNOSTICOS[k][2], "n": 0, "inv_costo": 0.0, "margen": 0.0}
               for k in ORDEN_DIAG}
    for i in items:
        r = resumen[i["diag"]]; r["n"] += 1; r["inv_costo"] += i["inv_costo"] or 0.0; r["margen"] += i["margen"] or 0.0
    z = [x for x in _csv(zonas) if x in ZONAS]; d = [x for x in _csv(diag) if x in ORDEN_DIAG]
    vis = [i for i in items if (not z or i.get("zona") in z) and (not d or i["diag"] in d)]
    vis.sort(key=lambda i: (ORDEN_DIAG.index(i["diag"]), i["puesto"] or 10**9, i["producto_id"], i["bodega_id"]))
    return vis, [resumen[k] for k in ORDEN_DIAG], meta, len(items)


@router.get("")
def salud(criterio: str = "margen", meses: int = 12, empresa: str | None = None, bodegas: str | None = None, labs: str | None = None,
          crit: str | None = None, q: str | None = None, zonas: str | None = None, diag: str | None = None,
          limit: int = Query(3000, le=20000), user=Depends(usuario_actual)):
    vis, resumen, meta, total = _datos(user, criterio, meses, empresa, bodegas, labs, crit, q, zonas, diag)
    return {"meta": meta, "resumen": resumen, "filas": vis[:limit], "total": len(vis), "truncado": len(vis) > limit}


COLS = [{"t": "Atender", "k": "etq", "w": 24}, {"t": "Tienda", "k": "bodega_id", "w": 9}, {"t": "Nombre tienda", "k": "bodega_nombre", "w": 24},
        {"t": "Item", "k": "producto_id", "w": 11}, {"t": "Descripcion", "k": "descripcion", "w": 44}, {"t": "Laboratorio", "k": "laboratorio", "w": 14},
        {"t": "Zona hoy", "k": "zona", "w": 11, "zona": True}, {"t": "% buffer", "k": "pct_buffer", "f": "dec1"}, {"t": "Clase", "k": "clase", "w": 8},
        {"t": "Ranking", "k": "puesto", "f": "int"}, {"t": "Inventario (u.)", "k": "inventario", "f": "int"}, {"t": "Flujo neto", "k": "flujo_neto", "f": "int"},
        {"t": "Sugerido (u.)", "k": "sugerido", "f": "int"}, {"t": "Dias de inventario", "k": "dias_inv", "f": "int"}, {"t": "Rotacion (uds/mes)", "k": "rotacion", "f": "dec2"},
        {"t": "Sobran (u.)", "k": "sobran", "f": "int"}, {"t": "Faltan (u.)", "k": "faltan", "f": "int"},
        {"t": "Inventario a costo $", "k": "inv_costo", "f": "cop"}, {"t": "Venta neta $", "k": "valor", "f": "cop"}, {"t": "Margen $", "k": "margen", "f": "cop"},
        {"t": "Margen %", "k": "margen_pct", "f": "dec1"}, {"t": "GMROI (anual)", "k": "gmroi", "f": "dec2"}, {"t": "IV", "k": "iv", "f": "dec2"}]


@router.get("/excel")
def exportar(criterio: str = "margen", meses: int = 12, empresa: str | None = None, bodegas: str | None = None, labs: str | None = None,
             crit: str | None = None, q: str | None = None, zonas: str | None = None, diag: str | None = None, user=Depends(usuario_actual)):
    vis, resumen, meta, total = _datos(user, criterio, meses, empresa, bodegas, labs, crit, q, zonas, diag)
    for i in vis:
        i["etq"] = cl.DIAGNOSTICOS[i["diag"]][0]
    wb = excel.libro()
    excel.hoja(wb, "Resumen", [{"t": "Atender", "k": "etiqueta", "w": 26}, {"t": "Que hacer", "k": "ayuda", "w": 70}, {"t": "Tienda x item", "k": "n", "f": "int"},
                               {"t": "Inventario a costo $", "k": "inv_costo", "f": "cop"}, {"t": "Margen $", "k": "margen", "f": "cop"}], resumen)
    excel.hoja(wb, "Detalle", COLS, vis, fijar=5)
    excel.hoja_texto(wb, "Filtros", [("Reporte", "Salud del inventario"), ("Generado", datetime.now().strftime("%Y-%m-%d %H:%M")), ("Usuario", f"{user.get('nombre', '')} ({user.get('id', '')})"),
                                     ("Ventana", f"{meta['desde']} a {meta['hasta']} ({meta['meses']} meses)"), ("ABC segun", meta["criterio_nombre"]),
                                     ("Empresa", empresa or "todas"), ("Tiendas", bodegas or "todas"), ("Laboratorios", labs or "todos"), ("Criterios de items", crit or ""),
                                     ("Busqueda", q or ""), ("Zonas", zonas or "todas"), ("Atender", diag or "todos"), ("Filas", f"{len(vis)} de {total}"),
                                     ("Nota", "Cruza la zona del buffer de hoy con la clase ABC x XYZ (ver la hoja Metodologia de Clasificacion ABC).")])
    return Response(excel.a_bytes(wb), media_type=excel.XLSX,
                    headers={"Content-Disposition": f'attachment; filename="salud_inventario_{datetime.now():%Y%m%d_%H%M}.xlsx"'})
