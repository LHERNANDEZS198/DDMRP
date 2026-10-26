"""Cambios de esquema idempotentes que se aplican al arrancar el backend (la base puede ser anterior al cambio)."""
import logging
from sqlalchemy import text
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
    "INSERT INTO ddmrp.parametro VALUES ('cedi_regla_reparto', 1, 'Si el inventario del CEDI no alcanza: 0 no limita, 1 proporcional a la rotacion (ADU), 4 proporcional a la necesidad, 2 parejo, 3 prioridad al mas critico') ON CONFLICT DO NOTHING",
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
    "INSERT INTO ddmrp.parametro VALUES ('vectorizacion_un_solo_uso', 0, 'Derrame (vectorizacion): 0 = se sigue sumando en cada corrida; 1 = un solo uso, se pone en 0 al marcar la fila como enviada') ON CONFLICT DO NOTHING",
    "INSERT INTO ddmrp.parametro VALUES ('inv_tiendas_resta_sin_acumular', 1, 'Inventario de las tiendas: 1 = resta las ventas del POS aun sin acumular (salida sin confirmar), como el disponible de Siesa; 0 = no') ON CONFLICT DO NOTHING",
    # CEDI por empresa: el inventario del CEDI se guarda por (empresa, item) y solo se reparte entre las tiendas de esa empresa
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
    "INSERT INTO ddmrp.abast_leadtime_cedi (empresa, producto_id, leadtime) SELECT e, '*', 30 FROM (VALUES ('05'), ('21')) v(e) ON CONFLICT DO NOTHING",
    "INSERT INTO ddmrp.parametro VALUES ('oc_dias_historia', 365, 'Antiguedad maxima (dias) de las ordenes de compra abiertas que cuentan como transito: una OC vieja sin cerrar en Siesa no debe inflar el flujo neto') ON CONFLICT DO NOTHING",
    # de donde sale la demanda de cada CEDI: TODAS las tiendas de la bitacora de su empresa (su venta) y el propio CEDI (venta directa mayorista / digital).
    # Un CEDI por empresa (el primero del maestro), igual que el reparto y la matriz de despacho, que tampoco miran la columna cedi de la bitacora:
    # asi una tienda con la columna cedi vacia o distinta no deja al CEDI sin su demanda (le pasaba al CEDI de Stores: salia «sin venta»).
    """CREATE OR REPLACE VIEW ddmrp.v_origen_cedi AS
       WITH cedis AS (SELECT empresa, min(bodega_id) AS bodega_id FROM ddmrp.maestro_cedi GROUP BY empresa)
       SELECT b.empresa, c.bodega_id AS cedi, b.bodega_id AS origen FROM ddmrp.abast_bitacora b JOIN cedis c ON c.empresa = b.empresa
       UNION
       SELECT empresa, bodega_id AS cedi, bodega_id AS origen FROM cedis""",
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
          '{ver_control,ver_alertas,ver_compras,cargar_maestros_compras}', true)
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
]


def esquema_cedi() -> None:
    for s in SENTENCIAS_CEDI + SENTENCIAS_BITACORA + SENTENCIAS_COMPRAS:
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
