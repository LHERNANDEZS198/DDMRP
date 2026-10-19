import { ColDef } from 'ag-grid-community'

/** Explicación en palabras simples de cada término, para quien arranca. Se muestra al pasar el mouse por el encabezado,
 *  la pestaña o el indicador. La clave es el texto del encabezado. */
export const AYUDA: Record<string, string> = {
  // niveles / agrupaciones
  Empresa: 'Funat (05) o Stores (21).',
  Tienda: 'Punto de venta. Se identifica por su código de Siesa (ej. SV021).',
  Laboratorio: 'Laboratorio o marca del item (plan 006 de Siesa).',
  'Criterio de items': 'Cualquier clasificación de Siesa del item: línea, acción, uso… Elige primero el criterio y luego sus valores.',
  Item: 'Referencia del producto.',
  'Tienda × item': 'El detalle más fino: un producto en una tienda, que es lo que calcula el motor.',
  Nombre: 'Nombre del grupo (tienda, laboratorio, etc.).',
  'Nombre tienda': 'Nombre de la tienda en Siesa.',
  Descripción: 'Nombre del producto.',
  'Lab.': 'Código del laboratorio del producto.',

  // conteos y zonas
  Combinaciones: 'Cuántos pares tienda × item hay en este grupo; cada uno es una fila de buffer que calcula el motor.',
  'Zonas del buffer': 'Cómo se reparten las combinaciones entre rojo, amarillo, verde y exceso. Pasa el mouse sobre cada color.',
  Rojo: 'Riesgo de quedarse sin producto: el flujo neto está en el nivel de emergencia o por debajo (TOR). Hay que reponer ya.',
  Amarillo: 'Hay que reponer: el flujo neto está sobre el nivel de emergencia pero por debajo del nivel de pedido (TOY).',
  Verde: 'Saludable: el flujo neto está entre el nivel de pedido y el tope (TOG). No hay que pedir. También sale verde un producto sin buffer definido (sin ventas) y sin stock, que no es alerta.',
  Exceso: 'Sobra: el flujo neto supera el tope (TOG). No se pide. También sale en exceso un producto sin buffer definido pero con stock.',
  '% buffer prom.': 'Promedio del porcentaje de buffer: flujo neto ÷ tope verde (TOG) × 100. Cerca de 0% es vacío, 100% es el tope.',
  '% buffer': 'Qué tan lleno está el buffer: flujo neto ÷ tope verde (TOG) × 100. Sobre 100% es exceso.',
  Buffer: 'Barra del buffer: rojo, amarillo y verde son las zonas; el marcador es dónde está el flujo neto hoy.',
  'Buffer (TOG)': 'TOG ajustado: el tope de la zona verde, hasta donde se repone. Es la suma de lo filtrado.',
  'TOG aj.': 'TOG ajustado: el tope de la zona verde, hasta donde se repone al pedir.',

  // inventario y flujo
  Inventario: 'Unidades disponibles en la tienda según el último corte de Siesa.',
  Tránsito: 'Unidades en traslados abiertos hacia la tienda que aún no llegan.',
  Transito: 'Unidades en traslados abiertos hacia la tienda que aún no llegan.',
  'Flujo neto': 'Inventario + tránsito − demanda calificada. Es lo que se compara contra las zonas para decidir si se pide.',
  ADU: 'Consumo promedio diario/mensual del producto en esa tienda (venta + pronóstico). Define qué tan grande es el buffer.',
  'A pedir': 'Cuántas combinaciones necesitan un pedido según las reglas.',
  'Unidades sug.': 'Total de unidades que el motor sugiere enviar, ya redondeadas a la unidad de despacho.',
  Control: 'Abre esta tienda y este item en Control DDMRP (foto actual) en una pestaña nueva, para ver su buffer y su historia.',
  Necesario: 'Lo que pide el buffer para llevar este item de esta tienda a su tope, ya redondeado a la unidad de despacho.',
  'Stock CEDI': 'Unidades de este item disponibles en el CEDI al correr el motor (inventario fresco de PT001 menos la reserva del item). Es el mismo para todas las tiendas del item.',
  Asignado: 'Lo que realmente se puede enviar a la tienda. Si la necesidad total del item (todas las tiendas) supera el CEDI, se reparte según la regla de Reglas de pedido; en rojo cuando es menos de lo necesario.',
  Sugerido: 'Cantidad que el motor sugiere enviar a la tienda, redondeada a la unidad de despacho.',
  Condenado: 'NxP: el item no se despacha (a esa tienda o a todas). El buffer se calcula, pero lo sugerido queda en 0.',
  Zona: 'Color del semáforo: rojo (urgente), amarillo (reponer), verde (bien), exceso (sobra).',

  // cambios
  'Antes / ahora': 'Reparto de zonas al inicio del periodo (barra de arriba) y hoy (barra de abajo).',
  'Entraron a rojo': 'Combinaciones que no estaban en rojo al inicio del periodo y hoy sí: se deterioraron.',
  'Salieron de rojo': 'Combinaciones que estaban en rojo y hoy ya no: se recuperaron.',
  Empeoraron: 'Combinaciones que bajaron de zona (ej. de verde a amarillo).',
  Mejoraron: 'Combinaciones que subieron de zona (ej. de rojo a amarillo).',
  Antes: 'Zona al inicio del periodo.',
  Ahora: 'Zona hoy.',
  '% antes': '% de buffer al inicio del periodo.',
  '% ahora': '% de buffer hoy.',
  'Cambio (pp)': 'Diferencia de % de buffer en puntos porcentuales. Negativo = el buffer se vació.',

  // matriz de despacho
  Bodega: 'Tienda que recibe el envío (código de Siesa).',
  Producto: 'Referencia del producto.',
  Descripcion: 'Nombre del producto.',
  Estado: 'PENDIENTE: por revisar. APROBADA: lista para el plano. ENVIADA: ya generada con “Marcar como enviadas”. Al correr el motor de nuevo todo vuelve a PENDIENTE (los estados viven en la corrida).',
  Forecast: 'Pronóstico ajustado a 30–60 días de inventario; entra al ADU junto con las ventas recientes.',
  TOR: 'Tope rojo: por debajo o igual a este nivel la referencia está en zona ROJA.',
  'TOY aj.': 'Tope amarillo ajustado por cotas y promoción.',
  'Und. desp.': 'Unidad de despacho: el múltiplo en que se despacha el producto (ej. cajas de 6). Lo sugerido se redondea a ese múltiplo.',
  Derrame: 'Vectorización: unidades extra que se suman a lo sugerido para productos nuevos o campañas.',
  'A enviar': 'Cantidad que vas a despachar. Por defecto es lo sugerido; puedes editarla antes de aprobar.',
}

/** Agrega el tooltip de ayuda al encabezado de cada columna que tenga explicación. */
export const ayudar = (cols: ColDef[]): ColDef[] =>
  cols.map(c => ({ ...c, headerTooltip: c.headerTooltip ?? AYUDA[(c.headerName ?? c.field ?? '') as string] }))
