import type { ColDef } from 'ag-grid-community'
/** Tiendas que se pueden elegir según la empresa filtrada (cada tienda trae su(s) empresa(s) separadas por coma). Sin empresa elegida, todas. */
export const tiendasDeEmpresa = (tiendas: any[], emp: string[]) =>
  emp.length ? tiendas.filter(t => (t.empresa ?? '').split(',').some((e: string) => emp.includes(e))) : tiendas

/** De las tiendas ya elegidas deja solo las que son de la empresa filtrada (al cambiar la empresa). */
export const bodegasDeEmpresa = (bodegas: string[], tiendas: any[], emp: string[]) => {
  if (!emp.length) return bodegas
  const ok = new Set(tiendasDeEmpresa(tiendas, emp).map(t => t.bodega_id))
  return bodegas.filter(b => ok.has(b))
}

/** Días de venta que cubre una cantidad: unidades ÷ (ADU mensual ÷ 30). Sin ADU no hay cobertura (null). */
export const diasCob = (unidades: any, adu: any) => { const a = Number(adu); return unidades == null || !(a > 0) ? null : Number(unidades) / (a / 30) }
const fmtDias = (p: { value: any }) => p.value == null ? '' : Number(p.value).toLocaleString('es-CO', { maximumFractionDigits: 1 })

/** Columnas «Cobertura (días)» y «TOG (días)»: ponen el flujo neto y el tope verde en la misma unidad que el ADU (días de venta), que es como se arma el buffer. */
export const colsCobertura = (): ColDef[] => [
  { colId: 'cob_dias', headerName: 'Cobertura (días)', type: 'numericColumn', width: 130, valueGetter: p => diasCob(p.data?.flujo_neto, p.data?.adu ?? p.data?.rotacion), valueFormatter: fmtDias,
    headerTooltip: 'Cuántos días de venta cubre el flujo neto (inventario + tránsito): flujo neto ÷ (ADU ÷ 30).' },
  { colId: 'tog_dias', headerName: 'TOG (días)', type: 'numericColumn', width: 110, valueGetter: p => diasCob(p.data?.tog_aj, p.data?.adu ?? p.data?.rotacion), valueFormatter: fmtDias,
    headerTooltip: 'Cuántos días de venta cubre el tope verde ajustado (TOG aj.). Si la cobertura pasa de este número, hay sobrestock.' },
]
