"""Items activos. El estado de cada item sale de Siesa (extension del item, t121_mc_items_extensiones.f121_ind_estado, configurable con SIESA_ITEM_ESTADO_COL) y el ETL lo deja en
ddmrp.item_estado (empresa, producto_id, estado): 1 activo, 0 inactivo, 2 bloqueado. Solo los ACTIVOS entran al modelo
(ETL, motor, matriz de despacho, controles) mientras la regla 'solo_items_activos' este en Si (por defecto).
Un item sin fila en item_estado (estado desconocido, p.ej. antes del primer ETL con estado) se trata como activo."""

SOLO_ACTIVOS = "(SELECT COALESCE(max(valor), 1) FROM ddmrp.parametro WHERE clave = 'solo_items_activos')"

ESTADOS = {1: "Activo", 0: "Inactivo", 2: "Bloqueado"}


def solo_activos(a: str = "s") -> str:
    """Fragmento WHERE: deja pasar lo que NO es un item inactivo/bloqueado de su empresa. `a` = alias de la tabla con
    empresa y producto_id. Con la regla en No no filtra nada."""
    return (f"(({SOLO_ACTIVOS}) = 0 OR NOT EXISTS (SELECT 1 FROM ddmrp.item_estado ie_x "
            f"WHERE ie_x.empresa = {a}.empresa AND ie_x.producto_id = {a}.producto_id AND ie_x.estado <> 1))")
