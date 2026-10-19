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
    dict(clave="pron_meses_minimos", titulo="Pronostico directo en casos nuevos (meses de venta minimos)",
         ayuda="Si una tienda o referencia tiene menos meses de venta que este numero y tiene pronostico cargado, el motor usa el pronostico tal cual como venta mensual esperada (junto con los meses que si vendio). Con mas meses, el pronostico se ajusta contra el historial (queda entre 1 y 2 veces el ADU de referencia). 0 = nunca: sin historial el pronostico se ignora (como en el Excel original).",
         opciones=None, min=0, max=12, entero=True),
    dict(clave="meses_adu", titulo="Meses que entran al ADU (+ forecast)", ayuda="1 hasta los meses de historia (Excel: 4).", opciones=None, min=1, max=12, entero=True),
    dict(clave="cedi_regla_reparto", titulo="Si el inventario del CEDI no alcanza",
         ayuda="Se aplica en cada corrida del motor, sumando la necesidad de la referencia en TODAS las tiendas. El inventario es el fresco de la bodega del CEDI (PT001) menos la reserva por item. Si la necesidad total cabe, cada tienda recibe lo que pide.",
         opciones=[{"valor": 1, "label": "Proporcional a la rotación de cada tienda (ADU): (rotación de la tienda / rotación total) × inventario del CEDI"},
                   {"valor": 4, "label": "Proporcional a lo que pide cada tienda: (necesidad de la tienda / necesidad total) × inventario del CEDI"},
                   {"valor": 2, "label": "Repartir parejo (igual a cada tienda hasta cubrir su necesidad)"},
                   {"valor": 3, "label": "Dar prioridad a la tienda mas critica (menor % de buffer)"},
                   {"valor": 0, "label": "No limitar (ignora el inventario del CEDI)"}]),
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
    return {"ok": True, "aviso": "Se aplica en la proxima corrida del motor (o con 'Recalcular ahora')."}

