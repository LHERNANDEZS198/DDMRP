/** Tiendas que se pueden elegir según la empresa filtrada (cada tienda trae su(s) empresa(s) separadas por coma). Sin empresa elegida, todas. */
export const tiendasDeEmpresa = (tiendas: any[], emp: string[]) =>
  emp.length ? tiendas.filter(t => (t.empresa ?? '').split(',').some((e: string) => emp.includes(e))) : tiendas

/** De las tiendas ya elegidas deja solo las que son de la empresa filtrada (al cambiar la empresa). */
export const bodegasDeEmpresa = (bodegas: string[], tiendas: any[], emp: string[]) => {
  if (!emp.length) return bodegas
  const ok = new Set(tiendasDeEmpresa(tiendas, emp).map(t => t.bodega_id))
  return bodegas.filter(b => ok.has(b))
}
