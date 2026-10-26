import { useEffect, useMemo, useState } from 'react'
import Tabla from '../Tabla'
import { ColDef } from 'ag-grid-community'
import { Alert, Autocomplete, Box, Button, Card, Chip, MenuItem, Paper, Tab, Tabs, TextField, Tooltip, Typography } from '@mui/material'
import Download from '@mui/icons-material/Download'
import { api, bajar } from '../api'
import { useEmpresa } from '../Empresa'

const num = (p: any) => p.value == null ? '' : Number(p.value).toLocaleString('es-CO', { maximumFractionDigits: 2 })
const ent = (p: any) => p.value == null ? '' : Math.round(Number(p.value)).toLocaleString('es-CO')
const COP = (p: any) => p.value == null ? '' : '$' + Math.round(p.value).toLocaleString('es-CO')
const MM = (v: number) => '$' + (Math.abs(v) >= 1e6 ? (v / 1e6).toLocaleString('es-CO', { maximumFractionDigits: 1 }) + ' M' : Math.round(v).toLocaleString('es-CO'))
const ZONA: Record<string, string> = { ROJA: '#c62828', AMARILLA: '#f9a825', VERDE: '#2e7d32', EXCESO: '#1565c0' }
const CATEGORIAS: Record<string, string> = { '0001': '0001 · Productos Funat', '0002': '0002 · Productos de terceros', '0003': '0003 · Maquila Funat' }
const ZONAS = ['ROJA', 'AMARILLA', 'VERDE', 'EXCESO']

type Resp = { config: Record<string, number>; ejecucion: { id: number; fecha_calculo: string } | null; aviso: string | null; filas: any[]; proveedores: any[]; bloqueados: any[]
  sin_proveedor: { total: number; filas: any[] }; totales: Record<string, number>; truncado: boolean }
const VACIO: Resp = { config: {}, ejecucion: null, aviso: null, filas: [], proveedores: [], bloqueados: [], sin_proveedor: { total: 0, filas: [] }, totales: {}, truncado: false }

function Kpi({ t, v, sub, color }: { t: string; v: string; sub?: string; color?: string }) {
  return (
    <Card variant="outlined" sx={{ p: 1.25, minWidth: 140, flex: '1 1 140px', borderLeft: `4px solid ${color ?? '#6b8e23'}` }}>
      <Typography variant="caption" color="text.secondary">{t}</Typography>
      <Typography sx={{ fontSize: 22, fontWeight: 700, lineHeight: 1.2 }}>{v}</Typography>
      {sub && <Typography variant="caption" color="text.secondary">{sub}</Typography>}
    </Card>)
}

export default function Necesidades() {
  const { lista: empresa } = useEmpresa()
  const [d, setD] = useState<Resp>(VACIO)
  const [cargando, setCargando] = useState(true); const [err, setErr] = useState('')
  const [tab, setTab] = useState(0)
  const [provs, setProvs] = useState<string[]>([]); const [cats, setCats] = useState<string[]>([]); const [zonas, setZonas] = useState<string[]>([])
  const [labs, setLabs] = useState<string[]>([]); const [qd, setQd] = useState(''); const [q, setQ] = useState('')
  const [opcLabs, setOpcLabs] = useState<{ codigo: string; nombre?: string }[]>([])
  const [bajando, setBajando] = useState(false)
  useEffect(() => { api('/control/filtros').then(x => setOpcLabs((x.laboratorios ?? x.labs ?? []).filter((l: any) => l.codigo))).catch(() => {}) }, [])
  useEffect(() => { const t = setTimeout(() => setQ(qd), 400); return () => clearTimeout(t) }, [qd])
  const qs = useMemo(() => {
    const p = new URLSearchParams()
    if (empresa.length) p.set('empresa', empresa.join(','))
    if (provs.length) p.set('proveedores', provs.join(','))
    if (cats.length) p.set('categorias', cats.join(','))
    if (zonas.length) p.set('zonas', zonas.join(','))
    if (labs.length) p.set('labs', labs.join(','))
    if (q.trim()) p.set('q', q.trim())
    return p.toString()
  }, [empresa, provs, cats, zonas, labs, q])
  useEffect(() => {
    let vivo = true; setCargando(true); setErr('')
    api('/compras/necesidades?' + qs).then(r => vivo && setD(r)).catch(e => vivo && setErr(e.message)).finally(() => vivo && setCargando(false))
    return () => { vivo = false }
  }, [qs])
  const excel = async () => { setBajando(true); setErr(''); try { await bajar('/compras/necesidades/excel?' + qs, 'necesidades_compra.xlsx') } catch (e: any) { setErr(e.message) } finally { setBajando(false) } }

  const t = d.totales
  const colsProv: ColDef[] = useMemo(() => [
    { field: 'empresa', headerName: 'Emp.', width: 70, pinned: 'left', filter: true },
    { field: 'proveedor_id', headerName: 'NIT', width: 120, filter: true },
    { field: 'proveedor_nombre', headerName: 'Proveedor', width: 280, filter: true },
    { field: 'items', headerName: 'Ítems', type: 'numericColumn', width: 90, valueFormatter: ent },
    { field: 'unidades', headerName: 'Unidades', type: 'numericColumn', width: 110, valueFormatter: ent },
    { field: 'valor', headerName: 'Valor sin IVA', type: 'numericColumn', width: 140, valueFormatter: COP, sort: 'desc', headerTooltip: 'Suma de los ítems con cotización; los ítems sin cotización no suman' },
    { field: 'iva', headerName: 'IVA estimado', type: 'numericColumn', width: 130, valueFormatter: COP, headerTooltip: 'Tarifa estimada: Siesa calcula el IVA real al crear la OC' },
    { field: 'total', headerName: 'Total', type: 'numericColumn', width: 140, valueFormatter: COP },
    { field: 'pedido_minimo', headerName: 'Pedido mínimo', type: 'numericColumn', width: 130, valueFormatter: COP },
    { field: 'sin_costo', headerName: 'Sin cotización', type: 'numericColumn', width: 120, valueFormatter: ent },
    { field: 'poca_historia', headerName: 'Poca historia', type: 'numericColumn', width: 120, valueFormatter: ent },
    { field: 'redondeo', headerName: 'Redondeo', width: 100 },
    { field: 'estado', headerName: 'Estado', width: 230, cellStyle: (p: any): Record<string, string | number> => p.value === 'OK' ? { color: '#2e7d32' } : { color: '#b45309', fontWeight: 600 } },
  ], [])
  const colsDet: ColDef[] = useMemo(() => [
    { field: 'empresa', headerName: 'Emp.', width: 70, pinned: 'left', filter: true },
    { field: 'proveedor_nombre', headerName: 'Proveedor', width: 200, pinned: 'left', filter: true },
    { field: 'producto_id', headerName: 'Producto', width: 100, filter: true },
    { field: 'descripcion', headerName: 'Descripción', width: 260, filter: true },
    { field: 'categoria', headerName: 'Categoría', width: 200, filter: true },
    { field: 'lab_nombre', headerName: 'Laboratorio', width: 160, filter: true },
    { field: 'zona', headerName: 'Zona', width: 100, filter: true, cellStyle: (p: any) => ({ color: ZONA[p.value] ?? '#333', fontWeight: 700 }) },
    { field: 'adu', headerName: 'ADU (u/mes)', type: 'numericColumn', width: 110, valueFormatter: num },
    { field: 'lead_time', headerName: 'Lead time (d)', type: 'numericColumn', width: 110, valueFormatter: ent },
    { field: 'inventario', headerName: 'Inventario', type: 'numericColumn', width: 110, valueFormatter: ent },
    { field: 'en_transito', headerName: 'Tránsito', type: 'numericColumn', width: 100, valueFormatter: ent },
    { field: 'flujo_neto', headerName: 'Flujo neto', type: 'numericColumn', width: 110, valueFormatter: ent },
    { field: 'tog_aj', headerName: 'TOG aj.', type: 'numericColumn', width: 100, valueFormatter: ent },
    { field: 'cobertura_dias', headerName: 'Cobertura (días)', type: 'numericColumn', width: 120, valueFormatter: num },
    { field: 'qty_buffer', headerName: 'Pide el buffer', type: 'numericColumn', width: 120, valueFormatter: ent, headerTooltip: 'Lo que pide el buffer del CEDI (hasta el tope verde)' },
    { field: 'unidad_pedido', headerName: 'Unidad de pedido', type: 'numericColumn', width: 130, valueFormatter: num },
    { field: 'qty_pedir', headerName: 'A pedir', type: 'numericColumn', width: 100, valueFormatter: ent, cellStyle: { fontWeight: 700 }, headerTooltip: 'Cantidad llevada al múltiplo de la unidad de pedido según el redondeo del proveedor' },
    { field: 'costo', headerName: 'Costo', type: 'numericColumn', width: 120, valueFormatter: (p: any) => p.value == null ? 'Sin cotización' : '$' + Number(p.value).toLocaleString('es-CO', { maximumFractionDigits: 2 }),
      cellStyle: (p: any) => p.value == null ? { color: '#b45309', fontWeight: 600 } : undefined },
    { field: 'origen_costo', headerName: 'Origen del costo', width: 130 },
    { field: 'valor', headerName: 'Valor sin IVA', type: 'numericColumn', width: 130, valueFormatter: COP },
    { field: 'iva_tasa', headerName: 'IVA % (est.)', type: 'numericColumn', width: 110, valueFormatter: num },
    { field: 'total', headerName: 'Total', type: 'numericColumn', width: 130, valueFormatter: COP },
    { field: 'alertas', headerName: 'Alertas', width: 280, cellStyle: (p: any) => p.value ? { color: '#b45309' } : undefined },
  ], [])
  const colsSin: ColDef[] = useMemo(() => [
    { field: 'empresa', headerName: 'Emp.', width: 70, pinned: 'left', filter: true },
    { field: 'producto_id', headerName: 'Producto', width: 100, filter: true },
    { field: 'descripcion', headerName: 'Descripción', width: 280, filter: true },
    { field: 'categoria', headerName: 'Categoría', width: 200, filter: true },
    { field: 'lab_nombre', headerName: 'Laboratorio', width: 160, filter: true },
    { field: 'zona', headerName: 'Zona', width: 100, filter: true, cellStyle: (p: any) => ({ color: ZONA[p.value] ?? '#333', fontWeight: 700 }) },
    { field: 'adu', headerName: 'ADU (u/mes)', type: 'numericColumn', width: 110, valueFormatter: num },
    { field: 'flujo_neto', headerName: 'Flujo neto', type: 'numericColumn', width: 110, valueFormatter: ent },
    { field: 'qty_buffer', headerName: 'Pide el buffer', type: 'numericColumn', width: 120, valueFormatter: ent },
  ], [])

  const bloquea = (d.config.pedido_minimo_bloquea ?? 0) >= 1
  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', height: '100%', gap: 1.25, minHeight: 520 }}>
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, flexWrap: 'wrap' }}>
        <Typography variant="h6" sx={{ fontWeight: 700, flex: 1 }}>Necesidades de compra del CEDI</Typography>
        {d.ejecucion && <Typography variant="caption" color="text.secondary">Corrida del motor: {d.ejecucion.fecha_calculo} · pedido mínimo: {bloquea ? 'bloquea' : 'solo alerta'}</Typography>}
        <Button variant="outlined" startIcon={<Download />} onClick={excel} disabled={bajando || !d.filas.length}>{bajando ? 'Preparando…' : 'Descargar Excel'}</Button>
      </Box>
      <Typography variant="body2" color="text.secondary">
        Lo que pide el buffer del CEDI de los ítems que se compran en cada empresa, con su proveedor, costo y múltiplo de pedido. Es solo una propuesta para validar: no crea ni envía órdenes.
      </Typography>
      {d.aviso && <Alert severity="warning">{d.aviso}</Alert>}
      {err && <Alert severity="error">{err}</Alert>}
      {d.truncado && <Alert severity="info">Se muestran los primeros ítems por criticidad: filtra por proveedor, categoría o zona, o baja el Excel.</Alert>}
      <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap' }}>
        <Kpi t="Proveedores" v={(t.proveedores ?? 0).toLocaleString('es-CO')} />
        <Kpi t="Ítems a pedir" v={(t.items ?? 0).toLocaleString('es-CO')} sub={`${Math.round(t.unidades ?? 0).toLocaleString('es-CO')} unidades`} />
        <Kpi t="Valor sin IVA" v={MM(t.valor ?? 0)} sub="solo ítems con cotización" />
        <Kpi t="IVA estimado" v={MM(t.iva ?? 0)} />
        <Kpi t="Total" v={MM(t.total ?? 0)} />
        <Kpi t="Sin cotización" v={(t.sin_costo ?? 0).toLocaleString('es-CO')} sub="no suman al valor" color="#b45309" />
        <Kpi t="Poca historia" v={(t.poca_historia ?? 0).toLocaleString('es-CO')} sub={`< ${d.config.poca_historia_meses ?? 3} meses con venta`} color="#b45309" />
        <Kpi t={bloquea ? 'Bloqueados por mínimo' : 'Bajo el pedido mínimo'} v={(bloquea ? (t.bloqueados ?? 0) : (t.bajo_minimo ?? 0)).toLocaleString('es-CO')} color="#c62828"
          sub={bloquea ? 'no se muestran' : 'con alerta'} />
      </Box>
      <Paper variant="outlined" sx={{ p: 1, display: 'flex', flexWrap: 'wrap', gap: 1, alignItems: 'center' }}>
        <Autocomplete multiple size="small" limitTags={1} sx={{ minWidth: 240, flex: '1 1 240px', maxWidth: 380 }} value={provs}
          options={[...new Map(d.proveedores.map((p: any) => [p.proveedor_id, p])).keys()] as string[]}
          getOptionLabel={(id: string) => { const p = d.proveedores.find((x: any) => x.proveedor_id === id); return p ? `${id} · ${p.proveedor_nombre ?? ''}` : id }}
          onChange={(_, v) => setProvs(v)} renderInput={p => <TextField {...p} label="Proveedor(es)" />} />
        <Autocomplete multiple size="small" limitTags={1} sx={{ minWidth: 200, flex: '0 1 260px' }} value={cats} options={Object.keys(CATEGORIAS)} getOptionLabel={(c: string) => CATEGORIAS[c] ?? c}
          onChange={(_, v) => setCats(v)} renderInput={p => <TextField {...p} label="Categoría" />} />
        <Autocomplete multiple size="small" limitTags={1} sx={{ minWidth: 200, flex: '0 1 260px' }} value={labs} options={opcLabs.map(l => l.codigo)}
          getOptionLabel={(c: string) => { const l = opcLabs.find(x => x.codigo === c); return l?.nombre ? `${c} · ${l.nombre}` : c }}
          onChange={(_, v) => setLabs(v)} renderInput={p => <TextField {...p} label="Laboratorio" />} />
        <Autocomplete multiple size="small" limitTags={2} sx={{ minWidth: 170, flex: '0 1 200px' }} value={zonas} options={ZONAS} onChange={(_, v) => setZonas(v)} renderInput={p => <TextField {...p} label="Zona" />} />
        <TextField size="small" label="Item o descripción" value={qd} onChange={e => setQd(e.target.value)} sx={{ width: 200 }} />
        {(provs.length || cats.length || labs.length || zonas.length || qd) ? <Button size="small" onClick={() => { setProvs([]); setCats([]); setLabs([]); setZonas([]); setQd('') }}>Quitar filtros</Button> : null}
      </Paper>
      <Tabs value={tab} onChange={(_, v) => setTab(v)} sx={{ minHeight: 36, '& .MuiTab-root': { minHeight: 36, textTransform: 'none' } }}>
        <Tab label={`Por proveedor (${d.proveedores.length})`} />
        <Tab label={`Detalle por ítem (${d.filas.length})`} />
        <Tab label={<Tooltip title="Ítems que se compran y tienen necesidad, pero ni su cotización ni el ítem en Siesa traen proveedor: hay que asignarlo para que entren a la compra"><span>Sin proveedor ({d.sin_proveedor.total.toLocaleString('es-CO')})</span></Tooltip>} />
        {d.bloqueados.length > 0 && <Tab label={`Bloqueados por pedido mínimo (${d.bloqueados.length})`} />}
      </Tabs>
      <Box className="ag-theme-quartz" sx={{ flex: 1, minHeight: 320 }}>
        {tab === 0 && <Tabla textoCargando="Calculando…" vacio="Sin necesidades con estos filtros" rowData={d.proveedores} columnDefs={colsProv} cargando={cargando} defaultColDef={{ resizable: true, sortable: true }}
          onRowDoubleClicked={(e: any) => { if (e.data) { setProvs([e.data.proveedor_id]); setTab(1) } }} tooltipShowDelay={300} />}
        {tab === 1 && <Tabla textoCargando="Calculando…" vacio="Sin necesidades con estos filtros" rowData={d.filas} columnDefs={colsDet} cargando={cargando} rowBuffer={20} tooltipShowDelay={300} defaultColDef={{ resizable: true, sortable: true }} />}
        {tab === 2 && <Tabla textoCargando="Calculando…" vacio="Todos los ítems con necesidad tienen proveedor" rowData={d.sin_proveedor.filas} columnDefs={colsSin} cargando={cargando} defaultColDef={{ resizable: true, sortable: true }} />}
        {tab === 3 && <Tabla vacio="Ninguno" rowData={d.bloqueados} columnDefs={colsProv} defaultColDef={{ resizable: true, sortable: true }} />}
      </Box>
      <Typography variant="caption" color="text.secondary">
        Doble clic en un proveedor para ver sus ítems. Las alertas (sin cotización, poca historia, proveedor inactivo, redondeo a 0) no bloquean: son para revisar. El redondeo y el pedido mínimo se configuran en Maestros de compras.
      </Typography>
    </Box>)
}
