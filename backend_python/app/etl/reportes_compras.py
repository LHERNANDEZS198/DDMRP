"""Reportes de compras: historico mensual de Siesa -> Postgres (ddmrp.rep_venta_mes, rep_compra_mes, rep_otif).
Alimenta los informes «Ventas por producto» y «Proveedor / PT» (los que antes vivian en el Power BI de compras). Va aparte del ETL diario porque son consultas
historicas mas pesadas: se lanza con el boton «Actualizar datos» del informe o solo, a la hora, minuto y cada cuantos dias de las reglas rep_hora, rep_minuto y rep_cada_dias (Reglas de compras), aparte del ETL del motor.
  - ventas   etl/sql/rep_ventas_siesa.sql   facturas de venta por mes, item, canal y unidad de negocio (bruto, descuento, costo)
  - compras  etl/sql/rep_compras_siesa.sql  el mismo procedimiento del Power BI (analisis de documentos de compras), agregado por mes, item y proveedor
  - otif     etl/sql/rep_otif_siesa.sql     lineas de OC con su ultima entrada real; aqui se calcula a tiempo y completa con los umbrales de compras_config
Cada tarea falla sola: si una no se puede leer las otras igual se cargan y el informe avisa cual quedo sin actualizar. Funat (05) y, si tiene base configurada, Stores (21); compania 1 en ambas."""
import logging
import re
from datetime import date, datetime, timedelta
from pathlib import Path
import psycopg
from sqlalchemy import text
from ..config import settings
from .. import progreso, bitacora
from ..db import pg, siesa_engine
from ..progreso import Ocupado
from .replicacion import _stream

log = logging.getLogger("etl.reportes")
SQL_DIR = Path(__file__).parent / "sql"
EMPRESAS = (("05", lambda: settings.siesa_db), ("21", lambda: settings.siesa_db_s))      # Stores (21) solo si hay base configurada (SIESA_DB_S); si no, se salta
CFG_DEFECTO = {"rep_meses_historia": 48.0, "rep_meses_refresco": 3.0, "rep_auto": 1.0, "rep_hora": 4.0, "rep_otif_dias_tolerancia": 0.0,
               "rep_minuto": 0.0, "rep_cada_dias": 1.0, "rep_recalcular_compras": 1.0, "rep_calcular_indicadores": 1.0, "rep_gmroi_minimo": 1.0, "rep_gmroi_meta": 3.2, "rep_otif_pct_completo": 98.0, "rep_otif_excluir_regularizadas": 1.0}
COLS_COMPRAS = ("f_fecha", "f_valor_bruto_local", "f_cant_base", "f_proveedor", "f_proveedor_razon_soc", "f_referencia")


def _sql(nombre: str) -> str:
    """El texto de la consulta sin las lineas de comentario (se edita en etl/sql/ sin tocar el codigo)."""
    q = "\n".join(l for l in (SQL_DIR / nombre).read_text(encoding="utf-8").splitlines() if not l.strip().startswith("--"))
    if not q.strip():
        raise RuntimeError(f"etl/sql/{nombre} no tiene consulta")
    return q.strip()


SP_COMPRAS_DEFECTO = {"05": "sp_pv_cons_analisis_docto_com_FUNAT", "21": "sp_pv_cons_analisis_docto_com_stores"}


def _sp_compras(empresa: str) -> str:
    """Procedimiento de compras de la empresa. Se cambia sin tocar el codigo: fila ddmrp.compras_config con clave rep_sp_compras_<empresa> y el nombre en «detalle»
    (p. ej. rep_sp_compras_21); si no hay, el de SP_COMPRAS_DEFECTO. Se valida como identificador porque se pega en el texto de la consulta."""
    nombre = SP_COMPRAS_DEFECTO.get(empresa, SP_COMPRAS_DEFECTO["05"])
    try:
        with pg.connect() as c:
            v = c.execute(text("SELECT detalle FROM ddmrp.compras_config WHERE clave = :k"), {"k": f"rep_sp_compras_{empresa}"}).scalar()
        if v and str(v).strip():
            nombre = str(v).strip()
    except Exception:       # noqa: BLE001
        log.exception("No se pudo leer rep_sp_compras_%s: se usa %s", empresa, nombre)
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,127}", nombre):
        raise RuntimeError(f"Nombre de procedimiento de compras no valido: {nombre!r}")
    return nombre


def config() -> dict:
    cfg = dict(CFG_DEFECTO)
    try:
        with pg.connect() as c:
            for k, v in c.execute(text("SELECT clave, valor::float8 FROM ddmrp.compras_config WHERE clave LIKE 'rep\\_%' AND valor IS NOT NULL")).all():
                cfg[k] = v
    except Exception:       # noqa: BLE001
        log.exception("No se pudo leer la configuracion de los reportes de compras: quedan los valores por defecto")
    return cfg


def _mes_hace(hoy: date, meses: int) -> date:
    """Primer dia del mes de hace `meses` meses."""
    m = hoy.year * 12 + hoy.month - 1 - max(int(meses), 0)
    return date(m // 12, m % 12 + 1, 1)


def _desde(empresa: str, tabla: str, cfg: dict, hoy: date, completo: bool) -> date:
    """Desde cuando se relee: toda la historia la primera vez (o con «recarga completa») y los ultimos meses de refresco despues."""
    with pg.connect() as c:
        hay = c.execute(text(f"SELECT EXISTS (SELECT 1 FROM ddmrp.{tabla} WHERE empresa = :e)"), {"e": empresa}).scalar()
    return _mes_hace(hoy, cfg["rep_meses_historia"] if (completo or not hay) else cfg["rep_meses_refresco"])


def _cargar(cur, destino: str, cols: list[str], claves: list[str], medidas: list[str], filas) -> int:
    """COPY a una tabla temporal SIN llaves y luego INSERT agrupado: las medidas se SUMAN y el resto (texto, fechas) toma el maximo. Asi un duplicado del origen
    (dos grupos que solo difieren en espacios al final) se junta en vez de perderse."""
    stg = "stg_" + destino.split(".")[-1]
    cur.execute(f"CREATE TEMP TABLE {stg} (LIKE {destino} INCLUDING DEFAULTS) ON COMMIT DROP")
    n = 0
    with cur.copy(f"COPY {stg} ({', '.join(cols)}) FROM STDIN") as cp:
        for r in filas:
            cp.write_row(r)
            n += 1
    otras = [c for c in cols if c not in claves and c not in medidas]
    sel = claves + [f"COALESCE(SUM({c}), 0)" for c in medidas] + [f"MAX({c})" for c in otras]
    cur.execute(f"INSERT INTO {destino} ({', '.join(claves + medidas + otras)}) SELECT {', '.join(sel)} FROM {stg} GROUP BY {', '.join(claves)}")
    cur.execute(f"DROP TABLE {stg}")
    log.info("  %s: %s filas leidas", destino, n)
    return n


def _f(v) -> float:
    return float(v) if v is not None else 0.0


# ---------------------------------------------------------------------------------------------- ventas
def _ventas(eng, empresa: str, cfg: dict, hoy: date, completo: bool) -> tuple[int, str]:
    desde = _desde(empresa, "rep_venta_mes", cfg, hoy, completo)
    periodo = f"{desde:%Y%m}"
    progreso.avance(f"Leyendo las ventas facturadas de Siesa desde {periodo}… puede tardar unos minutos")
    sql = _sql("rep_ventas_siesa.sql")
    raw = pg.raw_connection()
    try:
        with raw.cursor() as cur:
            cur.execute("DELETE FROM ddmrp.rep_venta_mes WHERE empresa = %s AND periodo >= %s", (empresa, periodo))
            filas = ((empresa, str(r[0]).strip(), str(r[1]).strip(), (r[2] or "").strip(), (r[3] or "").strip(), _f(r[4]), _f(r[5]), _f(r[6]), _f(r[7]))
                     for r in _stream(eng, sql, {"cia": settings.siesa_cia, "periodo_desde": periodo}))
            n = _cargar(cur, "ddmrp.rep_venta_mes", ["empresa", "periodo", "producto_id", "canal", "unidad_negocio", "cantidad", "valor_bruto", "descuento", "costo"],
                        ["empresa", "periodo", "producto_id", "canal", "unidad_negocio"], ["cantidad", "valor_bruto", "descuento", "costo"], filas)
        raw.commit()
    except Exception:
        raw.rollback()
        raise
    finally:
        raw.close()
    return n, periodo


# ---------------------------------------------------------------------------------------------- compras
def _filas_compras(eng, sql: str, prm: dict):
    """Resultado del procedimiento de compras de Siesa. Se lee con el cursor crudo porque el procedimiento puede devolver conteos de filas antes de la tabla
    (por eso se salta cada resultado sin columnas hasta llegar al que las tiene). Las :variables del texto pasan a ? en el mismo orden en que aparecen."""
    orden = re.findall(r":(\w+)", sql)
    qsql = re.sub(r":(\w+)", "?", sql)
    cx = eng.raw_connection()
    try:
        cur = cx.cursor()
        cur.execute(qsql, [prm[n] for n in orden])
        while cur.description is None and cur.nextset():
            pass
        if cur.description is None:
            raise RuntimeError("El procedimiento de compras no devolvio filas ni columnas")
        cols = [d[0].lower() for d in cur.description]
        faltan = [c for c in COLS_COMPRAS if c not in cols]
        if faltan:
            raise RuntimeError(f"El procedimiento de compras no devolvio las columnas {', '.join(faltan)} (devolvio: {', '.join(cols[:30])})")
        ix = {c: cols.index(c) for c in COLS_COMPRAS}
        while True:
            lote = cur.fetchmany(10000)
            if not lote:
                break
            for r in lote:
                yield r[ix["f_fecha"]], r[ix["f_valor_bruto_local"]], r[ix["f_cant_base"]], r[ix["f_proveedor"]], r[ix["f_proveedor_razon_soc"]], r[ix["f_referencia"]]
        cur.close()
    finally:
        cx.close()


def _compras(eng, empresa: str, cfg: dict, hoy: date, completo: bool) -> tuple[int, str]:
    desde = _desde(empresa, "rep_compra_mes", cfg, hoy, completo)
    periodo = f"{desde:%Y%m}"
    hasta = date(hoy.year + 1, 12, 31)
    progreso.avance(f"Leyendo las compras de Siesa desde {periodo}… puede tardar unos minutos")
    sp = _sp_compras(empresa)
    sql = _sql("rep_compras_siesa.sql").replace("{sp}", sp)
    log.info("  compras %s: procedimiento %s", empresa, sp)
    prm = {"desde": f"{desde:%d/%m/%Y}", "hasta": f"{hasta:%d/%m/%Y}"}

    def filas():
        for f, valor, cant, nit, nombre, ref in _filas_compras(eng, sql, prm):
            if f is None or not ref:
                continue
            p = f"{f.year}{f.month:02d}"
            if p < periodo:
                continue
            yield (empresa, p, str(ref).strip(), str(nit or "").strip(), (str(nombre).strip() if nombre else None), _f(cant), _f(valor))

    raw = pg.raw_connection()
    try:
        with raw.cursor() as cur:
            cur.execute("DELETE FROM ddmrp.rep_compra_mes WHERE empresa = %s AND periodo >= %s", (empresa, periodo))
            n = _cargar(cur, "ddmrp.rep_compra_mes", ["empresa", "periodo", "producto_id", "proveedor_id", "proveedor_nombre", "cantidad", "valor"],
                        ["empresa", "periodo", "producto_id", "proveedor_id"], ["cantidad", "valor"], filas())
        raw.commit()
    except Exception:
        raw.rollback()
        raise
    finally:
        raw.close()
    return n, periodo


# ---------------------------------------------------------------------------------------------- otif
def calcular_otif(fila: tuple, tol_dias: int, pct_completo: float, excluir_regularizadas: bool) -> tuple | None:
    """(oc, referencia, nit, nombre, fecha_oc, fecha_pactada, pedida, entrada, ultima_entrada) -> (periodo, a_tiempo, completa), o None si la linea no mide al proveedor
    (sin entrada, sin fecha pactada, sin cantidad pedida, o una regularizacion: la OC se monto el mismo dia de la entrada o despues)."""
    _oc, _ref, _nit, _nom, f_oc, f_pact, pedida, entrada, f_ent = fila
    if not f_ent or not f_pact or not pedida or float(pedida) <= 0:
        return None
    if excluir_regularizadas and f_oc and f_ent <= f_oc:
        return None
    a_tiempo = 1 if f_ent <= f_pact + timedelta(days=tol_dias) else 0
    completa = 1 if float(entrada or 0) >= float(pedida) * pct_completo else 0
    return f"{f_ent:%Y%m}", a_tiempo, completa


def _otif(eng, empresa: str, cfg: dict, hoy: date, completo: bool) -> tuple[int, str]:
    desde = _mes_hace(hoy, cfg["rep_meses_historia"])
    progreso.avance(f"Leyendo las OC y sus entradas de Siesa desde {desde:%Y-%m}…")
    tol, pct, excl = int(cfg["rep_otif_dias_tolerancia"]), cfg["rep_otif_pct_completo"] / 100.0, cfg["rep_otif_excluir_regularizadas"] >= 1
    out = []
    for r in _stream(eng, _sql("rep_otif_siesa.sql"), {"cia": settings.siesa_cia, "desde": desde}):
        m = calcular_otif(tuple(r), tol, pct, excl)
        if m is None:
            continue
        oc, ref, nit, nombre, f_oc, f_pact, pedida, entrada, f_ent = r
        out.append((empresa, str(oc).strip(), str(ref).strip(), str(nit or "").strip(), (str(nombre).strip() if nombre else None), f_oc, f_pact, f_ent,
                    _f(pedida), _f(entrada), m[0], m[1], m[2]))
    raw = pg.raw_connection()
    try:
        with raw.cursor() as cur:
            cur.execute("DELETE FROM ddmrp.rep_otif WHERE empresa = %s", (empresa,))
            n = _cargar(cur, "ddmrp.rep_otif", ["empresa", "oc", "producto_id", "proveedor_id", "proveedor_nombre", "fecha_oc", "fecha_pactada", "fecha_entrada",
                                                "cant_pedida", "cant_entrada", "periodo", "a_tiempo", "completa"],
                        ["empresa", "oc", "producto_id"], ["cant_pedida", "cant_entrada"], out)
        raw.commit()
    except Exception:
        raw.rollback()
        raise
    finally:
        raw.close()
    return n, f"{desde:%Y%m}"


# ---------------------------------------------------------------------------------------------- orquestacion
def _marcar(empresa: str, tarea: str, filas: int | None, desde: str | None, mensaje: str | None) -> None:
    try:
        with pg.begin() as c:
            c.execute(text("""INSERT INTO ddmrp.rep_actualizacion (empresa, tarea, fecha, filas, desde, mensaje) VALUES (:e, :t, now(), :f, :d, :m)
                              ON CONFLICT (empresa, tarea) DO UPDATE SET fecha = now(), filas = EXCLUDED.filas, desde = EXCLUDED.desde, mensaje = EXCLUDED.mensaje"""),
                      {"e": empresa, "t": tarea, "f": filas, "d": desde, "m": mensaje})
    except Exception:       # noqa: BLE001
        log.exception("No se pudo anotar la actualizacion de %s/%s", empresa, tarea)


def sincronizar_reportes_compras(origen: str = "manual", usuario: str | None = None, completo: bool = False) -> dict:
    with progreso.tarea("Reportes", "Reportes de compras actualizados"), bitacora.registrar("reportes", origen, usuario) as r:
        r.resumen = res = _sincronizar(completo)
        return res


def _sincronizar(completo: bool) -> dict:
    if not settings.siesa_host:
        raise RuntimeError("Siesa no esta configurado (SIESA_HOST)")
    cfg, hoy, res = config(), date.today(), {}
    hechas = 0
    for empresa, db_fn in EMPRESAS:
        db = db_fn()
        if not db:
            res[f"aviso_{empresa}"] = "sin base de Siesa configurada"
            continue
        eng = siesa_engine(db)
        for tarea, fn in (("ventas", _ventas), ("compras", _compras), ("otif", _otif)):
            try:
                n, desde = fn(eng, empresa, cfg, hoy, completo)
                res[f"{tarea}_{empresa}"] = n
                _marcar(empresa, tarea, n, desde, None)
                hechas += 1
            except Exception as e:      # una tarea que falla no tumba a las otras
                if isinstance(e, psycopg.Error):
                    log.exception("Reportes de compras: %s/%s fallo escribiendo en Postgres", empresa, tarea)
                else:
                    log.warning("Reportes de compras: %s/%s no se pudo leer de Siesa: %s", empresa, tarea, e)
                msg = str(e).strip().splitlines()[0][:300] if str(e).strip() else type(e).__name__
                res[f"error_{tarea}_{empresa}"] = msg
                _marcar(empresa, tarea, None, None, msg)
    if not hechas:
        raise RuntimeError("No se pudo actualizar ninguno de los reportes: " + "; ".join(f"{k}: {v}" for k, v in res.items() if k.startswith(("error", "aviso")))[:600])
    return res


def calcular_indicadores(origen: str = "manual", usuario: str | None = None) -> dict:
    """Deja calculado (aparte del motor y del ETL) lo que usa el informe «Indicadores de compras», para que el informe solo sume y no recorra la historia:
    ddmrp.rep_indicadores_mes (por alcance, mes, empresa e item: venta, inventario promedio, dias en cero/zonas) y ddmrp.rep_indicadores_item (inventario de hoy)."""
    with progreso.tarea("Indicadores", "Indicadores de compras calculados"), bitacora.registrar("indicadores", origen, usuario) as r:
        r.resumen = res = _calcular_indicadores()
        return res


def _ejec(c, paso: str, sql: str, params: dict):
    """Ejecuta una sentencia del calculo y, si Postgres la rechaza, deja en el Log el mensaje REAL de Postgres (columna o tabla que falta, sintaxis...) con el nombre del paso,
    no el volcado de la consulta (el Log guarda solo los ultimos 500 caracteres y el mensaje queda al principio)."""
    try:
        return c.execute(text(sql), params)
    except Exception as e:      # noqa: BLE001
        d = getattr(getattr(e, "orig", None), "diag", None)
        msg = (getattr(d, "message_primary", None) or str(getattr(e, "orig", e)).splitlines()[0])[:300]
        det = f" · {d.message_detail}"[:150] if d is not None and getattr(d, "message_detail", None) else ""
        raise RuntimeError(f"Indicadores · {paso}: {msg}{det}") from None


def _calcular_indicadores() -> dict:
    from ..activos import solo_activos
    hoy, res = date.today(), {}
    mes_min = _mes_hace(hoy, 35).strftime("%Y%m")        # 36 meses de venta; el inventario mensual solo guarda 13
    for alc, cedi in (("tiendas", False), ("cedi", True)):
        # mismas reglas que la Clasificacion: tiendas = solo tiendas (sin la venta directa del CEDI); CEDI = su venta directa + la de todas las tiendas que abastece
        v_bod = "d.cedi" if cedi else "a.bodega_id"
        v_from = "FROM ddmrp.ventas_mensual a JOIN ddmrp.v_origen_cedi d ON d.empresa = a.empresa AND d.origen = a.bodega_id" if cedi else "FROM ddmrp.ventas_mensual a"
        v_sin = "true" if cedi else "NOT EXISTS (SELECT 1 FROM ddmrp.maestro_cedi mc WHERE mc.empresa = a.empresa AND mc.bodega_id = a.bodega_id)"
        t_sug = "ddmrp.sugerencias_cedi" if cedi else "ddmrp.sugerencias_envio"
        h_cedi = "IN" if cedi else "NOT IN"
        ultima = "ANY (SELECT max(id) FROM ddmrp.ejecucion_motor WHERE estado='ok' GROUP BY empresa)"
        with pg.begin() as c:
            c.execute(text("SET LOCAL statement_timeout = 0"))
            _ejec(c, f"{alc}: borrar", "DELETE FROM ddmrp.rep_indicadores_mes WHERE alcance = :a", {"a": alc})
            n = _ejec(c, f"{alc}: item por mes", f"""
                INSERT INTO ddmrp.rep_indicadores_mes (alcance, mes, empresa, producto_id, cant, valor, inv_prom, dias, dias_tot, dias_cero, dias_z, dias_roja)
                WITH v AS (
                  SELECT a.mes, a.empresa, COALESCE(r.original_id, a.producto_id) AS producto_id, SUM(a.cantidad)::float8 AS cant, SUM(a.valor)::float8 AS valor
                  {v_from} LEFT JOIN ddmrp.v_item_rec r ON r.empresa = a.empresa AND r.rec_id = a.producto_id
                  WHERE a.mes >= :mes_min AND {v_sin} GROUP BY 1, 2, 3),
                h AS (
                  SELECT mes, empresa, producto_id, SUM(CASE WHEN dias > 0 THEN inv_suma::float8 / dias ELSE 0 END) AS inv_prom, MAX(dias) AS dias, SUM(dias) AS dias_tot,
                         SUM(dias_cero) AS dias_cero, SUM(dias_z) AS dias_z, SUM(dias_roja) AS dias_roja
                  FROM ddmrp.inventario_mes
                  WHERE mes >= :mes_min AND (empresa, bodega_id) {h_cedi} (SELECT empresa, bodega_id FROM ddmrp.maestro_cedi) GROUP BY 1, 2, 3),
                k AS (
                  SELECT COALESCE(v.mes, h.mes) AS mes, COALESCE(v.empresa, h.empresa) AS empresa, COALESCE(v.producto_id, h.producto_id) AS producto_id,
                         v.cant, v.valor, h.inv_prom, h.dias, h.dias_tot, h.dias_cero, h.dias_z, h.dias_roja
                  FROM v FULL JOIN h ON h.mes = v.mes AND h.empresa = v.empresa AND h.producto_id = v.producto_id)
                SELECT CAST(:a AS TEXT), k.mes, k.empresa, k.producto_id, COALESCE(k.cant, 0), COALESCE(k.valor, 0), COALESCE(k.inv_prom, 0), COALESCE(k.dias, 0), COALESCE(k.dias_tot, 0),
                       COALESCE(k.dias_cero, 0), COALESCE(k.dias_z, 0), COALESCE(k.dias_roja, 0)
                FROM k WHERE {solo_activos('k')}""", {"a": alc, "mes_min": mes_min}).rowcount
            _ejec(c, f"{alc}: borrar inventario", "DELETE FROM ddmrp.rep_indicadores_item WHERE alcance = :a", {"a": alc})
            _ejec(c, f"{alc}: inventario de hoy", f"""
                INSERT INTO ddmrp.rep_indicadores_item (alcance, empresa, producto_id, inventario)
                SELECT CAST(:a AS TEXT), s.empresa, s.producto_id, SUM(GREATEST(s.inventario, 0))::float8
                FROM {t_sug} s WHERE s.ejecucion_id = {ultima} AND {solo_activos('s')} GROUP BY s.empresa, s.producto_id""", {"a": alc})
        res[f"filas_{alc}"] = n
        log.info("Indicadores de compras (%s): %s filas item-mes", alc, n)
    return res


def revisar_reportes() -> None:
    """Se llama cada 10 minutos: si rep_auto = 1, ya paso la hora:minuto de rep_hora / rep_minuto (Colombia) y la ultima actualizacion (automatica o con el boton) fue
    hace rep_cada_dias dias o mas, actualiza. Una actualizacion fallida tambien cuenta como intento (queda el error en el informe) para no martillar Siesa.
    Con rep_recalcular_compras = 1 antes recalcula las necesidades de compra (como el boton «Recalcular»), para que compras no dependa del ETL del motor.
    Si hay otra tarea corriendo (ETL, motor) espera al siguiente turno. Es independiente del ETL del motor."""
    import pytz
    try:
        cfg = config()
        if cfg["rep_auto"] < 1:
            return
        ahora = datetime.now(pytz.timezone("America/Bogota"))
        if (ahora.hour, ahora.minute) < (int(cfg["rep_hora"]), int(cfg["rep_minuto"])):
            return
        with pg.connect() as c:
            ultima = c.execute(text("SELECT max((fecha AT TIME ZONE 'America/Bogota')::date) FROM ddmrp.rep_actualizacion")).scalar()
            marca = c.execute(text("SELECT valor::int FROM ddmrp.parametro WHERE clave = 'rep_ultima_auto'")).scalar()
        if marca:       # ultimo dia que se intento la corrida automatica (aunque algo fallara): evita repetirla cada 10 minutos
            intento = date(marca // 10000, marca // 100 % 100, marca % 100)
            ultima = max(ultima, intento) if ultima else intento
        if ultima and (ahora.date() - ultima).days < max(int(cfg["rep_cada_dias"]), 1):
            return
        ocupado = False
        try:
            if cfg["rep_recalcular_compras"] >= 1:
                from ..orchestrator import recalcular_compras      # aqui para no crear una importacion circular al arrancar
                try:
                    recalcular_compras("auto")
                except Ocupado:
                    raise
                except Exception:       # noqa: BLE001  (p. ej. el motor nunca ha corrido): queda en el Log y los reportes siguen
                    log.exception("Corrida automatica: no se pudieron recalcular las necesidades de compra")
            try:
                sincronizar_reportes_compras("auto")
            finally:       # el calculo de indicadores no depende de Siesa: corre igual aunque la descarga falle (usa lo ya guardado)
                if cfg["rep_calcular_indicadores"] >= 1:
                    try:
                        calcular_indicadores("auto")
                    except Ocupado:
                        raise
                    except Exception:       # noqa: BLE001
                        log.exception("Corrida automatica: no se pudieron calcular los indicadores de compras")
        except Ocupado:
            ocupado = True
            raise
        finally:
            if not ocupado:
                h = ahora.date()
                with pg.begin() as c:
                    c.execute(text("INSERT INTO ddmrp.parametro (clave, valor, detalle) VALUES ('rep_ultima_auto', :v, 'Ultimo dia (AAAAMMDD) en que se intento la corrida automatica de reportes y necesidades de compra') "
                                   "ON CONFLICT (clave) DO UPDATE SET valor = EXCLUDED.valor"), {"v": h.year * 10000 + h.month * 100 + h.day})
    except Ocupado:
        log.info("Reportes de compras: hay otra tarea corriendo, se intenta en el proximo turno")
    except Exception:       # noqa: BLE001
        log.exception("No se pudieron actualizar los reportes de compras (automatico)")
