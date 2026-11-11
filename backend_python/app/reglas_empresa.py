"""Reglas por empresa (Funat 05 / Stores 21). La regla general vive en ddmrp.parametro y ddmrp.compras_config; lo que una empresa cambie se guarda en
parametro_empresa / compras_config_empresa y manda sobre la general. Sin empresa (None) se usa la general."""
from sqlalchemy import text

# Reglas de sistema: aplican a todo (horarios de la corrida automatica, retencion de historia, lectura de Siesa, reportes, cache del tablero).
# No se pueden cambiar por empresa; todo lo demas de Reglas de pedido y de compras si es de cada empresa.
GLOBALES_PARAM = {"pipeline_auto", "pipeline_hora", "pipeline_minuto", "pipeline_cada_dias", "pipeline_ultima_auto", "retener_dias", "meses_retencion_ventas",
                  "etl_traer_ventas", "ventas_todas_tiendas", "solo_items_activos", "rec_suma_original", "inv_tiendas_resta_comprometido",
                  "inv_tiendas_resta_sin_acumular", "rit_abiertas_transito", "rit_incluir_aprobadas", "rit_dias_historia", "rit_alerta_dias", "rep_ultima_auto",
                  "meses_historia", "oc_dias_historia"}     # los dos los lee el ETL (una sola ventana de datos para ambas empresas)
PREFIJOS_GLOBALES_COMPRAS = ("tablero_", "rep_")


def es_global_param(clave: str) -> bool:
    return clave in GLOBALES_PARAM


def es_global_compras(clave: str) -> bool:
    return clave.startswith(PREFIJOS_GLOBALES_COMPRAS)


def param(c, clave: str, empresa: str | None, defecto=None):
    """Valor de la regla de pedido para la empresa (la propia o, si no la cambio, la general)."""
    v = c.execute(text("SELECT COALESCE((SELECT valor FROM ddmrp.parametro_empresa WHERE empresa = :e AND clave = :k), (SELECT valor FROM ddmrp.parametro WHERE clave = :k))"),
                  {"e": empresa, "k": clave}).scalar()
    return defecto if v is None else v


def compras(c, clave: str, empresa: str | None, defecto=None):
    """Igual para las reglas de compras (compras_config)."""
    v = c.execute(text("SELECT COALESCE((SELECT valor FROM ddmrp.compras_config_empresa WHERE empresa = :e AND clave = :k), (SELECT valor FROM ddmrp.compras_config WHERE clave = :k))"),
                  {"e": empresa, "k": clave}).scalar()
    return defecto if v is None else v


def todas_param(c, empresa: str | None) -> dict:
    """{clave: valor} de todas las reglas de pedido vigentes para la empresa."""
    return {k: float(v) for k, v in c.execute(text(
        "SELECT p.clave, COALESCE(e.valor, p.valor) FROM ddmrp.parametro p LEFT JOIN ddmrp.parametro_empresa e ON e.clave = p.clave AND e.empresa = :e"), {"e": empresa}).all() if v is not None}


def todas_compras(c, empresa: str | None) -> dict:
    return {k: float(v) for k, v in c.execute(text(
        "SELECT p.clave, COALESCE(e.valor, p.valor) FROM ddmrp.compras_config p LEFT JOIN ddmrp.compras_config_empresa e ON e.clave = p.clave AND e.empresa = :e"),
        {"e": empresa}).all() if v is not None}
