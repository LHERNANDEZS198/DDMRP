from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from ..orchestrator import pipeline_nocturno, ejecutar_motor
from ..estadisticas import analizar_todo
from ..etl.replicacion import correr_etl, sincronizar_bodegas_ahora, sincronizar_items_ahora, sincronizar_ventas, diagnostico_inventario, diagnostico_estado_items
from ..security import usuario_actual
from .. import progreso
from ..security import requiere
from ..bitacora import usuario_de, registrar

router = APIRouter(prefix="/admin", tags=["admin"])


def _emp(empresa: str | None) -> str | None:
    """Empresa de la corrida: 05 (Funat) o 21 (Stores). Vacio = las dos (solo tiene sentido en el pipeline completo)."""
    empresa = (empresa or "").strip()
    if empresa and empresa not in ("05", "21"):
        raise HTTPException(400, "Empresa invalida: usa 05 (Funat) o 21 (Stores)")
    return empresa or None


@router.post("/correr-pipeline")
def pipeline(bg: BackgroundTasks, empresa: str | None = None, user=Depends(requiere("correr_motor"))):
    """ETL + motor completo, en segundo plano, de una empresa (o de las dos si no se indica)."""
    emp = _emp(empresa)
    progreso.exigir_libre()
    bg.add_task(pipeline_nocturno, "manual", usuario_de(user), emp); return {"estado": "lanzado", "empresa": emp}


@router.post("/correr-etl")
def etl(empresa: str | None = None, user=Depends(requiere("correr_motor"))):
    return correr_etl("manual", usuario_de(user), _emp(empresa))


@router.post("/correr-motor")
def motor(empresa: str | None = None, user=Depends(requiere("correr_motor"))):
    """Corre el motor de UNA empresa: no toca la ultima corrida ni la historia de la otra. Sin empresa corre las dos."""
    return ejecutar_motor(None, "manual", usuario_de(user), _emp(empresa))


@router.post("/actualizar-estadisticas")
def estadisticas(user=Depends(requiere("correr_motor"))):
    """ANALYZE de las tablas de los informes: ayuda cuando un informe se pone lento tras cargar datos. No cambia datos y no bloquea la lectura."""
    with registrar("analyze", "manual", usuario_de(user)) as r:
        r.resumen = res = analizar_todo()
        r.mensaje = f"{res['tablas']} tablas en {res['segundos']} s" + (f" · fallaron: {', '.join(res['fallas'])}" if res.get("fallas") else "")
        return res


@router.post("/sincronizar-bodegas")
def bodegas(user=Depends(requiere("sincronizar_siesa"))):
    """Trae las tiendas (codigo y nombre) de Siesa: sirve para que los Excel se llenen por codigo o por nombre."""
    with progreso.tarea("Tiendas", "Tiendas traídas de Siesa"):
        progreso.avance("Leyendo las tiendas de Siesa…")
        return {"tiendas": sincronizar_bodegas_ahora(usuario_de(user))}


@router.post("/sincronizar-items")
def items(empresa: str | None = None, user=Depends(requiere("sincronizar_siesa"))):
    """Trae de Siesa la descripcion, el laboratorio y todos los criterios de items (con sus nombres), para filtrar en las vistas."""
    try:
        with progreso.tarea("Items", "Items traídos de Siesa"):
            progreso.avance("Leyendo items y criterios de Siesa… puede tardar un par de minutos")
            return sincronizar_items_ahora(usuario_de(user), _emp(empresa))
    except RuntimeError as e:
        raise HTTPException(400, str(e))


@router.post("/sincronizar-ventas")
def ventas(empresa: str | None = None, user=Depends(requiere("sincronizar_siesa"))):
    """Trae a demanda las ventas por mes de Siesa (la consulta pesada, aparte del ETL)."""
    try:
        return sincronizar_ventas("manual", usuario_de(user), _emp(empresa))
    except RuntimeError as e:
        raise HTTPException(400, str(e))


@router.get("/motor-hoy")
def motor_hoy(empresa: str | None = None, user=Depends(requiere("correr_motor"))):
    """Para advertir antes de volver a correr el motor el mismo dia: cada corrida nueva crea una ejecucion y la matriz solo
    muestra la ultima: lo aprobado sin enviar vuelve a PENDIENTE (lo ENVIADO se hereda) y el plano solo exporta la ultima."""
    from datetime import date
    from sqlalchemy import text
    from ..db import pg
    with pg.connect() as c:
        emp = _emp(empresa) or "05"
        hoy = c.execute(text("SELECT count(*), max(id), max(inicio) FROM ddmrp.ejecucion_motor WHERE fecha_calculo = :f AND estado = 'ok' AND empresa = :m"),
                        {"f": date.today(), "m": emp}).one()
        est = {}
        if hoy[1]:
            est = dict(c.execute(text("SELECT estado::text, count(*) FROM ddmrp.sugerencias_envio WHERE ejecucion_id = :e GROUP BY 1"), {"e": hoy[1]}).all())
        from ..reparto import dias_alcance
        dias_reparto = dias_alcance(c, emp)
    return {"empresa": emp, "dias_reparto": dias_reparto, "corrio_hoy": hoy[0] > 0, "corridas": hoy[0], "ultima": hoy[2], "aprobadas": est.get("APROBADA", 0), "enviadas": est.get("ENVIADA", 0)}


@router.get("/salud")
def salud(empresa: str | None = None, user=Depends(usuario_actual)):
    """Estado para el aviso de arriba: lo que corre ahora y si la ultima corrida de cada tipo quedo a medias o fallo
    (reinicio del servidor, red, error de Siesa...), para invitar a correr de nuevo."""
    from datetime import datetime, timezone
    from sqlalchemy import text
    from ..db import pg
    est = progreso.estado()
    problemas = []
    with pg.connect() as c:
        for tipo in ("etl", "motor"):
            r = c.execute(text("SELECT estado, mensaje, inicio, origen, usuario FROM ddmrp.bitacora WHERE tipo = :t "
                               "ORDER BY inicio DESC, id DESC LIMIT 1"), {"t": tipo}).mappings().first()
            if r and r["estado"] in ("error", "interrumpido"):
                problemas.append({"tipo": tipo, **dict(r)})
        # ultima corrida buena de la empresa pedida; sin empresa, la MAS VIEJA de las empresas que ya corrieron (la que mas urge correr)
        ok = c.execute(text("""SELECT id, fecha_calculo, fin, empresa FROM
                               (SELECT DISTINCT ON (empresa) id, fecha_calculo, fin, empresa FROM ddmrp.ejecucion_motor
                                WHERE estado = 'ok' AND (CAST(:m AS text) IS NULL OR empresa = :m) ORDER BY empresa, id DESC) u
                               ORDER BY fin ASC NULLS FIRST LIMIT 1"""), {"m": _emp(empresa)}).mappings().first()
    horas = None
    if ok and ok["fin"]:
        horas = round((datetime.now(timezone.utc) - ok["fin"]).total_seconds() / 3600, 1)
    return {"en_curso": est if est["estado"] == "corriendo" else None, "problemas": problemas,
            "ultimo_motor_ok": {"fecha": ok["fecha_calculo"], "fin": ok["fin"], "empresa": ok["empresa"]} if ok else None,
            "horas_sin_motor": horas, "sin_corridas": ok is None}


@router.get("/progreso")
def avance(user=Depends(usuario_actual)):
    """Que esta haciendo la tarea larga en curso (la pantalla lo consulta cada par de segundos)."""
    return progreso.estado()


@router.get("/diagnostico-inventario")
def diag_inventario(bodega: str, producto: str, user=Depends(requiere("sincronizar_siesa", "correr_motor"))):
    """Compara lo que dice Siesa (t400, todas las columnas con dato: existencia, comprometida, costos) con lo que tiene el sistema
    para una tienda y una referencia. Sirve para saber por que un inventario no cuadra."""
    producto = producto.strip().zfill(6) if producto.strip().isdigit() else producto.strip()
    return diagnostico_inventario(bodega.strip().upper(), producto)


@router.get("/diagnostico-estado-items")
def diag_estado_items(user=Depends(requiere("sincronizar_siesa", "correr_motor"))):
    """Cuantos items hay en cada estado de t120 en Siesa (activo / inactivo / bloqueado) y que items REC se sumarian a su original.
    Sirve para confirmar la columna de estado antes de confiar en el filtro de items activos."""
    return diagnostico_estado_items()
