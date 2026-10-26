import { useEffect, useMemo, useState } from 'react'
import Tabla from '../Tabla'
import { ColDef } from 'ag-grid-community'
import { Autocomplete, Box, Card, CardActionArea, Chip, MenuItem, Paper, TextField, Typography } from '@mui/material'
import { api } from '../api'
import { bodegasDeEmpresa, colsCobertura, tiendasDeEmpresa } from '../filtros'
import { ayudar } from '../ayuda'
import { useEmpresa } from '../Empresa'

const num = (p: any) => p.value == null ? '' : Number(p.value).toLocaleString('es-CO', { maximumFractionDigits: 2 })
const COP = (p: any) => p.value == null ? '' : '$' + Math.round(p.value).toLocaleString('es-CO')
const MM = (v: number) => '$' + (Math.abs(v) >= 1e6 ? (v / 1e6).toLocaleString('es-CO', { maximumFractionDigits: 1 }) + ' M' : Math.round(v).toLocaleString('es-CO'))
const cols: ColDef[] = [
  { field: 'empresa', headerName: 'Emp.', filter: true, width: 70, pinned: 'left', headerTooltip: 'Empresa (05 Funat, 21 Stores): el CEDI PT001 existe en las dos.' },
  { field: 'bodega_id', headerName: 'Bodega', filter: true, width: 110, pinned: 'left' },
  { field: 'producto_id', headerName: 'Producto', filter: true, width: 110 },
  { field: 'descripcion', headerName: 'Descripción', filter: true, flex: 1, minWidth: 200 },
  { field: 'inventario', headerName: 'Inventario', type: 'numericColumn', valueFormatter: num },
  { field: 'en_transito', headerName: 'Tránsito', type: 'numericColumn', valueFormatter: num },
  { field: 'flujo_neto', headerName: 'Flujo neto', type: 'numericColumn', valueFormatter: num },
  { field: 'tor', headerName: 'TOR', type: 'numericColumn', valueFormatter: num },
  { field: 'tog_aj', headerName: 'TOG aj.', type: 'numericColumn', valueFormatter: num },
  { field: 'sobran', headerName: 'Sobran (u.)', type: 'numericColumn', headerTooltip: 'Unidades por encima del tope verde ajustado (TOG aj.) en las tiendas en sobrestock.', cellStyle: { color: '#1565c0', fontWeight: 600 }, valueFormatter: (p: any) => p.value ? Number(p.value).toLocaleString('es-CO', { maximumFractionDigits: 0 }) : '' },
  { field: 'faltan', headerName: 'Faltan (u.)', type: 'numericColumn', headerTooltip: 'Unidades que separan el flujo neto del tope verde ajustado (TOG aj.) cuando NO hay sobrestock. Es la distancia al tope, no el sugerido del motor (que además aplica mínimos, redondeo y el inventario del CEDI).', cellStyle: { color: '#c62828', fontWeight: 600 }, valueFormatter: (p: any) => p.value ? Number(p.value).toLocaleString('es-CO', { maximumFractionDigits: 0 }) : '' },
  { field: 'rotacion', headerName: 'Rotación (uds/mes)', type: 'numericColumn', headerTooltip: 'Venta mensual promedio que usa el motor (ADU), en unidades por mes.', valueFormatter: num },
  { field: 'sobran_costo', headerName: 'Sobra a costo $', type: 'numericColumn', width: 130, headerTooltip: 'Unidades que sobran × costo promedio actual del item: la plata que está de más sobre el tope verde.', cellStyle: { color: '#1565c0', fontWeight: 600 }, valueFormatter: p => p.value ? COP(p) : '' },
  { field: 'faltan_costo', headerName: 'Falta a costo $', type: 'numericColumn', width: 130, headerTooltip: 'Unidades que faltan para llegar al tope verde × costo promedio actual: lo que costaría llenar el buffer (no es el sugerido del motor).', cellStyle: { color: '#c62828', fontWeight: 600 }, valueFormatter: p => p.value ? COP(p) : '' },
  ...colsCobertura(),
  { field: 'pct_buffer', headerName: '% buffer', type: 'numericColumn', sort: 'asc', valueFormatter: num },
  { field: 'cantidad_sugerida', headerName: 'Sugerido', type: 'numericColumn', valueFormatter: num },
  { field: 'stock_cedi', headerName: 'CEDI antes', type: 'numericColumn', headerTooltip: 'Stock del CEDI de la empresa para este ítem (menos la reserva), antes de repartir a las tiendas', valueFormatter: num },
  { field: 'cedi_despues', headerName: 'CEDI después', type: 'numericColumn', headerTooltip: 'Lo que queda en el CEDI de este ítem después de enviar lo sugerido a TODAS las tiendas de la empresa (no solo a las filtradas). Negativo = lo pedido supera lo que hay', valueFormatter: num },
]
const color: Record<string, string> = { ROJA: '#c62828', AMARILLA: '#f9a825', VERDE: '#2e7d32', EXCESO: '#1565c0' }
const ORDEN = ['ROJA', 'AMARILLA', 'VERDE', 'EXCESO']
const AYUDA_ZONA: Record<string, string> = {
  ROJA: 'Inventario crítico: el flujo neto está dentro de la zona roja del buffer. Es lo urgente: hay riesgo de quedarse sin producto.',
  AMARILLA: 'Zona de reposición: el flujo neto bajó de lo normal y toca pedir para volver al tope.',
  VERDE: 'Zona sana: hay inventario suficiente, no se pide.',
  EXCESO: 'Por encima del tope del buffer: hay de más (capital inmovilizado).' }

export default function Dashboard() {
  const [res, setRes] = useState<{ zona: string; n: number; sobran_costo: number; faltan_costo: number; sin_costo: number }[]>([])
  const [d, setD] = useState<{ total: number; filas: any[]; totales?: any }>({ total: 0, filas: [] })
  const [cargando, setCargando] = useState(true)
  const [zona, setZona] = useState('ROJA')   // zona cuya lista se ve abajo (clic en una tarjeta)
  const [opc, setOpc] = useState<any>({ tiendas: [], laboratorios: [], empresas: [], criterios: [] })
  const { lista: empresa } = useEmpresa(); const setEmpresa = (_: string[]) => {}; const [bodegas, setBodegas] = useState<string[]>([]); const [labs, setLabs] = useState<string[]>([])
  const [plan, setPlan] = useState(''); const [crit, setCrit] = useState<string[]>([]); const [qd, setQd] = useState(''); const [q, setQ] = useState('')
  useEffect(() => { api('/control/filtros').then(setOpc).catch(() => {}) }, [])
  useEffect(() => { const t = setTimeout(() => setQ(qd), 400); return () => clearTimeout(t) }, [qd])
  // los filtros se resuelven en el servidor (mismos que Control DDMRP) y valen para las tarjetas y para la lista
  const qs = useMemo(() => {
    const p = new URLSearchParams()
    if (empresa.length) p.set('empresa', empresa.join(',')); if (bodegas.length) p.set('bodegas', bodegas.join(',')); if (labs.length) p.set('labs', labs.join(','))
    if (q.trim()) p.set('q', q.trim()); if (plan && crit.length) p.set('crit', crit.map(v => `${plan}:${v}`).join(','))
    return p.toString()
  }, [empresa, bodegas, labs, q, plan, crit])
  useEffect(() => {
    let vivo = true; setCargando(true)
    Promise.all([api('/alertas/resumen?' + qs), api('/alertas/zona-roja?' + qs + (qs ? '&' : '') + 'zona=' + zona)])
      .then(([r, z]) => { if (vivo) { setRes(r); setD(z) } }).catch(() => {}).finally(() => vivo && setCargando(false))
    return () => { vivo = false }
  }, [qs, zona])
  const hayFiltro = !!qs
  const pie = useMemo(() => d.totales ? [{ descripcion: `TOTAL · ${d.total.toLocaleString('es-CO')} combinaciones${d.total > d.filas.length ? ' (toda la lista, no solo las filas visibles)' : ''}`, ...d.totales }] : [], [d])
  const total = res.reduce((a, r) => a + r.n, 0) || 1
  const nl = (c: string) => opc.laboratorios.find((l: any) => l.codigo === c)?.nombre
  const nt = (id: string) => opc.tiendas.find((t: any) => t.bodega_id === id)?.nombre
  const valores = opc.criterios.find((p: any) => p.plan_id === plan)?.valores ?? []
  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', height: '100%', gap: 2 }}>
      <Paper variant="outlined" sx={{ flexShrink: 0, p: 1.25, display: 'flex', flexWrap: 'wrap', gap: 1, alignItems: 'center' }}>
        <Autocomplete multiple size="small" limitTags={2} sx={{ minWidth: 230, flex: '2 1 230px' }} options={tiendasDeEmpresa(opc.tiendas, empresa).map((t: any) => t.bodega_id)} value={bodegas}
          getOptionLabel={(o: string) => nt(o) ? `${o} · ${nt(o)}` : o} onChange={(_, v) => setBodegas(v)} renderInput={p => <TextField {...p} label="Tienda" />} />
        <Autocomplete multiple size="small" limitTags={2} sx={{ minWidth: 230, flex: '2 1 230px' }} options={opc.laboratorios.map((l: any) => l.codigo)} value={labs}
          getOptionLabel={(o: string) => nl(o) ? `${o} · ${nl(o)}` : o} onChange={(_, v) => setLabs(v)} renderInput={p => <TextField {...p} label="Laboratorio" />} />
        {opc.criterios.length > 0 && <>
          <TextField select size="small" label="Criterio de items" value={plan} onChange={e => { setPlan(e.target.value); setCrit([]) }} sx={{ minWidth: 190 }} slotProps={{ select: { displayEmpty: true }, inputLabel: { shrink: true } }}>
            <MenuItem value="">(elige un criterio)</MenuItem>{opc.criterios.map((p: any) => <MenuItem key={p.plan_id} value={p.plan_id}>{p.nombre}</MenuItem>)}</TextField>
          {plan && <Autocomplete multiple size="small" limitTags={2} sx={{ minWidth: 220, flex: '2 1 220px' }} options={valores.map((v: any) => v.id)} value={crit}
            getOptionLabel={(o: string) => valores.find((v: any) => v.id === o)?.nombre ?? o} onChange={(_, v) => setCrit(v)} renderInput={p => <TextField {...p} label="Valores" />} />}
        </>}
        <TextField size="small" label="Item (código o nombre)" value={qd} onChange={e => setQd(e.target.value)} sx={{ minWidth: 190, flex: '1 1 190px' }} />
        {hayFiltro && <Chip size="small" label="Quitar filtros" onClick={() => { setEmpresa([]); setBodegas([]); setLabs([]); setPlan(''); setCrit([]); setQd(''); setQ('') }} />}
      </Paper>
      <Paper variant="outlined" sx={{ flexShrink: 0, px: 1.5, py: 1, bgcolor: 'action.hover' }}>
        <Typography variant="body2" color="text.secondary">
          <b>Alertas</b> · cómo está el inventario de cada tienda × item frente a su buffer, según la última corrida del motor. Las tarjetas cuentan cuántas combinaciones hay en cada zona
          (<b style={{ color: color.ROJA }}>roja</b> = crítico, hay que reponer ya · <b style={{ color: '#b57f00' }}>amarilla</b> = toca pedir · <b style={{ color: color.VERDE }}>verde</b> = sano · <b style={{ color: color.EXCESO }}>exceso</b> = hay de más).
          Haz clic en una tarjeta para ver su lista (por defecto la roja, que es lo urgente); sale ordenada de la más vacía a la más llena e indica cuánto hay en el CEDI antes y después de repartir.
          Todo respeta los filtros y no incluye items condenados.
        </Typography>
      </Paper>
      <Box sx={{ display: 'grid', gridTemplateColumns: { xs: 'repeat(2, 1fr)', md: 'repeat(4, 1fr)' }, gap: 2 }}>
        {[...res].sort((a, b) => ORDEN.indexOf(a.zona) - ORDEN.indexOf(b.zona)).map(r => (
          <Card key={r.zona} variant="outlined" sx={{ borderLeft: `6px solid ${color[r.zona] ?? '#999'}`, outline: zona === r.zona ? `2px solid ${color[r.zona]}` : 'none', bgcolor: zona === r.zona ? 'action.selected' : undefined }}>
            <CardActionArea sx={{ p: 1.5 }} onClick={() => setZona(r.zona)} title={AYUDA_ZONA[r.zona]}>
              <Typography variant="caption" color="text.secondary">Zona {r.zona.toLowerCase()}</Typography>
              <Typography variant="h5" sx={{ fontWeight: 700 }}>{r.n.toLocaleString()}</Typography>
              <Typography variant="caption" color="text.secondary" sx={{ display: 'block' }}>{((r.n / total) * 100).toFixed(1)}% de las combinaciones</Typography>
              {r.zona === 'EXCESO'
                ? <Typography variant="body2" sx={{ fontWeight: 600, color: color.EXCESO }} title="Unidades por encima del tope verde ajustado × costo promedio (sin items condenados).">Sobra a costo {MM(r.sobran_costo)}</Typography>
                : r.zona !== 'VERDE' || r.faltan_costo > 0
                  ? <Typography variant="body2" sx={{ fontWeight: 600, color: color.ROJA }} title="Lo que separa el flujo neto del tope verde ajustado × costo promedio: lo que costaría llenar los buffers (no es el sugerido del motor; sin items condenados).">Falta a costo {MM(r.faltan_costo)}</Typography> : null}
              {r.sin_costo > 0 && <Typography variant="caption" color="warning.main" sx={{ display: 'block' }} title="Combinaciones con unidades por sobrar o faltar cuyo item no tiene costo en Siesa: no suman a este valor.">{r.sin_costo.toLocaleString('es-CO')} sin costo</Typography>}
            </CardActionArea>
          </Card>))}
      </Box>
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
        <Typography variant="subtitle1" sx={{ fontWeight: 600 }}>Productos en zona {zona.toLowerCase()}</Typography>
        <Chip size="small" color={d.total > d.filas.length ? 'warning' : 'default'}
          label={d.total > d.filas.length ? `Mostrando ${d.filas.length.toLocaleString('es-CO')} de ${d.total.toLocaleString('es-CO')}: filtra para ver el resto` : `${d.total.toLocaleString('es-CO')} combinaciones`} />
      </Box>
      <Box className="ag-theme-quartz" sx={{ flex: 1, minHeight: 300 }}>
        <Tabla cargando={cargando} vacio={`Sin productos en zona ${zona.toLowerCase()} con estos filtros`} rowData={d.filas} pinnedBottomRowData={pie} getRowStyle={p => p.node.rowPinned ? { fontWeight: 700, background: '#eef3e2' } : undefined} columnDefs={ayudar(cols)} rowBuffer={20} animateRows={false} tooltipShowDelay={300} defaultColDef={{ resizable: true, sortable: true }} />
      </Box>
    </Box>)
}
