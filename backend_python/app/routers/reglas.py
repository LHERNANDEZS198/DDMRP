"""Reglas de pedido configurables desde la UI. Viven en ddmrp.parametro y las lee el motor Rust en cada corrida."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from ..db import pg
from ..security import usuario_actual
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
         ayuda="Nivel al que se lleva el flujo neto al pedir.",
         opciones=[{"valor": 1, "label": "TOG ajustado (tope verde)"}, {"valor": 2, "label": "TOY ajustado"}]),
    dict(clave="regla_redondeo", titulo="Redondeo a la unidad de despacho",
         ayuda="La cantidad faltante se lleva a un multiplo de la unidad de despacho.",
         opciones=[{"valor": 1, "label": "Hacia arriba"}, {"valor": 2, "label": "Al multiplo mas cercano"},
                   {"valor": 3, "label": "Hacia abajo"}]),
    dict(clave="sumar_vectorizacion", titulo="Sumar vectorizacion (derrame)",
         ayuda="Agrega las unidades de vectorizacion a lo sugerido (producto nuevo o campana).", opciones=SI_NO),
    dict(clave="incluir_transito", titulo="Contar traslados abiertos (transito)",
         ayuda="Los traslados abiertos hacia la tienda suman al flujo neto.", opciones=SI_NO),
    dict(clave="restar_demanda_calificada", titulo="Restar demanda calificada",
         ayuda="Pedidos abiertos o picos conocidos restan del flujo neto.", opciones=SI_NO),
    dict(clave="cantidad_minima", titulo="Cantidad minima a sugerir", ayuda="Sugeridos menores a este valor se descartan (0 = sin minimo).",
         opciones=None),
    dict(clave="meses_historia", titulo="Meses de historia de ventas", ayuda="Incluye el mes en curso. 2 a 12 (Excel: 7).", opciones=None, min=2, max=12, entero=True),
    dict(clave="meses_adu", titulo="Meses que entran al ADU (+ forecast)", ayuda="1 hasta los meses de historia (Excel: 4).", opciones=None, min=1, max=12, entero=True),
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


class Cambio(BaseModel):
    valor: float


@router.put("/{clave}")
def cambiar(clave: str, body: Cambio, user=Depends(usuario_actual)):
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
