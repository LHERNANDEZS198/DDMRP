"""Items activos. El estado de cada item sale de Siesa (extension del item, t121_mc_items_extensiones.f121_ind_estado, configurable con SIESA_ITEM_ESTADO_COL) y el ETL lo deja en
ddmrp.item_estado (empresa, producto_id, estado): 1 activo, 0 inactivo, 2 bloqueado. Solo los ACTIVOS entran al modelo
(ETL, motor, matriz de despacho, controles) mientras la regla 'solo_items_activos' este en Si (por defecto).
Un item sin fila en item_estado (estado desconocido, p.ej. antes del primer ETL con estado) se trata como activo."""

SOLO_ACTIVOS = "(SELECT COALESCE(max(valor), 1) FROM ddmrp.parametro WHERE clave = 'solo_items_activos')"

ESTADOS = {1: "Activo", 0: "Inactivo", 2: "Bloqueado"}


def en_maestro(a: str = "s") -> str:
    """Fragmento WHERE: solo items del maestro (ddmrp.maestro_item = los que pasan el filtro de criterios de Siesa) Y que existan en la base de SU empresa
    (ddmrp.item_empresa: un item de Funat no se muestra en Stores ni al reves). Lo que no esta ahi (materia prima, etc.) no sale ni se usa.
    Con el maestro vacio (antes del primer ETL) no filtra, y una empresa sin items registrados tampoco. Un item REC vale si su original esta."""
    return (f"((NOT EXISTS (SELECT 1 FROM ddmrp.maestro_item) OR EXISTS (SELECT 1 FROM ddmrp.maestro_item mi_m WHERE mi_m.producto_id = {a}.producto_id) "
            f"OR EXISTS (SELECT 1 FROM ddmrp.item_rec ir_m JOIN ddmrp.maestro_item mo_m ON mo_m.producto_id = ir_m.original_id "
            f"WHERE ir_m.empresa = {a}.empresa AND ir_m.rec_id = {a}.producto_id)) "
            f"AND (NOT EXISTS (SELECT 1 FROM ddmrp.item_empresa ie_e WHERE ie_e.empresa = {a}.empresa) "
            f"OR EXISTS (SELECT 1 FROM ddmrp.item_empresa ie_e WHERE ie_e.empresa = {a}.empresa AND ie_e.producto_id = {a}.producto_id) "
            f"OR EXISTS (SELECT 1 FROM ddmrp.item_rec ir_e JOIN ddmrp.item_empresa io_e ON io_e.empresa = ir_e.empresa AND io_e.producto_id = ir_e.original_id "
            f"WHERE ir_e.empresa = {a}.empresa AND ir_e.rec_id = {a}.producto_id)))")


def solo_activos(a: str = "s") -> str:
    """Fragmento WHERE de lo que SI entra al modelo: item del maestro (siempre) y que no sea un item inactivo/bloqueado de su empresa
    (esto ultimo con la regla en No no filtra nada). `a` = alias de la tabla con empresa y producto_id."""
    return (f"({en_maestro(a)} AND (({SOLO_ACTIVOS}) = 0 OR NOT EXISTS (SELECT 1 FROM ddmrp.item_estado ie_x "
            f"WHERE ie_x.empresa = {a}.empresa AND ie_x.producto_id = {a}.producto_id AND ie_x.estado <> 1)))")


# tablas que se llenan desde Siesa / el motor y llevan (empresa, producto_id)
TABLAS_CON_ITEM = ("ventas_mensual", "inventario_actual", "transitos", "demanda_calificada", "buffer_historia", "inventario_mes", "sugerencias_envio", "sugerencias_cedi", "cedi_evento")


def purgas_fuera_del_maestro() -> list[str]:
    """DELETEs que sacan de las tablas de datos los items que no estan en el maestro (se ejecutan con cualquier cursor/conexion)."""
    return [f"DELETE FROM ddmrp.{t} x WHERE EXISTS (SELECT 1 FROM ddmrp.maestro_item) "
            f"AND NOT {en_maestro('x')}" for t in TABLAS_CON_ITEM]
