"""Cambios de esquema idempotentes que se aplican al arrancar el backend (la base puede ser anterior al cambio)."""
import logging
from sqlalchemy import text
from .config import settings
from .db import pg

log = logging.getLogger("esquema")

SENTENCIAS = [
    "CREATE TABLE IF NOT EXISTS ddmrp.criterio_plan (plan_id TEXT PRIMARY KEY, nombre TEXT)",
    "ALTER TABLE ddmrp.criterio_plan ADD COLUMN IF NOT EXISTS en_filtros SMALLINT NOT NULL DEFAULT 1 CHECK (en_filtros IN (0,1))",   # 1 = el plan sale en los filtros; el ETL no lo toca
    "CREATE TABLE IF NOT EXISTS ddmrp.criterio (plan_id TEXT NOT NULL, criterio_id TEXT NOT NULL, nombre TEXT, PRIMARY KEY (plan_id, criterio_id))",
    "CREATE TABLE IF NOT EXISTS ddmrp.item_criterio (producto_id TEXT NOT NULL, plan_id TEXT NOT NULL, criterio_id TEXT NOT NULL, PRIMARY KEY (producto_id, plan_id))",
    "CREATE INDEX IF NOT EXISTS idx_itemcrit_plan ON ddmrp.item_criterio (plan_id, criterio_id)",
    "CREATE TABLE IF NOT EXISTS ddmrp.item_condenado (producto_id TEXT NOT NULL, bodega_id TEXT NOT NULL DEFAULT '*', motivo TEXT, PRIMARY KEY (producto_id, bodega_id))",
    "ALTER TABLE ddmrp.sugerencias_envio ADD COLUMN IF NOT EXISTS condenado BOOLEAN NOT NULL DEFAULT false",
    """CREATE TABLE IF NOT EXISTS ddmrp.buffer_historia (   -- foto diaria liviana: sirve a "cambios en un periodo" y a la tendencia
         fecha DATE NOT NULL, empresa TEXT NOT NULL, bodega_id TEXT NOT NULL, producto_id TEXT NOT NULL,
         zona ddmrp.zona_buffer NOT NULL, tor REAL, toy_aj REAL, tog_aj REAL, inventario REAL, flujo_neto REAL, pct_buffer REAL,
         PRIMARY KEY (fecha, bodega_id, producto_id))""",
    "CREATE INDEX IF NOT EXISTS idx_bufhist_item ON ddmrp.buffer_historia (producto_id, bodega_id, fecha)",
    "ALTER TABLE ddmrp.sugerencias_envio ADD COLUMN IF NOT EXISTS cantidad_necesaria NUMERIC(14,3), ADD COLUMN IF NOT EXISTS stock_cedi NUMERIC(14,3)",
    "CREATE TABLE IF NOT EXISTS ddmrp.inventario_cedi (producto_id TEXT PRIMARY KEY, disponible NUMERIC(14,3) NOT NULL, fecha_corte DATE NOT NULL)",
    "CREATE TABLE IF NOT EXISTS ddmrp.reserva_cedi (producto_id TEXT PRIMARY KEY, porcentaje NUMERIC(8,4) NOT NULL CHECK (porcentaje >= 0 AND porcentaje <= 1))",
    "INSERT INTO ddmrp.parametro VALUES ('cedi_regla_reparto', 1, 'Si el inventario del CEDI no alcanza: 0 no limita, 1 proporcional a la rotacion (ADU), 4 proporcional a la necesidad, 2 parejo, 3 prioridad al mas critico, 5 por clase de tienda: A primero, luego B y C') ON CONFLICT DO NOTHING",
    "INSERT INTO ddmrp.parametro VALUES ('etl_traer_ventas', 0, 'El ETL tambien trae las ventas por mes de Siesa (1 = si, 0 = solo con el boton)') ON CONFLICT DO NOTHING",
    "INSERT INTO ddmrp.parametro VALUES ('meses_retencion_ventas', 36, 'Meses de ventas por mes que se conservan en la base (los anteriores se borran al traer ventas)') ON CONFLICT DO NOTHING",
    """CREATE TABLE IF NOT EXISTS ddmrp.consulta_log (
         id        BIGSERIAL PRIMARY KEY,
         ts        TIMESTAMPTZ NOT NULL DEFAULT now(),
         usuario   TEXT,
         metodo    TEXT,
         ruta      TEXT,
         params    JSONB,
         http      INT,
         estado    TEXT,
         ms        INT,
         ms_sql    INT,
         ms_calc   INT,
         filas     INT,
         bytes     BIGINT,
         error     TEXT,
         extra     JSONB)""",
    "CREATE INDEX IF NOT EXISTS idx_consulta_log_ts ON ddmrp.consulta_log (ts DESC)",
    "CREATE INDEX IF NOT EXISTS idx_consulta_log_ruta ON ddmrp.consulta_log (ruta, ts DESC)",
    "INSERT INTO ddmrp.parametro VALUES ('retener_dias', 180, 'Dias de historia diaria del buffer que se conservan') ON CONFLICT DO NOTHING",
    "ALTER TABLE ddmrp.sugerencias_envio ADD COLUMN IF NOT EXISTS regla_objetivo SMALLINT",
    "CREATE TABLE IF NOT EXISTS ddmrp.costo_item (producto_id TEXT PRIMARY KEY, costo NUMERIC(16,4) NOT NULL, fecha_corte DATE NOT NULL DEFAULT current_date)",
    # hasta donde se repone por item o por laboratorio (1 TOG aj, 2 TOY aj, 3 TOY aj + mitad de la zona verde); el item gana sobre el laboratorio
    "CREATE TABLE IF NOT EXISTS ddmrp.reposicion_item (producto_id TEXT PRIMARY KEY, regla SMALLINT NOT NULL CHECK (regla IN (1,2,3)))",
    "CREATE TABLE IF NOT EXISTS ddmrp.reposicion_laboratorio (laboratorio TEXT PRIMARY KEY, regla SMALLINT NOT NULL CHECK (regla IN (1,2,3)))",
    "CREATE TABLE IF NOT EXISTS ddmrp.reparto_dia (dia INT PRIMARY KEY)",   # vacio = el CEDI se reparte entre todas las tiendas
    "INSERT INTO ddmrp.parametro VALUES ('valor_minimo_envio', 350000, 'Valor minimo (a costo promedio) del despacho a una tienda: por debajo no se deja enviar. 0 = sin minimo') ON CONFLICT DO NOTHING",
    "INSERT INTO ddmrp.parametro VALUES ('inv_tiendas_resta_comprometido', 0, 'Inventario de las tiendas: 0 = existencia (como el reporte de Siesa), 1 = existencia menos cantidad comprometida') ON CONFLICT DO NOTHING",
    "INSERT INTO ddmrp.parametro VALUES ('pron_meses_minimos', 3, 'Meses de venta minimos para ajustar el pronostico contra el historial; con menos, se usa el pronostico tal cual (0 = nunca)') ON CONFLICT DO NOTHING",
    "INSERT INTO ddmrp.parametro VALUES ('pron_calculado', 1, 'Forecast: 1 = se calcula del historial (bloque BI..CB del Excel); 0 = valor estatico del maestro de pronosticos') ON CONFLICT DO NOTHING",
    "INSERT INTO ddmrp.parametro VALUES ('pron_divisor', 3, 'Forecast calculado: pronostico = TOY aj + (TOG aj - TOY aj) / este numero (Excel de ejemplo: 3)') ON CONFLICT DO NOTHING",
    "INSERT INTO ddmrp.parametro VALUES ('vectorizacion_un_solo_uso', 0, 'Vectorización: 0 = se sigue sumando en cada corrida; 1 = un solo uso, se pone en 0 al marcar la fila como enviada') ON CONFLICT DO NOTHING",
    "INSERT INTO ddmrp.parametro VALUES ('inv_tiendas_resta_sin_acumular', 1, 'Inventario de las tiendas: 1 = resta las ventas del POS aun sin acumular (salida sin confirmar), como el disponible de Siesa; 0 = no') ON CONFLICT DO NOTHING",
    # CEDI por empresa: el inventario del CEDI se guarda por (empresa, item) y solo se reparte entre las tiendas de esa empresa
    "ALTER TABLE ddmrp.promocion ADD COLUMN IF NOT EXISTS aum_cota_max NUMERIC(8,4), ADD COLUMN IF NOT EXISTS aum_cota_min NUMERIC(8,4)",   # % de aumento de cota por referencia en promocion (1 = 100%); vacio = multiplicador global de Reglas
    "ALTER TABLE ddmrp.inventario_cedi ADD COLUMN IF NOT EXISTS empresa TEXT NOT NULL DEFAULT '05'",
    """DO $$ BEGIN
         IF NOT EXISTS (SELECT 1 FROM pg_index i JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)
                        WHERE i.indrelid = 'ddmrp.inventario_cedi'::regclass AND i.indisprimary AND a.attname = 'empresa') THEN
           ALTER TABLE ddmrp.inventario_cedi DROP CONSTRAINT IF EXISTS inventario_cedi_pkey;
           ALTER TABLE ddmrp.inventario_cedi ADD PRIMARY KEY (empresa, producto_id);
         END IF;
       END $$""",
    # la bitacora era unica por bodega: el mismo codigo existe en las dos empresas (Melonn), la llave es (empresa, bodega)
    "DROP INDEX IF EXISTS ddmrp.uq_bitacora_bodega",
    # la bitacora es el maestro de tiendas que se abastecen: lleva tambien su CEDI y su centro de operacion (antes tabla aparte)
    "ALTER TABLE ddmrp.abast_bitacora ADD COLUMN IF NOT EXISTS cedi TEXT",
    "ALTER TABLE ddmrp.abast_bitacora ADD COLUMN IF NOT EXISTS id_co TEXT",
    "CREATE TABLE IF NOT EXISTS ddmrp.maestro_cedi (empresa TEXT NOT NULL, bodega_id TEXT NOT NULL, descripcion TEXT, PRIMARY KEY (empresa, bodega_id))",
    # centro de operacion por (empresa, bodega): un mismo codigo de bodega (ej. MBG01 de Melonn) existe en Funat y en Stores con CO distinto
    "ALTER TABLE ddmrp.bodega_centro_operacion ADD COLUMN IF NOT EXISTS empresa TEXT",
    """UPDATE ddmrp.bodega_centro_operacion co SET empresa = COALESCE(
         (SELECT mb.empresa FROM ddmrp.maestro_bodega mb WHERE mb.bodega_id = co.bodega_id),
         (SELECT min(b.empresa) FROM ddmrp.abast_bitacora b WHERE b.bodega_id = co.bodega_id), '05') WHERE empresa IS NULL""",
    "ALTER TABLE ddmrp.bodega_centro_operacion ALTER COLUMN empresa SET NOT NULL",
    """DO $$ BEGIN
         IF NOT EXISTS (SELECT 1 FROM pg_index i JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)
                        WHERE i.indrelid = 'ddmrp.bodega_centro_operacion'::regclass AND i.indisprimary AND a.attname = 'empresa') THEN
           ALTER TABLE ddmrp.bodega_centro_operacion DROP CONSTRAINT IF EXISTS bodega_centro_operacion_pkey;
           ALTER TABLE ddmrp.bodega_centro_operacion ADD PRIMARY KEY (empresa, bodega_id);
         END IF;
       END $$""",
    # a que empresa(s) pertenece cada item (lo llena "Traer items"); sirve al filtro por empresa de Maestros
    "CREATE TABLE IF NOT EXISTS ddmrp.item_empresa (empresa TEXT NOT NULL, producto_id TEXT NOT NULL, PRIMARY KEY (empresa, producto_id))",
    "INSERT INTO ddmrp.item_empresa SELECT DISTINCT empresa, producto_id FROM ddmrp.sugerencias_envio WHERE NOT EXISTS (SELECT 1 FROM ddmrp.item_empresa) ON CONFLICT DO NOTHING",
    # laboratorios (categoria de maestro_item) que no se envian: no se sugieren, no compiten por el CEDI ni salen en el plano
    "CREATE TABLE IF NOT EXISTS ddmrp.laboratorio_sin_envio (laboratorio TEXT PRIMARY KEY, motivo TEXT)",
    "CREATE TABLE IF NOT EXISTS ddmrp.laboratorio (codigo TEXT PRIMARY KEY, nombre TEXT)",
    # estado de cada item en Siesa por empresa (1 activo, 0 inactivo, 2 bloqueado): solo los activos entran al modelo
    "CREATE TABLE IF NOT EXISTS ddmrp.item_estado (empresa TEXT NOT NULL, producto_id TEXT NOT NULL, estado SMALLINT NOT NULL, PRIMARY KEY (empresa, producto_id))",
    "INSERT INTO ddmrp.parametro VALUES ('ventas_todas_tiendas', 1, 'Demanda del CEDI y ventas por mes: 1 = de TODAS las tiendas de Siesa (catalogo de tiendas), esten o no en la Bitacora; 0 = solo las de la Bitacora') ON CONFLICT DO NOTHING",
    "INSERT INTO ddmrp.parametro VALUES ('solo_items_activos', 1, 'Solo los items ACTIVOS de Siesa entran al modelo (ETL, motor, matriz, controles): 1 = si, 0 = tambien inactivos y bloqueados') ON CONFLICT DO NOTHING",
    # items REC: su inventario y ventas se suman al item original (referencia sin el primer digito); origen auto = lo deduce el ETL de la descripcion
    "CREATE TABLE IF NOT EXISTS ddmrp.item_rec (empresa TEXT NOT NULL, rec_id TEXT NOT NULL, original_id TEXT NOT NULL, descripcion TEXT, origen TEXT NOT NULL DEFAULT 'manual', PRIMARY KEY (empresa, rec_id))",
    "INSERT INTO ddmrp.parametro VALUES ('rec_suma_original', 1, 'Items REC (descripcion que empieza por REC): 1 = su inventario y ventas se suman al item original para el calculo y el despacho, 0 = se calculan aparte') ON CONFLICT DO NOTHING",
    """CREATE OR REPLACE VIEW ddmrp.v_item_rec AS
       SELECT empresa, rec_id, original_id FROM ddmrp.item_rec
       WHERE COALESCE((SELECT max(valor) FROM ddmrp.parametro WHERE clave = 'rec_suma_original'), 1) <> 0""",
    # lanzamientos: primera existencia y reingresos al CEDI, detectados por el ETL (historia propia; la primera lectura es la linea base)
    "CREATE TABLE IF NOT EXISTS ddmrp.cedi_estado (empresa TEXT NOT NULL, producto_id TEXT NOT NULL, existencia NUMERIC(14,3) NOT NULL DEFAULT 0, visto_desde DATE NOT NULL, ultima_con_stock DATE, PRIMARY KEY (empresa, producto_id))",
    """CREATE TABLE IF NOT EXISTS ddmrp.cedi_evento (
         id BIGSERIAL PRIMARY KEY, empresa TEXT NOT NULL, producto_id TEXT NOT NULL, fecha DATE NOT NULL,
         tipo TEXT NOT NULL CHECK (tipo IN ('PRIMERA','REINGRESO')), dias_sin_stock INT, existencia NUMERIC(14,3) NOT NULL,
         UNIQUE (empresa, producto_id, fecha))""",
    "CREATE INDEX IF NOT EXISTS idx_cedi_evento_fecha ON ddmrp.cedi_evento (fecha, empresa)",
    "CREATE TABLE IF NOT EXISTS ddmrp.cedi_base (empresa TEXT PRIMARY KEY, fecha DATE NOT NULL)",
    # venta neta SIN IVA del mes (la trae el ETL con la cantidad); base de la clasificacion ABC por margen. 0 = aun no traida / carga manual
    "ALTER TABLE ddmrp.ventas_mensual ADD COLUMN IF NOT EXISTS valor NUMERIC(18,2) NOT NULL DEFAULT 0",
    "ALTER TABLE ddmrp.maestro_bodega ADD COLUMN IF NOT EXISTS descripcion TEXT",
    # cotas como fraccion (0.125 = 12,5%): 4 decimales en vez de 2
    """DO $$ BEGIN
         IF (SELECT numeric_scale FROM information_schema.columns WHERE table_schema='ddmrp'
             AND table_name='abast_control_referencias' AND column_name='cota_maxima') = 2 THEN
           ALTER TABLE ddmrp.abast_control_referencias
             ALTER COLUMN cota_maxima TYPE NUMERIC(12,4), ALTER COLUMN cota_minima TYPE NUMERIC(12,4);
         END IF; END $$""",
    """CREATE TABLE IF NOT EXISTS ddmrp.bitacora (
         id        BIGSERIAL PRIMARY KEY,
         tipo      TEXT NOT NULL,
         origen    TEXT NOT NULL DEFAULT 'manual' CHECK (origen IN ('manual','auto')),
         usuario   TEXT,
         inicio    TIMESTAMPTZ NOT NULL DEFAULT now(),
         fin       TIMESTAMPTZ,
         estado    TEXT NOT NULL DEFAULT 'corriendo' CHECK (estado IN ('corriendo','ok','error','interrumpido')),
         mensaje   TEXT,
         resumen   JSONB,
         padre_id  BIGINT)""",
    "CREATE INDEX IF NOT EXISTS idx_bitacora_inicio ON ddmrp.bitacora (inicio DESC)",
    "CREATE INDEX IF NOT EXISTS idx_bitacora_tipo ON ddmrp.bitacora (tipo, inicio DESC)",
    """CREATE TABLE IF NOT EXISTS ddmrp.perfil (
         perfil_id   TEXT PRIMARY KEY,
         nombre      TEXT NOT NULL,
         descripcion TEXT,
         nivel       TEXT NOT NULL DEFAULT 'lectura' CHECK (nivel IN ('lectura','edicion','aprobacion')),
         permisos    TEXT[] NOT NULL DEFAULT '{}',
         sistema     BOOLEAN NOT NULL DEFAULT FALSE)""",
    """CREATE TABLE IF NOT EXISTS ddmrp.inventario_mes (   -- resumen mensual de la foto diaria (buffer_historia): base del inventario promedio / GMROI
         mes TEXT NOT NULL, empresa TEXT NOT NULL, bodega_id TEXT NOT NULL, producto_id TEXT NOT NULL,
         inv_suma REAL NOT NULL, dias INT NOT NULL, dias_cero INT NOT NULL,
         PRIMARY KEY (empresa, bodega_id, producto_id, mes))""",
    "CREATE INDEX IF NOT EXISTS idx_invmes_mes ON ddmrp.inventario_mes (mes)",
    """CREATE TABLE IF NOT EXISTS ddmrp.vista_guardada (
         usuario_id  TEXT NOT NULL,
         informe     TEXT NOT NULL,
         nombre      TEXT NOT NULL,
         config      JSONB NOT NULL,
         compartida  BOOLEAN NOT NULL DEFAULT FALSE,
         actualizado TIMESTAMPTZ NOT NULL DEFAULT now(),
         PRIMARY KEY (usuario_id, informe, nombre))""",
    """CREATE TABLE IF NOT EXISTS ddmrp.usuario (
         usuario_id  TEXT PRIMARY KEY,
         nombre      TEXT,
         perfil_id   TEXT REFERENCES ddmrp.perfil(perfil_id),
         activo      BOOLEAN NOT NULL DEFAULT TRUE,
         bodegas     TEXT[] NOT NULL DEFAULT '{}',
         categorias  TEXT[] NOT NULL DEFAULT '{}',
         actualizado TIMESTAMPTZ NOT NULL DEFAULT now())""",
    "ALTER TABLE ddmrp.usuario ADD COLUMN IF NOT EXISTS email TEXT",   # correo del usuario: viaja con sus OC al BPM (avisos de OC creada, rechazada, fallas de Siesa)
    "ALTER TABLE ddmrp.usuario ADD COLUMN IF NOT EXISTS empresas TEXT[] NOT NULL DEFAULT '{}'",   # empresas que puede ver (05 Funat, 21 Stores); vacio = ambas
    """INSERT INTO ddmrp.perfil (perfil_id, nombre, descripcion, nivel, permisos, sistema) VALUES
         ('administrador', 'Administrador', 'Todo, incluido administrar usuarios', 'aprobacion', '{admin}', true),
         ('abastecimiento', 'Abastecimiento', 'Analiza el buffer, aprueba y descarga los planos', 'aprobacion',
            '{ver_control,ver_alertas,ver_despacho,aprobar_despacho,descargar_planos,ver_maestros,ver_auditoria}', true),
         ('maestros', 'Cargador de maestros', 'Carga y corrige maestros y reglas', 'edicion',
            '{ver_control,ver_alertas,ver_maestros,cargar_maestros,editar_reglas}', true),
         ('operador', 'Operador del motor', 'Corre ETL y motor, trae tiendas e items de Siesa', 'lectura',
            '{ver_control,ver_alertas,ver_maestros,correr_motor,sincronizar_siesa,ver_log}', true),
         ('logistica', 'Logistica (planos)', 'Ve la matriz y descarga los planos', 'aprobacion',
            '{ver_control,ver_alertas,ver_despacho,descargar_planos}', true),
         ('consulta', 'Consulta', 'Solo ve el control y las alertas', 'lectura', '{ver_control,ver_alertas}', true)
       ON CONFLICT (perfil_id) DO NOTHING""",
    # usuarios que ya tenian filas en rbac_asignacion: se registran con un perfil equivalente (no se tocan sus filas)
    """INSERT INTO ddmrp.usuario (usuario_id, nombre, perfil_id)
       SELECT r.usuario_id, r.usuario_id,
              CASE WHEN bool_or(r.es_admin) THEN 'administrador'
                   WHEN bool_or(r.nivel::text = 'aprobacion') THEN 'abastecimiento'
                   WHEN bool_or(r.nivel::text = 'edicion') THEN 'maestros' ELSE 'consulta' END
       FROM ddmrp.rbac_asignacion r GROUP BY r.usuario_id
       ON CONFLICT (usuario_id) DO NOTHING""",
]

# Tablas con empresa en la llave (y el resto de la llave): una carga vieja pudo guardar "Funat"/"Stores" en vez de 05/21
EMPRESA_EN_TABLAS = {
    "abast_bitacora": ["bodega_id"], "abast_control_referencias": ["bodega_id", "producto_id"],
    "abast_unidad_despacho": ["producto_id"], "abast_vectorizacion": ["bodega_id", "producto_id"],
    "pronostico": ["bodega_id", "producto_id"], "promocion": ["producto_id"], "maestro_bodega": [],
}
ALIAS = {"05": ("funat",), "21": ("stores", "store", "tiendas")}


def normalizar_empresas(c) -> int:
    """Convierte 'Funat'/'Stores' en 05/21. Si ya existe la fila con el codigo correcto, esa gana y la mala se borra."""
    n = 0
    for tabla, llave in EMPRESA_EN_TABLAS.items():
        for cod, nombres in ALIAS.items():
            mal = "lower(trim(t.empresa)) = ANY(:n)"
            dup = " AND ".join(f"x.{k} = t.{k}" for k in llave) if llave else "FALSE"
            if llave:
                c.execute(text(f"DELETE FROM ddmrp.{tabla} t WHERE {mal} AND EXISTS (SELECT 1 FROM ddmrp.{tabla} x WHERE x.empresa = :c AND {dup})"),
                          {"n": list(nombres), "c": cod})
            r = c.execute(text(f"UPDATE ddmrp.{tabla} t SET empresa = :c WHERE {mal}"), {"n": list(nombres), "c": cod})
            n += r.rowcount or 0
    return n


# Llave con empresa: el mismo codigo de bodega existe en Funat (05) y en Stores (21) (Melonn: MBG01...), asi que NINGUNA tabla por tienda
# puede identificar la fila solo por la bodega. tabla -> llave nueva
LLAVE_CON_EMPRESA = {
    "maestro_bodega": ("empresa", "bodega_id"),
    "inventario_actual": ("empresa", "producto_id", "bodega_id"),
    "transitos": ("empresa", "producto_id", "bodega_id", "documento"),
    "demanda_calificada": ("empresa", "producto_id", "bodega_id"),
    "item_condenado": ("empresa", "producto_id", "bodega_id"),
    "bodega_dia": ("empresa", "bodega_id", "dia"),
    "ventas_mensual": ("empresa", "mes", "bodega_id", "producto_id"),
    "buffer_historia": ("fecha", "empresa", "bodega_id", "producto_id"),
    "sugerencias_envio": ("ejecucion_id", "empresa", "bodega_id", "producto_id"),
}


def empresa_en_llaves() -> None:
    """Migracion idempotente: agrega la columna empresa (deducida de la tienda) y la mete en la llave primaria de cada tabla por tienda."""
    for tabla, llave in LLAVE_CON_EMPRESA.items():
        try:
            with pg.begin() as c:
                if not c.execute(text("SELECT to_regclass(:t)"), {"t": f"ddmrp.{tabla}"}).scalar():
                    continue
                en_pk = c.execute(text("""SELECT count(*) FROM pg_index i JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)
                                          WHERE i.indrelid = CAST(:t AS regclass) AND i.indisprimary AND a.attname = 'empresa'"""), {"t": f"ddmrp.{tabla}"}).scalar()
                if en_pk:
                    continue
                c.execute(text(f"ALTER TABLE ddmrp.{tabla} ADD COLUMN IF NOT EXISTS empresa TEXT"))
                if tabla != "maestro_bodega":   # el maestro de bodegas ya tenia empresa
                    c.execute(text(f"""UPDATE ddmrp.{tabla} t SET empresa = COALESCE(
                          (SELECT mb.empresa FROM ddmrp.maestro_bodega mb WHERE mb.bodega_id = t.bodega_id LIMIT 1),
                          (SELECT min(b.empresa) FROM ddmrp.abast_bitacora b WHERE b.bodega_id = t.bodega_id), '05') WHERE t.empresa IS NULL"""))
                if tabla == "item_condenado":   # '*' = todas las tiendas: ahora una fila por empresa
                    c.execute(text("""INSERT INTO ddmrp.item_condenado (empresa, producto_id, bodega_id, motivo)
                                      SELECT e.e, t.producto_id, t.bodega_id, t.motivo FROM ddmrp.item_condenado t, (VALUES ('05'), ('21')) e(e)
                                      WHERE t.bodega_id = '*' ON CONFLICT DO NOTHING"""))
                c.execute(text(f"ALTER TABLE ddmrp.{tabla} ALTER COLUMN empresa SET NOT NULL"))
                pk = c.execute(text("SELECT conname FROM pg_constraint WHERE conrelid = CAST(:t AS regclass) AND contype = 'p'"), {"t": f"ddmrp.{tabla}"}).scalar()
                if pk:
                    c.execute(text(f'ALTER TABLE ddmrp.{tabla} DROP CONSTRAINT "{pk}"'))
                c.execute(text(f"ALTER TABLE ddmrp.{tabla} ADD PRIMARY KEY ({', '.join(llave)})"))
                log.warning("Llave con empresa aplicada a %s", tabla)
        except Exception:
            log.exception("No se pudo meter la empresa en la llave de %s", tabla)


COLS_SUG = ("ejecucion_id, fecha_calculo, empresa, bodega_id, producto_id, adu, iv, forecast, lead_time, frecuencia, unidad_despacho, zrb, zrs, za, zv, "
            "tor, toy, tog, toy_aj, tog_aj, inventario, en_transito, demanda_calificada, flujo_neto, pct_buffer, zona, vectorizacion, cantidad_sugerida, "
            "condenado, cantidad_necesaria, stock_cedi, regla_objetivo, estado, cantidad_aprobada")

# El CEDI como fila del buffer (modo «Ver solo CEDI» de los Informes). Va aparte del bloque principal y cada sentencia en su propia transaccion:
# si algo falla aqui no se pierde el resto del esquema.
SENTENCIAS_CEDI = [
    # buffer del CEDI: mismas columnas que las de las tiendas, pero en otra tabla para que el despacho, el reparto y los planos NUNCA lo vean
    "CREATE TABLE IF NOT EXISTS ddmrp.sugerencias_cedi (LIKE ddmrp.sugerencias_envio INCLUDING DEFAULTS)",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_sug_cedi ON ddmrp.sugerencias_cedi (ejecucion_id, empresa, bodega_id, producto_id)",
    # lead time del abastecimiento al CEDI (dias): una fila por item o producto_id = '*' para el general de la empresa. Por ahora 30 dias para todo
    # (comprado o maquilado; la produccion propia no se modela): luego se afina por proveedor / item en este maestro.
    "CREATE TABLE IF NOT EXISTS ddmrp.abast_leadtime_cedi (empresa TEXT NOT NULL, producto_id TEXT NOT NULL DEFAULT '*', "
    "leadtime NUMERIC(8,2) NOT NULL CHECK (leadtime >= 0), PRIMARY KEY (empresa, producto_id))",
    "INSERT INTO ddmrp.abast_leadtime_cedi (empresa, producto_id, leadtime) SELECT e, '*', 8 FROM (VALUES ('05'), ('21')) v(e) ON CONFLICT DO NOTHING",
    "INSERT INTO ddmrp.parametro VALUES ('oc_dias_historia', 365, 'Antiguedad maxima (dias) de las ordenes de compra abiertas que cuentan como transito: una OC vieja sin cerrar en Siesa no debe inflar el flujo neto') ON CONFLICT DO NOTHING",
    "INSERT INTO ddmrp.parametro VALUES ('rit_abiertas_transito', 1, 'Requisiciones RIT (abastecimiento) aun no despachadas: 1 = su saldo (requerido - despachado) cuenta como transito hacia la tienda; 0 = solo cuentan los traslados ya despachados') ON CONFLICT DO NOTHING",
    "INSERT INTO ddmrp.parametro VALUES ('rit_incluir_aprobadas', 0, 'Requisiciones RIT: 1 = tambien cuentan como transito las lineas APROBADAS (el CEDI aun no las compromete, pueden no salir); 0 = solo las COMPROMETIDAS (ya reservadas para despachar)') ON CONFLICT DO NOTHING",
    "INSERT INTO ddmrp.parametro VALUES ('rit_alerta_dias', 15, 'Alerta en el item (columna y fila resaltada) cuando tiene una requisicion RIT COMPROMETIDA hace mas de estos dias sin despacharse (las Aprobadas no alertan)') ON CONFLICT DO NOTHING",
    "ALTER TABLE ddmrp.transitos ADD COLUMN IF NOT EXISTS fecha_oc DATE",
    "ALTER TABLE ddmrp.transitos ADD COLUMN IF NOT EXISTS fecha_esperada DATE",
    "CREATE TABLE IF NOT EXISTS ddmrp.rit_alerta (empresa TEXT NOT NULL, producto_id TEXT NOT NULL, bodega_id TEXT NOT NULL, documento TEXT NOT NULL, fecha DATE NOT NULL, "
    "saldo NUMERIC(14,4) NOT NULL DEFAULT 0, estado SMALLINT NOT NULL DEFAULT 1, PRIMARY KEY (empresa, producto_id, bodega_id, documento))",
    "INSERT INTO ddmrp.parametro VALUES ('vectorizacion_en_adu', 1, 'Vectorizacion como piso del ADU: 1 = en una referencia con promocion (indicativo 1) cuyo promedio de ultimos meses + forecast es menor que la vectorizacion, el ADU parte de la vectorizacion (como la columna Promedio ADU del Excel); 0 = no') ON CONFLICT DO NOTHING",
    "INSERT INTO ddmrp.parametro VALUES ('rit_dias_historia', 30, 'Antiguedad maxima (dias) de las requisiciones RIT abiertas que cuentan como transito: una requisicion vieja sin cerrar en Siesa no debe inflar el flujo neto (0 = sin limite, hasta 365 dias)') ON CONFLICT DO NOTHING",
    # de donde sale la demanda de cada CEDI: TODAS las tiendas de la bitacora de su empresa (su venta) y el propio CEDI (venta directa mayorista / digital).
    # Un CEDI por empresa (el primero del maestro), igual que el reparto y la matriz de despacho, que tampoco miran la columna cedi de la bitacora:
    # asi una tienda con la columna cedi vacia o distinta no deja al CEDI sin su demanda (le pasaba al CEDI de Stores: salia «sin venta»).
    # bodegas cuya venta NO pasa por el POS sino por facturas (FED/FEM/NED/CFV): de ahi lee el ETL su venta (antes la lista estaba fija en la consulta de ventas).
    # Van antes de la vista porque esta las lee. Sembrado inicial por empresa (se edita en Maestros): 05 Funat con domicilios, TC001 y Melonn; 21 Stores con Melonn
    "CREATE TABLE IF NOT EXISTS ddmrp.bodega_factura (empresa TEXT NOT NULL, bodega_id TEXT NOT NULL, nota TEXT, PRIMARY KEY (empresa, bodega_id))",
    """INSERT INTO ddmrp.bodega_factura (empresa, bodega_id, nota) VALUES
       ('05', 'DM039', 'Domicilios'), ('05', 'DM040', 'Domicilios'), ('05', 'DM140', 'Domicilios'), ('05', 'DM240', 'Domicilios'), ('05', 'DM340', 'Domicilios'),
       ('05', 'TC001', 'Tienda de confianza'), ('05', 'TC002', 'Tienda de confianza'), ('05', 'SV036', 'Vende por factura manual (FEM)'),
       ('05', 'MBG01', 'Melonn (e-commerce)'),
       ('05', 'SVM01', 'Sol Verde por factura'), ('05', 'SVS01', 'Sol Verde por factura'), ('05', 'WB001', 'Web / e-commerce'), ('05', 'CD002', 'Web / e-commerce'), ('05', 'YR001', 'Canal YR'), ('05', 'YR002', 'Canal YR'), ('05', 'YR003', 'Canal YR'), ('05', 'YR004', 'Canal YR'), ('05', 'YR005', 'Canal YR'), ('05', 'ML001', 'Canal ML'), ('05', 'FL001', 'Canal FL'), ('05', 'PT005', 'Producto terminado'), ('05', 'PT006', 'Producto terminado'), ('05', 'PT007', 'Producto terminado'), ('05', 'PT008', 'Producto terminado'), ('05', 'PT200', 'Producto terminado'), ('05', 'ZF001', 'Zona Franca'), ('05', 'ZF002', 'Zona Franca'), ('05', 'BG005', 'Bodega BG'), ('05', 'MBQ01', 'Melonn Barranquilla'), ('05', 'MCA01', 'Melonn Cali'), ('05', 'MMD01', 'Melonn Medellin'),
       ('21', 'MBG01', 'Melonn Bogota'), ('21', 'MBQ01', 'Melonn Barranquilla'), ('21', 'MCA01', 'Melonn Cali'), ('21', 'MMD01', 'Melonn Medellin')
       ON CONFLICT DO NOTHING""",
    # la primera siembra puso la misma lista en las dos empresas: se quitan de la 21 las que no son suyas (solo las que llevan la nota sembrada)
    "DELETE FROM ddmrp.bodega_factura WHERE empresa = '21' AND bodega_id IN ('DM039', 'DM040', 'DM140', 'DM240', 'DM340', 'TC001') AND nota IN ('Domicilios', 'Tienda de confianza')",
    "ALTER TABLE ddmrp.abast_bitacora ADD COLUMN IF NOT EXISTS activa SMALLINT DEFAULT 1 CHECK (activa IS NULL OR activa IN (0, 1))",   # 0 = tienda apagada: no cuenta (vacio = activa)
    """CREATE OR REPLACE VIEW ddmrp.v_origen_cedi AS
       WITH cedis AS (SELECT empresa, min(bodega_id) AS bodega_id FROM ddmrp.maestro_cedi GROUP BY empresa)
       SELECT b.empresa, c.bodega_id AS cedi, b.bodega_id AS origen FROM ddmrp.abast_bitacora b JOIN cedis c ON c.empresa = b.empresa WHERE COALESCE(b.activa, 1) = 1
       UNION
       SELECT empresa, bodega_id AS cedi, bodega_id AS origen FROM cedis
       UNION
       -- regla ventas_todas_tiendas: tambien las tiendas del catalogo de Siesa (maestro_bodega) aunque no esten en la bitacora (su venta suma a la demanda del CEDI)
       SELECT mb.empresa, c.bodega_id AS cedi, mb.bodega_id AS origen FROM ddmrp.maestro_bodega mb JOIN cedis c ON c.empresa = mb.empresa
       WHERE COALESCE((SELECT valor FROM ddmrp.parametro WHERE clave = 'ventas_todas_tiendas'), 1) >= 1
         AND NOT EXISTS (SELECT 1 FROM ddmrp.maestro_cedi mc WHERE mc.empresa = mb.empresa AND mc.bodega_id = mb.bodega_id)
         AND NOT EXISTS (SELECT 1 FROM ddmrp.abast_bitacora bx WHERE bx.empresa = mb.empresa AND bx.bodega_id = mb.bodega_id AND COALESCE(bx.activa, 1) = 0)
       UNION
       -- las bodegas que venden por factura (maestro «Bodegas que venden por factura») cuentan siempre, esten o no en la bitacora, salvo que la bitacora las apague
       SELECT bf.empresa, c.bodega_id AS cedi, bf.bodega_id AS origen FROM ddmrp.bodega_factura bf JOIN cedis c ON c.empresa = bf.empresa
       WHERE NOT EXISTS (SELECT 1 FROM ddmrp.maestro_cedi mc WHERE mc.empresa = bf.empresa AND mc.bodega_id = bf.bodega_id)
         AND NOT EXISTS (SELECT 1 FROM ddmrp.abast_bitacora bx WHERE bx.empresa = bf.empresa AND bx.bodega_id = bf.bodega_id AND COALESCE(bx.activa, 1) = 0)""",
    # lo que leen los Informes: tiendas + CEDI. Cual de los dos se ve lo decide app/modo.py (por defecto solo tiendas)
    f"""CREATE OR REPLACE VIEW ddmrp.v_sugerencias_informe AS
        SELECT {COLS_SUG} FROM ddmrp.sugerencias_envio UNION ALL SELECT {COLS_SUG} FROM ddmrp.sugerencias_cedi""",
]


# La bitacora es la fuente de verdad de las tiendas y de sus nombres. maestro_bodega (catalogo que usan los demas joins: filtros, permisos, nombres en pantalla)
# solo la refleja: un trigger copia el nombre de la bitacora cada vez que se escribe, y el ETL de Siesa ya no pisa un nombre que la bitacora tenga.
SENTENCIAS_BITACORA = [
    "ALTER TABLE ddmrp.abast_bitacora ADD COLUMN IF NOT EXISTS descripcion TEXT",
    # una sola vez de hecho: solo llena los nombres que falten con el que ya tenia el catalogo (Siesa)
    """UPDATE ddmrp.abast_bitacora b SET descripcion = mb.descripcion FROM ddmrp.maestro_bodega mb
       WHERE mb.empresa = b.empresa AND mb.bodega_id = b.bodega_id AND (b.descripcion IS NULL OR btrim(b.descripcion) = '')
         AND mb.descripcion IS NOT NULL AND btrim(mb.descripcion) <> ''""",
    """CREATE OR REPLACE FUNCTION ddmrp.fn_bitacora_nombre() RETURNS trigger AS $$
       BEGIN
         INSERT INTO ddmrp.maestro_bodega (bodega_id, empresa, descripcion)
         VALUES (NEW.bodega_id, NEW.empresa, NULLIF(btrim(NEW.descripcion), ''))
         ON CONFLICT (empresa, bodega_id) DO UPDATE
           SET descripcion = COALESCE(NULLIF(btrim(NEW.descripcion), ''), ddmrp.maestro_bodega.descripcion);
         RETURN NEW;
       END
       $$ LANGUAGE plpgsql""",
    """INSERT INTO ddmrp.perfil (perfil_id, nombre, descripcion, nivel, permisos, sistema) VALUES
         ('compras', 'Compras', 'Ve el CEDI (necesidades, sobrestock, clasificacion) y administra los maestros de compras', 'edicion',
          '{ver_control,ver_alertas,ver_control_compras,ver_compras,cargar_maestros_compras,gestionar_compras}', true)
       ON CONFLICT (perfil_id) DO NOTHING""",
    "DROP TRIGGER IF EXISTS trg_bitacora_nombre ON ddmrp.abast_bitacora",
    "CREATE TRIGGER trg_bitacora_nombre AFTER INSERT OR UPDATE OF descripcion ON ddmrp.abast_bitacora FOR EACH ROW EXECUTE FUNCTION ddmrp.fn_bitacora_nombre()",
]


# Compras: proveedores (se completan con lo que llega de Siesa y compras agrega lead time, correos...) y datos de compra de cada item.
SENTENCIAS_COMPRAS = [
    """CREATE TABLE IF NOT EXISTS ddmrp.proveedor (
         empresa TEXT NOT NULL, proveedor_id TEXT NOT NULL, sucursal TEXT NOT NULL DEFAULT '001',   -- proveedor_id = NIT (f200_id del tercero en Siesa)
         nombre TEXT, leadtime NUMERIC(8,2) CHECK (leadtime IS NULL OR leadtime >= 0),                -- dias; vacio = se usa el general del CEDI
         email_para TEXT, email_cc TEXT,                                                              -- varios correos separados por ;
         activo SMALLINT DEFAULT 1 CHECK (activo IN (0, 1)),                                           -- vacio se trata como activo
         pedido_minimo NUMERIC(16,2) CHECK (pedido_minimo IS NULL OR pedido_minimo >= 0),            -- valor minimo de una OC a este proveedor
         contacto TEXT, telefono TEXT, notas TEXT, origen TEXT NOT NULL DEFAULT 'manual',            -- origen: siesa (llego del maestro de items) o manual
         PRIMARY KEY (empresa, proveedor_id, sucursal))""",
    """CREATE TABLE IF NOT EXISTS ddmrp.item_compra (
         empresa TEXT NOT NULL, producto_id TEXT NOT NULL,
         proveedor_id TEXT, sucursal TEXT,                                          -- los pone el ETL desde el item de Siesa (un solo proveedor por item)
         cotizacion NUMERIC(16,4) CHECK (cotizacion IS NULL OR cotizacion >= 0),    -- costo de la cotizacion vigente (se carga a mano o por Excel)
         unidad_pedido NUMERIC(12,2) DEFAULT 1 CHECK (unidad_pedido IS NULL OR unidad_pedido > 0),     -- multiplo en que se pide al proveedor
         unidad_empaque NUMERIC(12,2) DEFAULT 1 CHECK (unidad_empaque IS NULL OR unidad_empaque > 0),  -- unidades por caja / empaque
         PRIMARY KEY (empresa, producto_id))""",
    "INSERT INTO ddmrp.item_compra (empresa, producto_id) SELECT empresa, producto_id FROM ddmrp.item_empresa ON CONFLICT DO NOTHING",
    # de Siesa (el ETL los reescribe): costo de la cotizacion vigente del proveedor del item (costo bruto, con el descuento del primer rango de cantidad) y
    # tarifa de IVA del grupo impositivo del item. La columna «cotizacion» queda para que compras fije un costo a mano (pisa el de Siesa).
    "ALTER TABLE ddmrp.item_compra ADD COLUMN IF NOT EXISTS cotizacion_siesa NUMERIC(16,4)",
    "ALTER TABLE ddmrp.item_compra ADD COLUMN IF NOT EXISTS cotizacion_fecha DATE",
    "ALTER TABLE ddmrp.item_compra ADD COLUMN IF NOT EXISTS iva_tasa NUMERIC(8,4)",
    # ultimo costo de compra del item (precio de la ultima OC aprobada / parcial / cumplida): costo de respaldo cuando no hay cotizacion
    "ALTER TABLE ddmrp.item_compra ADD COLUMN IF NOT EXISTS ultimo_costo NUMERIC(16,4)",
    "ALTER TABLE ddmrp.item_compra ADD COLUMN IF NOT EXISTS ultimo_costo_fecha DATE",
    "ALTER TABLE ddmrp.item_compra ADD COLUMN IF NOT EXISTS ultimo_costo_nit TEXT",
    # condicion de pago de las OC a este proveedor (f420_id_cond_pago, ej. C30): la pone compras; el ETL solo la pre-llena con la de la ultima OC del proveedor en Siesa
    "ALTER TABLE ddmrp.proveedor ADD COLUMN IF NOT EXISTS cond_pago TEXT",
    # cada cuantos dias se le compra a este proveedor: define el tamaño de la zona verde del CEDI (vacio = el general de compras_config, 15 dias)
    "ALTER TABLE ddmrp.proveedor ADD COLUMN IF NOT EXISTS frecuencia NUMERIC(8,2) CHECK (frecuencia IS NULL OR frecuencia > 0)",
    # cantidad minima de compra del item en unidades (MOQ): si el pedido queda por debajo se sube a este minimo (al multiplo de pedido)
    "ALTER TABLE ddmrp.item_compra ADD COLUMN IF NOT EXISTS moq NUMERIC(14,3) DEFAULT 1 CHECK (moq IS NULL OR moq >= 1)",
    # como se redondea la cantidad al multiplo de pedido de ese proveedor: arriba (por defecto), cercano o abajo
    "ALTER TABLE ddmrp.proveedor ADD COLUMN IF NOT EXISTS redondeo TEXT CHECK (redondeo IS NULL OR redondeo IN ('arriba', 'cercano', 'abajo'))",
    # pedir tambien en zona verde (1 = si, 0 = no, vacio = la regla general pedir_en_verde) y colchon (multiplica la zona roja del CEDI; vacio/1 = sin cambio) por proveedor
    "ALTER TABLE ddmrp.proveedor ADD COLUMN IF NOT EXISTS pedir_verde SMALLINT CHECK (pedir_verde IS NULL OR pedir_verde IN (0, 1))",
    "ALTER TABLE ddmrp.proveedor ADD COLUMN IF NOT EXISTS factor_tor NUMERIC(6,2) CHECK (factor_tor IS NULL OR factor_tor >= 1)",
    # configuracion general de compras (valor vacio = el defecto)
    """CREATE TABLE IF NOT EXISTS ddmrp.compras_config (clave TEXT PRIMARY KEY, valor NUMERIC, detalle TEXT)""",
    """INSERT INTO ddmrp.compras_config (clave, valor, detalle) VALUES
         ('pedido_minimo_bloquea', 0, 'Proveedores bajo su pedido minimo: 0 = se muestran con alerta (no se bloquean); 1 = se bloquean y no se muestran'),
         ('poca_historia_meses', 3, 'Un item con menos de estos meses con venta (ultimos 12) se marca «poca historia»: solo es una alerta, no bloquea'),
         ('frecuencia_defecto', 15, 'Frecuencia de compra (dias) de los proveedores que no tienen la suya: cada cuanto se les compra; define el tamaño de la zona verde del CEDI'),
         ('oc_umbral_total', 0, 'OC: total (con IVA, en pesos) hasta el cual una OC SIN desvios se crea sin revision en el BPM. 0 = toda OC pasa por revision'),
         ('oc_desvio_cant_pct', 30, 'OC: una linea pasa a revision si la cantidad se aparta mas de este % de la cantidad calculada (sugerida)'),
         ('oc_desvio_cant_min', 15, 'OC: la regla de cantidad solo se evalua si la cantidad calculada (sugerida) supera estas unidades (asi 1 por 2 no dispara revision)'),
         ('oc_desvio_costo_pct', 30, 'OC: una linea pasa a revision si el costo editado sube mas de este % frente a la cotizacion (manual › Siesa › ultima compra)'),
         ('oc_exigir_entiendo', 1, 'OC: 1 = para enviar una OC hay que marcar la casilla «Entiendo que se envia al BPM»; 0 = no se pide esa confirmacion'),
         ('oc_listado_dias', 30, 'OC enviadas: dias hacia atras que muestra por defecto el listado (se puede cambiar con los filtros de la pantalla)'),
         ('oc_email_proveedor', 0, 'OC: 1 = el correo de fin de proceso del BPM le llega al proveedor (a sus correos del maestro); 0 = no se envia nada al proveedor (pruebas)'),
         ('oc_exigir_email', 0, 'OC: 1 = no se puede montar la OC de un proveedor sin correo (email_para) en el maestro de proveedores; 0 = se monta igual'),
         ('tablero_dias_trabada', 2, 'Tablero de compras: una OC sin cerrar (borrador, enviando, incierta, error o en BPM) mas de estos dias aparece como trabada'),
         ('tablero_leadtime_defecto', 30, 'Tablero de compras: lead time (dias) para decidir si una OC ya debio llegar, cuando el proveedor no tiene el suyo'),
         ('tablero_dias_cumplimiento', 30, 'Tablero de compras: dias hacia atras del bloque de cumplimiento del proceso'),
         ('tablero_cache_horas', 6, 'Tablero de compras: horas que se guarda el bloque «Que pedir hoy» (es lo lento: recalcula todas las necesidades) por usuario; 0 = sin cache. El boton Actualizar lo recalcula'),
         ('tablero_top', 30, 'Tablero de compras: cuantas filas muestra cada lista'),
         ('transito_ignorar_dias', 30, 'Buffer del CEDI: las OC con mas de estos dias de atraso frente a su fecha esperada NO cuentan como transito (casi siempre son saldos que no llegan). 0 = contar todas'),
         ('pedir_en_verde', 0, 'Buffer del CEDI: 1 = tambien se pide cuando el flujo neto esta en zona verde (hasta el tope verde); 0 = solo en amarillo/rojo. Cada proveedor puede tener el suyo')
       ON CONFLICT DO NOTHING""",
    # el lead time general pasa de 30 a 8 dias (una sola vez: lo que se cambie despues no se pisa)
    "CREATE TABLE IF NOT EXISTS ddmrp.migracion_marca (clave TEXT PRIMARY KEY, fecha TIMESTAMPTZ NOT NULL DEFAULT now())",
    """DO $$ BEGIN
         IF NOT EXISTS (SELECT 1 FROM ddmrp.migracion_marca WHERE clave = 'leadtime_general_8') THEN
           UPDATE ddmrp.abast_leadtime_cedi SET leadtime = 8 WHERE producto_id = '*' AND leadtime = 30;
           INSERT INTO ddmrp.migracion_marca (clave) VALUES ('leadtime_general_8');
         END IF;
       END $$""",
    # cantidad a pedir que compras edito en «Necesidades de compra»: vive aparte del calculo, asi que sobrevive a las corridas del motor y se conserva hasta que se monte la OC
    """CREATE TABLE IF NOT EXISTS ddmrp.compras_cantidad (
         empresa TEXT NOT NULL, producto_id TEXT NOT NULL, cantidad NUMERIC(14,3) NOT NULL CHECK (cantidad >= 0), nota TEXT,
         usuario TEXT, actualizado TIMESTAMPTZ NOT NULL DEFAULT now(), PRIMARY KEY (empresa, producto_id))""",
    # costo que compras edito en «Necesidades de compra» (se compara contra la cotizacion para decidir si la OC pasa a revision); se conserva hasta que se monte la OC
    """CREATE TABLE IF NOT EXISTS ddmrp.compras_costo (
         empresa TEXT NOT NULL, producto_id TEXT NOT NULL, costo NUMERIC(18,4) NOT NULL CHECK (costo > 0),
         usuario TEXT, actualizado TIMESTAMPTZ NOT NULL DEFAULT now(), PRIMARY KEY (empresa, producto_id))""",
    "UPDATE ddmrp.compras_config SET detalle = 'OC: la regla de cantidad solo se evalua si la cantidad calculada (sugerida) supera estas unidades (asi 1 por 2 no dispara revision)' WHERE clave = 'oc_desvio_cant_min'",
    "UPDATE ddmrp.compras_config SET detalle = 'OC: una linea pasa a revision si el costo editado sube mas de este % frente a la cotizacion (manual › Siesa › ultima compra)' WHERE clave = 'oc_desvio_costo_pct'",
    # marcas de migraciones de una sola vez (p.ej. dar un permiso nuevo a un perfil de sistema que ya existia sin pisarlo despues)
    "CREATE TABLE IF NOT EXISTS ddmrp.migracion_marca (clave TEXT PRIMARY KEY, fecha TIMESTAMPTZ NOT NULL DEFAULT now())",
    """DO $$ BEGIN
         IF NOT EXISTS (SELECT 1 FROM ddmrp.migracion_marca WHERE clave = 'perfil_compras_gestionar') THEN
           UPDATE ddmrp.perfil SET permisos = array_append(permisos, 'gestionar_compras') WHERE perfil_id = 'compras' AND NOT ('gestionar_compras' = ANY(permisos));
           INSERT INTO ddmrp.migracion_marca (clave) VALUES ('perfil_compras_gestionar');
         END IF;
       END $$""",
    # informe Control compras: permiso nuevo, una sola vez a los perfiles que ya veian compras (despues cada perfil se ajusta en Usuarios)
    """DO $$ BEGIN
         IF NOT EXISTS (SELECT 1 FROM ddmrp.migracion_marca WHERE clave = 'permiso_control_compras') THEN
           UPDATE ddmrp.perfil SET permisos = array_append(permisos, 'ver_control_compras') WHERE 'ver_compras' = ANY(permisos) AND NOT ('ver_control_compras' = ANY(permisos));
           INSERT INTO ddmrp.migracion_marca (clave) VALUES ('permiso_control_compras');
         END IF;
       END $$""",
    # proveedor de compra: el de la COTIZACION vigente del item (lo que importa a compras) y, si no hay cotizacion, el del item de Siesa (respaldo). Aqui se guarda
    # el proveedor que trae el item en Siesa (informativo) y de donde salio el proveedor efectivo (proveedor_id/sucursal): 'cotizacion' o 'item'
    "ALTER TABLE ddmrp.item_compra ADD COLUMN IF NOT EXISTS activo SMALLINT DEFAULT 1 CHECK (activo IN (0, 1))",     # 0 = no se compra: sale de necesidades (vacio = activo)
    "ALTER TABLE ddmrp.item_compra ADD COLUMN IF NOT EXISTS proveedor_item TEXT",
    "ALTER TABLE ddmrp.item_compra ADD COLUMN IF NOT EXISTS sucursal_item TEXT",
    "ALTER TABLE ddmrp.item_compra ADD COLUMN IF NOT EXISTS proveedor_origen TEXT",
    # (en desuso) cotizacion vigente de OTRO proveedor (cuando la del proveedor del item no existe): sirve para revisar items cuyo proveedor en el item de Siesa no es el de la cotizacion
    "ALTER TABLE ddmrp.item_compra ADD COLUMN IF NOT EXISTS cotizacion_otro_nit TEXT",
    "ALTER TABLE ddmrp.item_compra ADD COLUMN IF NOT EXISTS cotizacion_otro_costo NUMERIC(16,4)",
    # que categorias (criterio del plan 001) se COMPRAN en cada empresa. Funat (05): terceros y maquila se compran, Productos Funat no (es produccion propia).
    # Stores (21): todo se compra. Una categoria sin fila se trata como compra.
    """CREATE TABLE IF NOT EXISTS ddmrp.categoria_compra (
         empresa TEXT NOT NULL, plan_id TEXT NOT NULL DEFAULT '001', criterio_id TEXT NOT NULL, nombre TEXT,
         se_compra SMALLINT DEFAULT 1 CHECK (se_compra IS NULL OR se_compra IN (0, 1)),   -- vacio se trata como compra
         PRIMARY KEY (empresa, plan_id, criterio_id))""",
    """INSERT INTO ddmrp.categoria_compra (empresa, plan_id, criterio_id, nombre, se_compra) VALUES
         ('05', '001', '0001', 'Productos Funat', 0), ('05', '001', '0002', 'Productos de terceros', 1), ('05', '001', '0003', 'Maquila Funat', 1),
         ('21', '001', '0001', 'Productos Funat', 1), ('21', '001', '0002', 'Productos de terceros', 1), ('21', '001', '0003', 'Maquila Funat', 1)
       ON CONFLICT DO NOTHING""",

    # Ordenes de compra que DDMRP manda a Siesa. La referencia (f420_num_docto_referencia) es la llave anti-duplicados: se arma con el id de esta tabla.
    # estado: borrador | enviando | creada | error | incierta (timeout: no se sabe si Siesa la guardo; se reconsulta por la referencia, NUNCA se reenvia a ciegas) | anulada
    """CREATE TABLE IF NOT EXISTS ddmrp.orden_compra (
         id BIGSERIAL PRIMARY KEY, empresa TEXT NOT NULL, proveedor_id TEXT NOT NULL, sucursal TEXT NOT NULL DEFAULT '001', proveedor_nombre TEXT,
         cond_pago TEXT, comprador TEXT, bodega TEXT, estado TEXT NOT NULL DEFAULT 'borrador', referencia TEXT NOT NULL,
         valor NUMERIC(18,2), iva NUMERIC(18,2), total NUMERIC(18,2), items INT, unidades NUMERIC(16,3),
         siesa_consecutivo TEXT, mensaje TEXT, plano TEXT, intentos INT NOT NULL DEFAULT 0,
         creado_por TEXT, creado TIMESTAMPTZ NOT NULL DEFAULT now(), enviado TIMESTAMPTZ, confirmado TIMESTAMPTZ)""",
    "ALTER TABLE ddmrp.orden_compra ADD COLUMN IF NOT EXISTS estado_siesa TEXT",
    "ALTER TABLE ddmrp.orden_compra ADD COLUMN IF NOT EXISTS estado_siesa_fecha TIMESTAMPTZ",
    "ALTER TABLE ddmrp.orden_compra ADD COLUMN IF NOT EXISTS bpm_id TEXT",
    "ALTER TABLE ddmrp.orden_compra ADD COLUMN IF NOT EXISTS consignacion BOOLEAN NOT NULL DEFAULT FALSE",
    "ALTER TABLE ddmrp.orden_compra ADD COLUMN IF NOT EXISTS justificacion TEXT",      # lo que compras le explica al aprobador al enviar la OC (opcional)
    "ALTER TABLE ddmrp.orden_compra ADD COLUMN IF NOT EXISTS requiere_revision BOOLEAN",
    "ALTER TABLE ddmrp.orden_compra ADD COLUMN IF NOT EXISTS motivo_revision TEXT",
    "ALTER TABLE ddmrp.orden_compra ADD COLUMN IF NOT EXISTS fecha_plano DATE",   # dia (Colombia) en que se armo el plano por ultima vez: de ahi se corren las fechas de entrega
    "ALTER TABLE ddmrp.orden_compra ADD COLUMN IF NOT EXISTS creado_por_email TEXT",   # correo de quien monto la OC (se copia al montarla)
    "ALTER TABLE ddmrp.orden_compra ADD COLUMN IF NOT EXISTS grupo TEXT",
    "ALTER TABLE ddmrp.orden_compra ADD COLUMN IF NOT EXISTS tomada_por TEXT",
    "ALTER TABLE ddmrp.orden_compra ADD COLUMN IF NOT EXISTS estado_bpm_fecha TIMESTAMPTZ",
    "CREATE UNIQUE INDEX IF NOT EXISTS orden_compra_ref ON ddmrp.orden_compra (referencia)",
    """CREATE TABLE IF NOT EXISTS ddmrp.orden_compra_linea (
         oc_id BIGINT NOT NULL REFERENCES ddmrp.orden_compra(id) ON DELETE CASCADE, nro INT NOT NULL, producto_id TEXT NOT NULL, descripcion TEXT,
         cantidad NUMERIC(16,3) NOT NULL, costo NUMERIC(16,4) NOT NULL, iva_tasa NUMERIC(6,2), origen_costo TEXT, fecha_entrega DATE, PRIMARY KEY (oc_id, nro))""",
    "ALTER TABLE ddmrp.orden_compra_linea ADD COLUMN IF NOT EXISTS cantidad_original NUMERIC(16,3)",
    "ALTER TABLE ddmrp.orden_compra_linea ADD COLUMN IF NOT EXISTS costo_original NUMERIC(16,4)",
    "ALTER TABLE ddmrp.orden_compra_linea ADD COLUMN IF NOT EXISTS cantidad_calculada NUMERIC(16,3)",   # lo que calculo el motor al montar la OC (para que el aprobador vea que cambio compras)
    "ALTER TABLE ddmrp.orden_compra_linea ADD COLUMN IF NOT EXISTS costo_calculado NUMERIC(16,4)",      # la cotizacion al montar la OC
]


# Apertura de tienda (espejo): una fila por tienda nueva con cuanto dura el espejo; el motor Rust la lee (meses_espejo) en lugar de la regla global pron_meses_minimos.
SENTENCIAS_APERTURA = [
    """CREATE TABLE IF NOT EXISTS ddmrp.apertura_tienda (
         empresa TEXT NOT NULL, bodega_id TEXT NOT NULL, espejo_bodega TEXT NOT NULL,
         factor NUMERIC(8,3) NOT NULL DEFAULT 1 CHECK (factor > 0),
         base TEXT NOT NULL DEFAULT 'venta' CHECK (base IN ('venta', 'pronostico')), base_meses INT,
         meses_espejo INT NOT NULL CHECK (meses_espejo BETWEEN 1 AND 12),
         fecha_apertura DATE, activa BOOLEAN NOT NULL DEFAULT true, items INT, unidades_mes NUMERIC(14,2),
         creado_por TEXT, creado TIMESTAMPTZ NOT NULL DEFAULT now(), actualizado_por TEXT, actualizado TIMESTAMPTZ,
         PRIMARY KEY (empresa, bodega_id))""",
    "INSERT INTO ddmrp.parametro VALUES ('apertura_meses_defecto', 4, 'Apertura de tienda: meses que dura el espejo por defecto. El motor usa el pronostico del maestro mientras la tienda tenga menos meses de venta que esto (el mes de apertura cuenta completo)') ON CONFLICT DO NOTHING",
    "INSERT INTO ddmrp.parametro VALUES ('apertura_factor_defecto', 1, 'Apertura de tienda: factor por defecto sobre la venta de la tienda espejo (1 = igual, 0.8 = 20 % menos)') ON CONFLICT DO NOTHING",
    """CREATE TABLE IF NOT EXISTS ddmrp.tienda_clase (
         empresa TEXT NOT NULL, bodega_id TEXT NOT NULL, clase_calc CHAR(1) CHECK (clase_calc IN ('A','B','C')),
         venta NUMERIC(18,2), pct_acum NUMERIC(6,2), clase_manual CHAR(1) CHECK (clase_manual IN ('A','B','C')),
         calculada TIMESTAMPTZ, PRIMARY KEY (empresa, bodega_id))""",
    "ALTER TABLE ddmrp.tienda_clase ADD COLUMN IF NOT EXISTS meses INT",
    "CREATE OR REPLACE VIEW ddmrp.v_tienda_clase AS SELECT empresa, bodega_id, COALESCE(clase_manual, clase_calc) AS clase, clase_calc, clase_manual, venta, pct_acum FROM ddmrp.tienda_clase",
    f"INSERT INTO ddmrp.compras_config (clave, valor, detalle) VALUES ('oc_destino', {2 if settings.oc_destino == 'bpm' else 1}, 'OC: a donde se envian: 0 = pausado (no se envia nada), 1 = directo a Siesa, 2 = al BPM (aprueba, crea en Siesa, PDF y correo al proveedor)') ON CONFLICT DO NOTHING",
    "INSERT INTO ddmrp.parametro VALUES ('pipeline_auto', 1, 'Corrida automatica del ETL + motor: 1 = corre sola a la hora indicada, 0 = solo cuando alguien la lance a mano') ON CONFLICT DO NOTHING",
    f"INSERT INTO ddmrp.parametro VALUES ('pipeline_hora', {int(settings.etl_cron_hour)}, 'Hora (0-23, hora de Colombia) de la corrida automatica') ON CONFLICT DO NOTHING",
    "INSERT INTO ddmrp.parametro VALUES ('pipeline_minuto', 0, 'Minuto (0-59) de la corrida automatica') ON CONFLICT DO NOTHING",
    "INSERT INTO ddmrp.parametro VALUES ('pipeline_cada_dias', 1, 'Cada cuantos dias corre sola (1 = todos los dias, 2 = un dia por medio...)') ON CONFLICT DO NOTHING",
    "INSERT INTO ddmrp.parametro VALUES ('clase_tienda_meses', 6, 'Clasificacion ABC de tiendas: meses cerrados de venta que se miden') ON CONFLICT DO NOTHING",
    "INSERT INTO ddmrp.parametro VALUES ('clase_tienda_corte_a', 80, 'Clasificacion ABC de tiendas: % acumulado de la venta que cubre la clase A') ON CONFLICT DO NOTHING",
    "INSERT INTO ddmrp.parametro VALUES ('clase_tienda_corte_b', 95, 'Clasificacion ABC de tiendas: % acumulado de la venta que cubre hasta la clase B (el resto es C)') ON CONFLICT DO NOTHING",
    "INSERT INTO ddmrp.parametro VALUES ('apertura_base_meses', 6, 'Apertura de tienda: meses cerrados de venta de la espejo que se promedian para proponer el pronostico') ON CONFLICT DO NOTHING",
]



# Reportes de compras (Ventas por producto, Proveedor / PT): historico mensual traido de Siesa por etl/reportes_compras.py. Son agregados por mes: pesan poco y
# hacen que los informes abran al instante sin golpear Siesa. Se alimentan aparte del ETL diario (boton «Actualizar datos» del informe y un refresco automatico).
SENTENCIAS_REPORTES = [
    # ventas facturadas por mes, item, canal (tipo de cliente) y unidad de negocio: bruto, descuento de linea y costo promedio (la venta neta = bruto - descuento)
    """CREATE TABLE IF NOT EXISTS ddmrp.rep_venta_mes (
         empresa TEXT NOT NULL, periodo CHAR(6) NOT NULL, producto_id TEXT NOT NULL, canal TEXT NOT NULL DEFAULT '', unidad_negocio TEXT NOT NULL DEFAULT '',
         cantidad NUMERIC(16,2) NOT NULL DEFAULT 0, valor_bruto NUMERIC(18,2) NOT NULL DEFAULT 0, descuento NUMERIC(18,2) NOT NULL DEFAULT 0, costo NUMERIC(18,2) NOT NULL DEFAULT 0,
         PRIMARY KEY (empresa, periodo, producto_id, canal, unidad_negocio))""",
    "CREATE INDEX IF NOT EXISTS idx_rep_venta_prod ON ddmrp.rep_venta_mes (empresa, producto_id, periodo)",
    # compras por mes, item y proveedor (lo que devuelve el analisis de documentos de compras de Siesa)
    """CREATE TABLE IF NOT EXISTS ddmrp.rep_compra_mes (
         empresa TEXT NOT NULL, periodo CHAR(6) NOT NULL, producto_id TEXT NOT NULL, proveedor_id TEXT NOT NULL DEFAULT '', proveedor_nombre TEXT,
         cantidad NUMERIC(16,2) NOT NULL DEFAULT 0, valor NUMERIC(18,2) NOT NULL DEFAULT 0,
         PRIMARY KEY (empresa, periodo, producto_id, proveedor_id))""",
    "CREATE INDEX IF NOT EXISTS idx_rep_compra_prod ON ddmrp.rep_compra_mes (empresa, producto_id, periodo)",
    # cumplimiento del proveedor por linea de OC (OC x item): a tiempo y completa; el periodo es el de la ultima entrada (como el OTIF de Power BI)
    """CREATE TABLE IF NOT EXISTS ddmrp.rep_otif (
         empresa TEXT NOT NULL, oc TEXT NOT NULL, producto_id TEXT NOT NULL, proveedor_id TEXT NOT NULL DEFAULT '', proveedor_nombre TEXT,
         fecha_oc DATE, fecha_pactada DATE, fecha_entrada DATE, cant_pedida NUMERIC(16,2), cant_entrada NUMERIC(16,2),
         periodo CHAR(6), a_tiempo SMALLINT, completa SMALLINT, PRIMARY KEY (empresa, oc, producto_id))""",
    "CREATE INDEX IF NOT EXISTS idx_rep_otif_prod ON ddmrp.rep_otif (empresa, producto_id, periodo)",
    # cuando y como quedo la ultima actualizacion de cada tarea (ventas / compras / otif) por empresa
    """CREATE TABLE IF NOT EXISTS ddmrp.rep_actualizacion (
         empresa TEXT NOT NULL, tarea TEXT NOT NULL, fecha TIMESTAMPTZ NOT NULL DEFAULT now(), filas INT, desde CHAR(6), mensaje TEXT, PRIMARY KEY (empresa, tarea))""",
    # reglas (editables en Config > Reglas de compras): nada de esto va en el .env
    """INSERT INTO ddmrp.compras_config (clave, valor, detalle) VALUES
         ('rep_meses_historia', 48, 'Reportes de compras: cuantos meses de historia se traen de Siesa en la carga completa'),
         ('rep_meses_refresco', 3, 'Reportes de compras: en cada actualizacion se vuelven a leer los ultimos N meses (captura documentos tardios); la primera vez se lee todo'),
         ('rep_auto', 1, 'Reportes de compras: 1 = se actualizan solos una vez al dia; 0 = solo con el boton Actualizar datos'),
         ('rep_hora', 4, 'Reportes de compras: hora (0-23, Colombia) en que corre la actualizacion automatica'),
         ('rep_minuto', 0, 'Reportes de compras: minuto (0-59) de la hora en que corre la actualizacion automatica'),
         ('rep_cada_dias', 1, 'Reportes de compras: cada cuantos dias corre la actualizacion automatica (1 = todos los dias)'),
         ('rep_recalcular_compras', 1, 'Corrida automatica de reportes: 1 = antes tambien recalcula las necesidades de compra (inventario y OC abiertas del CEDI + buffer del CEDI), sin depender del ETL del motor; 0 = solo los reportes'),
         ('rep_otif_dias_tolerancia', 0, 'OTIF: dias de gracia sobre la fecha pactada para contar una entrega como a tiempo'),
         ('rep_otif_pct_completo', 98, 'OTIF: % de lo pedido que debe haber llegado para contar la linea como completa (98 = tolera un faltante del 2 %)'),
         ('rep_otif_excluir_regularizadas', 1, 'OTIF: 1 = no cuentan las OC montadas el mismo dia (o despues) de la entrada (regularizaciones: no miden al proveedor); 0 = cuentan'),
         ('rep_plan_categoria', 1, 'Reportes de compras: plan de criterios de Siesa que es la CATEGORIA (001 = productos Funat / terceros / maquila)'),
         ('rep_plan_accion', 3, 'Reportes de compras: plan de criterios de Siesa que es la ACCION (003)')
       ON CONFLICT DO NOTHING""",
]

def esquema_cedi() -> None:
    for s in SENTENCIAS_CEDI + SENTENCIAS_BITACORA + SENTENCIAS_COMPRAS + SENTENCIAS_APERTURA + SENTENCIAS_REPORTES:
        try:
            with pg.begin() as c:
                c.execute(text(s))
        except Exception:
            log.exception("No se pudo aplicar el esquema del CEDI: %s", s[:80])


def asegurar_esquema():
    nueva = False
    try:
        with pg.connect() as c:   # la bitacora aun no tiene la columna cedi: es la primera vez con este esquema
            nueva = bool(c.execute(text("SELECT NOT EXISTS (SELECT 1 FROM information_schema.columns "
                                        "WHERE table_schema = 'ddmrp' AND table_name = 'abast_bitacora' AND column_name = 'cedi')")).scalar())
    except Exception:
        log.exception("No se pudo revisar la bitacora")
    try:
        with pg.begin() as c:
            for s in SENTENCIAS:
                c.execute(text(s))
            n = normalizar_empresas(c)
            if n:
                log.warning("Empresas corregidas (Funat/Stores -> 05/21): %s fila(s)", n)
    except Exception:
        log.exception("No se pudo actualizar el esquema")
    empresa_en_llaves()
    esquema_cedi()
    if nueva:
        cedi_y_co_iniciales()


def cedi_y_co_iniciales():
    """Una sola vez (cuando la bitacora gana las columnas cedi e id_co): el maestro de CEDIs sale de la configuracion (SIESA_CEDI_BODEGA[_S]),
    cada tienda ya en la bitacora queda con el CEDI de su empresa y toma el centro de operacion que tenia en la tabla anterior.
    Las filas de esa tabla que no estan en la bitacora no se pasan: la bitacora solo tiene lo que el usuario meta."""
    from .config import settings
    try:
        with pg.begin() as c:
            if not c.execute(text("SELECT 1 FROM ddmrp.maestro_cedi LIMIT 1")).first():
                for emp, bod in (("05", settings.siesa_cedi_bodega), ("21", settings.siesa_cedi_bodega_s)):
                    if bod and bod.strip():
                        c.execute(text("INSERT INTO ddmrp.maestro_cedi (empresa, bodega_id, descripcion) VALUES (:e, :b, 'CEDI') ON CONFLICT DO NOTHING"),
                                  {"e": emp, "b": bod.strip().upper()})
            c.execute(text("UPDATE ddmrp.abast_bitacora b SET cedi = (SELECT min(m.bodega_id) FROM ddmrp.maestro_cedi m WHERE m.empresa = b.empresa) WHERE b.cedi IS NULL"))
            c.execute(text("UPDATE ddmrp.abast_bitacora b SET id_co = co.id_co FROM ddmrp.bodega_centro_operacion co "
                           "WHERE co.empresa = b.empresa AND co.bodega_id = b.bodega_id AND b.id_co IS NULL"))
    except Exception:
        log.exception("No se pudieron sembrar los CEDIs ni los centros de operacion de la bitacora")
