"""Items REC: un item cuya descripcion empieza por "REC" (p.ej. 2190340 "REC CALENDULA SUSPENSION (ANTAX) X 360 ml") es el mismo
producto que su original, cuya referencia es la del REC SIN EL PRIMER DIGITO (190340). Para el calculo de despacho el REC deja de
existir como item propio y su inventario (tiendas, CEDI, transitos) y sus ventas se suman al original.

Funcion pura (sin base de datos) para poder probarla: recibe las referencias y descripciones de Siesa y devuelve los pares."""
import re

# "REC" como palabra: "REC CALENDULA", "REC. X", "REC-X". No atrapa RECARGABLE, RECUBIERTO, RECETA...
PATRON = re.compile(r"^\s*REC[\s.\-]", re.IGNORECASE)


def es_rec(descripcion: str | None) -> bool:
    return bool(descripcion and PATRON.match(descripcion))


def detectar_rec(items: list[tuple]) -> tuple[list[tuple[str, str, str]], list[str]]:
    """items = [(referencia, descripcion, ...)]. Devuelve ([(rec_id, original_id, descripcion)], [rec sin original]).
    El original debe existir en Siesa (con cualquier estado); si no existe el REC queda como item normal y se avisa.
    Si el original es a su vez un REC se sigue la cadena (maximo 3 saltos)."""
    refs = {str(x[0]).strip() for x in items if x[0]}
    desc = {str(x[0]).strip(): (x[1] or "") for x in items if x[0]}
    directo: dict[str, str] = {}
    sin: list[str] = []
    for ref, d in desc.items():
        if not es_rec(d):
            continue
        if len(ref) >= 2 and ref[1:] in refs:
            directo[ref] = ref[1:]
        else:
            sin.append(ref)
    pares = []
    for rec, o in directo.items():
        for _ in range(3):
            if o in directo and directo[o] != o:
                o = directo[o]
            else:
                break
        if o != rec:
            pares.append((rec, o, desc[rec]))
    return sorted(pares), sorted(sin)
