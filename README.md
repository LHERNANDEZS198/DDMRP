# DDMRP – Abastecimiento diario a tiendas

Monorrepo: `core_rust/` (motor de cálculo), `backend_python/` (FastAPI + ETL + orquestación), `frontend/` (React + AG Grid), `db/init/` (esquema Postgres), `docs/ARQUITECTURA.md` (diagrama y flujo).

## Arranque local
```bash
cp .env.example .env     # completar credenciales
docker compose up --build
# UI:  http://localhost:8080     API docs: http://localhost:8000/docs
```

## Estado
- [x] Esquema Postgres, motor Rust (formulas base + tests), API, UI base, docker-compose
- [ ] Queries reales de Siesa en `backend_python/app/etl/siesa_to_pg.py`
- [ ] Query/hash real de MySQL `reloj` en `.env` y `auth/mysql_auth.py`
- [ ] Formulas finales del Excel -> `core_rust/src/lib.rs`
- [ ] Fase 2: archivo plano Siesa · Fase 3: web service Siesa
