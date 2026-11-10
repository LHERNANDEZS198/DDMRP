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
               "rep_minuto": 0.0, "rep_cada_dias": 1.0, "rep_recalcular_compras": 1.0, "rep_otif_pct_completo": 98.0, "rep_otif_excluir_regularizadas": 1.0}
COLS_COMPRAS = ("f_fecha", "f_valor_bruto_local", "f_cant_base", "f_proveedor", "f_proveedor_razon_soc", "f_referencia")


def _sql(nombre: str) -> str:
    """El texto de la consulta sin las lineas de comentario (se edita en etl/sql/ sin tocar el codigo)."""
    q = "\n".join(l for l in (SQL_DIR / nombre).read_text(encoding="utf-8").splitlines() if not l.strip().startswith("--"))
    if not q.strip():
        raise RuntimeError(f"etl/sql/{nombre} no tiene consulta")
    return q.strip()


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
    sql = _sql("rep_compras_siesa.sql")
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
            sincronizar_reportes_compras("auto")
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
