# DDMRP – Abastecimiento diario a tiendas

Monorrepo: `core_rust/` (motor de calculo), `backend_python/` (FastAPI + ETL + orquestacion), `frontend/` (React + AG Grid),
`db/init/` (esquema Postgres), `docs/` (arquitectura, modelo DDMRP, scripts SQL de apoyo).

## Arranque local
```bash
cp .env.example .env     # completar credenciales (el .env NO se sube a git)
docker compose up --build
# UI:  http://localhost:8080     API docs: http://localhost:8000/docs
```
Variables nuevas a tener en el `.env`: `LAB_SERVER`, `LAB_DB` (por defecto `dbGTIntegrationIntermediaReal`), `LAB_USER`,
`LAB_PASSWORD`, `SIESA_DB_S` (BD de Siesa de la empresa 21), `SYNC_MAESTROS` (true/false), `ADMIN_BOOTSTRAP`.

Primera carga: entrar como admin y `POST /api/admin/correr-pipeline` (ETL + motor). Despues corre solo a las 02:00.

## Pruebas
```bash
cd core_rust && cargo test        # formulas del modelo
```

## Estado
- [x] Esquema Postgres, replica de tablas Abastecimiento_*, motor Rust con el modelo del Excel, API, UI base, docker-compose
- [ ] Transitos (fuente: OC / traslados abiertos en Siesa) y demanda calificada
- [ ] Promociones (de donde sale el indicativo 0/1/2)
- [ ] Confirmar la regla de pedido y zona (ver docs/MODELO_DDMRP.md, seccion 3)
- [x] Fase 2: archivo plano de Siesa (requisicion RIT; formato de `docs/Abastecimiento día 4_15102026.xlsx`)
- [ ] Confirmar que significa "DÍA 4" en la nota del documento y el consecutivo de los documentos
- [ ] Fase 3: web service Siesa
