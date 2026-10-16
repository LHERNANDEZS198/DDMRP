import logging
from contextlib import asynccontextmanager
from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI
from .config import settings
from .orchestrator import pipeline_nocturno
from .routers import auth, alertas, config_items, despacho, admin

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    sch = BackgroundScheduler(timezone="America/Bogota")
    sch.add_job(pipeline_nocturno, "cron", hour=settings.etl_cron_hour, minute=0, id="nocturno")
    sch.start()
    yield
    sch.shutdown()


app = FastAPI(title="DDMRP API", lifespan=lifespan, root_path="")
for r in (auth, alertas, config_items, despacho, admin):
    app.include_router(r.router, prefix="/api")


@app.get("/api/health")
def health():
    return {"ok": True}
