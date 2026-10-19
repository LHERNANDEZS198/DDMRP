"""Cambios de esquema idempotentes que se aplican al arrancar el backend (la base puede ser anterior al cambio)."""
import logging
from sqlalchemy import text
from .db import pg

log = logging.getLogger("esquema")

SENTENCIAS = [
    "CREATE TABLE IF NOT EXISTS ddmrp.criterio_plan (plan_id TEXT PRIMARY KEY, nombre TEXT)",
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
    """CREATE TABLE IF NOT EXISTS ddmrp.usuario (
         usuario_id  TEXT PRIMARY KEY,
         nombre      TEXT,
         perfil_id   TEXT REFERENCES ddmrp.perfil(perfil_id),
         activo      BOOLEAN NOT NULL DEFAULT TRUE,
         bodegas     TEXT[] NOT NULL DEFAULT '{}',
         categorias  TEXT[] NOT NULL DEFAULT '{}',
         actualizado TIMESTAMPTZ NOT NULL DEFAULT now())""",
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


def asegurar_esquema():
    try:
        with pg.begin() as c:
            for s in SENTENCIAS:
                c.execute(text(s))
            n = normalizar_empresas(c)
            if n:
                log.warning("Empresas corregidas (Funat/Stores -> 05/21): %s fila(s)", n)
    except Exception:
        log.exception("No se pudo actualizar el esquema")
