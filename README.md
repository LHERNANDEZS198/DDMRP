# DDMRP – Abastecimiento diario a tiendas

Monorrepo: `core_rust/` (motor de calculo), `backend_python/` (FastAPI + ETL + orquestacion), `frontend/` (React + AG Grid),
`db/init/` (esquema Postgres), `docs/` (arquitectura, modelo DDMRP, scripts SQL de apoyo).

## Arranque local
```bash
cp .env.example .env     # completar credenciales (el .env NO se sube a git)
docker compose up --build
# UI:  http://localhost:8080     API docs: http://localhost:8000/docs
```
FUNATLAB ya no se usa. Variables a tener en el `.env`: `SIESA_DB` (empresa 05), `SIESA_DB_S` (empresa 21, `Stores`), `ADMIN_BOOTSTRAP`.
Las variables `LAB_*` y `SYNC_MAESTROS` ya no existen (se pueden borrar).

Base de datos ya creada (volumen existente)? Los scripts de `db/init` solo corren en una base nueva. Aplicar el cambio con:
`docker compose exec -T db psql -U ddmrp -d ddmrp < db/init/003_sin_funatlab.sql`

Primera carga: entrar como admin y `POST /api/admin/correr-pipeline` (ETL + motor). Despues corre solo a las 02:00.

## Pruebas
```bash
cd core_rust && cargo test        # formulas del modelo
```

## Estado
- [x] Esquema Postgres, replica de tablas Abastecimiento_*, motor Rust con el modelo del Excel, API, UI base, docker-compose
- [x] Transitos: traslados abiertos de Siesa (t406) · [ ] demanda calificada (por Excel, sin fuente automatica)
- [ ] Promociones (de donde sale el indicativo 0/1/2)
- [x] Regla de pedido confirmada y configurable (pantalla “Reglas de pedido”)
- [x] DIA de abastecimiento por tienda, seleccion de tiendas antes de generar el plano
- [x] Todos los maestros se descargan/cargan por Excel (crear, actualizar, reemplazar)
- [x] Ventas por mes desde Siesa (`backend_python/app/etl/sql/ventas_siesa.sql`, basada en `Abastecimiento_Consulta_Ventas`): falta probarla contra Siesa
- [ ] Cargar los maestros iniciales por Excel (bitacora de 135 bodegas, unidad de despacho, vectorizacion, DIA por tienda, items/laboratorio)
- [x] Fase 2: archivo plano de Siesa (requisicion RIT; formato de `docs/Abastecimiento día 4_15102026.xlsx`)
- [ ] Consecutivo de los documentos del plano (hoy se digita al exportar)
- [ ] Fase 3: web service Siesa
