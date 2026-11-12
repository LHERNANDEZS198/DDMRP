import { useEffect, useMemo, useState } from 'react'
import { Alert, Box, Chip, CircularProgress, ToggleButton, ToggleButtonGroup, Typography } from '@mui/material'
import { ColDef } from 'ag-grid-community'
import Tabla from '../Tabla'
import { api } from '../api'
import { Actualizacion, AvisoEmpresa, BarraFiltros, COLOR, Kpi, LineasAnio, MM, Panel, SelectorVista, ejeM, ent, mesLargo, pct, pesos, useFiltros, useModoVista } from '../reportes/comun'

const pesos2 = (v: any) => v == null ? '' : '$' + Number(v).toLocaleString('es-CO', { maximumFractionDigits: 2 })
const ejeUds = (v: number) => Math.abs(v) >= 1e6 ? (Math.round(v / 1e5) / 10).toLocaleString('es-CO') + ' M' : Math.abs(v) >= 1e3 ? (Math.round(v / 100) / 10).toLocaleString('es-CO') + ' mil' : String(Math.round(v))

/** Ventas por producto: lo que era la hoja «Ventas x Producto» del Power BI de compras. */
export default function ReporteVentas() {
  const { op, f, setF, qs, err, recargarOpciones } = useFiltros('ventas')
  const [d, setD] = useState<any>(null)
  const [modo, setModo] = useModoVista()
  const [agrupar, setAgrupar] = useState<'producto' | 'mes'>('producto')
  const [vistaCanal, setVistaCanal] = useState<'general' | 'canal' | 'un'>('general')     // «Por canal» / «Por UN»: el detalle sale por canal (o unidad de negocio) y producto y arriba un resumen
  const [grafUnidad, setGrafUnidad] = useState<'valor' | 'cantidad'>('valor')     // la gráfica por mes: venta y costo en pesos, o solo las unidades
  const nomGrupo = vistaCanal === 'un' ? 'Unidad de negocio' : 'Canal'
  const [canalSel, setCanalSel] = useState<string | null>(null)     // canal clicado en el resumen: el detalle muestra solo ese
  const [cargando, setCargando] = useState(false)
  const [e2, setE2] = useState('')
  const cargar = () => {
    if (!f) return
    setCargando(true); setE2('')
    api(`/compras/reportes/ventas-producto?${qs}&agrupar=${vistaCanal !== 'general' ? vistaCanal : agrupar}`).then(setD).catch(e => setE2(String(e?.message || e))).finally(() => setCargando(false))
  }
  useEffect(cargar, [qs, agrupar, vistaCanal])
  useEffect(() => { setCanalSel(null) }, [vistaCanal])
  useEffect(() => { setCanalSel(null) }, [qs])

  const num = (campo: string, titulo: string, fmt: (v: any) => string, ancho = 120, tip?: string): ColDef => ({ field: campo, headerName: titulo, type: 'numericColumn', width: ancho, filter: 'agNumberColumnFilter', headerTooltip: tip, valueFormatter: (p: any) => p.value == null ? '' : fmt(p.value) })
  const cols: ColDef[] = useMemo(() => [
    ...(vistaCanal !== 'general' ? [{ field: 'grupo', headerName: nomGrupo, width: 160, filter: true, pinned: 'left', valueFormatter: (p: any) => p.value || '(Sin dato)' } as ColDef] : []),
    ...(agrupar === 'mes' && vistaCanal === 'general' ? [{ field: 'periodo', headerName: 'Periodo', width: 100, filter: true, valueFormatter: (p: any) => mesLargo(p.value) } as ColDef] : []),
    { field: 'producto_id', headerName: 'SKU', width: 100, pinned: 'left', filter: true },
    { field: 'descripcion', headerName: 'Producto', width: 300, pinned: 'left', filter: true },
    { field: 'laboratorio', headerName: 'Laboratorio', width: 170, filter: true },
    { field: 'categoria', headerName: 'Categoría', width: 160, filter: true },
    { field: 'accion', headerName: 'Acción', width: 140, filter: true },
    num('inv_cedi', 'Inv. CEDI', ent, 110, 'Disponible hoy en el CEDI (inventario que trae el ETL)'),
    num('inv_tiendas', 'Inv. tiendas', ent, 115, 'Disponible hoy en las tiendas de la bitácora'),
    num('cantidad', 'Ventas uds', ent, 115, 'Unidades facturadas en el rango (las devoluciones restan)'),
    num('adu', 'Demanda (ADU mes)', ent, 140, 'Rotación mensual que usa el buffer del CEDI (reemplaza la «Demanda» del Sheet Top Terceros)'),
    num('costo_unit', 'Costo unitario', pesos2, 125, 'Costo total ÷ unidades vendidas del periodo (el costo que trae Siesa en cada venta)'),
    num('precio_unit', 'Precio unit. venta', pesos2, 135, 'Venta neta (bruto − descuento) ÷ unidades vendidas: el precio promedio al que se vendió'),
    num('costo', 'Costo total', pesos, 130),
    num('neta', 'Venta neta', pesos, 135, 'Valor bruto − descuento de línea'),
    num('bruto', 'Valor bruto', pesos, 135),
    num('descuento', 'Descuento', pesos, 125),
    num('margen', 'Margen $', pesos, 130, 'Venta neta − costo'),
    num('rent', '% Rent', v => pct(v, 0), 95, '(Venta neta − costo) ÷ venta neta'),
  ], [agrupar, vistaCanal, nomGrupo])
  const colsCanal: ColDef[] = useMemo(() => [
    { field: 'grupo', headerName: nomGrupo, width: 170, pinned: 'left', filter: true, valueFormatter: (p: any) => p.value || '(Sin dato)' },
    num('neta', 'Venta total (neta)', pesos, 160, 'Valor bruto − descuento de línea'),
    num('part', '% del total', v => pct(v, 0), 105, 'Participación del canal en la venta neta de lo filtrado'),
    num('margen', 'Margen $', pesos, 140, 'Venta neta − costo'),
    num('rent', '% Rent', v => pct(v, 0), 95, '(Venta neta − costo) ÷ venta neta'),
    num('cantidad', 'Unidades', ent, 115),
    num('items', 'Productos', ent, 110, 'Productos distintos vendidos en el canal'),
    num('precio_unit', 'Precio unit. venta', pesos2, 135),
    num('costo_unit', 'Costo unitario', pesos2, 125),
    num('bruto', 'Valor bruto', pesos, 135),
    num('descuento', 'Descuento', pesos, 125),
    num('costo', 'Costo total', pesos, 130),
  ], [nomGrupo])
  const totalCanal = d ? [{ grupo: 'Total', neta: d.kpis.neta, part: 1, margen: d.kpis.neta - d.kpis.costo, rent: d.kpis.rent, cantidad: d.kpis.cantidad, items: d.kpis.items,
    precio_unit: d.kpis.cantidad > 0 ? d.kpis.neta / d.kpis.cantidad : null, costo_unit: d.kpis.cantidad > 0 ? d.kpis.costo / d.kpis.cantidad : null, bruto: d.kpis.bruto, descuento: d.kpis.descuento, costo: d.kpis.costo }] : []
  const filasDetalle = useMemo(() => (d?.filas || []).filter((r: any) => vistaCanal === 'general' || canalSel === null || (r.grupo ?? '') === canalSel), [d, vistaCanal, canalSel])
  const total = d ? [{ descripcion: 'Total', cantidad: d.kpis.cantidad, costo: d.kpis.costo, neta: d.kpis.neta, bruto: d.kpis.bruto, descuento: d.kpis.descuento, rent: d.kpis.rent, margen: d.kpis.neta - d.kpis.costo }] : []

  if (err) return <Alert severity="error">{err}</Alert>
  if (!op || !f) return <Box sx={{ display: 'grid', placeItems: 'center', height: '40vh' }}><CircularProgress /></Box>
  const k = d?.kpis
  const per = d?.serie.map((s: any) => s.periodo) ?? []
  return (
    <Box sx={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr)', gap: 1.5, pb: 3 }}>
      <Box sx={{ display: 'flex', alignItems: 'baseline', gap: 2, flexWrap: 'wrap' }}>
        <Typography variant="h5" sx={{ fontWeight: 700 }}>Ventas por producto</Typography>
        <Actualizacion op={op} alTerminar={() => { recargarOpciones(); cargar() }} />
        <Box sx={{ ml: 'auto' }}><SelectorVista modo={modo} setModo={setModo} /></Box>
      </Box>
      <BarraFiltros op={op} f={f} setF={setF} conUn conCanal />
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
      <Panel titulo={grafUnidad === 'valor' ? 'Venta neta y costo por mes' : 'Unidades vendidas por mes'} ayuda="Pasa el cursor por un mes para ver las cifras. Con el selector cambias entre pesos (venta neta y costo) y unidades vendidas.">
        <ToggleButtonGroup size="small" exclusive value={grafUnidad} onChange={(_, v) => v && setGrafUnidad(v)} sx={{ mb: 1 }}>
          <ToggleButton value="valor">Venta y costo ($)</ToggleButton><ToggleButton value="cantidad">Cantidad (uds)</ToggleButton>
        </ToggleButtonGroup>
        {grafUnidad === 'valor'
          ? <LineasAnio modo={modo} periodos={per} fmt={v => MM(v)} fmtEje={ejeM} alto={220}
              series={[{ nombre: 'Venta neta', color: COLOR.azul, valores: d?.serie.map((s: any) => s.neta) ?? [] }, { nombre: 'Costo', color: COLOR.naranja, valores: d?.serie.map((s: any) => s.costo) ?? [] }]} />
          : <LineasAnio modo={modo} periodos={per} fmt={v => ent(v) + ' uds'} fmtEje={ejeUds} alto={220}
              series={[{ nombre: 'Unidades vendidas', color: COLOR.azul, valores: d?.serie.map((s: any) => s.cantidad) ?? [] }]} />}
      </Panel>
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 2, flexWrap: 'wrap' }}>
        <ToggleButtonGroup size="small" exclusive value={vistaCanal} onChange={(_, v) => v && setVistaCanal(v)}>
          <ToggleButton value="general">General</ToggleButton><ToggleButton value="canal">Por canal</ToggleButton><ToggleButton value="un">Por UN</ToggleButton>
        </ToggleButtonGroup>
        <ToggleButtonGroup size="small" exclusive value={agrupar} onChange={(_, v) => v && setAgrupar(v)} disabled={vistaCanal !== 'general'}>
          <ToggleButton value="producto">Por producto</ToggleButton><ToggleButton value="mes">Por mes y producto</ToggleButton>
        </ToggleButtonGroup>
        {vistaCanal !== 'general' && canalSel !== null && <Chip size="small" color="primary" label={`Detalle solo de: ${canalSel || '(Sin dato)'}`} onDelete={() => setCanalSel(null)} />}
        {vistaCanal !== 'general' && canalSel === null && !!d?.resumen?.length && <Typography variant="caption" color="text.secondary">Haz clic en una fila del resumen para ver solo su detalle</Typography>}
        <Typography variant="caption" color="text.secondary">
          {d ? `${ent(vistaCanal !== 'general' ? filasDetalle.length : d.filas.length)} de ${ent(d.total_filas)} filas${d.recortado ? ' (afina los filtros para ver el resto)' : ''}` : ''} · Ctrl+A y Ctrl+C copian la tabla a Excel
        </Typography>
      </Box>
      {vistaCanal !== 'general' && <Panel titulo={vistaCanal === 'un' ? 'Resumen por unidad de negocio' : 'Resumen por canal'} ayuda="Venta, margen y rentabilidad de cada grupo con los filtros de arriba. Los filtros «Canal» y «Unidad de negocio» de la barra dejan solo lo que elijas; sin elegir, salen todos.">
        <Box className="ag-theme-quartz">
          <Tabla memoria={'rep_ventas_resumen_' + vistaCanal} cargando={cargando} textoCargando="Cargando…" vacio="Sin ventas con estos filtros" rowData={d?.resumen || []} columnDefs={colsCanal}
            pinnedBottomRowData={totalCanal} defaultColDef={{ resizable: true, sortable: true }} domLayout="autoHeight"
            onRowClicked={(e: any) => setCanalSel(prev => { const c = e.data?.grupo ?? ''; return prev === c ? null : c })}
            getRowStyle={(p: any) => ({ cursor: 'pointer', ...(canalSel !== null && (p.data?.grupo ?? '') === canalSel ? { background: '#e3f2fd', fontWeight: 600 } : {}) })} />
        </Box>
      </Panel>}
      <Box className="ag-theme-quartz">
        <Tabla memoria={'rep_ventas_' + agrupar + (vistaCanal !== 'general' ? '_' + vistaCanal : '')} cargando={cargando} textoCargando="Cargando ventas…" vacio="Sin ventas con estos filtros" rowData={filasDetalle} columnDefs={cols}
          pinnedBottomRowData={total} defaultColDef={{ resizable: true, sortable: true }} tooltipShowDelay={300}
          pagination paginationPageSize={100} paginationPageSizeSelector={[25, 50, 100, 200]} domLayout="autoHeight" />
      </Box>
    </Box>)
}
