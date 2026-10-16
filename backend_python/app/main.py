import logging
from contextlib import asynccontextmanager
from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI
from .config import settings
from .esquema import asegurar_esquema
from .orchestrator import pipeline_nocturno
from .routers import auth, alertas, maestros, despacho, admin, reglas, control, usuarios

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    asegurar_esquema()
    sch = BackgroundScheduler(timezone="America/Bogota")
    sch.add_job(pipeline_nocturno, "cron", hour=settings.etl_cron_hour, minute=0, id="nocturno")
    sch.start()
    yield
    sch.shutdown()


app = FastAPI(title="DDMRP API", lifespan=lifespan)
for r in (auth, alertas, maestros, despacho, admin, reglas, control, usuarios):
    app.include_router(r.router, prefix="/api")


@app.get("/api/health")
def health():
    return {"ok": True}
