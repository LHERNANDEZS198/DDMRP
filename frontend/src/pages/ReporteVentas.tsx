import { useEffect, useMemo, useState } from 'react'
import { Alert, Box, CircularProgress, ToggleButton, ToggleButtonGroup, Typography } from '@mui/material'
import { ColDef } from 'ag-grid-community'
import Tabla from '../Tabla'
import { api } from '../api'
import { Actualizacion, AvisoEmpresa, BarraFiltros, COLOR, Kpi, Lineas, MM, Panel, ejeM, ent, mesLargo, pct, pesos, useFiltros } from '../reportes/comun'

/** Ventas por producto: lo que era la hoja «Ventas x Producto» del Power BI de compras. */
export default function ReporteVentas() {
  const { op, f, setF, qs, err, recargarOpciones } = useFiltros('ventas')
  const [d, setD] = useState<any>(null)
  const [agrupar, setAgrupar] = useState<'producto' | 'mes'>('producto')
  const [cargando, setCargando] = useState(false)
  const [e2, setE2] = useState('')
  const cargar = () => {
    if (!f) return
    setCargando(true); setE2('')
    api(`/compras/reportes/ventas-producto?${qs}&agrupar=${agrupar}`).then(setD).catch(e => setE2(String(e?.message || e))).finally(() => setCargando(false))
  }
  useEffect(cargar, [qs, agrupar])

  const num = (campo: string, titulo: string, fmt: (v: any) => string, ancho = 120, tip?: string): ColDef => ({ field: campo, headerName: titulo, type: 'numericColumn', width: ancho, filter: 'agNumberColumnFilter', headerTooltip: tip, valueFormatter: (p: any) => p.value == null ? '' : fmt(p.value) })
  const cols: ColDef[] = useMemo(() => [
    ...(agrupar === 'mes' ? [{ field: 'periodo', headerName: 'Periodo', width: 100, filter: true, valueFormatter: (p: any) => mesLargo(p.value) } as ColDef] : []),
    { field: 'producto_id', headerName: 'SKU', width: 100, pinned: 'left', filter: true },
    { field: 'descripcion', headerName: 'Producto', width: 300, pinned: 'left', filter: true },
    { field: 'laboratorio', headerName: 'Laboratorio', width: 170, filter: true },
    { field: 'categoria', headerName: 'Categoría', width: 160, filter: true },
    { field: 'accion', headerName: 'Acción', width: 140, filter: true },
    num('inv_cedi', 'Inv. CEDI', ent, 110, 'Disponible hoy en el CEDI (inventario que trae el ETL)'),
    num('inv_tiendas', 'Inv. tiendas', ent, 115, 'Disponible hoy en las tiendas de la bitácora'),
    num('cantidad', 'Ventas uds', ent, 115, 'Unidades facturadas en el rango (las devoluciones restan)'),
    num('adu', 'Demanda (ADU mes)', ent, 140, 'Rotación mensual que usa el buffer del CEDI (reemplaza la «Demanda» del Sheet Top Terceros)'),
    num('costo', 'Costo total', pesos, 130),
    num('neta', 'Venta neta', pesos, 135, 'Valor bruto − descuento de línea'),
    num('bruto', 'Valor bruto', pesos, 135),
    num('descuento', 'Descuento', pesos, 125),
    num('rent', '% Rent', v => pct(v, 0), 95, '(Venta neta − costo) ÷ venta neta'),
  ], [agrupar])
  const total = d ? [{ descripcion: 'Total', cantidad: d.kpis.cantidad, costo: d.kpis.costo, neta: d.kpis.neta, bruto: d.kpis.bruto, descuento: d.kpis.descuento, rent: d.kpis.rent }] : []

  if (err) return <Alert severity="error">{err}</Alert>
  if (!op || !f) return <Box sx={{ display: 'grid', placeItems: 'center', height: '40vh' }}><CircularProgress /></Box>
  const k = d?.kpis
  const per = d?.serie.map((s: any) => s.periodo) ?? []
  return (
    <Box sx={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr)', gap: 1.5, pb: 3 }}>
      <Box sx={{ display: 'flex', alignItems: 'baseline', gap: 2, flexWrap: 'wrap' }}>
        <Typography variant="h5" sx={{ fontWeight: 700 }}>Ventas por producto</Typography>
        <Actualizacion op={op} alTerminar={() => { recargarOpciones(); cargar() }} />
      </Box>
      <BarraFiltros op={op} f={f} setF={setF} conUn />
      <AvisoEmpresa op={op} />
      {e2 && <Alert severity="error">{e2}</Alert>}
      {!!d && !d.filas.length && !cargando && <Alert severity="info">No hay ventas con estos filtros. Si es la primera vez, un usuario con permiso debe pulsar «Actualizar datos».</Alert>}
      <Box sx={{ display: 'flex', gap: 1.25, flexWrap: 'wrap', opacity: cargando ? .6 : 1 }}>
        <Kpi titulo="Productos" valor={k ? ent(k.items) : '…'} />
        <Kpi titulo="Unidades vendidas" valor={k ? ent(k.cantidad) : '…'} />
        <Kpi titulo="Venta neta" valor={k ? MM(k.neta) : '…'} sub="bruto − descuento" />
        <Kpi titulo="Costo" valor={k ? MM(k.costo) : '…'} />
        <Kpi titulo="% Rentabilidad" valor={k ? pct(k.rent, 0) : '…'} ayuda="(Venta neta − costo) ÷ venta neta" />
        <Kpi titulo="Descuento" valor={k ? MM(k.descuento) : '…'} />
      </Box>
      <Panel titulo="Venta neta y costo por mes" ayuda="Pasa el cursor por un mes para ver las cifras.">
        <Lineas periodos={per} fmt={v => MM(v)} fmtEje={ejeM} alto={220}
          series={[{ nombre: 'Venta neta', color: COLOR.azul, valores: d?.serie.map((s: any) => s.neta) ?? [] }, { nombre: 'Costo', color: COLOR.naranja, valores: d?.serie.map((s: any) => s.costo) ?? [] }]} />
      </Panel>
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 2, flexWrap: 'wrap' }}>
        <ToggleButtonGroup size="small" exclusive value={agrupar} onChange={(_, v) => v && setAgrupar(v)}>
          <ToggleButton value="producto">Por producto</ToggleButton><ToggleButton value="mes">Por mes y producto</ToggleButton>
        </ToggleButtonGroup>
        <Typography variant="caption" color="text.secondary">
          {d ? `${ent(d.filas.length)} de ${ent(d.total_filas)} filas${d.recortado ? ' (afina los filtros para ver el resto)' : ''}` : ''} · Ctrl+A y Ctrl+C copian la tabla a Excel
        </Typography>
      </Box>
      <Box className="ag-theme-quartz">
        <Tabla memoria={'rep_ventas_' + agrupar} cargando={cargando} textoCargando="Cargando ventas…" vacio="Sin ventas con estos filtros" rowData={d?.filas || []} columnDefs={cols}
          pinnedBottomRowData={total} defaultColDef={{ resizable: true, sortable: true }} tooltipShowDelay={300}
          pagination paginationPageSize={100} paginationPageSizeSelector={[25, 50, 100, 200]} domLayout="autoHeight" />
      </Box>
    </Box>)
}
