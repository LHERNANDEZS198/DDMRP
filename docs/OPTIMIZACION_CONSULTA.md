# Optimizacion de `Abastecimiento_Modelo_Consulta`

El procedimiento de FUNATLAB hace trabajo que ya no hace falta y tiene varios problemas. Lo que se hizo en la app y lo que
conviene si se vuelve a escribir la consulta de ventas sobre Siesa.

## Problemas del SP original
1. **Recorre toda la tabla** (585.852 filas y creciendo cada mes) sin filtro de fechas, aunque solo usa los ultimos 8 meses.
2. **`mes` es `varchar(6)` y se compara con variables `INT`**: SQL Server convierte la columna fila por fila (precedencia de tipos),
   no puede usar un indice sobre `mes` y fallaria con cualquier valor no numerico.
3. **`GROUP BY` incluye `descripcionProducto` y `codigoLaboratorio`**: si una descripcion cambia, la misma referencia/bodega sale
   en dos filas con ventas partidas.
4. **Tabla temporal + dos `UPDATE`** para promedio y desviacion, y un `ORDER BY` dentro de `SELECT INTO` que no sirve de nada.
5. **Ventana de 8 meses** (`@Mes1` = hace 7 meses hasta el actual) y promedio `/8`, mientras que el Excel del modelo usa 7 meses
   (J..P). El motor de la app sigue el Excel (7 meses). Confirmar cual es el correcto.
6. Calcula promedio/desviacion/IV que luego el modelo vuelve a calcular: es trabajo duplicado.

## Que hace la app
- La consulta de origen solo **agrega por mes** (mes, bodega, referencia, unidades) y solo de la ventana de 7 meses; una vez por
  empresa. El resto del historico no se vuelve a leer.
- En Postgres queda `ventas_mensual` con PK `(mes, bodega, producto)`: unas pocas decenas de miles de filas por mes en lugar de
  lineas de factura. El ETL solo reemplaza la ventana de meses (el historico anterior no se toca).
- Promedio, desviacion, ADU y zonas se calculan una sola vez, en memoria, en el motor Rust (337.448 combinaciones en ~9 s).

## Para la consulta de ventas sobre Siesa (`etl/sql/ventas_siesa.sql`)
- Filtrar por rango de fecha `>= :desde` (sargable), no por `mes` convertido.
- Agrupar por `CONVERT(char(6), fecha, 112)`, bodega y referencia (sin descripcion ni laboratorio; esos van en `maestro_item`).
- Solo bodegas de tiendas (`IN :bodegas`) y solo documentos de venta/devolucion que cuenten como demanda.
- Un indice por fecha + bodega + item que cubra la cantidad hace la lectura casi instantanea.
- Implementado en `ventas_siesa.sql` a partir de `Abastecimiento_Consulta_Ventas` (POS vigente t9820/t9830, POS archivado t9920/t9930 y facturas t350/t470 de las bodegas fuera de POS). Ese procedimiento solo trae los ultimos 7 dias y alguien/algo debia insertarlos en la tabla de FUNATLAB: esa carga quedo detenida el 5 de agosto, por eso la tabla esta desactualizada.
