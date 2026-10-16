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
    "CREATE TABLE IF NOT EXISTS ddmrp.inventario_cedi (producto_id TEXT PRIMARY KEY, disponible NUMERIC(14,3) NOT NULL, fecha_corte DATE NOT NULL)",
    "CREATE TABLE IF NOT EXISTS ddmrp.reserva_cedi (producto_id TEXT PRIMARY KEY, porcentaje NUMERIC(8,4) NOT NULL CHECK (porcentaje >= 0 AND porcentaje <= 1))",
    "INSERT INTO ddmrp.parametro VALUES ('cedi_regla_reparto', 1, 'Si el inventario del CEDI no alcanza: 0 no limita, 1 proporcional, 2 parejo, 3 prioridad al mas critico') ON CONFLICT DO NOTHING",
    "INSERT INTO ddmrp.parametro VALUES ('etl_traer_ventas', 0, 'El ETL tambien trae las ventas por mes de Siesa (1 = si, 0 = solo con el boton)') ON CONFLICT DO NOTHING",
    "INSERT INTO ddmrp.parametro VALUES ('retener_dias', 180, 'Dias de historia diaria del buffer que se conservan') ON CONFLICT DO NOTHING",
    "CREATE TABLE IF NOT EXISTS ddmrp.laboratorio (codigo TEXT PRIMARY KEY, nombre TEXT)",
    "ALTER TABLE ddmrp.maestro_bodega ADD COLUMN IF NOT EXISTS descripcion TEXT",
    # cotas como fraccion (0.125 = 12,5%): 4 decimales en vez de 2
    """DO $$ BEGIN
         IF (SELECT numeric_scale FROM information_schema.columns WHERE table_schema='ddmrp'
             AND table_name='abast_control_referencias' AND column_name='cota_maxima') = 2 THEN
           ALTER TABLE ddmrp.abast_control_referencias
             ALTER COLUMN cota_maxima TYPE NUMERIC(12,4), ALTER COLUMN cota_minima TYPE NUMERIC(12,4);
         END IF; END $$""",
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
            '{ver_control,ver_alertas,ver_despacho,aprobar_despacho,descargar_planos,ver_maestros}', true),
         ('maestros', 'Cargador de maestros', 'Carga y corrige maestros y reglas', 'edicion',
            '{ver_control,ver_alertas,ver_maestros,cargar_maestros,editar_reglas}', true),
         ('operador', 'Operador del motor', 'Corre ETL y motor, trae tiendas e items de Siesa', 'lectura',
            '{ver_control,ver_alertas,ver_maestros,correr_motor,sincronizar_siesa}', true),
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
