import { useEffect, useMemo, useState } from 'react'
import Tabla from '../Tabla'
import { ColDef, CellClickedEvent } from 'ag-grid-community'
import { Alert, Autocomplete, Box, Button, Card, Paper, Tab, Tabs, TextField, Tooltip, Typography } from '@mui/material'
import Download from '@mui/icons-material/Download'
import HelpOutline from '@mui/icons-material/HelpOutline'
import { api, bajar } from '../api'
import { useEmpresa } from '../Empresa'
import { GuiaNecesidades } from '../guias'

const num = (p: any) => p.value == null ? '' : Number(p.value).toLocaleString('es-CO', { maximumFractionDigits: 2 })
const ent = (p: any) => p.value == null ? '' : Math.round(Number(p.value)).toLocaleString('es-CO')
const COP = (p: any) => p.value == null ? '' : '$' + Math.round(p.value).toLocaleString('es-CO')
const MM = (v: number) => '$' + (Math.abs(v) >= 1e6 ? (v / 1e6).toLocaleString('es-CO', { maximumFractionDigits: 1 }) + ' M' : Math.round(v).toLocaleString('es-CO'))
const ZONA: Record<string, string> = { ROJA: '#c62828', AMARILLA: '#f9a825', VERDE: '#2e7d32', EXCESO: '#1565c0' }
const CATEGORIAS: Record<string, string> = { '0001': '0001 · Productos Funat', '0002': '0002 · Productos de terceros', '0003': '0003 · Maquila Funat' }
const ZONAS = ['ROJA', 'AMARILLA', 'VERDE', 'EXCESO']
const ENLACE = { color: '#1565c0', cursor: 'pointer', textDecoration: 'underline' }   // celdas en las que se hace clic

type Resp = { config: Record<string, number>; ejecucion: { id: number; fecha_calculo: string } | null; aviso: string | null; filas: any[]; proveedores: any[]; bloqueados: any[]
  sin_proveedor: { total: number; filas: any[] }; totales: Record<string, number>; truncado: boolean }
const VACIO: Resp = { config: {}, ejecucion: null, aviso: null, filas: [], proveedores: [], bloqueados: [], sin_proveedor: { total: 0, filas: [] }, totales: {}, truncado: false }

/** Tooltip que sale ARRIBA y se apaga mientras la lista del filtro está abierta: así nunca tapa las opciones. */
function AutoMulti({ ayuda, label, value, options, getOptionLabel, onChange, sx }: { ayuda: string; label: string; value: string[]; options: string[]
  getOptionLabel: (c: string) => string; onChange: (v: string[]) => void; sx?: any }) {
  const [abierto, setAbierto] = useState(false)
  return (
    <Tooltip title={abierto ? '' : ayuda} placement="top-start" disableInteractive enterDelay={600}>
      <Autocomplete multiple size="small" limitTags={1} sx={sx} value={value} options={options} getOptionLabel={getOptionLabel}
        onOpen={() => setAbierto(true)} onClose={() => setAbierto(false)} onChange={(_, v) => onChange(v)} renderInput={p => <TextField {...p} label={label} />} />
    </Tooltip>)
}

function Kpi({ t, v, sub, color, ayuda }: { t: string; v: string; sub?: string; color?: string; ayuda: string }) {
  return (
    <Tooltip title={ayuda} placement="top" disableInteractive enterDelay={400}>
      <Card variant="outlined" sx={{ p: 1.25, minWidth: 140, flex: '1 1 140px', borderLeft: `4px solid ${color ?? '#6b8e23'}` }}>
        <Typography variant="caption" color="text.secondary">{t}</Typography>
        <Typography sx={{ fontSize: 22, fontWeight: 700, lineHeight: 1.2 }}>{v}</Typography>
        {sub && <Typography variant="caption" color="text.secondary">{sub}</Typography>}
      </Card>
    </Tooltip>)
}

export default function Necesidades() {
  const { lista: empresa } = useEmpresa()
  const [d, setD] = useState<Resp>(VACIO)
  const [cargando, setCargando] = useState(true); const [err, setErr] = useState('')
  const [tab, setTab] = useState(0); const [guia, setGuia] = useState(false)
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

  // clic en el proveedor → sus ítems; clic en inventario / ADU → Control DDMRP con ese ítem en todas las tiendas más el CEDI
  const alProveedor = (e: CellClickedEvent) => {
    if (e.data && ['proveedor_nombre', 'items'].includes(e.colDef.field ?? '')) { setProvs([e.data.proveedor_id]); setTab(1) }
  }
  const alDetalle = (e: CellClickedEvent) => {
    if (e.data && ['inventario', 'adu'].includes(e.colDef.field ?? '')) window.open(`/control?item=${encodeURIComponent(e.data.producto_id)}&modo=todos`, '_blank', 'noopener')
  }

  const t = d.totales
  const colsProv: ColDef[] = useMemo(() => [
    { field: 'proveedor_id', headerName: 'NIT', width: 120, pinned: 'left', filter: true, headerTooltip: 'NIT del proveedor (el de la cotización vigente; si no hay, el del ítem en Siesa)' },
    { field: 'proveedor_nombre', headerName: 'Proveedor', width: 280, pinned: 'left', filter: true, cellStyle: ENLACE, headerTooltip: 'Haz clic en un proveedor para ver sus ítems' },
    { field: 'empresa', headerName: 'Emp.', width: 70, filter: true, headerTooltip: 'Empresa (05 Funat, 21 Stores): cada una tiene su CEDI' },
    { field: 'items', headerName: 'Ítems', type: 'numericColumn', width: 90, valueFormatter: ent, cellStyle: ENLACE, headerTooltip: 'Ítems con necesidad de este proveedor. Clic para verlos' },
    { field: 'unidades', headerName: 'Unidades', type: 'numericColumn', width: 110, valueFormatter: ent, headerTooltip: 'Unidades a pedir (ya llevadas al múltiplo de pedido)' },
    { field: 'valor', headerName: 'Valor sin IVA', type: 'numericColumn', width: 140, valueFormatter: COP, sort: 'desc', headerTooltip: 'Suma de los ítems con costo; los ítems sin cotización no suman' },
    { field: 'iva', headerName: 'IVA estimado', type: 'numericColumn', width: 130, valueFormatter: COP, headerTooltip: 'Tarifa estimada: Siesa calcula el IVA real al crear la OC' },
    { field: 'total', headerName: 'Total', type: 'numericColumn', width: 140, valueFormatter: COP, headerTooltip: 'Valor sin IVA + IVA estimado' },
    { field: 'pedido_minimo', headerName: 'Pedido mínimo', type: 'numericColumn', width: 130, valueFormatter: COP, headerTooltip: 'Valor mínimo de una orden a este proveedor (maestro de proveedores)' },
    { field: 'sin_costo', headerName: 'Sin cotización', type: 'numericColumn', width: 120, valueFormatter: ent, headerTooltip: 'Ítems sin ningún costo: no suman al valor, por eso el total puede quedar corto' },
    { field: 'poca_historia', headerName: 'Poca historia', type: 'numericColumn', width: 120, valueFormatter: ent, headerTooltip: 'Ítems con pocos meses de venta: el ADU puede no ser confiable' },
    { field: 'redondeo', headerName: 'Redondeo', width: 100, headerTooltip: 'Cómo se lleva la cantidad al múltiplo de pedido de este proveedor (maestro de proveedores)' },
    { field: 'estado', headerName: 'Estado', width: 230, headerTooltip: 'OK · Bajo el pedido mínimo · Incompleto (ítems sin cotización) · Proveedor inactivo',
      cellStyle: (p: any): Record<string, string | number> => p.value === 'OK' ? { color: '#2e7d32' } : { color: '#b45309', fontWeight: 600 } },
  ], [])
  const colsDet: ColDef[] = useMemo(() => [
    { field: 'producto_id', headerName: 'SKU', width: 100, pinned: 'left', filter: true, headerTooltip: 'Código del producto' },
    { field: 'descripcion', headerName: 'Ítem', width: 260, pinned: 'left', filter: true, headerTooltip: 'Nombre del ítem' },
    { field: 'empresa', headerName: 'Emp.', width: 70, filter: true, headerTooltip: 'Empresa (05 Funat, 21 Stores)' },
    { field: 'proveedor_nombre', headerName: 'Proveedor', width: 200, filter: true, headerTooltip: 'Proveedor de la cotización vigente (o del ítem si no hay cotización)' },
    { field: 'categoria', headerName: 'Categoría', width: 200, filter: true, headerTooltip: 'Categoría de Siesa (plan 001): productos Funat, de terceros o maquila' },
    { field: 'lab_nombre', headerName: 'Laboratorio', width: 160, filter: true, headerTooltip: 'Laboratorio del ítem' },
    { field: 'zona', headerName: 'Zona', width: 100, filter: true, cellStyle: (p: any) => ({ color: ZONA[p.value] ?? '#333', fontWeight: 700 }), headerTooltip: 'Zona del buffer del CEDI: roja (urgente), amarilla (reponer), verde, exceso' },
    { field: 'adu', headerName: 'ADU (u/mes)', type: 'numericColumn', width: 110, valueFormatter: num, cellStyle: ENLACE,
      headerTooltip: 'Rotación mensual del CEDI: venta de las tiendas que abastece + venta directa. Clic: ver la rotación por tienda y CEDI' },
    { field: 'lead_time', headerName: 'Lead time (d)', type: 'numericColumn', width: 110, valueFormatter: ent, headerTooltip: 'Días de reposición: ítem, proveedor o general (30)' },
    { field: 'inventario', headerName: 'Inventario', type: 'numericColumn', width: 110, valueFormatter: ent, cellStyle: ENLACE,
      headerTooltip: 'Stock disponible del CEDI. Clic: ver el saldo por tienda y CEDI' },
    { field: 'en_transito', headerName: 'Tránsito', type: 'numericColumn', width: 100, valueFormatter: ent, headerTooltip: 'Saldo de órdenes de compra abiertas hacia el CEDI' },
    { field: 'flujo_neto', headerName: 'Flujo neto', type: 'numericColumn', width: 110, valueFormatter: ent, headerTooltip: 'Inventario + tránsito − demanda calificada. Con esto se decide si se pide' },
    { field: 'tog_aj', headerName: 'TOG aj.', type: 'numericColumn', width: 100, valueFormatter: ent, headerTooltip: 'Tope verde ajustado: hasta donde se repone' },
    { field: 'cobertura_dias', headerName: 'Cobertura (días)', type: 'numericColumn', width: 120, valueFormatter: num, headerTooltip: 'Días que dura el inventario actual al ritmo del ADU' },
    { field: 'qty_buffer', headerName: 'Pide el buffer', type: 'numericColumn', width: 120, valueFormatter: ent, headerTooltip: 'Lo que pide el buffer del CEDI (hasta el tope verde), antes del múltiplo de pedido' },
    { field: 'unidad_pedido', headerName: 'Unidad de pedido', type: 'numericColumn', width: 130, valueFormatter: num, headerTooltip: 'Múltiplo en que se pide al proveedor (maestro de ítems de compras)' },
    { field: 'qty_pedir', headerName: 'A pedir', type: 'numericColumn', width: 100, valueFormatter: ent, cellStyle: { fontWeight: 700 }, headerTooltip: 'Cantidad llevada al múltiplo de la unidad de pedido según el redondeo del proveedor' },
    { field: 'costo', headerName: 'Costo', type: 'numericColumn', width: 120, headerTooltip: 'Cotización manual › cotización de Siesa › última compra. Sin ninguno: “Sin cotización”',
      valueFormatter: (p: any) => p.value == null ? 'Sin cotización' : '$' + Number(p.value).toLocaleString('es-CO', { maximumFractionDigits: 2 }), cellStyle: (p: any) => p.value == null ? { color: '#b45309', fontWeight: 600 } : undefined },
    { field: 'origen_costo', headerName: 'Origen del costo', width: 130, headerTooltip: 'De dónde sale el costo: Manual, Cotización o Última compra' },
    { field: 'costo_fecha', headerName: 'Costo vigente desde', width: 140, headerTooltip: 'Fecha de la cotización o de la última compra: una fecha muy vieja pide revisar el costo' },
    { field: 'valor', headerName: 'Valor sin IVA', type: 'numericColumn', width: 130, valueFormatter: COP, headerTooltip: 'A pedir × costo' },
    { field: 'iva_tasa', headerName: 'IVA % (est.)', type: 'numericColumn', width: 110, valueFormatter: num, headerTooltip: 'Tarifa estimada del grupo impositivo del ítem' },
    { field: 'total', headerName: 'Total', type: 'numericColumn', width: 130, valueFormatter: COP, headerTooltip: 'Valor + IVA estimado' },
    { field: 'alertas', headerName: 'Alertas', width: 280, cellStyle: (p: any) => p.value ? { color: '#b45309' } : undefined,
      headerTooltip: 'Sin cotización · Poca historia · Proveedor inactivo · Redondeo a 0. No bloquean: son para revisar' },
  ], [])
  const colsSin: ColDef[] = useMemo(() => [
    { field: 'producto_id', headerName: 'SKU', width: 100, pinned: 'left', filter: true, headerTooltip: 'Código del producto' },
    { field: 'descripcion', headerName: 'Ítem', width: 280, pinned: 'left', filter: true, headerTooltip: 'Nombre del ítem' },
    { field: 'empresa', headerName: 'Emp.', width: 70, filter: true, headerTooltip: 'Empresa (05 Funat, 21 Stores)' },
    { field: 'categoria', headerName: 'Categoría', width: 200, filter: true, headerTooltip: 'Categoría de Siesa (plan 001)' },
    { field: 'lab_nombre', headerName: 'Laboratorio', width: 160, filter: true, headerTooltip: 'Laboratorio del ítem' },
    { field: 'zona', headerName: 'Zona', width: 100, filter: true, cellStyle: (p: any) => ({ color: ZONA[p.value] ?? '#333', fontWeight: 700 }), headerTooltip: 'Zona del buffer del CEDI' },
    { field: 'adu', headerName: 'ADU (u/mes)', type: 'numericColumn', width: 110, valueFormatter: num, headerTooltip: 'Rotación mensual del CEDI' },
    { field: 'flujo_neto', headerName: 'Flujo neto', type: 'numericColumn', width: 110, valueFormatter: ent, headerTooltip: 'Inventario + tránsito − demanda calificada' },
    { field: 'qty_buffer', headerName: 'Pide el buffer', type: 'numericColumn', width: 120, valueFormatter: ent, headerTooltip: 'Lo que pide el buffer. Falta asignar un proveedor (en Siesa o con una cotización) para poder comprarlo' },
  ], [])

  const bloquea = (d.config.pedido_minimo_bloquea ?? 0) >= 1
  const hayFiltro = !!(provs.length || cats.length || labs.length || zonas.length || qd)
  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', height: '100%', gap: 1.25, minHeight: 520 }}>
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, flexWrap: 'wrap' }}>
        <Typography variant="h6" sx={{ fontWeight: 700, flex: 1 }}>Necesidades de compra del CEDI</Typography>
        {d.ejecucion && <Typography variant="caption" color="text.secondary">Corrida del motor: {d.ejecucion.fecha_calculo} · pedido mínimo: {bloquea ? 'bloquea' : 'solo alerta'}</Typography>}
        <Tooltip title="Cómo se calcula cada número y cómo leer la pantalla" placement="top" disableInteractive>
          <Button size="small" startIcon={<HelpOutline />} onClick={() => setGuia(true)}>¿Cómo funciona?</Button></Tooltip>
        <Tooltip title="Baja lo filtrado con la hoja “Cálculo CEDI”: todo el cálculo en fórmulas, con las ventas de los últimos meses" placement="top" disableInteractive>
          <span><Button variant="outlined" startIcon={<Download />} onClick={excel} disabled={bajando || !d.filas.length}>{bajando ? 'Preparando…' : 'Descargar Excel'}</Button></span></Tooltip>
      </Box>
      <Typography variant="body2" color="text.secondary">
        Lo que pide el buffer del CEDI de los ítems que se compran en cada empresa, con su proveedor, costo y múltiplo de pedido. Es solo una propuesta para validar: no crea ni envía órdenes.
      </Typography>
      {d.aviso && <Alert severity="warning">{d.aviso}</Alert>}
      {err && <Alert severity="error">{err}</Alert>}
      {d.truncado && <Alert severity="info">Se muestran los primeros ítems por criticidad: filtra por proveedor, categoría o zona, o baja el Excel.</Alert>}
      <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap' }}>
        <Kpi t="Proveedores" v={(t.proveedores ?? 0).toLocaleString('es-CO')} ayuda="Proveedores con algo que pedir con los filtros actuales" />
        <Kpi t="Ítems a pedir" v={(t.items ?? 0).toLocaleString('es-CO')} sub={`${Math.round(t.unidades ?? 0).toLocaleString('es-CO')} unidades`} ayuda="Ítems comprables con necesidad según el buffer del CEDI, y las unidades a pedir (ya al múltiplo)" />
        <Kpi t="Valor sin IVA" v={MM(t.valor ?? 0)} sub="solo ítems con cotización" ayuda="Suma de A pedir × costo de los ítems que tienen costo" />
        <Kpi t="IVA estimado" v={MM(t.iva ?? 0)} ayuda="Tarifa estimada del grupo impositivo; Siesa calcula el IVA real al crear la orden" />
        <Kpi t="Total" v={MM(t.total ?? 0)} ayuda="Valor sin IVA + IVA estimado" />
        <Kpi t="Sin cotización" v={(t.sin_costo ?? 0).toLocaleString('es-CO')} sub="no suman al valor" color="#b45309" ayuda="Ítems sin ningún costo (ni manual, ni cotización, ni última compra): hay que cargarles uno" />
        <Kpi t="Poca historia" v={(t.poca_historia ?? 0).toLocaleString('es-CO')} sub={`< ${d.config.poca_historia_meses ?? 3} meses con venta`} color="#b45309" ayuda="Ítems con pocos meses de venta: el ADU puede no ser confiable. Solo es una alerta" />
        <Kpi t={bloquea ? 'Bloqueados por mínimo' : 'Bajo el pedido mínimo'} v={(bloquea ? (t.bloqueados ?? 0) : (t.bajo_minimo ?? 0)).toLocaleString('es-CO')} color="#c62828"
          sub={bloquea ? 'no se muestran' : 'con alerta'} ayuda="Proveedores cuyo valor queda por debajo de su pedido mínimo (se configura en Maestros de compras → Configuración de compras)" />
      </Box>
      <Paper variant="outlined" sx={{ p: 1, display: 'flex', flexWrap: 'wrap', gap: 1, alignItems: 'center' }}>
        <AutoMulti ayuda="Filtra por uno o varios proveedores" label="Proveedor(es)" value={provs} sx={{ minWidth: 240, flex: '1 1 240px', maxWidth: 380 }}
          options={[...new Map(d.proveedores.map((p: any) => [p.proveedor_id, p])).keys()] as string[]}
          getOptionLabel={(id: string) => { const p = d.proveedores.find((x: any) => x.proveedor_id === id); return p ? `${id} · ${p.proveedor_nombre ?? ''}` : id }} onChange={setProvs} />
        <AutoMulti ayuda="Categoría de Siesa: productos Funat, de terceros o maquila" label="Categoría" value={cats} sx={{ minWidth: 200, flex: '0 1 260px' }}
          options={Object.keys(CATEGORIAS)} getOptionLabel={(c: string) => CATEGORIAS[c] ?? c} onChange={setCats} />
        <AutoMulti ayuda="Laboratorio del ítem" label="Laboratorio" value={labs} sx={{ minWidth: 200, flex: '0 1 260px' }} options={opcLabs.map(l => l.codigo)}
          getOptionLabel={(c: string) => { const l = opcLabs.find(x => x.codigo === c); return l?.nombre ? `${c} · ${l.nombre}` : c }} onChange={setLabs} />
        <AutoMulti ayuda="Zona del buffer del CEDI: roja es lo más urgente" label="Zona" value={zonas} sx={{ minWidth: 170, flex: '0 1 200px' }} options={ZONAS} getOptionLabel={(c: string) => c} onChange={setZonas} />
        <Tooltip title="Busca por SKU o por parte del nombre" placement="top-start" disableInteractive enterDelay={600}>
          <TextField size="small" label="Item o descripción" value={qd} onChange={e => setQd(e.target.value)} sx={{ width: 200 }} /></Tooltip>
        {hayFiltro ? <Button size="small" onClick={() => { setProvs([]); setCats([]); setLabs([]); setZonas([]); setQd('') }}>Quitar filtros</Button> : null}
      </Paper>
      <Tabs value={tab} onChange={(_, v) => setTab(v)} sx={{ minHeight: 36, '& .MuiTab-root': { minHeight: 36, textTransform: 'none' } }}>
        <Tab label={<Tooltip title="Total a pedir por proveedor: valor, IVA, pedido mínimo y estado" placement="top" disableInteractive><span>Por proveedor ({d.proveedores.length})</span></Tooltip>} />
        <Tab label={<Tooltip title="Cada ítem con su cálculo: buffer, múltiplo, costo y valor" placement="top" disableInteractive><span>Detalle por ítem ({d.filas.length})</span></Tooltip>} />
        <Tab label={<Tooltip title="Ítems que se compran y tienen necesidad, pero ni su cotización ni el ítem en Siesa traen proveedor: hay que asignarlo para que entren a la compra" placement="top" disableInteractive><span>Sin proveedor ({d.sin_proveedor.total.toLocaleString('es-CO')})</span></Tooltip>} />
        {d.bloqueados.length > 0 && <Tab label={<Tooltip title="Proveedores que quedaron bajo su pedido mínimo y se bloquearon (configuración de compras)" placement="top" disableInteractive><span>Bloqueados por pedido mínimo ({d.bloqueados.length})</span></Tooltip>} />}
      </Tabs>
      <Box className="ag-theme-quartz" sx={{ flex: 1, minHeight: 320 }}>
        {tab === 0 && <Tabla textoCargando="Calculando…" vacio="Sin necesidades con estos filtros" rowData={d.proveedores} columnDefs={colsProv} cargando={cargando} tooltipShowDelay={300}
          defaultColDef={{ resizable: true, sortable: true }} onCellClicked={alProveedor} />}
        {tab === 1 && <Tabla textoCargando="Calculando…" vacio="Sin necesidades con estos filtros" rowData={d.filas} columnDefs={colsDet} cargando={cargando} rowBuffer={20} tooltipShowDelay={300}
          defaultColDef={{ resizable: true, sortable: true }} onCellClicked={alDetalle} />}
        {tab === 2 && <Tabla textoCargando="Calculando…" vacio="Todos los ítems con necesidad tienen proveedor" rowData={d.sin_proveedor.filas} columnDefs={colsSin} cargando={cargando} tooltipShowDelay={300}
          defaultColDef={{ resizable: true, sortable: true }} />}
        {tab === 3 && <Tabla vacio="Ninguno" rowData={d.bloqueados} columnDefs={colsProv} tooltipShowDelay={300} defaultColDef={{ resizable: true, sortable: true }} />}
      </Box>
      <Typography variant="caption" color="text.secondary">
        Clic en un proveedor para ver sus ítems · clic en el inventario o el ADU de un ítem para ver su saldo y rotación en todas las tiendas más el CEDI · arrastra una columna hasta la raya para fijarla.
      </Typography>
      <GuiaNecesidades abierta={guia} cerrar={() => setGuia(false)} cfg={d.config} />
    </Box>)
}
