import { useEffect, useMemo, useState } from 'react'
import { Alert, Box, CircularProgress, Typography } from '@mui/material'
import { ColDef } from 'ag-grid-community'
import Tabla from '../Tabla'
import { api } from '../api'
import { Actualizacion, BarraFiltros, COLOR, Kpi, Lineas, MM, Panel, ent, pct, pesos, useFiltros } from '../reportes/comun'

/** Proveedor / PT: compras vs ventas, rentabilidad y cumplimiento (OTIF) por mes. Reemplaza las hojas «Ficha Proveedor» y «PT» del Power BI de compras. */
export default function ReporteProveedor() {
  const { op, f, setF, qs, err, recargarOpciones } = useFiltros('proveedor')
  const [d, setD] = useState<any>(null)
  const [cargando, setCargando] = useState(false)
  const [e2, setE2] = useState('')
  const cargar = () => {
    if (!f) return
    setCargando(true); setE2('')
    api(`/compras/reportes/proveedor?${qs}`).then(setD).catch(e => setE2(String(e?.message || e))).finally(() => setCargando(false))
  }
  useEffect(cargar, [qs])
  const num = (campo: string, titulo: string, fmt: (v: any) => string, ancho = 125, tip?: string): ColDef => ({ field: campo, headerName: titulo, type: 'numericColumn', width: ancho, filter: 'agNumberColumnFilter', headerTooltip: tip, valueFormatter: (p: any) => p.value == null ? '' : fmt(p.value) })
  const colsProd: ColDef[] = useMemo(() => [
    { field: 'producto_id', headerName: 'SKU', width: 100, pinned: 'left', filter: true },
    { field: 'descripcion', headerName: 'Producto', width: 300, pinned: 'left', filter: true },
    { field: 'laboratorio', headerName: 'Laboratorio', width: 170, filter: true },
    num('cant_v', 'Uds vendidas', ent, 120), num('ventas', 'Ventas netas', pesos, 140), num('rent', '% Rent', v => pct(v, 0), 95),
    num('cant_c', 'Uds compradas', ent, 130), num('compras', 'Compras', pesos, 140),
  ], [])
  const colsProv: ColDef[] = useMemo(() => [
    { field: 'proveedor_id', headerName: 'NIT', width: 120, filter: true },
    { field: 'nombre', headerName: 'Proveedor', width: 280, filter: true },
    num('compras', 'Compras', pesos, 140), num('items', 'Ítems', ent, 90),
    num('infull', '% Completo', v => pct(v, 0), 115, 'Líneas de OC que llegaron completas'), num('ontime', '% A tiempo', v => pct(v, 0), 115, 'Líneas de OC cuya última entrada llegó en la fecha pactada'),
    num('lineas', 'Líneas OC', ent, 105),
  ], [])

  if (err) return <Alert severity="error">{err}</Alert>
  if (!op || !f) return <Box sx={{ display: 'grid', placeItems: 'center', height: '40vh' }}><CircularProgress /></Box>
  const k = d?.kpis, s: any[] = d?.serie ?? [], per = s.map(x => x.periodo)
  const eje = (v: number) => (v / 1e6).toLocaleString('es-CO', { maximumFractionDigits: 0 }) + ' M'
  return (
    <Box sx={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr)', gap: 1.5, pb: 3 }}>
      <Box sx={{ display: 'flex', alignItems: 'baseline', gap: 2, flexWrap: 'wrap' }}>
        <Typography variant="h5" sx={{ fontWeight: 700 }}>Proveedor / PT</Typography>
        <Actualizacion op={op} alTerminar={() => { recargarOpciones(); cargar() }} />
      </Box>
      <BarraFiltros op={op} f={f} setF={setF} conUn />
      {e2 && <Alert severity="error">{e2}</Alert>}
      {!!d && !s.length && !cargando && <Alert severity="info">No hay datos con estos filtros. Si es la primera vez, un usuario con permiso debe pulsar «Actualizar datos».</Alert>}
      <Box sx={{ display: 'flex', gap: 1.25, flexWrap: 'wrap', opacity: cargando ? .6 : 1 }}>
        <Kpi titulo="Compras" valor={k ? MM(k.compras) : '…'} />
        <Kpi titulo="Ventas netas" valor={k ? MM(k.ventas) : '…'} sub="bruto − descuento" />
        <Kpi titulo="Compras ÷ ventas" valor={k ? pct(k.compras_sobre_ventas, 0) : '…'} ayuda="Por encima de 100 % se compra más de lo que se vende en el rango" />
        <Kpi titulo="% Rentabilidad" valor={k ? pct(k.rent, 0) : '…'} />
        <Kpi titulo="% Completo (infull)" valor={k ? pct(k.infull, 0) : '…'} sub={k ? `${ent(k.lineas_otif)} líneas de OC` : ''} ayuda="Líneas de OC que llegaron completas (umbral en Reglas de compras)" />
        <Kpi titulo="% A tiempo (ontime)" valor={k ? pct(k.ontime, 0) : '…'} ayuda="Líneas de OC cuya última entrada llegó en la fecha pactada (días de gracia en Reglas de compras)" />
      </Box>
      <Box sx={{ display: 'grid', gridTemplateColumns: { xs: 'minmax(0, 1fr)', lg: 'minmax(0, 3fr) minmax(0, 2fr)' }, gap: 1.5 }}>
        <Panel titulo="Compras vs ventas por mes" ayuda="Las ventas son netas (sin descuento de línea). Pasa el cursor por un mes.">
          <Lineas periodos={per} fmt={v => MM(v)} fmtEje={eje} alto={250}
            series={[{ nombre: 'Ventas netas', color: COLOR.azul, valores: s.map(x => x.ventas) }, { nombre: 'Compras', color: COLOR.naranja, valores: s.map(x => x.compras) }]} />
        </Panel>
        <Panel titulo="% Rentabilidad por mes" ayuda="Gráfico propio: no comparte eje con los pesos.">
          <Lineas periodos={per} fmt={v => pct(v, 1)} fmtEje={v => (v * 100).toFixed(0) + ' %'} alto={250} piso={0}
            series={[{ nombre: '% Rent', color: COLOR.violeta, valores: s.map(x => x.rent) }]} />
        </Panel>
      </Box>
      <Panel titulo="Cumplimiento del proveedor por mes (OTIF)" ayuda="Mes de la última entrada de cada línea de OC. Completo: llegó lo pedido. A tiempo: llegó en la fecha pactada.">
        <Lineas periodos={per} fmt={v => pct(v, 0)} fmtEje={v => (v * 100).toFixed(0) + ' %'} alto={220} techo={1} piso={0}
          series={[{ nombre: '% Completo', color: COLOR.azul, valores: s.map(x => x.infull) }, { nombre: '% A tiempo', color: COLOR.naranja, valores: s.map(x => x.ontime) }]} />
      </Panel>
      <Typography sx={{ fontWeight: 700, mt: 1 }}>Proveedores con más compras</Typography>
      <Box className="ag-theme-quartz" sx={{ height: 360 }}>
        <Tabla memoria="rep_prov_prov" cargando={cargando} vacio="Sin compras con estos filtros" rowData={d?.proveedores || []} columnDefs={colsProv} defaultColDef={{ resizable: true, sortable: true }} />
      </Box>
      <Typography sx={{ fontWeight: 700, mt: 1 }}>Productos <Typography component="span" variant="caption" color="text.secondary">{d ? `${ent(d.productos.length)} filas${d.recortado ? ' (afina los filtros para ver el resto)' : ''} · Ctrl+A y Ctrl+C copian a Excel` : ''}</Typography></Typography>
      <Box className="ag-theme-quartz" sx={{ height: 'min(70vh, 560px)', minHeight: 340 }}>
        <Tabla memoria="rep_prov_prod" cargando={cargando} vacio="Sin productos con estos filtros" rowData={d?.productos || []} columnDefs={colsProd} defaultColDef={{ resizable: true, sortable: true }} tooltipShowDelay={300} />
      </Box>
    </Box>)
}
