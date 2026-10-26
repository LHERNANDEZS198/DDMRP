import logging, time
import jwt
from contextlib import asynccontextmanager
from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from .config import settings
from .esquema import asegurar_esquema
from .bitacora import cerrar_huerfanas
from .progreso import Ocupado
from .orchestrator import pipeline_nocturno
from .routers import auth, alertas, maestros, despacho, admin, reglas, control, usuarios, log, auditoria, lanzamientos, clasificacion, salud, vistas, diagnostico, compras, oc
from . import consultas

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    asegurar_esquema()
    cerrar_huerfanas()
    consultas.arrancar()
    sch = BackgroundScheduler(timezone="America/Bogota")
    sch.add_job(pipeline_nocturno, "cron", hour=settings.etl_cron_hour, minute=0, id="nocturno")
    sch.start()
    yield
    sch.shutdown()


app = FastAPI(title="DDMRP API", lifespan=lifespan, **({} if settings.habilitar_docs else {"docs_url": None, "redoc_url": None, "openapi_url": None}))
@app.exception_handler(Ocupado)
async def _ocupado(request: Request, exc: Ocupado):
    return JSONResponse(status_code=409, content={"detail": str(exc)})


@app.middleware("http")
async def _registrar_consulta(request: Request, call_next):
    """Anota en ddmrp.consulta_log cada llamada a la API (menos la salud, el login y la pantalla de diagnostico)."""
    ruta = request.url.path
    if request.method == "OPTIONS" or not ruta.startswith("/api") or ruta.startswith(consultas.OMITIR):
        return await call_next(request)
    det = consultas.iniciar()
    t0 = time.perf_counter()
    usuario = None
    try:
        tok = request.headers.get("authorization", "").split(" ", 1)[-1]
        usuario = jwt.decode(tok, options={"verify_signature": False}).get("nombre") if tok else None
    except Exception:       # noqa: BLE001
        pass
    try:
        resp = await call_next(request)
    except Exception as e:
        consultas.encolar({"usuario": usuario, "metodo": request.method, "ruta": ruta, "params": consultas.parametros(request.url.query), "http": 500,
                           "estado": "error", "ms": int((time.perf_counter() - t0) * 1000), "error": f"{type(e).__name__}: {e}"[:500], **{k: v for k, v in det.items() if k not in ("estado", "error")}})
        raise
    ms = int((time.perf_counter() - t0) * 1000)
    estado = det.get("estado") or ("ok" if resp.status_code < 400 else "rechazado" if resp.status_code < 500 else "error")
    try:
        nbytes = int(resp.headers.get("content-length") or 0) or None
    except ValueError:
        nbytes = None
    consultas.encolar({"usuario": usuario, "metodo": request.method, "ruta": ruta, "params": consultas.parametros(request.url.query), "http": resp.status_code,
                       "ms": ms, "bytes": nbytes, **{**det, "estado": estado}})
    return resp


for r in (auth, alertas, maestros, despacho, admin, reglas, control, usuarios, log, auditoria, lanzamientos, clasificacion, salud, vistas, diagnostico, compras, oc):
    app.include_router(r.router, prefix="/api")


@app.get("/api/health")
def health():
    return {"ok": True}
