# Modelo DDMRP implementado (hoja "Modelo", fila 6 del Excel)

Llave de cada fila: **empresa + bodega + referencia** (empresa '05' Funat, '21' Store; la empresa sale de la Bitacora).
Implementacion: `core_rust/src/lib.rs` (con pruebas). Columnas del Excel entre parentesis.

## 1. Entradas
| Dato | Origen en Postgres |
|---|---|
| Ventas mensuales, 7 meses (J..P; el ultimo es el mes en curso) | `ventas_mensual` (mes, bodega, referencia, unidades), traida ya agregada de Siesa (`etl/sql/ventas_siesa.sql`) o cargada por Excel |
| Lead time (AA), frecuencia (AC) | `abast_bitacora` por bodega |
| Unidad de despacho (AD) | `abast_unidad_despacho` por referencia |
| Cotas max / min (AX, AY) | `abast_control_referencias` |
| Vectorizacion (derrame) | `abast_vectorizacion` |
| Pronostico (valor estatico) | `pronostico` (se alimenta desde la app) |
| Promocion (AN: 0/1/2) | `promocion` (por definir) |
| Factores LT / variabilidad (hoja Factores) | `factor_tramo` |
| Multiplicadores de cota en promocion (1.2 / 1.1), rango ADU bajo (1 a 4) | `parametro` |
| Inventario | `inventario_actual` (Siesa, por empresa) |
| Transitos / demanda calificada | `transitos`: traslados abiertos de Siesa (`t406_cm_movto_transito`, `f406_ind_estado = 0`, bodega de entrada = tienda, cantidad pendiente); `demanda_calificada`: por Excel |

## 2. Calculo
1. **Pronostico ajustado (Q = CB):** `BK = ROUNDUP(BI + BI*BM)` con `BI` = promedio de los 7 meses y `BM` = desv.est./promedio.
   `CA = Pronostico/BK*30`. Si `CA<30` -> `Pronostico/CA*30`; si `CA>60` -> `Pronostico/CA*60`; si no, `Pronostico`. Sin historial -> 0.
2. **ADU (W):** `U` = promedio de [ultimos 4 meses (M..P), Q]; `Y = DESVEST.M / U`; `W = ROUNDUP(U + U*Y)` (unidades/mes).
3. **Factores:** LT por dias de lead time (0-3: 0.61 · 3-5: 0.41 · 5-50: 0.21); variabilidad por `Y` (0-0.5: 0.21 · 0.5-0.8: 0.41 · >0.8: 0.61).
4. **Zonas:** `ZA = ROUNDUP(LT * W/30)` · `ZRB = ROUND(ZA * factorLT)` (0 si W entre 1 y 4) · `ZRS = ROUND(ZRB * factorVar)` ·
   `ZV = MAX(ROUNDUP(frecuencia * W/30), unidadDespacho, ZRB)` (0 si W=0 o TOY=0).
5. **Topes:** `TOR = ZRB+ZRS` · `TOY = TOR+ZA` · `TOG = TOY+ZV`.
6. **Ajuste por cotas/promocion:**
   `TOY aj = ROUNDUP(TOG*cotaMax + TOR + ZA)` (en promocion la cota max x 1.2) ·
   `TOG aj = ROUNDUP(TOY aj + ZV + TOG*cotaMin)` (en promocion la cota min x 1.1; con promo=2 solo bodegas GN).
   Si W esta entre 1 y 4 y no hay promocion, los ajustados son TOY y TOG. La promocion no aplica a bodegas TC ni DM.

## 3. Regla de pedido (confirmada por Lucas; los parametros se cambian en la pantalla "Reglas de pedido")
Valores por defecto:
- Flujo neto = inventario + transito - demanda calificada (`incluir_transito`, `restar_demanda_calificada`).
- Zona: `<= TOR` roja · `<= TOY aj` amarilla · `<= TOG aj` verde · mayor, exceso. Sin buffer (TOG aj = 0): sin alerta.
- Se pide (`regla_disparo`): 1 = flujo neto `<= TOY aj` · 2 = `<= TOR` · 3 = `< TOG aj`.
- Cantidad = objetivo - flujo neto (`regla_objetivo`: 1 = TOG aj, 2 = TOY aj), al multiplo de la unidad de despacho
  (`regla_redondeo`: 1 arriba, 2 cercano, 3 abajo). `cantidad_minima` descarta sugeridos pequenos.
- La vectorizacion (derrame) se suma tal cual (`sumar_vectorizacion`).
- El mes en curso entra completo en el promedio aunque este incompleto (como en el Excel): al inicio de mes el ADU sale subestimado.

## 4. Archivo plano de Siesa (Fase 2)
`POST /api/despacho/exportar-plano` toma las sugerencias **aprobadas** (cantidad aprobada, o la sugerida si no se edito) y arma el mismo
Excel que `docs/Abastecimiento día 4_15102026.xlsx`: hojas Inicial · Documentos · Movimientos · Final.
- Un documento **RIT** por bodega destino (sale de `PT001`, solicitante `S688`, 1 dia de entrega), un movimiento por referencia (UND, motivo 01, un. negocio 12).
- `f440_id_co` = centro de operacion de la bodega: tabla `bodega_centro_operacion` (sembrada con las 37 bodegas del ejemplo; el ETL la completa desde Siesa).
  Si falta, se deduce con la regla del ejemplo (3 digitos finales del codigo, o `000`) y la respuesta avisa en el encabezado `X-Bodegas-CO-Derivado`.
- Nota del documento y consecutivo inicial se eligen al exportar. `marcar_enviadas` pasa las filas a estado ENVIADA.
- Cada usuario solo puede exportar si tiene permiso de aprobacion en todas las bodegas incluidas.

## 5. DIA de abastecimiento
Maestro `dias-bodega` (bodega, dia). En la matriz de despacho se elige el DIA, se agregan o quitan tiendas de esa corrida y
el archivo plano se genera solo con ellas; la nota por defecto queda "ABASTECIMIENTO DEL <dia> DE <MES> DÍA <n>".
