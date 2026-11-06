"""Reglas de pedido configurables desde la UI. Viven en ddmrp.parametro y las lee el motor Rust en cada corrida."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from ..db import pg
from ..security import usuario_actual, requiere
from .maestros import _puede_global

router = APIRouter(prefix="/reglas", tags=["reglas"])

SI_NO = [{"valor": 1, "label": "Si"}, {"valor": 0, "label": "No"}]
REGLAS = [
    dict(clave="regla_disparo", titulo="Cuando se pide",
         ayuda="Condicion sobre el flujo neto (inventario + transito - demanda calificada).",
         opciones=[{"valor": 1, "label": "Flujo neto <= TOY ajustado (zona amarilla o roja)"},
                   {"valor": 2, "label": "Flujo neto <= TOR (solo zona roja)"},
                   {"valor": 3, "label": "Flujo neto < TOG ajustado (cualquier faltante)"}]),
    dict(clave="regla_objetivo", titulo="Hasta donde se repone",
         ayuda="Nivel al que se lleva el flujo neto al pedir. Es la regla general: un laboratorio o un item puede tener la suya en el maestro 'Hasta donde se repone por laboratorio o item' (la del item gana sobre la del laboratorio, y esta sobre la general).",
         opciones=[{"valor": 1, "label": "TOG ajustado (tope verde)"}, {"valor": 2, "label": "TOY ajustado (tope amarillo)"},
                   {"valor": 3, "label": "Amarillo + mitad de la zona verde (TOY aj + (TOG aj − TOY aj) / 2)"}]),
    dict(clave="regla_redondeo", titulo="Redondeo a la unidad de despacho",
         ayuda="La cantidad faltante se lleva a un multiplo de la unidad de despacho.",
         opciones=[{"valor": 1, "label": "Hacia arriba"}, {"valor": 2, "label": "Al multiplo mas cercano"},
                   {"valor": 3, "label": "Hacia abajo"}]),
    dict(clave="sumar_vectorizacion", titulo="Sumar vectorizacion (derrame)",
         ayuda="Agrega las unidades de vectorizacion a lo sugerido (producto nuevo o campana).", opciones=SI_NO),
    dict(clave="vectorizacion_un_solo_uso", titulo="Derrame: un solo uso o seguir enviando",
         ayuda="Seguir enviando: el derrame del maestro se suma en cada corrida mientras exista (hay que borrarlo a mano). Un solo uso: al marcar la sugerencia como enviada (o bajar el plano marcando enviadas) el derrame de esa tienda y referencia vuelve a 0 en el maestro.",
         opciones=[{"valor": 0, "label": "Seguir enviando"}, {"valor": 1, "label": "Un solo uso (se borra al enviar)"}]),
    dict(clave="incluir_transito", titulo="Contar traslados abiertos (transito)",
         ayuda="Los traslados abiertos hacia la tienda suman al flujo neto.", opciones=SI_NO),
    dict(clave="restar_demanda_calificada", titulo="Restar demanda calificada",
         ayuda="Pedidos abiertos o picos conocidos restan del flujo neto.", opciones=SI_NO),
    dict(clave="cantidad_minima", titulo="Cantidad minima a sugerir", ayuda="Sugeridos menores a este valor se descartan (0 = sin minimo).",
         opciones=None),
    dict(clave="meses_historia", titulo="Meses de historia de ventas", ayuda="Incluye el mes en curso. 2 a 12 (Excel: 7).", opciones=None, min=2, max=12, entero=True),
    dict(clave="meses_retencion_ventas", titulo="Meses de ventas que se conservan", ayuda="Al traer las ventas por mes se borran las de meses anteriores a este tope (el informe usa como maximo 12). 13 a 120.", opciones=None, min=13, max=120, entero=True),
    dict(clave="pron_meses_minimos", titulo="Pronostico directo en casos nuevos (meses de venta minimos)",
         ayuda="Si una tienda o referencia tiene menos meses de venta que este numero y tiene pronostico cargado, el motor usa el pronostico tal cual como venta mensual esperada (junto con los meses que si vendio). Con mas meses, el pronostico se ajusta contra el historial (queda entre 1 y 2 veces el ADU de referencia). 0 = nunca: sin historial el pronostico se ignora (como en el Excel original).",
         opciones=None, min=0, max=12, entero=True),
    dict(clave="apertura_meses_defecto", titulo="Apertura de tienda: meses que dura el espejo (por defecto)",
         ayuda="En Apertura de tienda cada tienda nueva puede tener su propia duracion; este es el valor que aparece por defecto. Mientras la tienda tenga menos meses de venta que esto, el motor usa su pronostico del maestro tal cual. El mes de apertura cuenta completo aunque la tienda abra a final de mes. No puede pasar de los meses de historia.",
         opciones=None, min=1, max=12, entero=True),
    dict(clave="apertura_factor_defecto", titulo="Apertura de tienda: factor por defecto",
         ayuda="Multiplica la venta de la tienda espejo para proponer el pronostico de la tienda nueva (1 = igual que la espejo, 0.8 = 20 % menos).", opciones=None, min=0.1, max=10),
    dict(clave="apertura_base_meses", titulo="Apertura de tienda: meses de venta de la espejo que se promedian",
         ayuda="Cuantos meses cerrados de venta de la tienda espejo se promedian para proponer el pronostico (no cuenta el mes en curso ni los meses anteriores a la apertura de la espejo).",
         opciones=None, min=1, max=12, entero=True),
    dict(clave="pron_calculado", titulo="Forecast: calcularlo del historial",
         ayuda="Si: el forecast (el que entra al ADU) se calcula como en el Excel (bloque BI..CB): un ADU de referencia con las ventas de la ventana, el buffer de ese ADU y, de ahi, el pronostico ajustado a 30-60 dias de inventario. No: se usa el valor estatico del maestro de pronosticos.",
         opciones=[{"valor": 1, "label": "Si: calculado del historial (Excel)"}, {"valor": 0, "label": "No: valor del maestro de pronosticos"}]),
    dict(clave="pron_divisor", titulo="Forecast calculado: divisor entre TOY aj y TOG aj",
         ayuda="Pronostico = TOY aj + (TOG aj - TOY aj) / divisor del buffer del ADU de referencia. El Excel de ejemplo usa 3 (antes 2).", opciones=None, min=1, max=10),
    dict(clave="meses_adu", titulo="Meses que entran al ADU (+ forecast)", ayuda="1 hasta los meses de historia (Excel: 4).", opciones=None, min=1, max=12, entero=True),
    dict(clave="cedi_regla_reparto", titulo="Si el inventario del CEDI no alcanza",
         ayuda="Se aplica en cada corrida del motor, sumando la necesidad de la referencia en TODAS las tiendas. El inventario es el fresco de la bodega del CEDI (PT001) menos la reserva por item. Si la necesidad total cabe, cada tienda recibe lo que pide.",
         opciones=[{"valor": 1, "label": "Proporcional a la rotación de cada tienda (ADU): (rotación de la tienda / rotación total) × inventario del CEDI"},
                   {"valor": 4, "label": "Proporcional a lo que pide cada tienda: (necesidad de la tienda / necesidad total) × inventario del CEDI"},
                   {"valor": 2, "label": "Repartir parejo (igual a cada tienda hasta cubrir su necesidad)"},
                   {"valor": 3, "label": "Dar prioridad a la tienda mas critica (menor % de buffer)"},
                   {"valor": 5, "label": "Por clase de tienda: primero las A, luego B y C (dentro de cada clase, proporcional a la rotación)"},
                   {"valor": 0, "label": "No limitar (ignora el inventario del CEDI)"}]),
    dict(clave="clase_tienda_meses", titulo="Clase de tienda (ABC): meses de venta que se miden",
         ayuda="La clase A/B/C de cada tienda se calcula con su venta neta (sin IVA) de los ultimos meses cerrados, comparada con las demas tiendas de su empresa. Se recalcula en cada corrida del motor. En Maestros > Clase de tienda se puede fijar a mano. Sirve de desempate en el reparto del CEDI (si dos tiendas empatan, gana la mejor clase) y para la regla 'Por clase de tienda'.",
         opciones=None, min=1, max=12, entero=True),
    dict(clave="clase_tienda_corte_a", titulo="Clase de tienda (ABC): % de la venta que cubre la clase A",
         ayuda="Las tiendas que mas venden, hasta juntar este % de la venta total de la empresa, son A. La que cruza el corte queda en A.", opciones=None, min=1, max=100),
    dict(clave="clase_tienda_corte_b", titulo="Clase de tienda (ABC): % acumulado hasta la clase B",
         ayuda="Despues de las A, las tiendas que sigan hasta llegar a este % acumulado son B; el resto son C. Debe ser mayor que el corte A.", opciones=None, min=1, max=100),
    dict(clave="valor_minimo_envio", titulo="Valor mínimo del despacho a una tienda ($)",
         ayuda="Valor de lo que se envía a una tienda, a costo promedio. Si está por debajo, la Matriz de despacho no deja enviarla (ni exportar su plano). 0 = sin mínimo. Si aún no hay costos cargados no se aplica.",
         opciones=None, min=0, max=1e12),
    dict(clave="inv_tiendas_resta_comprometido", titulo="Inventario de las tiendas: restar lo comprometido",
         ayuda="No: el inventario es la existencia, como en el reporte 'Existencia a la fecha por bodega' de Siesa. Sí: existencia menos la cantidad comprometida. (El CEDI siempre descuenta lo comprometido.) Se aplica en el siguiente ETL.",
         opciones=[{"valor": 0, "label": "No: existencia (como Siesa)"}, {"valor": 1, "label": "Sí: existencia − comprometido"}]),
    dict(clave="inv_tiendas_resta_sin_acumular", titulo="Inventario de las tiendas: restar ventas sin acumular",
         ayuda="Sí: al inventario de la tienda se le restan las ventas del POS que aún no se han acumulado (salida sin confirmar), igual que el 'disponible' de Siesa; esas unidades ya salieron del estante y todavía no están en la demanda histórica. No: solo la existencia. No aplica al CEDI. Se aplica en el siguiente ETL.",
         opciones=[{"valor": 1, "label": "Sí: restar ventas sin acumular"}, {"valor": 0, "label": "No"}]),
    dict(clave="etl_traer_ventas", titulo="El ETL trae las ventas por mes de Siesa",
         ayuda="Si: cada corrida del ETL (y la nocturna) trae las ventas. No: solo con el boton 'Traer ventas por mes' de Maestros.", opciones=SI_NO),
    dict(clave="ventas_todas_tiendas", titulo="Ventas de todas las tiendas de Siesa (no solo las de la Bitácora)",
         ayuda="Sí: se traen las ventas por mes de todas las tiendas del catálogo de Siesa (Maestros > Traer tiendas de Siesa) y suman a la demanda del CEDI y a Necesidades de compra, estén o no en la Bitácora. No: solo las tiendas de la Bitácora. Las tiendas que no están en la Bitácora no tienen buffer ni envíos, solo aportan demanda al CEDI. Tras cambiarla: Traer tiendas, Traer ventas por mes y correr el motor.", opciones=SI_NO),
    dict(clave="solo_items_activos", titulo="Solo items ACTIVOS en el modelo",
         ayuda="Si: los items inactivos o bloqueados en Siesa (extension del item, f121_ind_estado) no entran al ETL, al motor, a la matriz de despacho ni a los controles. No: entran todos. Un item REC se trata como su original, aunque el REC este inactivo. Tras cambiarla corre el ETL y el motor.", opciones=SI_NO),
    dict(clave="rec_suma_original", titulo="Items REC se suman a su original",
         ayuda="Si: un item cuya descripcion empieza por REC cuenta como su original (el SKU sin el primer digito: 2190340 -> 190340): su inventario, transito y ventas se suman al original y el REC sale del calculo. Los pares se ven y se corrigen en Maestros > Items REC. Tras cambiarla corre el motor.", opciones=SI_NO),
    dict(clave="rit_abiertas_transito", titulo="Requisiciones RIT pendientes cuentan como tránsito",
         ayuda="Sí: el saldo de las requisiciones RIT (abastecimiento a tiendas) que el CEDI aún no despacha, es decir lo requerido menos lo ya despachado, se suma al tránsito de la tienda. Sin esto, mientras no exista el traslado en Siesa la tienda vuelve a pedir lo ya pedido. No: solo cuentan los traslados ya despachados. Se aplica en el siguiente ETL.",
         opciones=[{"valor": 1, "label": "Sí: cuentan como tránsito"}, {"valor": 0, "label": "No: solo traslados despachados"}]),
    dict(clave="rit_incluir_aprobadas", titulo="Requisiciones RIT: contar también las Aprobadas",
         ayuda="No: solo cuentan las líneas Comprometidas (el CEDI ya las reservó para despachar). Sí: también las Aprobadas, que el CEDI aún no compromete y pueden no salir nunca (por ejemplo sin stock). Se aplica en el siguiente ETL.",
         opciones=[{"valor": 0, "label": "No: solo las Comprometidas"}, {"valor": 1, "label": "Sí: también las Aprobadas"}]),
    dict(clave="rit_dias_historia", titulo="Requisiciones RIT: antigüedad máxima que cuenta como tránsito (días)",
         ayuda="Una requisición RIT abierta hace más días que esto NO suma al tránsito (una vieja sin cerrar en Siesa inflaría el tránsito para siempre). 0 = sin límite (hasta 365 días). Las viejas igual generan la alerta del item. Se aplica en el siguiente ETL.",
         opciones=None, min=0, max=365, entero=True),
    dict(clave="rit_alerta_dias", titulo="Requisiciones RIT: alerta en el item después de (días)",
         ayuda="Si un item tiene una requisición RIT COMPROMETIDA (el CEDI la reservó) hace más de estos días sin despacharse, sale la columna «RIT abierto (d)» y la fila resaltada en el Control y en la Matriz de despacho: hay que despacharla o anularla en Siesa. Las Aprobadas (aún sin comprometer) no generan alerta. Se aplica en el siguiente ETL.",
         opciones=None, min=1, max=365, entero=True),
    dict(clave="pipeline_auto", titulo="Corrida automática (ETL + motor)",
         ayuda="Si: el ETL y el motor corren solos a la hora indicada. No: no corre nada solo; el personal lo lanza cuando lo necesite (botón de correr el pipeline). Útil mientras se hacen pruebas. Se aplica en menos de un minuto, sin reiniciar.",
         opciones=[{"valor": 1, "label": "Sí: corre sola a la hora indicada"}, {"valor": 0, "label": "No: solo cuando alguien la lance a mano"}]),
    dict(clave="pipeline_hora", titulo="Corrida automática: hora", ayuda="Hora de Colombia (0 a 23) a la que corre sola. Si el backend está apagado a esa hora, la corrida se pierde ese día (tolera hasta 30 minutos de retraso).", opciones=None, min=0, max=23, entero=True),
    dict(clave="pipeline_minuto", titulo="Corrida automática: minuto", ayuda="Minuto (0 a 59) de esa hora.", opciones=None, min=0, max=59, entero=True),
    dict(clave="pipeline_cada_dias", titulo="Corrida automática: cada cuántos días", ayuda="1 = todos los días, 2 = un día por medio, 7 = una vez por semana. Cuenta desde la última vez que corrió sola.", opciones=None, min=1, max=30, entero=True),
    dict(clave="retener_dias", titulo="Dias de historial que se conservan", ayuda="Para la vista de cambios en un periodo: se guarda la ultima corrida de cada dia. 7 a 730.", opciones=None, min=7, max=730, entero=True),
    dict(clave="mult_cota_max_promo", titulo="Multiplicador de cota maxima en promocion", ayuda="Hoja Modelo AZ.", opciones=None),
    dict(clave="mult_cota_min_promo", titulo="Multiplicador de cota minima en promocion", ayuda="Hoja Modelo BA.", opciones=None),
    dict(clave="adu_bajo_min", titulo="ADU bajo: desde", ayuda="Entre desde y hasta, ZRB = 0.", opciones=None),
    dict(clave="adu_bajo_max", titulo="ADU bajo: hasta", ayuda="Entre desde y hasta, ZRB = 0.", opciones=None),
]
CLAVES = {r["clave"]: r for r in REGLAS}


@router.get("")
def listar(user=Depends(usuario_actual)):
    with pg.connect() as c:
        vals = dict(c.execute(text("SELECT clave, valor::float8 FROM ddmrp.parametro")).all())
    return [{**r, "valor": vals.get(r["clave"])} for r in REGLAS]


# ---- A que tiendas se reparte el inventario del CEDI cuando no alcanza ----
@router.get("/reparto-dias")
def reparto_dias(user=Depends(usuario_actual)):
    """DIAs elegidos (vacio = todas las tiendas) y los DIAs que existen con cuantas tiendas tiene cada uno."""
    with pg.connect() as c:
        elegidos = [r[0] for r in c.execute(text("SELECT dia FROM ddmrp.reparto_dia ORDER BY dia")).all()]
        dias = [{"dia": d, "tiendas": n} for d, n in c.execute(text("SELECT dia, count(*) FROM ddmrp.bodega_dia GROUP BY dia ORDER BY dia")).all()]
    return {"elegidos": elegidos, "dias": dias}


class Dias(BaseModel):
    dias: list[int]


@router.put("/reparto-dias")
def cambiar_reparto_dias(body: Dias, user=Depends(requiere("editar_reglas"))):
    if not _puede_global(user):
        raise HTTPException(403, "Requiere permiso de edicion sobre todas las bodegas")
    with pg.begin() as c:
        ant = [r[0] for r in c.execute(text("SELECT dia FROM ddmrp.reparto_dia ORDER BY dia")).all()]
        existentes = {r[0] for r in c.execute(text("SELECT DISTINCT dia FROM ddmrp.bodega_dia")).all()}
        nuevos = sorted(set(body.dias))
        if set(nuevos) - existentes:
            raise HTTPException(400, f"DIA(s) sin tiendas: {sorted(set(nuevos) - existentes)}")
        c.execute(text("DELETE FROM ddmrp.reparto_dia"))
        for d in nuevos:
            c.execute(text("INSERT INTO ddmrp.reparto_dia (dia) VALUES (:d)"), {"d": d})
        c.execute(text("INSERT INTO ddmrp.config_audit (tabla, llave, campo, valor_anterior, valor_nuevo, usuario) "
                       "VALUES ('reglas', 'reparto_dias', 'valor', :a, :n, :u)"),
                  {"a": ",".join(map(str, ant)) or "todas", "n": ",".join(map(str, nuevos)) or "todas", "u": user["nombre"]})
    return {"ok": True, "aviso": "Se aplica en la proxima corrida del motor (o con 'Recalcular ahora')."}


class Cambio(BaseModel):
    valor: float


# ---- Reglas de compras: viven en ddmrp.compras_config (las leen Necesidades de compra y las OC) ----
REGLAS_COMPRAS = [
    dict(grupo="Necesidades de compra", clave="pedido_minimo_bloquea", titulo="Proveedores bajo su pedido mínimo",
         ayuda="Qué pasa con un proveedor cuyo valor a pedir no llega a su pedido mínimo (se configura por proveedor en Maestros de compras).",
         opciones=[{"valor": 0, "label": "Se muestran con alerta (no se bloquean)"}, {"valor": 1, "label": "Se bloquean y no se muestran"}]),
    dict(grupo="Necesidades de compra", clave="poca_historia_meses", titulo="Poca historia: meses con venta",
         ayuda="Un ítem con menos de estos meses con venta (en los últimos 12) se marca «poca historia». Es solo una alerta, no bloquea.", opciones=None, min=1, max=12, entero=True),
    dict(grupo="Necesidades de compra", clave="frecuencia_defecto", titulo="Frecuencia de compra por defecto (días)",
         ayuda="Cada cuántos días se le compra a un proveedor que no tiene la suya. Define el tamaño de la zona verde del buffer del CEDI.", opciones=None, min=1, max=365, entero=True),
    dict(grupo="Órdenes de compra (revisión en el BPM)", clave="oc_destino", titulo="Envío de las OC",
         ayuda="A dónde van las OC al enviarlas desde Necesidades de compra. Pausado: no se envía nada (útil en pruebas; la vista previa sigue funcionando). Directo a Siesa: se crean en Siesa ya aprobadas, sin pasar por nadie. Al BPM: allí se revisa y aprueba, se crea en Siesa, se genera el PDF y se envía el correo al proveedor.",
         opciones=[{"valor": 0, "label": "Pausado: no se envía ninguna OC"}, {"valor": 1, "label": "Directo a Siesa (sin BPM, sin correo al proveedor)"}, {"valor": 2, "label": "Al BPM (revisión, Siesa, PDF y correo al proveedor)"}]),
    dict(grupo="Órdenes de compra (revisión en el BPM)", clave="oc_umbral_total", titulo="Total hasta el cual una OC sin desvíos no se revisa ($)",
         ayuda="Total (con IVA, en pesos) hasta el cual una OC SIN desvíos se crea sin revisión en el BPM. 0 = toda OC pasa por revisión.", opciones=None, min=0, max=1e12),
    dict(grupo="Órdenes de compra (revisión en el BPM)", clave="oc_desvio_cant_pct", titulo="Desvío de cantidad que manda a revisión (%)",
         ayuda="Una línea pasa a revisión si la cantidad se aparta más de este % de la cantidad calculada (sugerida).", opciones=None, min=0, max=1000),
    dict(grupo="Órdenes de compra (revisión en el BPM)", clave="oc_desvio_cant_min", titulo="Desvío de cantidad: solo si la sugerida supera (unidades)",
         ayuda="La regla de cantidad solo se evalúa si la cantidad calculada (sugerida) supera estas unidades; así pedir 2 en vez de 1 no dispara revisión.", opciones=None, min=0, max=1e9),
    dict(grupo="Órdenes de compra (revisión en el BPM)", clave="oc_desvio_costo_pct", titulo="Subida de costo que manda a revisión (%)",
         ayuda="Una línea pasa a revisión si el costo editado sube más de este % frente a la cotización (manual › Siesa › última compra).", opciones=None, min=0, max=1000),
    dict(grupo="Órdenes de compra (revisión en el BPM)", clave="oc_exigir_entiendo", titulo="Confirmar antes de enviar la OC",
         ayuda="Si: para enviar una OC hay que marcar la casilla «Entiendo que se envía al BPM». No: no se pide esa confirmación.",
         opciones=[{"valor": 1, "label": "Sí: pedir la confirmación"}, {"valor": 0, "label": "No"}]),
    dict(grupo="Órdenes de compra (revisión en el BPM)", clave="oc_listado_dias", titulo="OC enviadas: días que muestra el listado",
         ayuda="Días hacia atrás que muestra por defecto el listado de OC enviadas (se puede cambiar con los filtros de la pantalla).", opciones=None, min=1, max=3650, entero=True),
]
CLAVES_COMPRAS = {r["clave"]: r for r in REGLAS_COMPRAS}


@router.get("/compras")
def listar_compras(user=Depends(requiere("ver_compras", "cargar_maestros_compras", "editar_reglas_compras"))):
    with pg.connect() as c:
        vals = dict(c.execute(text("SELECT clave, valor::float8 FROM ddmrp.compras_config")).all())
    return [{**r, "valor": vals.get(r["clave"])} for r in REGLAS_COMPRAS]


@router.put("/compras/{clave}")
def cambiar_compras(clave: str, body: Cambio, user=Depends(requiere("cargar_maestros_compras", "editar_reglas_compras"))):
    r = CLAVES_COMPRAS.get(clave)
    if not r:
        raise HTTPException(404, "Regla desconocida")
    if r["opciones"] and body.valor not in {o["valor"] for o in r["opciones"]}:
        raise HTTPException(400, "Valor no permitido")
    if body.valor < r.get("min", 0) or body.valor > r.get("max", 1e12):
        raise HTTPException(400, f"Debe estar entre {r.get('min', 0)} y {r.get('max', 'sin tope')}")
    if r.get("entero") and body.valor != int(body.valor):
        raise HTTPException(400, "Debe ser un numero entero")
    with pg.begin() as c:
        ant = c.execute(text("SELECT valor::text FROM ddmrp.compras_config WHERE clave = :c"), {"c": clave}).scalar()
        c.execute(text("INSERT INTO ddmrp.compras_config (clave, valor, detalle) VALUES (:c, :v, :d) ON CONFLICT (clave) DO UPDATE SET valor = EXCLUDED.valor"),
                  {"c": clave, "v": body.valor, "d": r["ayuda"]})
        c.execute(text("INSERT INTO ddmrp.config_audit (tabla, llave, campo, valor_anterior, valor_nuevo, usuario) "
                       "VALUES ('reglas_compras', :c, 'valor', :a, :n, :u)"), {"c": clave, "a": ant, "n": str(body.valor), "u": user["nombre"]})
    return {"ok": True, "aviso": "Se aplica de inmediato."}


@router.put("/{clave}")
def cambiar(clave: str, body: Cambio, user=Depends(requiere("editar_reglas"))):
    r = CLAVES.get(clave)
    if not r:
        raise HTTPException(404, "Regla desconocida")
    if not _puede_global(user):
        raise HTTPException(403, "Requiere permiso de edicion sobre todas las bodegas")
    if r["opciones"] and body.valor not in {o["valor"] for o in r["opciones"]}:
        raise HTTPException(400, "Valor no permitido")
    if body.valor < r.get("min", 0) or body.valor > r.get("max", 1e12):
        raise HTTPException(400, f"Debe estar entre {r.get('min', 0)} y {r.get('max', 'sin tope')}")
    if r.get("entero") and body.valor != int(body.valor):
        raise HTTPException(400, "Debe ser un numero entero")
    with pg.begin() as c:
        ant = c.execute(text("SELECT valor::text FROM ddmrp.parametro WHERE clave=:c"), {"c": clave}).scalar()
        c.execute(text("INSERT INTO ddmrp.parametro (clave, valor) VALUES (:c, :v) "
                       "ON CONFLICT (clave) DO UPDATE SET valor = EXCLUDED.valor"), {"c": clave, "v": body.valor})
        c.execute(text("INSERT INTO ddmrp.config_audit (tabla, llave, campo, valor_anterior, valor_nuevo, usuario) "
                       "VALUES ('reglas', :c, 'valor', :a, :n, :u)"),
                  {"c": clave, "a": ant, "n": str(body.valor), "u": user["nombre"]})
    if clave.startswith("pipeline_"):
        return {"ok": True, "aviso": "Se aplica en menos de un minuto: no hace falta reiniciar."}
    return {"ok": True, "aviso": "Se aplica en la proxima corrida del motor (o con 'Recalcular ahora')."}

