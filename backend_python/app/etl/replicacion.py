"""ETL: trae a Postgres lo que el motor necesita, para no consultar los servidores de origen durante el calculo.

 SOLO Siesa (una BD por compania: '05' SIESA_DB, '21' SIESA_DB_S). FUNATLAB ya no se usa: los maestros de
 abastecimiento (bitacora, cotas, unidad de despacho, vectorizacion, pronostico, ...) los alimenta la propia app
 por pantalla o Excel, y no se tocan aqui.

   - inventario disponible por bodega/referencia          -> ddmrp.inventario_actual
   - traslados abiertos (t406, estado 0)                   -> ddmrp.transitos
   - descripcion de items (t120)                           -> ddmrp.maestro_item (no pisa categoria/linea)
   - centro de operacion de cada bodega                    -> columna id_co de ddmrp.abast_bitacora, solo donde falte (no fatal)
   - ventas por mes (consulta en etl/sql/ventas_siesa.sql) -> ddmrp.ventas_mensual (solo la ventana de meses)

Patron: leer el origen en chunks, COPY a tabla temporal y volcar a destino en UNA transaccion: si algo falla,
Postgres queda como estaba y el pipeline no corre el motor con datos viejos sin avisar.
"""
import logging
import re
import psycopg
from datetime import date, timedelta
from pathlib import Path
from sqlalchemy import bindparam, text
from ..config import settings
from .. import progreso, bitacora, lanzamientos
from ..db import pg, siesa_engine
from ..rec import detectar_rec
from ..activos import purgas_fuera_del_maestro

log = logging.getLogger("etl")
CHUNK = 50_000
MESES_VENTANA = 7  # por defecto; se lee de ddmrp.parametro 'meses_historia' (2 a 12), editable en Reglas de pedido


SQL_INVENTARIO = """
SELECT RTRIM(i.f120_referencia), RTRIM(b.f150_id), CAST(GETDATE() AS date),
       CONVERT(float, SUM(e.f400_cant_existencia_1 - :resta * e.f400_cant_comprometida_1
                       - :resta_sa * ISNULL(e.f400_cant_salida_sin_conf_1, 0)))
FROM t400_cm_existencia e
JOIN t150_mc_bodegas b ON b.f150_rowid = e.f400_rowid_bodega
JOIN t121_mc_items_extensiones x ON x.f121_rowid = e.f400_rowid_item_ext
JOIN t120_mc_items i ON i.f120_rowid = x.f121_rowid_item
WHERE i.f120_id_cia = :cia AND b.f150_id IN :bodegas /*ACTIVO:x,i*/
GROUP BY i.f120_referencia, b.f150_id"""

def _sql_costo() -> str:
    """Costo promedio unitario por referencia. Por defecto POR INSTALACION: tabla y columna configurables (SIESA_COSTO_TABLA /
    SIESA_COSTO_COLUMNA), unida por item y por la instalacion de la bodega (t400.f400_id_instalacion). Sin tabla, lee t400."""
    col = settings.siesa_costo_columna.strip().lower(); tabla = settings.siesa_costo_tabla.strip().lower()
    m = re.fullmatch(r"(f\d+)_[a-z0-9_]+", col)
    if not m or (tabla and not re.fullmatch(r"t\d+_[a-z0-9_]+", tabla)):
        raise ValueError(f"SIESA_COSTO_COLUMNA / SIESA_COSTO_TABLA invalida: {tabla!r} {col!r}")
    pref = m.group(1)
    union = (f"JOIN {tabla} c ON c.{pref}_id_cia = e.f400_id_cia AND c.{pref}_rowid_item_ext = e.f400_rowid_item_ext "
             f"AND c.{pref}_id_instalacion = e.f400_id_instalacion") if tabla else ""
    origen = "c" if tabla else "e"
    # Una referencia puede tener varias extensiones (unidad, caja...) con costos distintos: se toma el de la extension que tiene el
    # inventario en esas bodegas (la que se maneja como unidad), no el maximo de todas (la caja saldria 12 veces mas cara).
    return f"""
SELECT referencia, costo FROM (
  SELECT RTRIM(i.f120_referencia) AS referencia, CONVERT(float, MAX({origen}.{col})) AS costo,
         ROW_NUMBER() OVER (PARTITION BY RTRIM(i.f120_referencia)
                            ORDER BY SUM(e.f400_cant_existencia_1) DESC, MAX({origen}.{col})) AS rn
  FROM t400_cm_existencia e
  JOIN t150_mc_bodegas b ON b.f150_rowid = e.f400_rowid_bodega
  JOIN t121_mc_items_extensiones x ON x.f121_rowid = e.f400_rowid_item_ext
  JOIN t120_mc_items i ON i.f120_rowid = x.f121_rowid_item
  {union}
  WHERE i.f120_id_cia = :cia AND b.f150_id IN :bodegas AND {origen}.{col} > 0 /*ACTIVO:x,i*/
  GROUP BY RTRIM(i.f120_referencia), e.f400_rowid_item_ext) q
WHERE rn = 1"""


SQL_CO = "SELECT RTRIM(f150_id), RTRIM(f150_id_co) FROM t150_mc_bodegas WHERE f150_id_cia = :cia AND f150_id IN :bodegas"

def _sql_item_proveedor() -> str:
    """Proveedor de cada item (pestaña Generales del item en Siesa): referencia, NIT (f200_id del tercero), sucursal y razon social. UN proveedor por item."""
    col, suc = settings.siesa_item_proveedor_col, settings.siesa_item_proveedor_suc_col
    return f"""SELECT RTRIM(i.f120_referencia), RTRIM(t.f200_id), RTRIM(CONVERT(varchar(10), i.{suc})), MAX(RTRIM(t.f200_razon_social))
FROM t120_mc_items i JOIN t200_mm_terceros t ON t.f200_rowid = i.{col}
WHERE i.f120_id_cia = :cia AND i.{col} IS NOT NULL AND i.f120_referencia IS NOT NULL AND RTRIM(i.f120_referencia) <> ''
GROUP BY RTRIM(i.f120_referencia), RTRIM(t.f200_id), RTRIM(CONVERT(varchar(10), i.{suc}))"""


# Cotizaciones VIGENTES (t212) con el mismo criterio de sp_cotizacion_consulta_compra (consulta 10047, «solo cotizaciones vigentes»): dentro de la vigencia y, por cada
# proveedor-sucursal-item-moneda-UM-CO-instalacion, la de mayor fecha de activacion. El costo bruto es el precio menos el descuento del PRIMER rango de cantidad (la menor
# cantidad_hasta de t214: valor si lo tiene, si no el porcentaje), igual que el SP. No se llama al SP: arma una consulta dinamica generica (depende de la configuracion de la
# consulta y del usuario, devuelve varios resultados, usa tablas temporales y cinco UPDATE) y aqui basta UNA consulta sobre las tablas.
SQL_COTIZACIONES = """
WITH vig AS (
  SELECT c.f212_rowid AS rowid, c.f212_rowid_tercero AS tercero, c.f212_id_sucursal AS sucursal, c.f212_rowid_item_ext AS item_ext, c.f212_id_moneda AS moneda,
         c.f212_precio AS precio, c.f212_fecha_activacion AS activacion, c.f212_id_um AS um,
         ROW_NUMBER() OVER (PARTITION BY c.f212_rowid_tercero, c.f212_id_sucursal, c.f212_rowid_item_ext, c.f212_id_moneda, c.f212_id_um,
                                         ISNULL(c.f212_id_co, ''), ISNULL(c.f212_id_instalacion, '')
                            ORDER BY c.f212_fecha_activacion DESC, c.f212_rowid DESC) AS rn
  FROM t212_mm_cotizaciones c
  WHERE c.f212_id_cia = :cia AND c.f212_fecha_activacion <= GETDATE() AND (c.f212_fecha_hasta IS NULL OR GETDATE() BETWEEN c.f212_fecha_activacion AND c.f212_fecha_hasta)
)
SELECT RTRIM(i.f120_referencia), RTRIM(t.f200_id), RTRIM(v.sucursal), RTRIM(v.moneda), RTRIM(v.um), v.activacion,
       CONVERT(float, v.precio), CONVERT(float, ISNULL(d.f214_valor_dscto, 0)), CONVERT(float, ISNULL(d.f214_porcentaje_dscto, 0)), RTRIM(t.f200_razon_social)
FROM vig v
JOIN t121_mc_items_extensiones x ON x.f121_rowid = v.item_ext
JOIN t120_mc_items i ON i.f120_rowid = x.f121_rowid_item
JOIN t200_mm_terceros t ON t.f200_rowid = v.tercero
OUTER APPLY (SELECT TOP 1 d2.f214_valor_dscto, d2.f214_porcentaje_dscto FROM t214_mm_cotizacion_dscto d2
             WHERE d2.f214_rowid_cotizacion = v.rowid ORDER BY d2.f214_cantidad_hasta ASC, d2.f214_orden ASC) d
WHERE v.rn = 1 AND i.f120_id_cia = :cia AND i.f120_referencia IS NOT NULL AND RTRIM(i.f120_referencia) <> '' /*ACTIVO:x,i*/"""

# Tarifa de IVA del item: grupo impositivo del item -> llave de impuesto de la clase IVA (t114 -> t037), como en el SP (solo si el calculo es por tasa).
SQL_IVA_ITEM = """
SELECT RTRIM(i.f120_referencia), MAX(CONVERT(float, l.f037_tasa))
FROM t120_mc_items i
JOIN t121_mc_items_extensiones x ON x.f121_rowid_item = i.f120_rowid
JOIN t114_mc_grupos_impo_impuestos g ON g.f114_grupo_impositivo = i.f120_id_grupo_impositivo AND g.f114_id_cia = i.f120_id_cia AND g.f114_id_clase_impuesto = :clase
JOIN t037_mm_llaves_impuesto l ON l.f037_id = g.f114_id_llave_impuesto AND l.f037_id_cia = g.f114_id_cia AND l.f037_ind_calculo = 1
WHERE i.f120_id_cia = :cia AND i.f120_referencia IS NOT NULL AND RTRIM(i.f120_referencia) <> '' /*ACTIVO:x,i*/
GROUP BY RTRIM(i.f120_referencia)"""


# Ultimo costo de compra: precio unitario de la ULTIMA linea de OC del item (OC y linea no anuladas; la linea Aprobada, Parcial o Cumplida: un borrador no es una compra).
# Es el respaldo cuando el item no tiene cotizacion vigente. {moneda} se reemplaza por el filtro de moneda de la OC (si esa columna no existe en la base se reintenta sin el).
SQL_ULTIMO_COSTO = """
WITH u AS (
  SELECT x.f121_rowid_item AS rowid_item, d.f420_fecha AS fecha, m.f421_precio_unitario AS precio, d.f420_rowid_tercero_prov AS tercero,
         ROW_NUMBER() OVER (PARTITION BY x.f121_rowid_item ORDER BY d.f420_fecha DESC, d.f420_rowid DESC) AS rn
  FROM t420_cm_oc_docto d
  JOIN t421_cm_oc_movto m ON m.f421_rowid_oc_docto = d.f420_rowid
  JOIN t121_mc_items_extensiones x ON x.f121_rowid = m.f421_rowid_item_ext
  WHERE d.f420_id_cia = :cia AND d.f420_ind_estado <> 9 AND m.f421_ind_estado IN (1, 2, 3) AND m.f421_precio_unitario > 0 {moneda}
)
SELECT RTRIM(i.f120_referencia), CONVERT(float, u.precio), u.fecha, RTRIM(t.f200_id)
FROM u
JOIN t120_mc_items i ON i.f120_rowid = u.rowid_item
LEFT JOIN t200_mm_terceros t ON t.f200_rowid = u.tercero
WHERE u.rn = 1 AND i.f120_id_cia = :cia AND i.f120_referencia IS NOT NULL AND RTRIM(i.f120_referencia) <> '' /*ACTIVO:x,i*/"""


# Condicion de pago de la ULTIMA orden de compra (no anulada) de cada proveedor: valor inicial de la condicion de pago de DDMRP (f420_id_cond_pago, ej. C30).
SQL_COND_PAGO = """
WITH u AS (
  SELECT d.f420_rowid_tercero_prov AS tercero, RTRIM(d.f420_id_cond_pago) AS cond,
         ROW_NUMBER() OVER (PARTITION BY d.f420_rowid_tercero_prov ORDER BY d.f420_fecha DESC, d.f420_rowid DESC) AS rn
  FROM t420_cm_oc_docto d
  WHERE d.f420_id_cia = :cia AND d.f420_ind_estado <> 9 AND d.f420_id_cond_pago IS NOT NULL AND RTRIM(d.f420_id_cond_pago) <> ''
)
SELECT RTRIM(t.f200_id), u.cond FROM u JOIN t200_mm_terceros t ON t.f200_rowid = u.tercero WHERE u.rn = 1"""


def _sql_items(con_estado: bool) -> str:
    """Referencia, descripcion y, si la columna de estado existe, cuantas extensiones (t121) de esa referencia estan activas y cuantas
    bloqueadas (una referencia puede tener varias extensiones: es activa si alguna lo es)."""
    if not con_estado:
        return """SELECT RTRIM(f120_referencia), MAX(RTRIM(f120_descripcion)), CAST(NULL AS int), CAST(NULL AS int) FROM t120_mc_items
WHERE f120_id_cia = :cia AND f120_referencia IS NOT NULL AND RTRIM(f120_referencia) <> '' GROUP BY RTRIM(f120_referencia)"""
    col = _col_estado()
    return f"""SELECT RTRIM(i.f120_referencia), MAX(RTRIM(i.f120_descripcion)),
       SUM(CASE WHEN x.{col} = {int(settings.siesa_item_estado_activo)} THEN 1 ELSE 0 END),
       SUM(CASE WHEN x.{col} = {int(settings.siesa_item_estado_bloqueado)} THEN 1 ELSE 0 END)
FROM t120_mc_items i LEFT JOIN t121_mc_items_extensiones x ON x.f121_rowid_item = i.f120_rowid
WHERE i.f120_id_cia = :cia AND i.f120_referencia IS NOT NULL AND RTRIM(i.f120_referencia) <> '' GROUP BY RTRIM(i.f120_referencia)"""

# Tiendas: bodegas del grupo de bodegas de tiendas (t152) con su nombre. Es la lista que ve el usuario en los Excel.
SQL_BODEGAS = """SELECT RTRIM(b.f150_id), RTRIM(b.f150_descripcion)
FROM t150_mc_bodegas b
JOIN t152_mc_bodega_grupo_bodega g ON g.f152_rowid_bodega = b.f150_rowid
WHERE b.f150_id_cia = :cia AND g.f152_id_grupo_bodega = :grupo"""

# Laboratorio (categoria, base de los permisos) = criterio mayor del plan de items (mismo join que MercadoLibre_Items_Funat)
SQL_LAB = """SELECT RTRIM(i.f120_referencia), MAX(RTRIM(m.f106_id))
FROM t120_mc_items i
JOIN t125_mc_items_criterios c ON c.f125_rowid_item = i.f120_rowid
JOIN t106_mc_criterios_item_mayores m ON m.f106_id_plan = c.f125_id_plan AND m.f106_id = c.f125_id_criterio_mayor
                                     AND m.f106_id_cia = i.f120_id_cia
WHERE c.f125_id_plan = :plan AND i.f120_id_cia = :cia AND i.f120_referencia IS NOT NULL
GROUP BY i.f120_referencia"""

# Todos los criterios de items (cada plan de criterios tiene un criterio mayor por item): linea, marca, categoria, etc.
SQL_ITEM_CRITERIOS = """SELECT DISTINCT RTRIM(i.f120_referencia), RTRIM(c.f125_id_plan), RTRIM(c.f125_id_criterio_mayor)
FROM t120_mc_items i
JOIN t125_mc_items_criterios c ON c.f125_rowid_item = i.f120_rowid
WHERE i.f120_id_cia = :cia AND i.f120_referencia IS NOT NULL AND RTRIM(i.f120_referencia) <> ''
  AND c.f125_id_criterio_mayor IS NOT NULL"""
SQL_PLANES_NOMBRES = "SELECT RTRIM(f105_id), RTRIM(f105_descripcion) FROM t105_mc_criterios_item_planes WHERE f105_id_cia = :cia"
SQL_CRITERIOS_NOMBRES = """SELECT RTRIM(f106_id_plan), RTRIM(f106_id), RTRIM(f106_descripcion) FROM t106_mc_criterios_item_mayores
WHERE f106_id_cia = :cia"""

# Nombre de cada laboratorio (criterio mayor del mismo plan)
SQL_LAB_NOMBRES = """SELECT RTRIM(f106_id), MAX(RTRIM(f106_descripcion)) FROM t106_mc_criterios_item_mayores
WHERE f106_id_plan = :plan AND f106_id_cia = :cia GROUP BY f106_id"""

# Traslados abiertos hacia las tiendas (f406_ind_estado = 0). Se agrupan por referencia/bodega destino/bodega origen.
SQL_TRANSITOS = """
SELECT RTRIM(i.f120_referencia), RTRIM(be.f150_id), 'TR-' + RTRIM(bs.f150_id),
       CONVERT(float, SUM(t.f406_cant_base_pendiente))
FROM t406_cm_movto_transito t
JOIN t150_mc_bodegas be ON be.f150_rowid = t.f406_rowid_bodega_ent
JOIN t150_mc_bodegas bs ON bs.f150_rowid = t.f406_rowid_bodega_sal
JOIN t121_mc_items_extensiones x ON x.f121_rowid = t.f406_rowid_item_ext
JOIN t120_mc_items i ON i.f120_rowid = x.f121_rowid_item
WHERE t.f406_ind_estado = 0 AND t.f406_id_cia = :cia AND be.f150_id IN :bodegas /*ACTIVO:x,i*/
GROUP BY i.f120_referencia, be.f150_id, bs.f150_id
HAVING SUM(t.f406_cant_base_pendiente) > 0"""

# Ordenes de compra ABIERTAS (saldo por recibir) hacia las bodegas de la empresa: el CEDI y, en la etapa 2, las tiendas con compra directa. Entran a
# ddmrp.transitos con documento 'OC-<tipo><consecutivo>' y suman al flujo neto de la bodega destino (el CEDI los lee en su buffer).
# Regla de «abierta» (la misma de la hoja de OC de compras): estado del ITEM Aprobado (1) o Parcial (2). En los grupos de documento de OC de Siesa
# (401, 402, 409) los estados son 0 En elaboracion, 1 Aprobado, 2 Parcial, 3 Cumplido, 7 En proceso de aprobacion, 9 Anulado: «no es Cumplido, ni En
# elaboracion, ni En proceso de aprobacion» (y no anulado) es exactamente 1 o 2. Se usan los CODIGOS y no las descripciones: no dependen de tildes
# ni de la collation. Sin el cruce con el plan 006 de la consulta original: el laboratorio sale del maestro de items y ese INNER JOIN duplicaria las
# lineas de un item con mas de un criterio.
SQL_OC_ABIERTAS = """
SELECT RTRIM(i.f120_referencia), RTRIM(b.f150_id),
       'OC-' + RTRIM(d.f420_id_tipo_docto) + RTRIM(CONVERT(varchar(12), d.f420_consec_docto)),
       CONVERT(float, SUM(m.f421_cant_pedida - m.f421_cant_entrada))
FROM t420_cm_oc_docto d
JOIN t421_cm_oc_movto m ON m.f421_rowid_oc_docto = d.f420_rowid
JOIN t150_mc_bodegas b ON b.f150_rowid = m.f421_rowid_bodega
JOIN t121_mc_items_extensiones x ON x.f121_rowid = m.f421_rowid_item_ext
JOIN t120_mc_items i ON i.f120_rowid = x.f121_rowid_item
WHERE d.f420_id_cia = :cia AND d.f420_fecha >= :desde_oc AND b.f150_id IN :bodegas
  AND d.f420_ind_estado <> 9 AND m.f421_ind_estado IN (1, 2) /*ACTIVO:x,i*/
GROUP BY i.f120_referencia, b.f150_id, d.f420_id_tipo_docto, d.f420_consec_docto
HAVING SUM(m.f421_cant_pedida - m.f421_cant_entrada) > 0"""

ACTIVO_RE = re.compile(r"/\*ACTIVO:(\w+),(\w+)\*/")


def _purgar_fuera_del_maestro(cur) -> int:
    """Quita de ventas, inventario, transitos, demanda y fotos lo que no esta en maestro_item (p.ej. materia prima MP...). Devuelve cuantas filas."""
    n = 0
    for sql in purgas_fuera_del_maestro():
        cur.execute(sql); n += max(cur.rowcount, 0)
    if n:
        log.info("Se sacaron %s filas de items que no estan en el maestro de items", n)
    return n


def _col_estado() -> str:
    col = settings.siesa_item_estado_col.strip().lower()
    if not re.fullmatch(r"f121_[a-z0-9_]+", col):
        raise ValueError(f"SIESA_ITEM_ESTADO_COL invalida: {col!r} (debe ser una columna de t121_mc_items_extensiones, p.ej. f121_ind_estado)")
    return col


def _cond_criterios(i: str) -> str:
    """Condicion de ITEM DEL MAESTRO sobre el alias `i` (t120): tiene alguno de los criterios de SIESA_CRITERIOS_ITEMS ("plan:criterio", los mismos
    con que se arma maestro_item) o es un REC (se suma a su original). Asi lo que no es del maestro (materia prima...) ni se trae de Siesa.
    Sin criterios configurados no filtra."""
    pares = [tuple(x.strip().split(":", 1)) for x in settings.siesa_criterios_items.split(",") if ":" in x]
    for plan, crit in pares:
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", plan) or not re.fullmatch(r"[A-Za-z0-9_.-]+", crit):
            raise ValueError(f"SIESA_CRITERIOS_ITEMS invalido: {plan}:{crit}")
    if not pares:
        return ""
    por_plan: dict[str, list[str]] = {}
    for plan, crit in pares:
        por_plan.setdefault(plan, []).append(crit)
    alguno = " OR ".join(f"(cm.f125_id_plan = '{pl}' AND cm.f125_id_criterio_mayor IN ({', '.join(repr(c) for c in cs)}))" for pl, cs in por_plan.items())
    return (f"AND (EXISTS (SELECT 1 FROM t125_mc_items_criterios cm WHERE cm.f125_rowid_item = {i}.f120_rowid AND ({alguno})) "
            f"OR {i}.f120_descripcion LIKE 'REC[ .-]%')")


def _con_estado(sql: str, activo: bool) -> str:
    """Cada /*ACTIVO:ext,item*/ de la consulta se reemplaza por (1) la condicion de item del MAESTRO (criterios de SIESA_CRITERIOS_ITEMS; siempre) y
    (2) la de extension ACTIVA (alias de t121) o item REC (alias de t120: los REC se suman a su original y su estado no importa); (2) con
    activo=False por nada. Asi inventario, transitos, costos y ventas solo traen items del maestro y activos."""
    def cond(m):
        x, i = m.group(1), m.group(2)
        crit = _cond_criterios(i)
        if not activo:
            return crit
        return f"{crit} AND ({x}.{_col_estado()} = {int(settings.siesa_item_estado_activo)} OR {i}.f120_descripcion LIKE 'REC[ .-]%')"
    return ACTIVO_RE.sub(cond, sql)


def _probe_estado(eng) -> str | None:
    """None si la columna de estado se puede leer en t121; si no, el mensaje de error."""
    try:
        with eng.connect() as c:
            c.execute(text(f"SELECT TOP 1 {_col_estado()} FROM t121_mc_items_extensiones"))
        return None
    except Exception as e:   # solo fallos del origen (la columna no existe, permisos...)
        return str(e).splitlines()[0][:200]


def _solo_activos(cur) -> bool:
    """Regla 'solo_items_activos' (por defecto Si)."""
    v = _param(cur, "solo_items_activos")
    return True if v is None else v >= 1


def _filtrar_activos(solo: bool, eng) -> tuple[bool, str | None]:
    """(filtrar, aviso). Si la columna de estado no existe se sigue SIN filtrar (como antes) y se avisa en el resultado del ETL."""
    if not solo:
        return False, None
    err = _probe_estado(eng)
    if err:
        log.warning("Sin filtro de estado de items: no se pudo leer %s en t121 (%s). Revisa SIESA_ITEM_ESTADO_COL.", settings.siesa_item_estado_col, err)
        return False, f"No se filtro por estado: no se pudo leer {settings.siesa_item_estado_col} en t121 ({err}). Revisa SIESA_ITEM_ESTADO_COL."
    return True, None


VENTAS_SQL_FILE = Path(__file__).parent / "sql" / "ventas_siesa.sql"


VENTAS_CEDI_SQL_FILE = Path(__file__).parent / "sql" / "ventas_cedi_siesa.sql"


def _ventas_sql(archivo: Path = VENTAS_SQL_FILE) -> str | None:
    """Consulta de ventas por mes; None si el archivo solo tiene comentarios (aun no definida)."""
    if not archivo.exists():
        return None
    q = "\n".join(l for l in archivo.read_text(encoding="utf-8").splitlines() if not l.strip().startswith("--"))
    return q.strip() or None


def _primer_mes(hoy: date, meses: int = MESES_VENTANA) -> date:
    m = hoy.year * 12 + hoy.month - 1 - (meses - 1)
    return date(m // 12, m % 12 + 1, 1)


def _stream(engine, sql, params=None, expanding=None):
    stmt = text(sql)
    if expanding:
        stmt = stmt.bindparams(bindparam(expanding, expanding=True))
    with engine.connect().execution_options(stream_results=True, yield_per=CHUNK) as c:
        for r in c.execute(stmt, params or {}):
            yield tuple(r)


def _volcar(cur, filas, destino: str, cols: list[str], reemplazar: bool = True) -> int:
    """COPY a tabla temporal y luego INSERT ... ON CONFLICT DO NOTHING (el origen puede traer duplicados)."""
    stg = "stg_" + destino.split(".")[-1]
    cur.execute(f"CREATE TEMP TABLE {stg} (LIKE {destino} INCLUDING DEFAULTS) ON COMMIT DROP")
    n = 0
    with cur.copy(f"COPY {stg} ({', '.join(cols)}) FROM STDIN") as cp:
        for r in filas:
            cp.write_row(r)
            n += 1
    if reemplazar:
        cur.execute(f"TRUNCATE {destino}")
    cur.execute(f"INSERT INTO {destino} ({', '.join(cols)}) SELECT {', '.join(cols)} FROM {stg} ON CONFLICT DO NOTHING")
    cur.execute(f"DROP TABLE {stg}")
    log.info("  %s: %s filas leidas", destino, n)
    return n


def _costos(cur, eng, bodegas: list[str], pisar: bool, filtrar: bool = False) -> int | str:
    """Costo promedio por referencia de esas bodegas -> ddmrp.costo_item. `pisar`=True (CEDI) manda sobre lo que haya;
    False (tiendas) solo llena lo que falte. Un fallo del origen (p.ej. la columna no existe) no tumba el ETL: devuelve el aviso."""
    try:
        filas = list(_stream(eng, _con_estado(_sql_costo(), filtrar), {"cia": settings.siesa_cia, "bodegas": bodegas}, expanding="bodegas"))
    except Exception as e:
        if isinstance(e, psycopg.Error):
            raise
        log.warning("Costos no leidos (revisa SIESA_COSTO_TABLA/COLUMNA=%s.%s): %s", settings.siesa_costo_tabla, settings.siesa_costo_columna, e)
        return "no se pudo leer " + settings.siesa_costo_tabla + "." + settings.siesa_costo_columna + ": " + str(e)[:150]
    accion = "DO UPDATE SET costo = EXCLUDED.costo, fecha_corte = current_date" if pisar else "DO NOTHING"
    cur.executemany(f"INSERT INTO ddmrp.costo_item (producto_id, costo) VALUES (%s, %s) ON CONFLICT (producto_id) {accion}",
                    [(p, c) for p, c in filas if c and c > 0])
    return len(filas)


def diagnostico_inventario(bodega: str, producto: str) -> dict:
    """Para entender por que un inventario no cuadra: la fila de Siesa (t400, todas las columnas con dato) en vivo, y lo que
    tiene este sistema (bitacora, inventario del ETL, costo). Solo lectura."""
    out: dict = {"bodega": bodega, "producto": producto, "siesa": [], "local": {}}
    with pg.connect() as c:
        out["local"]["en_bitacora"] = [dict(r) for r in c.execute(text("SELECT empresa, bodega_id FROM ddmrp.abast_bitacora WHERE bodega_id = :b"), {"b": bodega}).mappings()]
        out["local"]["inventario_actual"] = [{k: (float(v) if hasattr(v, "as_tuple") else str(v) if k == "fecha_corte" else v) for k, v in r.items()}
                                              for r in c.execute(text("SELECT empresa, producto_id, bodega_id, fecha_corte, disponible FROM ddmrp.inventario_actual WHERE bodega_id = :b AND producto_id = :p"), {"b": bodega, "p": producto}).mappings()]
        out["local"]["costo"] = [float(r[0]) for r in c.execute(text("SELECT costo FROM ddmrp.costo_item WHERE producto_id = :p"), {"p": producto}).all()]
        out["local"]["resta_comprometido"] = bool((c.execute(text("SELECT valor FROM ddmrp.parametro WHERE clave='inv_tiendas_resta_comprometido'")).scalar() or 0))
        out["local"]["resta_sin_acumular"] = bool((c.execute(text("SELECT valor FROM ddmrp.parametro WHERE clave='inv_tiendas_resta_sin_acumular'")).scalar() or 0))
        out["local"]["en_maestro"] = c.execute(text("SELECT count(*) FROM ddmrp.maestro_item WHERE producto_id = :p"), {"p": producto}).scalar() > 0
        out["local"]["estado"] = [dict(r) for r in c.execute(text("SELECT empresa, estado FROM ddmrp.item_estado WHERE producto_id = :p"), {"p": producto}).mappings()]
        out["local"]["ultimo_etl_inventario"] = str(c.execute(text("SELECT max(fecha_corte) FROM ddmrp.inventario_actual WHERE bodega_id = :b"), {"b": bodega}).scalar())
        out["local"]["filas_bodega"] = c.execute(text("SELECT count(*) FROM ddmrp.inventario_actual WHERE bodega_id = :b"), {"b": bodega}).scalar()
        resta = int(out["local"]["resta_comprometido"]); resta_sa = int(out["local"]["resta_sin_acumular"])
    if not settings.siesa_host:
        out["aviso"] = "Siesa no esta configurado"; return out
    sql = ("SELECT RTRIM(b.f150_id) AS bodega, RTRIM(i.f120_referencia) AS referencia, e.* FROM t400_cm_existencia e "
           "JOIN t150_mc_bodegas b ON b.f150_rowid = e.f400_rowid_bodega "
           "JOIN t121_mc_items_extensiones x ON x.f121_rowid = e.f400_rowid_item_ext "
           "JOIN t120_mc_items i ON i.f120_rowid = x.f121_rowid_item "
           "WHERE i.f120_id_cia = :cia AND RTRIM(b.f150_id) = :b AND RTRIM(i.f120_referencia) = :p")
    for empresa, db in (("05", settings.siesa_db), ("21", settings.siesa_db_s)):
        if not db:
            continue
        try:
            with siesa_engine(db).connect() as cn:
                for r in cn.execute(text(sql), {"cia": settings.siesa_cia, "b": bodega, "p": producto}).mappings():
                    out["siesa"].append({"empresa": empresa, "base": db, "columnas": {
                        k: (float(v) if hasattr(v, "as_tuple") else v if isinstance(v, (int, float, str)) else str(v))
                        for k, v in r.items() if v not in (None, "", 0, 0.0)}})
        except Exception as e:
            out["siesa"].append({"empresa": empresa, "base": db, "error": str(e)[:300]})
    out["etl"] = _por_que_no_entra(out, bodega, producto, resta, resta_sa)
    return out


def _por_que_no_entra(out: dict, bodega: str, producto: str, resta: int, resta_sa: int) -> list[dict]:
    """Corre la consulta de inventario del ETL para esa tienda con tres niveles de filtro (ninguno, solo items del maestro, maestro + activos) y las
    extensiones del item con su estado, para decir en cual filtro se pierde la existencia que Siesa si tiene."""
    res = []
    for empresa, db in (("05", settings.siesa_db), ("21", settings.siesa_db_s)):
        if not db or not any(x["empresa"] == empresa and "columnas" in x for x in out["siesa"]):
            continue
        r: dict = {"empresa": empresa, "pasos": [], "extensiones": []}
        try:
            eng = siesa_engine(db)
            prm = {"cia": settings.siesa_cia, "bodegas": [bodega], "resta": resta, "resta_sa": resta_sa}
            def valor(sql: str):
                for ref, _b, _f, disp in _stream(eng, sql, prm, expanding="bodegas"):
                    if ref == producto:
                        return float(disp) if disp is not None else None
                return "sin fila"
            r["pasos"] = [
                {"filtro": "ninguno (toda la existencia de Siesa)", "valor": valor(ACTIVO_RE.sub("", SQL_INVENTARIO))},
                {"filtro": "solo items del maestro (criterios SIESA_CRITERIOS_ITEMS)", "valor": valor(_con_estado(SQL_INVENTARIO, False))},
                {"filtro": "maestro + solo extensiones activas (lo que hace el ETL)", "valor": valor(_con_estado(SQL_INVENTARIO, True))},
            ]
            col = _col_estado()
            for rowid, est in _stream(eng, f"SELECT x.f121_rowid, x.{col} FROM t121_mc_items_extensiones x "
                                                  f"JOIN t120_mc_items i ON i.f120_rowid = x.f121_rowid_item WHERE i.f120_id_cia = :cia AND RTRIM(i.f120_referencia) = :p",
                                              {"cia": settings.siesa_cia, "p": producto}):
                r["extensiones"].append({"rowid": rowid, "estado": est})
            r["extensiones_nota"] = f"estado en {col} (el ETL deja pasar solo {settings.siesa_item_estado_activo} = activo)"
            v = [p_["valor"] for p_ in r["pasos"]]
            num = lambda x: isinstance(x, (int, float))
            if num(v[0]) and not num(v[1]):
                r["causa"] = "El item NO pasa el filtro de criterios del maestro en esta empresa (SIESA_CRITERIOS_ITEMS): se descarta aunque tenga existencia."
            elif num(v[1]) and not num(v[2]):
                r["causa"] = "La extensión del item que tiene la existencia está inactiva o bloqueada en Siesa (aunque otra extensión del mismo item esté activa): el filtro de estado del ETL la descarta."
            elif num(v[2]):
                r["causa"] = "El ETL SI lo lee con sus filtros: si el sistema no lo tiene, el ETL no corrió desde que cambió la existencia, o fue purgado después (revisa Maestros → Items y la fecha del último ETL)."
            else:
                r["causa"] = "La consulta del ETL no devuelve fila para esa tienda y referencia (revisa la bodega y que la referencia sea la de t120)."
        except Exception as e:
            r["error"] = str(e).splitlines()[0][:300]
        res.append(r)
    return res


def diagnostico_estado_items() -> dict:
    """En vivo, por empresa: cuantas extensiones de item hay en cada valor de la columna de estado de t121 (para confirmar la columna y que 1 = activo,
    0 = inactivo, 2 = bloqueado antes de confiar en el filtro) y los items REC que se sumarian a su original. Solo lectura."""
    out: dict = {"columna": settings.siesa_item_estado_col, "valor_activo": settings.siesa_item_estado_activo,
                 "valor_bloqueado": settings.siesa_item_estado_bloqueado, "empresas": []}
    if not settings.siesa_host:
        out["aviso"] = "Siesa no esta configurado"; return out
    col = _col_estado()
    for empresa, db in (("05", settings.siesa_db), ("21", settings.siesa_db_s)):
        if not db:
            continue
        try:
            eng = siesa_engine(db)
            estados = [{"estado": r[0], "extensiones": r[1], "rec": r[2]} for r in _stream(
                eng, f"SELECT x.{col}, COUNT(*), SUM(CASE WHEN i.f120_descripcion LIKE 'REC[ .-]%' THEN 1 ELSE 0 END) "
                     f"FROM t121_mc_items_extensiones x JOIN t120_mc_items i ON i.f120_rowid = x.f121_rowid_item "
                     f"WHERE i.f120_id_cia = :cia GROUP BY x.{col} ORDER BY x.{col}", {"cia": settings.siesa_cia})]
            todos = [(r[0], r[1]) for r in _stream(eng, "SELECT RTRIM(f120_referencia), MAX(RTRIM(f120_descripcion)) FROM t120_mc_items "
                                                        "WHERE f120_id_cia = :cia AND f120_referencia IS NOT NULL AND RTRIM(f120_referencia) <> '' "
                                                        "GROUP BY RTRIM(f120_referencia)", {"cia": settings.siesa_cia})]
            pares, sin = detectar_rec(todos)
            out["empresas"].append({"empresa": empresa, "base": db, "estados": estados, "rec_con_original": len(pares), "rec_sin_original": sin[:20],
                                    "rec_ejemplos": [{"rec": r, "original": o, "descripcion": d} for r, o, d in pares[:15]]})
        except Exception as e:
            out["empresas"].append({"empresa": empresa, "base": db, "error": str(e).splitlines()[0][:300]})
    return out


def sincronizar_bodegas(cur) -> int:
    """Trae de Siesa las tiendas (codigo + nombre) a ddmrp.maestro_bodega y suma las que ya esten en la bitacora.
    Un fallo del origen no tumba el ETL: se registra y se sigue con lo que haya."""
    n = 0
    if settings.siesa_host:
        for empresa, db in (("05", settings.siesa_db), ("21", settings.siesa_db_s)):
            if not db:
                continue
            try:
                filas = list(_stream(siesa_engine(db), SQL_BODEGAS,
                                     {"cia": settings.siesa_cia, "grupo": settings.siesa_grupo_bodegas_tienda}))
            except Exception as e:
                log.warning("No se pudieron leer las tiendas de %s: %s", db, e)
                continue
            for cod, nombre in filas:
                # el nombre de la bitacora (fuente de verdad) manda; el de Siesa solo se usa si la bitacora no tiene tienda o no tiene nombre
                cur.execute("INSERT INTO ddmrp.maestro_bodega (bodega_id, empresa, descripcion) VALUES (%s, %s, %s) "
                            "ON CONFLICT (empresa, bodega_id) DO UPDATE SET descripcion = COALESCE("
                            "(SELECT NULLIF(btrim(b.descripcion), '') FROM ddmrp.abast_bitacora b WHERE b.empresa = EXCLUDED.empresa AND b.bodega_id = EXCLUDED.bodega_id), EXCLUDED.descripcion)",
                            (cod, empresa, nombre))
                n += 1
    cur.execute("INSERT INTO ddmrp.maestro_bodega (bodega_id, empresa) SELECT bodega_id, empresa FROM ddmrp.abast_bitacora "
                "ON CONFLICT (empresa, bodega_id) DO NOTHING")
    return n


def sincronizar_bodegas_ahora(usuario: str | None = None) -> int:
    with bitacora.registrar("bodegas", "manual", usuario) as r:
        r.resumen = {"tiendas": (n := _sincronizar_bodegas_ahora())}
        return n


def _sincronizar_bodegas_ahora() -> int:
    raw = pg.raw_connection()
    try:
        with raw.cursor() as cur:
            n = sincronizar_bodegas(cur)
        raw.commit()
        return n
    except Exception:
        raw.rollback()
        raise
    finally:
        raw.close()


def _proveedores_de_siesa(cur, eng, empresa: str) -> tuple[dict, dict]:
    """Proveedor del ITEM en Siesa (pestaña Generales): se guarda como respaldo (proveedor_item) y como proveedor de compra de partida. La cotizacion vigente, si existe,
    lo reemplaza despues (_cotizaciones_de_siesa): para compras importa el proveedor de la cotizacion, no el del item. De los proveedores que ya existen en
    ddmrp.proveedor NO se toca nada (lead time, correos, activo... los pone compras)."""
    cur.execute("INSERT INTO ddmrp.item_compra (empresa, producto_id) SELECT %s, producto_id FROM ddmrp.item_empresa WHERE empresa = %s ON CONFLICT DO NOTHING", (empresa, empresa))
    try:   # lo que falle del ORIGEN (p.ej. la columna no existe) no tumba la sincronizacion de items
        filas = list(_stream(eng, _sql_item_proveedor(), {"cia": settings.siesa_cia}))
    except Exception as e:
        if isinstance(e, psycopg.Error):
            raise
        log.warning("Proveedor del item no leido (revisa SIESA_ITEM_PROVEEDOR_COL / _SUC_COL con docs/sql/proveedor_item.sql): %s", e)
        return {"aviso_proveedor": ("No se pudo leer el proveedor del item (se usa solo el de las cotizaciones): revisa SIESA_ITEM_PROVEEDOR_COL y SIESA_ITEM_PROVEEDOR_SUC_COL con docs/sql/proveedor_item.sql. " + str(e).splitlines()[0])[:300]}, {}
    por_item: dict[str, tuple] = {}
    for ref, nit, suc, nombre in filas:
        if not ref or not nit:
            continue
        s = (suc or "001").strip()
        por_item[ref.strip()] = (nit.strip(), s.zfill(3) if s.isdigit() else s, (nombre or "").strip() or None)
    cur.execute("CREATE TEMP TABLE IF NOT EXISTS stg_prov (producto_id text, proveedor_id text, sucursal text, nombre text)")
    cur.execute("TRUNCATE stg_prov")
    with cur.copy("COPY stg_prov FROM STDIN") as cp:
        for ref, (nit, suc, nom) in por_item.items():
            cp.write_row((ref, nit, suc, nom))
    cur.execute("""INSERT INTO ddmrp.proveedor (empresa, proveedor_id, sucursal, nombre, origen)
                   SELECT DISTINCT ON (s.proveedor_id, s.sucursal) %s, s.proveedor_id, s.sucursal, s.nombre, 'siesa'
                   FROM stg_prov s JOIN ddmrp.item_empresa ie ON ie.empresa = %s AND ie.producto_id = s.producto_id
                   ORDER BY s.proveedor_id, s.sucursal
                   ON CONFLICT (empresa, proveedor_id, sucursal) DO NOTHING""", (empresa, empresa))
    nuevos = cur.rowcount or 0
    cur.execute("""UPDATE ddmrp.item_compra ic SET proveedor_item = s.proveedor_id, sucursal_item = s.sucursal FROM stg_prov s
                   WHERE ic.empresa = %s AND ic.producto_id = s.producto_id
                     AND (ic.proveedor_item IS DISTINCT FROM s.proveedor_id OR ic.sucursal_item IS DISTINCT FROM s.sucursal)""", (empresa,))
    cur.execute("""UPDATE ddmrp.item_compra ic SET proveedor_item = NULL, sucursal_item = NULL
                   WHERE ic.empresa = %s AND ic.proveedor_item IS NOT NULL AND NOT EXISTS (SELECT 1 FROM stg_prov s WHERE s.producto_id = ic.producto_id)""", (empresa,))
    cur.execute("DROP TABLE stg_prov")
    # proveedor de compra de partida = el del item (la cotizacion lo cambia mas adelante en esta misma sincronizacion)
    cur.execute("""UPDATE ddmrp.item_compra SET proveedor_id = proveedor_item, sucursal = sucursal_item,
                          proveedor_origen = CASE WHEN proveedor_item IS NULL THEN NULL ELSE 'item' END WHERE empresa = %s""", (empresa,))
    return {"proveedores_nuevos": nuevos}, por_item


def _cotizaciones_de_siesa(cur, eng, empresa: str) -> dict:
    """Cotizacion vigente de cada item (en la moneda y unidad de compra) y tarifa de IVA -> ddmrp.item_compra (cotizacion_siesa, cotizacion_fecha, iva_tasa).
    El PROVEEDOR DE COMPRA es el de la cotizacion (lo que importa a compras: el proveedor que trae el item en Siesa suele estar desactualizado, sobre todo en maquila);
    si un item tiene cotizaciones vigentes de varios proveedores gana la de mayor fecha de activacion (y, a igual fecha, la mas barata). Sin cotizacion se queda el del item.
    Un fallo del origen solo deja esos campos como estaban."""
    prm = {"cia": settings.siesa_cia}
    out: dict = {}
    moneda = settings.siesa_moneda_compra.strip().upper()
    solo = _solo_activos(cur)
    filtrar, _ = _filtrar_activos(solo, eng)
    try:
        filas = list(_stream(eng, _con_estado(SQL_COTIZACIONES, filtrar), prm))
    except Exception as e:
        if isinstance(e, psycopg.Error):
            raise
        log.warning("Cotizaciones no leidas: %s", e)
        out["aviso_cotizacion"] = ("No se pudieron leer las cotizaciones (t212): " + str(e).splitlines()[0])[:300]
        filas = None
    if filas is not None:
        mejor: dict[str, tuple] = {}     # referencia -> (activacion, -costo, costo, nit, sucursal, nombre)
        provs: dict[str, set] = {}       # referencia -> proveedores con cotizacion vigente
        otra_moneda = otra_um = 0
        um_ok = settings.siesa_um_compra.strip().upper()
        for ref, nit, suc, mon, um, act, precio, dv, dp, nombre in filas:
            if not ref or not nit or (mon or "").strip().upper() != moneda:
                otra_moneda += 1
                continue
            if um_ok and (um or "").strip().upper() != um_ok:   # otra unidad de medida (caja...): su precio no es por unidad
                otra_um += 1
                continue
            ref, nit = ref.strip(), nit.strip()
            s = (suc or "001").strip(); suc = s.zfill(3) if s.isdigit() else s
            costo = float(precio or 0) - (float(dv) if dv else float(precio or 0) * float(dp or 0) / 100)
            provs.setdefault(ref, set()).add((nit, suc))
            clave = (act, -costo)
            if ref not in mejor or clave > mejor[ref][:2]:
                mejor[ref] = (act, -costo, costo, nit, suc, (nombre or "").strip() or None)
        # los proveedores de las cotizaciones que aun no existen en el maestro entran con su razon social (los que ya existen no se tocan)
        nuevos = {(v[3], v[4]): v[5] for v in mejor.values()}
        cur.executemany("INSERT INTO ddmrp.proveedor (empresa, proveedor_id, sucursal, nombre, origen) VALUES (%s, %s, %s, %s, 'siesa') ON CONFLICT DO NOTHING",
                        [(empresa, n, sc, nom) for (n, sc), nom in nuevos.items()])
        cur.execute("CREATE TEMP TABLE IF NOT EXISTS stg_cot (producto_id text, costo numeric, fecha date, nit text, suc text)")
        cur.execute("TRUNCATE stg_cot")
        with cur.copy("COPY stg_cot FROM STDIN") as cp:
            for ref, (act, _, costo, nit, suc, _nom) in mejor.items():
                cp.write_row((ref, round(costo, 4), act.date() if hasattr(act, "date") else act, nit, suc))
        cur.execute("""UPDATE ddmrp.item_compra ic SET cotizacion_siesa = s.costo, cotizacion_fecha = s.fecha, proveedor_id = s.nit, sucursal = s.suc, proveedor_origen = 'cotizacion'
                       FROM stg_cot s WHERE ic.empresa = %s AND ic.producto_id = s.producto_id""", (empresa,))
        cur.execute("""UPDATE ddmrp.item_compra ic SET cotizacion_siesa = NULL, cotizacion_fecha = NULL
                       WHERE ic.empresa = %s AND ic.cotizacion_siesa IS NOT NULL AND NOT EXISTS (SELECT 1 FROM stg_cot s WHERE s.producto_id = ic.producto_id)""", (empresa,))
        cur.execute("DROP TABLE stg_cot")
        cur.execute("UPDATE ddmrp.item_compra SET cotizacion_otro_nit = NULL, cotizacion_otro_costo = NULL WHERE empresa = %s AND (cotizacion_otro_nit IS NOT NULL OR cotizacion_otro_costo IS NOT NULL)", (empresa,))
        out.update(items_con_cotizacion=len(mejor), items_con_varios_proveedores_cotizando=sum(1 for v in provs.values() if len(v) > 1),
                   cotizaciones_en_otra_moneda=otra_moneda, cotizaciones_en_otra_um=otra_um)
    # resumen del proveedor de compra (despues de aplicar las cotizaciones): sirve para validar la sincronizacion
    cur.execute("""SELECT count(*) FILTER (WHERE ic.proveedor_id IS NOT NULL), count(*) FILTER (WHERE ic.proveedor_id IS NULL),
                          count(*) FILTER (WHERE ic.proveedor_origen = 'cotizacion'), count(*) FILTER (WHERE ic.proveedor_origen = 'item'),
                          count(*) FILTER (WHERE ic.proveedor_origen = 'cotizacion' AND ic.proveedor_item IS NOT NULL AND ic.proveedor_item IS DISTINCT FROM ic.proveedor_id)
                   FROM ddmrp.item_compra ic JOIN ddmrp.item_empresa ie ON ie.empresa = ic.empresa AND ie.producto_id = ic.producto_id WHERE ic.empresa = %s""", (empresa,))
    con, sin, de_cot, de_item, difiere = cur.fetchone()
    out.update(items_con_proveedor=con, items_sin_proveedor=sin, proveedor_de_cotizacion=de_cot, proveedor_del_item=de_item, proveedor_cotizacion_distinto_del_item=difiere)
    try:
        iva = list(_stream(eng, _con_estado(SQL_IVA_ITEM, filtrar), {**prm, "clase": settings.siesa_clase_impuesto_iva}))
    except Exception as e:
        if isinstance(e, psycopg.Error):
            raise
        log.warning("IVA de los items no leido: %s", e)
        out["aviso_iva"] = ("No se pudo leer la tarifa de IVA: " + str(e).splitlines()[0])[:300]
        return out
    cur.execute("CREATE TEMP TABLE IF NOT EXISTS stg_iva (producto_id text, tasa numeric)")
    cur.execute("TRUNCATE stg_iva")
    with cur.copy("COPY stg_iva FROM STDIN") as cp:
        for ref, tasa in iva:
            if ref and tasa is not None:
                cp.write_row((ref.strip(), tasa))
    cur.execute("UPDATE ddmrp.item_compra ic SET iva_tasa = s.tasa FROM stg_iva s WHERE ic.empresa = %s AND ic.producto_id = s.producto_id", (empresa,))
    cur.execute("""UPDATE ddmrp.item_compra ic SET iva_tasa = NULL WHERE ic.empresa = %s AND ic.iva_tasa IS NOT NULL
                   AND NOT EXISTS (SELECT 1 FROM stg_iva s WHERE s.producto_id = ic.producto_id)""", (empresa,))
    cur.execute("DROP TABLE stg_iva")
    out["items_con_iva"] = len(iva)
    return out


def _ultimo_costo_de_siesa(cur, eng, empresa: str) -> dict:
    """Ultimo costo de compra de cada item -> ddmrp.item_compra (ultimo_costo, ultimo_costo_fecha, ultimo_costo_nit). Es el respaldo cuando no hay cotizacion vigente;
    quien decide cual costo se usa es el maestro (manual > cotizacion de Siesa > ultima compra). Un fallo del origen solo deja esos campos como estaban."""
    out: dict = {}
    prm = {"cia": settings.siesa_cia}
    filas = None
    # primero con el filtro de moneda de la OC (una compra en dolares no sirve como costo en pesos); si esa columna no existe, sin el y con aviso
    for filtro_moneda, aviso in ((" AND d.f420_id_moneda_docto = :moneda", None),
                                 ("", "El ultimo costo se leyo SIN filtrar la moneda de la OC (no se pudo leer f420_id_moneda_docto): una compra en dolares se veria como pesos.")):
        try:
            filas = list(_stream(eng, _con_estado(SQL_ULTIMO_COSTO.replace("{moneda}", filtro_moneda), False), {**prm, "moneda": settings.siesa_moneda_compra}))
            if aviso:
                out["aviso_ultimo_costo"] = aviso
            break
        except Exception as e:
            if isinstance(e, psycopg.Error):
                raise
            err = str(e).splitlines()[0]
    if filas is None:
        log.warning("Ultimo costo de compra no leido: %s", err)
        out["aviso_ultimo_costo"] = ("No se pudo leer el ultimo costo de compra (OC): " + err)[:300]
        return out
    cur.execute("CREATE TEMP TABLE IF NOT EXISTS stg_uc (producto_id text, costo numeric, fecha date, nit text)")
    cur.execute("TRUNCATE stg_uc")
    with cur.copy("COPY stg_uc FROM STDIN") as cp:
        for ref, precio, fecha, nit in filas:
            if ref and precio:
                cp.write_row((ref.strip(), round(float(precio), 4), fecha.date() if hasattr(fecha, "date") else fecha, (nit or "").strip() or None))
    cur.execute("""UPDATE ddmrp.item_compra ic SET ultimo_costo = s.costo, ultimo_costo_fecha = s.fecha, ultimo_costo_nit = s.nit FROM stg_uc s
                   WHERE ic.empresa = %s AND ic.producto_id = s.producto_id""", (empresa,))
    cur.execute("""UPDATE ddmrp.item_compra ic SET ultimo_costo = NULL, ultimo_costo_fecha = NULL, ultimo_costo_nit = NULL
                   WHERE ic.empresa = %s AND ic.ultimo_costo IS NOT NULL AND NOT EXISTS (SELECT 1 FROM stg_uc s WHERE s.producto_id = ic.producto_id)""", (empresa,))
    cur.execute("DROP TABLE stg_uc")
    out["items_con_ultimo_costo"] = len(filas)
    return out


def _cond_pago_de_siesa(cur, eng, empresa: str) -> dict:
    """Pre-llena la condicion de pago de los proveedores que aun no la tienen con la de su ultima OC en Siesa. Lo que compras escribio NO se pisa. Un fallo del origen no
    tumba la sincronizacion. Devuelve cuantos proveedores con items quedan SIN condicion de pago (no se podra crear su OC)."""
    try:
        filas = list(_stream(eng, SQL_COND_PAGO, {"cia": settings.siesa_cia}))
    except Exception as e:
        if isinstance(e, psycopg.Error):
            raise
        log.warning("Condicion de pago de la ultima OC no leida: %s", e)
        return {"aviso_cond_pago": ("No se pudo leer la condicion de pago de las OC: " + str(e).splitlines()[0])[:300]}
    cur.execute("CREATE TEMP TABLE IF NOT EXISTS stg_cp (nit text, cond text)")
    cur.execute("TRUNCATE stg_cp")
    with cur.copy("COPY stg_cp FROM STDIN") as cp:
        for nit, cond in filas:
            if nit and cond:
                cp.write_row((nit.strip(), cond.strip().upper()))
    cur.execute("""UPDATE ddmrp.proveedor p SET cond_pago = s.cond FROM stg_cp s
                   WHERE p.empresa = %s AND p.proveedor_id = s.nit AND (p.cond_pago IS NULL OR btrim(p.cond_pago) = '')""", (empresa,))
    llenadas = cur.rowcount or 0
    cur.execute("DROP TABLE stg_cp")
    cur.execute("""SELECT count(*) FROM ddmrp.proveedor p WHERE p.empresa = %s AND (p.cond_pago IS NULL OR btrim(p.cond_pago) = '')
                   AND EXISTS (SELECT 1 FROM ddmrp.item_compra ic WHERE ic.empresa = p.empresa AND ic.proveedor_id = p.proveedor_id AND ic.sucursal = p.sucursal)""", (empresa,))
    return {"cond_pago_llenadas": llenadas, "proveedores_sin_cond_pago": cur.fetchone()[0]}


def _items_de_siesa(cur, eng, primera: bool = True, empresa: str | None = None) -> dict:
    """Descripcion, laboratorio (plan 006) y TODOS los criterios de items de una base de Siesa.
    Primero se lee todo del origen y solo despues se escribe, para que un fallo de Siesa no deje la tabla a medias.
    Si hay dos bases (Funat y Stores), la primera manda y la segunda solo agrega lo que falte."""
    prm = {"cia": settings.siesa_cia}
    aviso_estado = _probe_estado(eng)     # None = la columna de estado existe
    items_all = list(_stream(eng, _sql_items(aviso_estado is None), prm))   # TODOS los t120: el estado y los REC se leen antes de filtrar por criterio
    items = [x[:2] for x in items_all]
    labs = list(_stream(eng, SQL_LAB, {**prm, "plan": settings.siesa_plan_laboratorio}))
    crit = list(_stream(eng, SQL_ITEM_CRITERIOS, prm))
    permitidos = {tuple(x.strip().split(":", 1)) for x in settings.siesa_criterios_items.split(",") if ":" in x}
    if permitidos:   # el filtro elige ITEMS (los que tienen alguno de esos criterios); de cada uno se traen todos sus criterios
        validos = {c[0] for c in crit if (c[1], c[2]) in permitidos}
        crit = [c for c in crit if c[0] in validos]
        items = [x for x in items if x[0] in validos]
        labs = [x for x in labs if x[0] in validos]
    nombres_lab, nombres_plan, nombres_crit = [], [], []
    for sql, destino, aviso in ((SQL_LAB_NOMBRES, nombres_lab, "laboratorios"), (SQL_PLANES_NOMBRES, nombres_plan, "planes"),
                                (SQL_CRITERIOS_NOMBRES, nombres_crit, "criterios")):
        try:   # los nombres son un adorno: si la consulta falla no se pierde lo demas
            destino.extend(_stream(eng, sql, {**prm, "plan": settings.siesa_plan_laboratorio}))
        except Exception as e:
            log.warning("Nombres de %s no leidos: %s", aviso, e)
    cur.execute("CREATE TEMP TABLE IF NOT EXISTS stg_items (producto_id text, descripcion text)")
    cur.execute("TRUNCATE stg_items")
    with cur.copy("COPY stg_items FROM STDIN") as cp:
        for x in items:
            cp.write_row(x)
    # la primera base (Funat) manda: pisa la descripcion. La segunda (Stores) solo agrega los items que falten; antes tambien la pisaba y,
    # como se lee despues, un nombre viejo de Stores (p. ej. "*DESC ...") tapaba el nombre ya corregido en Funat
    cur.execute(f"""INSERT INTO ddmrp.maestro_item (producto_id, descripcion)
                   SELECT producto_id, COALESCE(descripcion, producto_id) FROM stg_items
                   ON CONFLICT (producto_id) DO {"UPDATE SET descripcion = EXCLUDED.descripcion, actualizado = now()" if primera else "NOTHING"}""")
    borrados = 0
    if primera and items:   # espejo de Siesa: se van los items viejos que ya no estan en la seleccion (los de Stores se agregan despues)
        cur.execute("DELETE FROM ddmrp.maestro_item m WHERE NOT EXISTS (SELECT 1 FROM stg_items s WHERE s.producto_id = m.producto_id)")
        borrados = cur.rowcount
    if empresa:   # a que empresa pertenece cada item (filtro por empresa de Maestros)
        cur.execute("DELETE FROM ddmrp.item_empresa WHERE empresa = %s", (empresa,))
        cur.execute("INSERT INTO ddmrp.item_empresa (empresa, producto_id) SELECT DISTINCT %s, producto_id FROM stg_items ON CONFLICT DO NOTHING", (empresa,))
    cur.execute("DROP TABLE stg_items")
    extra: dict = {}
    if empresa:
        if aviso_estado is None:   # estado de CADA item de Siesa (tambien los que quedan fuera de la seleccion por criterio)
            est = [(empresa, x[0], 1 if (x[2] or 0) > 0 else 2 if (x[3] or 0) > 0 else 0) for x in items_all]
            cur.execute("DELETE FROM ddmrp.item_estado WHERE empresa = %s", (empresa,))
            with cur.copy("COPY ddmrp.item_estado (empresa, producto_id, estado) FROM STDIN") as cp:
                for r in est:
                    cp.write_row(r)
            extra.update(activos=sum(1 for e in est if e[2] == 1), inactivos=sum(1 for e in est if e[2] == 0), bloqueados=sum(1 for e in est if e[2] == 2))
        else:
            extra["aviso_estado"] = f"No se filtra por estado: no se pudo leer {settings.siesa_item_estado_col} en t121 ({aviso_estado}). Revisa SIESA_ITEM_ESTADO_COL."
            log.warning(extra["aviso_estado"])
        pares, sin_original = detectar_rec(items_all)   # items REC -> su original (referencia sin el primer digito)
        cur.execute("DELETE FROM ddmrp.item_rec WHERE empresa = %s AND origen = 'auto'", (empresa,))
        cur.executemany("INSERT INTO ddmrp.item_rec (empresa, rec_id, original_id, descripcion, origen) VALUES (%s, %s, %s, %s, 'auto') "
                        "ON CONFLICT (empresa, rec_id) DO NOTHING", [(empresa, r, o, d) for r, o, d in pares])
        extra.update(rec=len(pares), rec_sin_original=len(sin_original))
        if sin_original:
            log.warning("Items REC sin original en Siesa (quedan como items normales): %s", ", ".join(sin_original[:10]))
    cur.executemany("UPDATE ddmrp.maestro_item SET categoria = %s WHERE producto_id = %s", [(l, p) for p, l in labs])
    for cod, nom in nombres_lab:
        cur.execute("INSERT INTO ddmrp.laboratorio (codigo, nombre) VALUES (%s, %s) "
                    "ON CONFLICT (codigo) DO UPDATE SET nombre = EXCLUDED.nombre", (cod, nom))
    if primera and crit:
        cur.execute("TRUNCATE ddmrp.item_criterio")
    resolver = "DO UPDATE SET criterio_id = EXCLUDED.criterio_id" if primera else "DO NOTHING"
    cur.executemany(f"INSERT INTO ddmrp.item_criterio (producto_id, plan_id, criterio_id) VALUES (%s, %s, %s) "
                    f"ON CONFLICT (producto_id, plan_id) {resolver}", crit)
    for pid, nom in nombres_plan:
        cur.execute("INSERT INTO ddmrp.criterio_plan (plan_id, nombre) VALUES (%s, %s) "
                    "ON CONFLICT (plan_id) DO UPDATE SET nombre = EXCLUDED.nombre", (pid, nom))
    for pid, cid, nom in nombres_crit:
        cur.execute("INSERT INTO ddmrp.criterio (plan_id, criterio_id, nombre) VALUES (%s, %s, %s) "
                    "ON CONFLICT (plan_id, criterio_id) DO UPDATE SET nombre = EXCLUDED.nombre", (pid, cid, nom))
    if empresa:
        r_prov, _por_item = _proveedores_de_siesa(cur, eng, empresa)
        extra.update(r_prov)
        extra.update(_cotizaciones_de_siesa(cur, eng, empresa))
        extra.update(_ultimo_costo_de_siesa(cur, eng, empresa))
        extra.update(_cond_pago_de_siesa(cur, eng, empresa))
    return {"items": len(items), "eliminados": borrados, "con_laboratorio": len(labs), "criterios": len(crit), "planes": len({c[1] for c in crit}), **extra}


def sincronizar_items_ahora(usuario: str | None = None) -> dict:
    with bitacora.registrar("items", "manual", usuario) as r:
        r.resumen = res = _sincronizar_items_ahora()
        return res


def _sincronizar_items_ahora() -> dict:
    """Boton "Traer items de Siesa": las dos bases (Funat y Stores) sin correr el ETL completo."""
    if not settings.siesa_host:
        raise RuntimeError("Siesa no esta configurado (SIESA_HOST)")
    out: dict = {}
    raw = pg.raw_connection()
    try:
        with raw.cursor() as cur:
            for empresa, db in (("05", settings.siesa_db), ("21", settings.siesa_db_s)):
                if db:
                    out[empresa] = _items_de_siesa(cur, siesa_engine(db), primera=(empresa == "05"), empresa=empresa)
        raw.commit()
        return out
    except Exception:
        raw.rollback()
        raise
    finally:
        raw.close()


def _cedi_de_siesa(cur) -> dict:
    """Inventario disponible del CEDI de cada empresa (05: SIESA_CEDI_BODEGA en la base Funat; 21: SIESA_CEDI_BODEGA_S en Stores).
    Se lee todo antes de escribir; si una empresa falla se conserva el ultimo corte de esa empresa y se avisa."""
    leidos: dict[str, tuple] = {}
    errores: dict[str, str] = {}
    avisos: dict[str, str] = {}
    solo = _solo_activos(cur)
    cur.execute("SELECT empresa, min(bodega_id) FROM ddmrp.maestro_cedi GROUP BY empresa")   # el CEDI de cada empresa sale del maestro de CEDIs
    cedis = dict(cur.fetchall())
    for emp, db, bod in (("05", settings.siesa_db, cedis.get("05") or settings.siesa_cedi_bodega), ("21", settings.siesa_db_s, cedis.get("21") or settings.siesa_cedi_bodega_s)):
        if not (db and bod):
            continue
        try:
            eng = siesa_engine(db)
            filtrar, aviso = _filtrar_activos(solo, eng)
            if aviso:
                avisos[emp] = aviso
            prm = {"cia": settings.siesa_cia, "bodegas": [bod], "resta": 1, "resta_sa": 0}
            filas = list(_stream(eng, _con_estado(SQL_INVENTARIO, filtrar), prm, expanding="bodegas"))   # el CEDI siempre descuenta lo comprometido; las ventas sin acumular no aplican
            try:   # existencia FISICA (sin descontar lo comprometido) de todos los items: base de los lanzamientos. Si falla, solo se omiten los lanzamientos
                fisica = list(_stream(eng, _con_estado(SQL_INVENTARIO, False), {**prm, "resta": 0}, expanding="bodegas"))
            except Exception as e:
                log.warning("Existencia fisica del CEDI %s no leida (lanzamientos omitidos): %s", emp, e); fisica = None
            leidos[emp] = (bod, eng, filas, fisica, filtrar)
        except Exception as e:
            if emp == "05":
                raise
            log.warning("Inventario del CEDI de la empresa %s no leido: %s", emp, e); errores[emp] = str(e)[:200]
    cur.execute("SELECT empresa, rec_id, original_id FROM ddmrp.v_item_rec")   # los REC suman al original
    rec: dict[str, dict[str, str]] = {}
    for e_, r_, o_ in cur.fetchall():
        rec.setdefault(e_, {})[r_] = o_
    out: dict = {}
    lanz: dict = {}
    for emp, (bod, eng, filas, fisica, filtrar) in leidos.items():
        costos = _costos(cur, eng, [bod], pisar=(emp == "05"), filtrar=filtrar)   # el costo del CEDI de Funat manda; el de Stores solo llena lo que falte
        cur.execute("DELETE FROM ddmrp.inventario_cedi WHERE empresa = %s", (emp,))
        mapa = rec.get(emp, {})
        datos: dict = {}
        for prod, _b, fecha, disp in filas:
            d = datos.setdefault(mapa.get(prod, prod), [fecha, 0.0])
            d[1] += float(disp or 0)
        for prod, (fecha, disp) in datos.items():
            cur.execute("INSERT INTO ddmrp.inventario_cedi (empresa, producto_id, disponible, fecha_corte) VALUES (%s, %s, %s, %s)", (emp, prod, max(disp, 0.0), fecha))
        out[emp] = {"bodega": bod, "productos": len(datos), "con_stock": sum(1 for d in datos.values() if d[1] > 0), "costos": costos, "rec_sumados": len(mapa)}
        if fisica is not None:
            exist: dict[str, float] = {}
            for prod, _b, fecha, disp in fisica:
                k = mapa.get(prod, prod)
                exist[k] = exist.get(k, 0.0) + float(disp or 0)
            hoy = (filas[0][2] if filas else fisica[0][2] if fisica else date.today())
            lanz[emp] = lanzamientos.registrar(cur, emp, exist, hoy)
    res = {**out["05"]} if "05" in out else {}
    res["por_empresa"] = out
    if lanz:
        res["lanzamientos"] = lanz
    if avisos:
        res["avisos_estado"] = avisos
    if errores:
        res["errores"] = errores
    return res


def refrescar_cedi() -> dict:
    """Lee de Siesa el inventario FRESCO del CEDI, para que el reparto del motor no dependa de cuando corrio el ETL.
    Si Siesa no responde se sigue con el ultimo corte y se avisa."""
    if not (settings.siesa_host and settings.siesa_db and settings.siesa_cedi_bodega):
        return {"fresco": False, "motivo": "Siesa no configurado"}
    raw = pg.raw_connection()
    try:
        with raw.cursor() as cur:
            r = _cedi_de_siesa(cur)
        raw.commit()
        return {"fresco": True, **r}
    except Exception as e:
        raw.rollback()
        log.warning("Inventario fresco del CEDI no leido, se usa el ultimo corte: %s", e)
        return {"fresco": False, "motivo": str(e)[:200]}
    finally:
        raw.close()


def refrescar_oc_cedi() -> dict:
    """Vuelve a leer de Siesa SOLO las ordenes de compra abiertas hacia los CEDI (su saldo por recibir es el transito del buffer del CEDI) y reemplaza esas filas de
    ddmrp.transitos. Es lo que necesita «recalcular necesidades de compra» sin correr el ETL completo. Si Siesa falla, queda lo que habia."""
    res: dict = {}
    if not settings.siesa_host:
        return {"aviso": "Siesa no configurado"}
    raw = pg.raw_connection()
    try:
        with raw.cursor() as cur:
            cur.execute("SELECT empresa, bodega_id FROM ddmrp.maestro_cedi")
            cedis: dict[str, list[str]] = {}
            for emp, b in cur.fetchall():
                cedis.setdefault(emp, []).append(b)
            oc_dias = _param(cur, "oc_dias_historia")
            desde_oc = date.today() - timedelta(days=int(min(max(oc_dias, 30), 1500)) if oc_dias else 365)
            solo = _solo_activos(cur)
            for empresa, db in (("05", settings.siesa_db), ("21", settings.siesa_db_s)):
                bods = cedis.get(empresa, [])
                if not db or not bods:
                    continue
                eng = siesa_engine(db)
                filtrar, _ = _filtrar_activos(solo, eng)
                filas = list(_stream(eng, _con_estado(SQL_OC_ABIERTAS, filtrar), {"cia": settings.siesa_cia, "bodegas": bods, "desde_oc": desde_oc}, expanding="bodegas"))
                cur.execute("DELETE FROM ddmrp.transitos WHERE empresa = %s AND bodega_id = ANY(%s) AND documento LIKE 'OC-%%'", (empresa, bods))
                res[f"oc_abiertas_{empresa}"] = _volcar(cur, ((empresa,) + r for r in filas), "ddmrp.transitos",
                                                         ["empresa", "producto_id", "bodega_id", "documento", "cantidad"], reemplazar=False)
        raw.commit()
    except Exception:
        raw.rollback()
        raise
    finally:
        raw.close()
    return res


def _param(cur, clave: str):
    cur.execute("SELECT valor FROM ddmrp.parametro WHERE clave = %s", (clave,))
    f = cur.fetchone()
    return float(f[0]) if f else None


def sincronizar_ventas(origen: str = "manual", usuario: str | None = None) -> dict:
    with bitacora.registrar("ventas", origen, usuario) as r:
        r.resumen = res = _sincronizar_ventas()
        return res


def _sincronizar_ventas() -> dict:
    """Ventas por mes de Siesa -> ddmrp.ventas_mensual. Solo reemplaza la ventana de meses y las bodegas leidas
    (el historico anterior no se toca). Va aparte del ETL porque es la consulta pesada: se lanza a demanda o por parametro."""
    res: dict = {}
    with progreso.tarea("Ventas", "Ventas por mes traídas de Siesa"):
        vsql = _ventas_sql()
        if not vsql:
            raise RuntimeError("etl/sql/ventas_siesa.sql no tiene consulta: cargalas por Excel (maestro ventas por mes)")
        if not settings.siesa_host:
            raise RuntimeError("Siesa no esta configurado (SIESA_HOST)")
        raw = pg.raw_connection()
        try:
            with raw.cursor() as cur:
                meses = _param(cur, "meses_historia")
                desde = _primer_mes(date.today(), min(max(int(meses), 2), 12) if meses else MESES_VENTANA)
                solo = _solo_activos(cur)
                cur.execute("SELECT empresa, bodega_id FROM ddmrp.abast_bitacora")
                por_empresa: dict[str, list[str]] = {}
                for emp, b in cur.fetchall():
                    por_empresa.setdefault(emp, []).append(b)
                if not por_empresa:
                    raise RuntimeError("abast_bitacora esta vacia: cargala en Maestros antes de traer las ventas")
                cur.execute("SELECT empresa, bodega_id FROM ddmrp.maestro_cedi")
                cedis_por_empresa: dict[str, list[str]] = {}
                for emp, b in cur.fetchall():
                    cedis_por_empresa.setdefault(emp, []).append(b)
                csql = _ventas_sql(VENTAS_CEDI_SQL_FILE)   # ventas directas del CEDI (PT001); su rotacion tambien cuenta para la necesidad de compra
                cur.execute("CREATE TEMP TABLE stg_vm (empresa text, mes char(6), bodega_id text, producto_id text, cantidad numeric, valor numeric) ON COMMIT DROP")
                leidas: list[str] = []
                for empresa, db in (("05", settings.siesa_db), ("21", settings.siesa_db_s)):
                    bodegas = por_empresa.get(empresa, [])
                    cedis = cedis_por_empresa.get(empresa, []) if csql else []
                    if not db or not (bodegas or cedis):
                        continue
                    eng = siesa_engine(db)
                    filtrar, aviso = _filtrar_activos(solo, eng)
                    if aviso:
                        res[f"aviso_estado_{empresa}"] = aviso
                    # (clave del resumen, consulta, bodegas): tiendas y, aparte, ventas directas de los CEDI
                    for clave, sql_v, bods in ((f"ventas_{empresa}", vsql, bodegas), (f"ventas_cedi_{empresa}", csql, cedis)):
                        if not bods:
                            continue
                        n = 0
                        progreso.avance(f"Leyendo ventas de {db} desde {desde:%Y-%m} ({len(bods)} bodegas{' CEDI' if 'cedi' in clave else ''})… puede tardar varios minutos")
                        with cur.copy("COPY stg_vm (empresa, mes, bodega_id, producto_id, cantidad, valor) FROM STDIN") as cp:
                            for r in _stream(eng, _con_estado(sql_v, filtrar), {"cia": settings.siesa_cia, "bodegas": bods, "desde": desde}, expanding="bodegas"):
                                cp.write_row((empresa,) + tuple(r)); n += 1
                                if n % 50000 == 0:
                                    progreso.avance(f"Leyendo ventas de {db}: {n:,} filas…")
                        res[clave] = n
                        leidas += [(empresa, b) for b in bods]
                if not leidas:
                    raise RuntimeError("No hay bodegas para leer (revisa SIESA_DB / SIESA_DB_S y la bitacora)")
                progreso.avance("Guardando las ventas en la base…")
                cur.execute("DELETE FROM ddmrp.ventas_mensual v WHERE v.mes >= %s AND (v.empresa || '|' || v.bodega_id) = ANY(%s)",
                            (f"{desde:%Y%m}", [f"{e}|{b}" for e, b in leidas]))
                cur.execute("""INSERT INTO ddmrp.ventas_mensual (empresa, mes, bodega_id, producto_id, cantidad, valor)
                               SELECT empresa, mes, bodega_id, producto_id, SUM(cantidad), COALESCE(SUM(valor), 0) FROM stg_vm
                               WHERE mes >= %s GROUP BY 1, 2, 3, 4""", (f"{desde:%Y%m}",))
                res["meses_desde"] = f"{desde:%Y%m}"
                ret = _param(cur, "meses_retencion_ventas")
                ret = int(min(max(ret if ret else 36, 13), 120))
                cur.execute("DELETE FROM ddmrp.ventas_mensual WHERE mes < to_char(current_date - make_interval(months => %s), 'YYYYMM')", (ret,))
                res["ventas_borradas_por_antiguas"] = cur.rowcount
                res["fuera_del_maestro"] = _purgar_fuera_del_maestro(cur)
            raw.commit()
        except Exception:
            raw.rollback()
            raise
        finally:
            raw.close()
    return res


def _analizar_tablas():
    """ANALYZE de lo que el ETL acaba de recargar: con estadisticas viejas Postgres elige planes pesimos en los informes (Clasificacion, Matriz)."""
    try:
        from ..estadisticas import analizar_todo
        analizar_todo()
    except Exception:
        log.exception("No se pudo actualizar las estadisticas tras el ETL (ANALYZE)")


def correr_etl(origen: str = "manual", usuario: str | None = None) -> dict:
    with progreso.tarea("ETL", "ETL listo"), bitacora.registrar("etl", origen, usuario) as r:
        r.resumen = res = _correr_etl(origen, usuario)
        _analizar_tablas()
        return res


def _correr_etl(origen: str = "manual", usuario: str | None = None) -> dict:
    res: dict = {}
    raw = pg.raw_connection()
    try:
        with raw.cursor() as cur:
            cur.execute("SELECT valor FROM ddmrp.parametro WHERE clave = 'meses_historia'")
            fila = cur.fetchone()
            desde = _primer_mes(date.today(), min(max(int(fila[0]), 2), 12) if fila else MESES_VENTANA)
            res["tiendas"] = sincronizar_bodegas(cur)
            cur.execute("SELECT empresa, bodega_id FROM ddmrp.abast_bitacora")
            por_empresa: dict[str, list[str]] = {}
            for emp, b in cur.fetchall():
                por_empresa.setdefault(emp, []).append(b)
            if not por_empresa:
                log.warning("abast_bitacora vacia: cargala en Configuracion (Excel) antes de correr el ETL")
            cur.execute("SELECT empresa, bodega_id FROM ddmrp.maestro_cedi")
            cedis_emp: dict[str, list[str]] = {}
            for emp, b in cur.fetchall():
                cedis_emp.setdefault(emp, []).append(b)
            oc_dias = _param(cur, "oc_dias_historia")   # las OC mas viejas que esto no cuentan (una OC olvidada sin cerrar inflaria el transito para siempre)
            desde_oc = date.today() - timedelta(days=int(min(max(oc_dias, 30), 1500)) if oc_dias else 365)
            if not settings.siesa_host:
                log.warning("Siesa no configurado: inventario, transitos y ventas quedan como estaban")
                raw.commit()
                return {"aviso": "Siesa no configurado"}

            cur.execute("TRUNCATE ddmrp.inventario_actual")
            cur.execute("TRUNCATE ddmrp.transitos")
            traer_ventas = (_param(cur, "etl_traer_ventas") or 0) >= 1
            resta_comp = (_param(cur, "inv_tiendas_resta_comprometido") or 0) >= 1
            resta_sa = (_param(cur, "inv_tiendas_resta_sin_acumular") or 0) >= 1   # ventas del POS aun sin acumular (salida sin confirmar)
            solo = _solo_activos(cur)
            if not traer_ventas:
                log.info("ETL: las ventas por mes no se traen aqui (parametro etl_traer_ventas = 0); usa el boton 'Traer ventas'")
            for empresa, db in (("05", settings.siesa_db), ("21", settings.siesa_db_s)):
                bodegas = por_empresa.get(empresa, [])
                if not db or not bodegas:
                    continue
                eng, prm = siesa_engine(db), {"cia": settings.siesa_cia, "bodegas": bodegas}
                prm_inv = {**prm, "resta": 1 if resta_comp else 0, "resta_sa": 1 if resta_sa else 0}
                filtrar, aviso = _filtrar_activos(solo, eng)   # solo items activos de Siesa (y REC); sin la columna de estado no se filtra y se avisa
                if aviso:
                    res[f"aviso_estado_{empresa}"] = aviso
                log.info("ETL empresa %s (%s): %s bodegas", empresa, db, len(bodegas))
                progreso.avance(f"Leyendo inventario de Siesa ({db}, {len(bodegas)} bodegas)…")
                res[f"inventario_{empresa}"] = _volcar(
                    cur, ((empresa,) + r for r in _stream(eng, _con_estado(SQL_INVENTARIO, filtrar), prm_inv, expanding="bodegas")), "ddmrp.inventario_actual",
                    ["empresa", "producto_id", "bodega_id", "fecha_corte", "disponible"], reemplazar=False)
                progreso.avance(f"Leyendo costos promedio de Siesa ({db})…")
                res[f"costos_{empresa}"] = _costos(cur, eng, bodegas, pisar=False, filtrar=filtrar)   # respaldo: el costo del CEDI manda (se lee al final)
                progreso.avance(f"Leyendo traslados en tránsito de Siesa ({db})…")
                res[f"transitos_{empresa}"] = _volcar(
                    cur, ((empresa,) + r for r in _stream(eng, _con_estado(SQL_TRANSITOS, filtrar), prm, expanding="bodegas")), "ddmrp.transitos",
                    ["empresa", "producto_id", "bodega_id", "documento", "cantidad"], reemplazar=False)
                progreso.avance(f"Leyendo órdenes de compra abiertas de Siesa ({db})…")
                bod_oc = sorted(set(bodegas) | set(cedis_emp.get(empresa, [])))
                try:   # sin las OC el buffer del CEDI solo pierde el transito: no tumba el ETL
                    filas_oc = list(_stream(eng, _con_estado(SQL_OC_ABIERTAS, filtrar), {**prm, "bodegas": bod_oc, "desde_oc": desde_oc}, expanding="bodegas"))   # se lee todo ANTES de escribir: un fallo del origen no deja la transaccion a medias
                    res[f"oc_abiertas_{empresa}"] = _volcar(
                        cur, ((empresa,) + r for r in filas_oc),
                        "ddmrp.transitos", ["empresa", "producto_id", "bodega_id", "documento", "cantidad"], reemplazar=False)
                except Exception as e:
                    if isinstance(e, psycopg.Error):
                        raise
                    log.warning("OC abiertas de %s no leidas: %s", db, e); res[f"oc_error_{empresa}"] = str(e)[:200]
                progreso.avance(f"Leyendo items, criterios y centros de operación ({db})…")
                try:  # descripciones, laboratorio, criterios y centro de operacion: utiles pero no criticos
                    res[f"items_{empresa}"] = _items_de_siesa(cur, eng, primera=(empresa == "05"), empresa=empresa)
                    for b, co in _stream(eng, SQL_CO, prm, expanding="bodegas"):
                        # solo completa el centro de operacion que falte en la bitacora (lo que el usuario escribio no se pisa; no crea tiendas)
                        cur.execute("UPDATE ddmrp.abast_bitacora SET id_co = %s WHERE empresa = %s AND bodega_id = %s AND (id_co IS NULL OR id_co = '')", (co, empresa, b))
                except Exception as e:  # solo fallos del origen; un error de Postgres si debe abortar
                    if isinstance(e, psycopg.Error):
                        raise
                    log.warning("Items / centro de operacion de %s no se actualizaron: %s", db, e)

            if settings.siesa_db and settings.siesa_cedi_bodega:
                progreso.avance(f"Leyendo el inventario del CEDI ({settings.siesa_cedi_bodega})…")
                try:
                    res["cedi"] = _cedi_de_siesa(cur)
                except Exception as e:   # un fallo de Siesa no debe tumbar el ETL: el CEDI queda con el corte anterior
                    if isinstance(e, psycopg.Error):
                        raise
                    log.warning("Inventario del CEDI no leido: %s", e); res["cedi_error"] = str(e)[:200]
            res["fuera_del_maestro"] = _purgar_fuera_del_maestro(cur)
        raw.commit()
    except Exception:
        raw.rollback()
        raise
    finally:
        raw.close()
    if traer_ventas:
        res.update(sincronizar_ventas(origen, usuario))
    return res
