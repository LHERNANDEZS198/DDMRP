"""Control compras (tablero de compras): foto del momento para el equipo de compras (solo lectura). Junta lo que ya calculan Necesidades de compra, las OC y los transitos:
que pedir hoy, OC en vuelo, lo pedido y no recibido, riesgo de desabastecimiento, exceso y cumplimiento del proceso. Todo se limita a los criterios comprables (maestro
«Criterios comprables») y a lo que el usuario puede ver. Los umbrales viven en ddmrp.compras_config. Cada tarjeta tiene su detalle completo en /detalle/{tipo}."""
import re
import time
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from .. import consultas
from ..db import pg
from ..security import requiere, filtro_sql_permisos
from .compras import _necesidades, ULTIMA, CONSIG, COMPRABLE
from .oc import _cfg_revision

router = APIRouter(prefix="/compras/tablero", tags=["compras"], dependencies=[Depends(requiere("ver_control_compras"))])
CFG_DEFECTO = {"tablero_dias_trabada": 2.0, "tablero_dias_cumplimiento": 30.0, "tablero_leadtime_defecto": 30.0, "tablero_top": 30.0, "tablero_cache_horas": 6.0}
COSTO = "COALESCE(ic.cotizacion, ic.cotizacion_siesa, ic.ultimo_costo)"
SIN_LIMITE = 200000
_CACHE: dict[str, tuple[float, dict]] = {}      # bloque 1 (necesidades completas, lo unico lento) por usuario: (cuando, resultado)


def _comprable(alias: str) -> str:
    """El filtro de criterios comprables (escrito para el alias «s» de sugerencias_cedi) llevado a otra tabla que tenga empresa y producto_id."""
    return re.sub(r"\bs\.", alias + ".", COMPRABLE)


def _fe(alias: str, emp: list[str]) -> tuple[str, dict]:
    """Filtro de empresa (el selector de la barra): fragmento SQL y parametros. Sin empresas elegidas = todas las que el usuario puede ver."""
    return (f" AND {alias + '.' if alias else ''}empresa = ANY(:emp)", {"emp": emp}) if emp else ("", {})


def _empresas(v: str | None) -> list[str]:
    return [x.strip() for x in (v or "").split(",") if x.strip()]


def _cfg() -> dict:
    cfg = dict(CFG_DEFECTO)
    try:
        with pg.connect() as c:
            for k, v in c.execute(text("SELECT clave, valor::float8 FROM ddmrp.compras_config WHERE clave LIKE 'tablero\\_%' AND valor IS NOT NULL")).all():
                if k in cfg:
                    cfg[k] = v
    except Exception:    # noqa: BLE001
        pass
    return cfg


def _filas(c, sql: str, p: dict | None = None) -> list[dict]:
    return [dict(r) for r in c.execute(text(sql), p or {}).mappings()]


# ---- consultas (cada una con tope; el detalle las llama sin tope) ----
def _q_base(user, emp: list[str]) -> tuple[str, dict]:
    w, pw = filtro_sql_permisos(user, "s.bodega_id", "mi.categoria")
    fe, pe = _fe("s", emp)
    return (f"""FROM ddmrp.sugerencias_cedi s JOIN ddmrp.item_compra ic ON ic.empresa = s.empresa AND ic.producto_id = s.producto_id
                LEFT JOIN ddmrp.maestro_item mi ON mi.producto_id = s.producto_id LEFT JOIN ddmrp.laboratorio lb ON lb.codigo = mi.categoria
                WHERE s.ejecucion_id = {ULTIMA} AND {w} AND {COMPRABLE}{fe}""", pw | pe)


def _riesgo(c, user, t: int, emp: list[str]) -> list[dict]:
    base, pw = _q_base(user, emp)
    # lo de mas rotacion primero: es lo que mas duele si falta, y asi la lista no se llena de ruido
    return _filas(c, f"""SELECT s.empresa, s.producto_id, mi.descripcion, COALESCE(lb.nombre, mi.categoria, '') AS laboratorio, s.inventario::float8 AS inventario,
                                s.en_transito::float8 AS en_transito, s.adu::float8 AS adu, s.lead_time::float8 AS lead_time, {CONSIG} AS consignacion,
                                CASE WHEN s.adu > 0 THEN (s.inventario / (s.adu / 30))::float8 END AS cobertura_dias
                         {base} AND s.zona::text = 'ROJA' AND COALESCE(s.en_transito, 0) <= 0
                         ORDER BY s.adu DESC NULLS LAST, s.producto_id LIMIT :t""", pw | {"t": t})


def _agotados(c, user, t: int, emp: list[str]) -> list[dict]:
    base, pw = _q_base(user, emp)
    return _filas(c, f"""SELECT s.empresa, s.producto_id, mi.descripcion, COALESCE(lb.nombre, mi.categoria, '') AS laboratorio, s.inventario::float8 AS inventario,
                                s.en_transito::float8 AS en_transito, s.adu::float8 AS adu, s.zona::text AS zona, {CONSIG} AS consignacion
                         {base} AND COALESCE(s.inventario, 0) <= 0 AND COALESCE(s.adu, 0) > 0
                         ORDER BY s.adu DESC, s.producto_id LIMIT :t""", pw | {"t": t})


def _exceso(c, user, t: int, emp: list[str]) -> list[dict]:
    base, pw = _q_base(user, emp)
    return _filas(c, f"""SELECT s.empresa, s.producto_id, mi.descripcion, COALESCE(lb.nombre, mi.categoria, '') AS laboratorio, s.inventario::float8 AS inventario,
                                GREATEST(s.flujo_neto - GREATEST(s.tog_aj, 0), 0)::float8 AS sobran,
                                (GREATEST(s.flujo_neto - GREATEST(s.tog_aj, 0), 0) * COALESCE({COSTO}, 0))::float8 AS valor,
                                CASE WHEN s.adu > 0 THEN (s.inventario / (s.adu / 30))::float8 END AS cobertura_dias, {CONSIG} AS consignacion
                         {base} AND s.zona::text = 'EXCESO' ORDER BY valor DESC LIMIT :t""", pw | {"t": t})


def _trabadas(c, cfg, t: int, emp: list[str]) -> list[dict]:
    fe, pe = _fe("", emp)
    return _filas(c, f"""SELECT id, empresa, referencia, proveedor_nombre, estado, total::float8 AS total, consignacion, left(COALESCE(mensaje, ''), 200) AS mensaje,
                               (EXTRACT(EPOCH FROM now() - COALESCE(estado_bpm_fecha, enviado, creado)) / 86400)::float8 AS dias
                        FROM ddmrp.orden_compra
                        WHERE estado IN ('borrador', 'enviando', 'incierta', 'error', 'en_bpm') AND creado > now() - interval '90 days'
                          AND now() - COALESCE(estado_bpm_fecha, enviado, creado) > make_interval(days => :d){fe}
                        ORDER BY dias DESC LIMIT :t""", {"d": int(cfg["tablero_dias_trabada"]), "t": t} | pe)


def _vencidas(c, cfg, t: int, emp: list[str]) -> list[dict]:
    fe, pe = _fe("o", emp)
    return _filas(c, f"""SELECT o.id, o.empresa, o.referencia, o.siesa_consecutivo, o.proveedor_nombre, o.total::float8 AS total, o.consignacion, o.estado_siesa,
                               (EXTRACT(EPOCH FROM now() - o.confirmado) / 86400)::float8 AS dias, COALESCE(pv.leadtime, :ld)::float8 AS leadtime
                        FROM ddmrp.orden_compra o
                        LEFT JOIN ddmrp.proveedor pv ON pv.empresa = o.empresa AND pv.proveedor_id = o.proveedor_id AND pv.sucursal = o.sucursal
                        WHERE o.estado = 'creada' AND o.confirmado IS NOT NULL AND COALESCE(o.estado_siesa, '') NOT ILIKE 'cumpl%'
                          AND o.confirmado > now() - interval '90 days'
                          AND now() - o.confirmado > make_interval(days => COALESCE(pv.leadtime, :ld)::int){fe}
                        ORDER BY dias DESC LIMIT :t""", {"ld": int(cfg["tablero_leadtime_defecto"]), "t": t} | pe)


def _rit(c, t: int, emp: list[str]) -> list[dict]:
    fe, pe = _fe("a", emp)
    return _filas(c, f"""SELECT a.empresa, a.producto_id, mi.descripcion, a.bodega_id, a.documento, a.saldo::float8 AS saldo, (current_date - a.fecha)::int AS dias
                         FROM ddmrp.rit_alerta a LEFT JOIN ddmrp.maestro_item mi ON mi.producto_id = a.producto_id
                         WHERE {_comprable('a')}{fe} ORDER BY dias DESC, a.producto_id LIMIT :t""", {"t": t} | pe)


def _oc_abiertas(c, t: int, emp: list[str]) -> list[dict]:
    """Lineas de OC abiertas en Siesa que cuentan como transito al CEDI (las trae el ETL a ddmrp.transitos con documento 'OC-...')."""
    fe, pe = _fe("t", emp)
    return _filas(c, f"""SELECT t.empresa, t.documento, t.bodega_id, t.producto_id, mi.descripcion, COALESCE(lb.nombre, mi.categoria, '') AS laboratorio, t.cantidad::float8 AS cantidad,
                                t.fecha_oc::text AS fecha_oc, t.fecha_esperada::text AS fecha_esperada, (current_date - t.fecha_esperada)::int AS dias_atraso
                         FROM ddmrp.transitos t LEFT JOIN ddmrp.maestro_item mi ON mi.producto_id = t.producto_id LEFT JOIN ddmrp.laboratorio lb ON lb.codigo = mi.categoria
                         WHERE t.documento LIKE 'OC-%' AND {_comprable('t')}{fe} ORDER BY t.fecha_esperada NULLS LAST, t.documento, t.producto_id LIMIT :t""", {"t": t} | pe)


def _en_vuelo(c, t: int, emp: list[str]) -> list[dict]:
    fe, pe = _fe("", emp)
    return _filas(c, f"""SELECT id, empresa, referencia, siesa_consecutivo, proveedor_nombre, estado, estado_siesa, total::float8 AS total, items, consignacion, requiere_revision,
                               (EXTRACT(EPOCH FROM now() - COALESCE(estado_bpm_fecha, enviado, creado)) / 86400)::float8 AS dias, left(COALESCE(mensaje, ''), 200) AS mensaje
                        FROM ddmrp.orden_compra WHERE creado > now() - interval '90 days'{fe} ORDER BY creado DESC LIMIT :t""", {"t": t} | pe)


@router.get("")
def tablero(fresco: bool = False, empresa: str | None = None, user=Depends(requiere("ver_control_compras"))):
    cfg = _cfg()
    emp = _empresas(empresa)
    top = int(cfg["tablero_top"])
    t0 = time.perf_counter(); tm: dict[str, int] = {}

    def marca(k: str) -> None:       # milisegundos que tardo cada bloque: es lo que muestra el pie del tablero para saber que esta lento
        nonlocal t0
        t1 = time.perf_counter(); tm[k] = int((t1 - t0) * 1000); t0 = t1

    # ---- 1. Que pedir hoy (lo mismo que ve Necesidades de compra, que ya filtra criterios comprables). Es lo unico lento (recalcula todas las necesidades), por eso se
    # guarda unos minutos por usuario (compras_config.tablero_cache_horas; 0 = sin cache). «Actualizar» en la pantalla lo recalcula (fresco=1). ----
    ttl = cfg["tablero_cache_horas"] * 3600
    clave_cache = f"{user['id']}|{','.join(sorted(emp))}"      # una copia por usuario y por empresas elegidas
    ent = _CACHE.get(clave_cache)
    if ttl > 0 and not fresco and ent and time.time() - ent[0] < ttl:
        pedir, edad, calculado = ent[1], int(time.time() - ent[0]), ent[0]
    else:
        edad, calculado = 0, time.time()
        r = _necesidades(user, ",".join(emp) or None, None, None, None, None, None, 20000)
        filas = [f for f in r["filas"] if (f["qty_pedir"] or 0) > 0]
        zonas: dict[str, dict] = {}
        for f in filas:
            z = zonas.setdefault(f["zona"], {"zona": f["zona"], "items": 0, "valor": 0.0})
            z["items"] += 1; z["valor"] += f["valor"] or 0
        cons = [f for f in filas if f.get("consignacion")]
        pedir = {
            "totales": r["totales"], "aviso": r["aviso"], "ejecucion": r["ejecucion"],
            "zonas": sorted(zonas.values(), key=lambda z: {"ROJA": 0, "AMARILLA": 1, "VERDE": 2}.get(z["zona"], 3)),
            "consignacion": {"items": len(cons), "valor": sum(f["valor"] or 0 for f in cons)},
            "sin_proveedor": r["sin_proveedor"]["total"],
            "proveedores": [{k: g[k] for k in ("empresa", "proveedor_id", "proveedor_nombre", "items", "unidades", "total", "estado", "bajo_minimo", "sin_costo")} for g in r["proveedores"][:top]],
            "con_problema": sum(1 for g in r["proveedores"] if g["estado"] != "OK"),
        }
        if ttl > 0:
            _CACHE[clave_cache] = (time.time(), pedir)
    marca("1_que_pedir (necesidades completas)")
    base, pw = _q_base(user, emp)
    fo, po = _fe("", emp)          # empresa en las consultas de orden_compra
    foo, poo = _fe("o", emp)        # ... cuando la tabla va con alias o
    with pg.connect() as c:
        # ---- 2. OC en vuelo ----
        estados = _filas(c, f"""SELECT estado, count(*)::int AS ocs, COALESCE(sum(total), 0)::float8 AS total,
                                      COALESCE(max(EXTRACT(EPOCH FROM now() - COALESCE(estado_bpm_fecha, enviado, creado)) / 86400), 0)::float8 AS dias_max
                               FROM ddmrp.orden_compra WHERE creado > now() - interval '90 days'{fo} GROUP BY estado ORDER BY 2 DESC""", po)
        trabadas = _trabadas(c, cfg, SIN_LIMITE, emp)
        marca("2_oc_en_vuelo")
        # ---- 3. Pedido y no recibido ----
        vencidas = _vencidas(c, cfg, SIN_LIMITE, emp)
        en_transito = _filas(c, f"""SELECT count(DISTINCT t.documento)::int AS documentos, COALESCE(sum(t.cantidad), 0)::float8 AS unidades
                                    FROM ddmrp.transitos t WHERE t.documento LIKE 'OC-%' AND {_comprable('t')}{_fe('t', emp)[0]}""", _fe('t', emp)[1])[0]
        rit = _rit(c, SIN_LIMITE, emp)
        marca("3_no_recibido")
        # ---- 4. Riesgo de desabastecimiento (zona roja sin nada en camino) ----
        n_riesgo = c.execute(text(f"SELECT count(*) {base} AND s.zona::text = 'ROJA' AND COALESCE(s.en_transito, 0) <= 0"), pw).scalar() or 0
        agotados = c.execute(text(f"SELECT count(*) {base} AND COALESCE(s.inventario, 0) <= 0 AND COALESCE(s.adu, 0) > 0"), pw).scalar() or 0
        riesgo = _riesgo(c, user, top, emp)
        marca("4_riesgo")
        # ---- 5. Exceso ----
        ex_tot = _filas(c, f"""SELECT count(*)::int AS items, COALESCE(sum(GREATEST(s.flujo_neto - GREATEST(s.tog_aj, 0), 0) * COALESCE({COSTO}, 0)), 0)::float8 AS valor
                               {base} AND s.zona::text = 'EXCESO'""", pw)[0]
        exceso = _exceso(c, user, top, emp)
        marca("5_exceso")
        # ---- 6. Cumplimiento del proceso ----
        dias = int(cfg["tablero_dias_cumplimiento"])
        rv = _cfg_revision()
        cum = _filas(c, f"""SELECT count(*)::int AS ocs, COALESCE(sum(total), 0)::float8 AS total,
                                  count(*) FILTER (WHERE requiere_revision)::int AS con_revision,
                                  count(*) FILTER (WHERE consignacion)::int AS consignacion,
                                  (avg(EXTRACT(EPOCH FROM confirmado - enviado) / 3600) FILTER (WHERE confirmado IS NOT NULL AND enviado IS NOT NULL))::float8 AS horas_envio_a_siesa
                           FROM ddmrp.orden_compra WHERE estado = 'creada' AND creado > now() - make_interval(days => :d){fo}""", {"d": dias} | po)[0]
        lin = _filas(c, f"""SELECT count(*)::int AS lineas,
                                  count(*) FILTER (WHERE l.cantidad_calculada IS NOT NULL AND l.cantidad_calculada > :cmin AND abs(l.cantidad - l.cantidad_calculada) > l.cantidad_calculada * :pct / 100)::int AS desv_cant,
                                  count(*) FILTER (WHERE l.costo_calculado > 0 AND l.costo > l.costo_calculado * (1 + :cpct / 100))::int AS desv_costo
                           FROM ddmrp.orden_compra_linea l JOIN ddmrp.orden_compra o ON o.id = l.oc_id
                           WHERE o.estado = 'creada' AND o.creado > now() - make_interval(days => :d){foo}""",
                    {"d": dias, "cmin": rv["oc_desvio_cant_min"], "pct": rv["oc_desvio_cant_pct"], "cpct": rv["oc_desvio_costo_pct"]} | poo)[0]
        por_prov = _filas(c, f"""SELECT proveedor_nombre, count(*)::int AS ocs, sum(total)::float8 AS total FROM ddmrp.orden_compra
                                WHERE estado = 'creada' AND creado > now() - make_interval(days => :d){fo} GROUP BY proveedor_nombre ORDER BY 3 DESC LIMIT 8""", {"d": dias} | po)
        por_lab = _filas(c, f"""SELECT COALESCE(lb.nombre, mi.categoria, '(sin laboratorio)') AS laboratorio, sum(l.cantidad * l.costo)::float8 AS valor
                               FROM ddmrp.orden_compra_linea l JOIN ddmrp.orden_compra o ON o.id = l.oc_id
                               LEFT JOIN ddmrp.maestro_item mi ON mi.producto_id = l.producto_id LEFT JOIN ddmrp.laboratorio lb ON lb.codigo = mi.categoria
                               WHERE o.estado = 'creada' AND o.creado > now() - make_interval(days => :d){foo} GROUP BY 1 ORDER BY 2 DESC LIMIT 8""", {"d": dias} | poo)
    marca("6_cumplimiento")
    # lo que ve la pantalla Diagnostico para esta llamada: calculo = las necesidades completas (bloque 1); SQL = el resto; y el tiempo de cada bloque en el detalle
    k1 = next(iter(tm))
    consultas.anotar(ms_calc=tm[k1], ms_sql=sum(v for k, v in tm.items() if k != k1), filas=pedir["totales"]["items"], bloques_ms=tm, cache_seg=edad)
    return {
        "config": cfg, "tiempos_ms": tm, "cache_seg": edad, "calculado": datetime.fromtimestamp(calculado, timezone.utc).isoformat(),
        "pedir": pedir,
        "vuelo": {"estados": estados, "trabadas": trabadas[:top], "n_trabadas": len(trabadas)},
        "no_recibido": {"vencidas": vencidas[:top], "n_vencidas": len(vencidas), "oc_en_transito": en_transito, "rit": rit[:top], "rit_total": len(rit)},
        "riesgo": {"total": n_riesgo, "agotados": agotados, "filas": riesgo},
        "exceso": {"total": ex_tot, "filas": exceso},
        "cumplimiento": {"dias": dias, "oc": cum, "lineas": lin, "por_proveedor": por_prov, "por_laboratorio": por_lab},
    }


# ---- detalle completo de cada tarjeta: columnas + todas las filas (sin tope) ----
N, T = "num", "txt"
DETALLES = {
    "oc_abiertas": ("OC abiertas en Siesa (tránsito al CEDI)", "Líneas de las OC abiertas en Siesa que hoy cuentan como tránsito al CEDI (solo criterios comprables), con la fecha en que se montó la OC y la fecha en que debía llegar (la más cercana de sus líneas). Las fechas se llenan en el próximo ETL. Días de atraso positivo = ya debía haber llegado; ordenadas de la más atrasada a la más reciente.",
                    [("empresa", "Emp.", T), ("documento", "OC", T), ("bodega_id", "Bodega", T), ("producto_id", "SKU", T), ("descripcion", "Ítem", T), ("laboratorio", "Laboratorio", T), ("cantidad", "Unidades", N),
                     ("fecha_oc", "Fecha de montaje", T), ("fecha_esperada", "Debía llegar", T), ("dias_atraso", "Días de atraso", N)]),
    "oc_vencidas": ("OC vencidas", "OC creadas en Siesa que ya pasaron el lead time del proveedor sin cumplirse.",
                    [("empresa", "Emp.", T), ("siesa_consecutivo", "OC Siesa", T), ("referencia", "Referencia", T), ("proveedor_nombre", "Proveedor", T), ("dias", "Días", N), ("leadtime", "Lead time", N),
                     ("estado_siesa", "Estado Siesa", T), ("total", "Total", N), ("consignacion", "Consig.", T)]),
    "rit_viejas": ("RIT viejas", "Requisiciones inter-bodega comprometidas con más días de los configurados (solo criterios comprables).",
                   [("empresa", "Emp.", T), ("documento", "RIT", T), ("producto_id", "SKU", T), ("descripcion", "Ítem", T), ("bodega_id", "Bodega destino", T), ("saldo", "Saldo", N), ("dias", "Días", N)]),
    "trabadas": ("OC trabadas", "OC sin cerrar (borrador, enviando, incierta, con error o en el BPM) por más de los días configurados.",
                 [("empresa", "Emp.", T), ("referencia", "Referencia", T), ("proveedor_nombre", "Proveedor", T), ("estado", "Estado", T), ("dias", "Días", N), ("total", "Total", N), ("consignacion", "Consig.", T), ("mensaje", "Mensaje", T)]),
    "oc_vuelo": ("OC de los últimos 90 días", "Todas las OC montadas en los últimos 90 días y dónde está cada una.",
                 [("empresa", "Emp.", T), ("referencia", "Referencia", T), ("siesa_consecutivo", "OC Siesa", T), ("proveedor_nombre", "Proveedor", T), ("estado", "Estado", T), ("estado_siesa", "Estado Siesa", T),
                  ("dias", "Días en el estado", N), ("items", "Ítems", N), ("total", "Total", N), ("consignacion", "Consig.", T), ("mensaje", "Mensaje", T)]),
    "riesgo": ("Riesgo de desabastecimiento", "Ítems en zona roja sin nada en tránsito, de mayor a menor rotación (ADU).",
               [("empresa", "Emp.", T), ("producto_id", "SKU", T), ("descripcion", "Ítem", T), ("laboratorio", "Laboratorio", T), ("adu", "ADU (mensual)", N), ("inventario", "Inventario CEDI", N),
                ("cobertura_dias", "Cobertura (días)", N), ("lead_time", "Lead time", N), ("consignacion", "Consig.", T)]),
    "agotados": ("Agotados con venta", "Ítems con inventario 0 en el CEDI y rotación mayor a 0, de mayor a menor rotación.",
                 [("empresa", "Emp.", T), ("producto_id", "SKU", T), ("descripcion", "Ítem", T), ("laboratorio", "Laboratorio", T), ("adu", "ADU (mensual)", N), ("en_transito", "En tránsito", N),
                  ("zona", "Zona", T), ("consignacion", "Consig.", T)]),
    "exceso": ("Exceso de inventario", "Ítems sobre el tope verde del CEDI, de mayor a menor valor que sobra.",
               [("empresa", "Emp.", T), ("producto_id", "SKU", T), ("descripcion", "Ítem", T), ("laboratorio", "Laboratorio", T), ("inventario", "Inventario CEDI", N), ("sobran", "Sobran", N),
                ("valor", "Valor que sobra", N), ("cobertura_dias", "Cobertura (días)", N), ("consignacion", "Consig.", T)]),
}


@router.get("/detalle/{tipo}")
def detalle(tipo: str, empresa: str | None = None, user=Depends(requiere("ver_control_compras"))):
    if tipo not in DETALLES:
        raise HTTPException(404, "Ese detalle no existe")
    titulo, ayuda, cols = DETALLES[tipo]
    cfg = _cfg()
    emp = _empresas(empresa)
    with pg.connect() as c:
        filas = {"oc_abiertas": lambda: _oc_abiertas(c, SIN_LIMITE, emp), "oc_vencidas": lambda: _vencidas(c, cfg, SIN_LIMITE, emp), "rit_viejas": lambda: _rit(c, SIN_LIMITE, emp),
                 "trabadas": lambda: _trabadas(c, cfg, SIN_LIMITE, emp), "oc_vuelo": lambda: _en_vuelo(c, SIN_LIMITE, emp), "riesgo": lambda: _riesgo(c, user, SIN_LIMITE, emp),
                 "agotados": lambda: _agotados(c, user, SIN_LIMITE, emp), "exceso": lambda: _exceso(c, user, SIN_LIMITE, emp)}[tipo]()
    for f in filas:
        for k in ("consignacion", "requiere_revision"):
            if k in f:
                f[k] = "SÍ" if f[k] else ""
    return {"tipo": tipo, "titulo": titulo, "ayuda": ayuda, "columnas": [{"field": f, "headerName": h, "tipo": t} for f, h, t in cols], "filas": filas}
