import { useEffect, useMemo, useRef, useState } from 'react'
import Tabla from '../Tabla'
import { ColDef, CellClickedEvent, CellValueChangedEvent, GridApi, ICellRendererParams } from 'ag-grid-community'
import { Alert, Autocomplete, Box, Button, Card, Checkbox, Chip, Dialog, DialogActions, DialogContent, DialogTitle, MenuItem, Paper, Tab, Table, TableBody, TableCell, TableHead, TableRow, Tabs, TextField, Tooltip, Typography } from '@mui/material'
import Download from '@mui/icons-material/Download'
import HelpOutline from '@mui/icons-material/HelpOutline'
import Refresh from '@mui/icons-material/Refresh'
import SendIcon from '@mui/icons-material/Send'
import { useSearchParams } from 'react-router-dom'
import { api, bajar, conProgreso } from '../api'
import { useYo } from '../Yo'
import { useEmpresa } from '../Empresa'
import { GuiaNecesidades } from '../guias'

const haceDias = (n: number) => new Date(Date.now() - n * 864e5 - 5 * 36e5).toISOString().slice(0, 10)      // fecha de Colombia (UTC-5)
const ESTADOS_OC = ['en_bpm', 'en_revision', 'aprobada', 'rechazada', 'creada', 'anulada', 'error', 'incierta', 'cancelada']
const num = (p: any) => p.value == null ? '' : Number(p.value).toLocaleString('es-CO', { maximumFractionDigits: 2 })
const ent = (p: any) => p.value == null ? '' : Math.round(Number(p.value)).toLocaleString('es-CO')
const colorOC = (e: string) => e === 'creada' ? '#2e7d32' : e === 'anulada' ? '#757575' : ['plano', 'en_bpm', 'en_revision', 'aprobada'].includes(e) ? '#1565c0' : e === 'incierta' ? '#b45309' : '#c62828'
const COP = (p: any) => p.value == null ? '' : '$' + Math.round(p.value).toLocaleString('es-CO')
const MM = (v: number) => '$' + (Math.abs(v) >= 1e6 ? (v / 1e6).toLocaleString('es-CO', { maximumFractionDigits: 1 }) + ' M' : Math.round(v).toLocaleString('es-CO'))
const ZONA: Record<string, string> = { ROJA: '#c62828', AMARILLA: '#f9a825', VERDE: '#2e7d32', EXCESO: '#1565c0' }
const CATEGORIAS: Record<string, string> = { '0001': '0001 · Productos Funat', '0002': '0002 · Productos de terceros', '0003': '0003 · Maquila Funat' }
const ZONAS = ['ROJA', 'AMARILLA', 'VERDE', 'EXCESO']
const COL_DEF = { resizable: true, sortable: true }   // con identidad fija: un objeto nuevo en cada render hace que AG Grid redefina las columnas y se pierda el orden que movió el usuario
const ENLACE = { color: '#1565c0', cursor: 'pointer', textDecoration: 'underline' }   // celdas en las que se hace clic

type Resp = { config: Record<string, number>; ejecucion: { id: number; fecha_calculo: string } | null; aviso: string | null; filas: any[]; proveedores: any[]; bloqueados: any[]
  sin_proveedor: { total: number; filas: any[] }; totales: Record<string, number>; truncado: boolean }
const VACIO: Resp = { config: {}, ejecucion: null, aviso: null, filas: [], proveedores: [], bloqueados: [], sin_proveedor: { total: 0, filas: [] }, totales: {}, truncado: false }

const kItem = (f: any) => `${f.empresa}|${f.proveedor_id}|${f.sucursal}|${f.producto_id}`
const kProv = (p: any) => `${p.empresa}|${p.proveedor_id}|${p.sucursal}`
const esCasilla = (e: CellClickedEvent) => !!(e.event?.target as HTMLElement | null)?.closest?.('.chk-oc')   // el clic fue en la casilla, no en el texto
const abrir = (ruta: string) => window.open(ruta, '_blank', 'noopener')

/** SKU con su casilla (para elegir el ítem de la OC que se va a montar); el texto es un enlace al maestro de ítems de compras. */
function CasillaItem(p: ICellRendererParams) {
  const k = kItem(p.data); const ctx = p.context
  return (
    <Box sx={{ display: 'flex', alignItems: 'center', height: '100%' }}>
      <Checkbox className="chk-oc" size="small" sx={{ p: .25, mr: .5 }} checked={ctx.sel.has(k)} onChange={() => ctx.alternarItem(k)} />
      <span style={ENLACE}>{p.value}</span>
    </Box>)
}
/** NIT con su casilla (elige TODOS los ítems del proveedor); el texto es un enlace al maestro de proveedores. */
function CasillaProv(p: ICellRendererParams) {
  const items: any[] = p.context.itemsDeProv.get(kProv(p.data)) ?? []
  const n = items.filter(i => p.context.sel.has(kItem(i))).length
  return (
    <Box sx={{ display: 'flex', alignItems: 'center', height: '100%' }}>
      <Checkbox className="chk-oc" size="small" sx={{ p: .25, mr: .5 }} checked={n > 0 && n === items.length} indeterminate={n > 0 && n < items.length} onChange={() => p.context.alternarProv(p.data)} />
      <span style={ENLACE}>{p.value}</span>
    </Box>)
}

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
  const { puede } = useYo(); const gestiona = puede('gestionar_compras')
  const [d, setD] = useState<Resp>(VACIO)
  const [cargando, setCargando] = useState(true); const [err, setErr] = useState(''); const [msg, setMsg] = useState('')
  const [tab, setTab] = useState(0); const [guia, setGuia] = useState(false); const [ocAbierta, setOcAbierta] = useState(false)
  const [provs, setProvs] = useState<string[]>([]); const [cats, setCats] = useState<string[]>([]); const [zonas, setZonas] = useState<string[]>([])
  const [sp] = useSearchParams(); const qUrl = sp.get('q') ?? ''      // enlace desde el BPM: /compras/necesidades?q=<item>
  const [labs, setLabs] = useState<string[]>([]); const [qd, setQd] = useState(qUrl); const [q, setQ] = useState(qUrl)
  const [opcLabs, setOpcLabs] = useState<{ codigo: string; nombre?: string }[]>([])
  const [bajando, setBajando] = useState(false); const [recalculando, setRecalculando] = useState(false)
  const [sel, setSel] = useState<Set<string>>(new Set())      // ítems elegidos para la OC (por proveedor o uno a uno)
  const [recarga, setRecarga] = useState(0); const silenciosa = useRef(false)
  const [ocDestino, setOcDestino] = useState('directo')
  const [ocExigir, setOcExigir] = useState(true)      // «Entiendo que se envía…»: se puede quitar en Configuración de compras (oc_exigir_entiendo = 0)
  const [histDias, setHistDias] = useState(30)
  useEffect(() => { api('/compras/oc/config').then(x => { setOcDestino(x.destino); setOcExigir(x.exigir_entiendo !== false); if (x.listado_dias > 0) { setHistDias(x.listado_dias); setHistF(f => ({ ...f, desde: haceDias(x.listado_dias) })) } }).catch(() => {}) }, [])
  const [ocEnviando, setOcEnviando] = useState(false); const [ocEntiendo, setOcEntiendo] = useState(false)
  const [ocRes, setOcRes] = useState<{ ordenes: any[]; avisos: string[] } | null>(null); const [ocErr, setOcErr] = useState('')
  const [histAbierta, setHistAbierta] = useState(false); const [hist, setHist] = useState<any[]>([]); const [histCarga, setHistCarga] = useState(false)
  const [histF, setHistF] = useState({ desde: haceDias(30), hasta: '', estado: '', proveedor: '', q: '', creado_por: '' })      // por defecto: últimos 30 días
  const apiDet = useRef<GridApi | null>(null); const apiProv = useRef<GridApi | null>(null)
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
    let vivo = true
    if (!silenciosa.current) setCargando(true)      // tras editar una cantidad se recarga sin tapar la tabla con el aviso de carga
    silenciosa.current = false; setErr('')
    api('/compras/necesidades?' + qs).then(r => vivo && setD(r)).catch(e => vivo && setErr(e.message)).finally(() => vivo && setCargando(false))
    return () => { vivo = false }
  }, [qs, recarga])
  const recargar = () => { silenciosa.current = true; setRecarga(x => x + 1) }
  const excel = async () => { setBajando(true); setErr(''); try { await bajar('/compras/necesidades/excel?' + qs, 'necesidades_compra.xlsx') } catch (e: any) { setErr(e.message) } finally { setBajando(false) } }

  // ---- selección: por proveedor (todos sus ítems) o ítem por ítem; ambas valen a la vez
  const itemsDeProv = useMemo(() => { const m = new Map<string, any[]>(); d.filas.forEach(f => { const k = kProv(f); m.set(k, [...(m.get(k) ?? []), f]) }); return m }, [d.filas])
  const alternarItem = (k: string) => setSel(x => { const n = new Set(x); if (n.has(k)) n.delete(k); else n.add(k); return n })
  const alternarProv = (p: any) => setSel(x => {
    const items = itemsDeProv.get(kProv(p)) ?? []; const n = new Set(x)
    if (items.length && items.every(i => n.has(kItem(i)))) items.forEach(i => n.delete(kItem(i))); else items.forEach(i => n.add(kItem(i)))
    return n
  })
  const ctx = useMemo(() => ({ sel, alternarItem, alternarProv, itemsDeProv }), [sel, itemsDeProv])
  useEffect(() => { for (const a of [apiDet.current, apiProv.current]) { try { if (a && !a.isDestroyed()) a.refreshCells({ force: true }) } catch { /* tabla ya cerrada */ } } }, [sel, d.filas, tab])
  const elegidas = useMemo(() => d.filas.filter(f => sel.has(kItem(f))), [d.filas, sel])
  const resumenSel = useMemo(() => {
    const g = new Map<string, any>()
    for (const f of elegidas) {
      const k = kProv(f)
      const r = g.get(k) ?? { empresa: f.empresa, proveedor_id: f.proveedor_id, sucursal: f.sucursal, proveedor_nombre: f.proveedor_nombre, cond_pago: f.cond_pago, activo: !!f.prov_activo, pedido_minimo: f.pedido_minimo, items: 0, unidades: 0, valor: 0, iva: 0, total: 0, sin_costo: 0, editadas: 0, no_multiplo: 0 }
      r.items++; r.unidades += f.qty_pedir
      if (f.valor == null) r.sin_costo++; else { r.valor += f.valor; r.iva += f.iva ?? 0; r.total += f.total ?? 0 }
      if (f.editada) { r.editadas++; if (f.unidad_pedido > 1 && Math.abs(f.qty_manual / f.unidad_pedido - Math.round(f.qty_manual / f.unidad_pedido)) > 1e-9) r.no_multiplo++ }
      g.set(k, r)
    }
    return [...g.values()].map(r => ({ ...r, bajo_minimo: !!(r.pedido_minimo && r.pedido_minimo > 0 && r.items > r.sin_costo && r.valor < r.pedido_minimo) }))
  }, [elegidas])

  // ---- órdenes de compra a Siesa
  const cuerpoOC = (soloPlano: boolean) => JSON.stringify({ items: elegidas.map(f => ({ empresa: f.empresa, producto_id: f.producto_id })), solo_plano: soloPlano })
  const enviarOC = async (soloPlano: boolean) => {
    setOcEnviando(true); setOcErr(''); setOcRes(null)
    try {
      const r = await api('/compras/oc/enviar', { method: 'POST', body: cuerpoOC(soloPlano) })
      setOcRes(r)
      if (!soloPlano) { setSel(new Set()); setOcEntiendo(false); recargar() }      // el resultado queda a la vista con el botón «Ir a OC enviadas a Siesa»
    } catch (e: any) { setOcErr(e.message || String(e)) } finally { setOcEnviando(false) }
  }
  const bajarPlano = (o: any) => {
    const b = new Blob([o.plano], { type: 'text/plain;charset=utf-8' }); const u = URL.createObjectURL(b); const a = document.createElement('a')
    a.href = u; a.download = `plano_oc_${o.empresa}_${o.proveedor_id}.txt`; a.click(); URL.revokeObjectURL(u)
  }
  const cargarHist = async (f = histF) => {
    setHistCarga(true)
    try {
      const p = new URLSearchParams({ limit: '500' })
      for (const [k, v] of Object.entries(f)) if (String(v).trim()) p.set(k, String(v).trim())
      if (empresa.length === 1) p.set('empresa', empresa[0])
      setHist((await api('/compras/oc?' + p.toString())).datos)
    } catch (e: any) { setOcErr(e.message || String(e)) } finally { setHistCarga(false) }
  }
  const irAEnviadas = () => { setOcAbierta(false); setOcRes(null); setHistAbierta(true); cargarHist() }
  const accionOC = async (id: number, que: 'reconsultar' | 'reenviar') => {
    try { const r = await api(`/compras/oc/${id}/${que}`, { method: 'POST' }); setMsg(`OC ${id}: ${r.estado}${r.consecutivo ? ' · ' + r.consecutivo : ''} — ${r.mensaje}`) } catch (e: any) { setMsg(e.message || String(e)) }
    cargarHist()
  }

  // ---- acciones
  const alProveedor = (e: CellClickedEvent) => {
    if (!e.data || esCasilla(e)) return
    const c = e.colDef.field ?? ''
    if (c === 'proveedor_id') abrir(`/compras/maestros?maestro=proveedores&q=${encodeURIComponent(e.data.proveedor_id)}`)      // NIT → maestro de proveedores
    else if (['proveedor_nombre', 'items'].includes(c)) { setProvs([e.data.proveedor_id]); setTab(1) }                          // proveedor → sus ítems
  }
  const alDetalle = (e: CellClickedEvent) => {
    if (!e.data || esCasilla(e)) return
    const c = e.colDef.field ?? ''
    if (c === 'producto_id') abrir(`/compras/maestros?maestro=items-compras&q=${encodeURIComponent(e.data.producto_id)}`)      // SKU → maestro de ítems de compras
    else if (['inventario', 'adu'].includes(c)) abrir(`/control?item=${encodeURIComponent(e.data.producto_id)}&modo=todos`)    // saldo y rotación: tiendas + CEDI
  }
  const alEditar = async (e: CellValueChangedEvent) => {
    if (!e.data) return
    if (e.colDef.field === 'costo') {
      const nc: number | null = e.newValue == null || e.newValue === '' ? null : Number(e.newValue)
      const costo = nc != null && nc === e.data.costo_calculado ? null : nc      // igual a la cotización = no es una edición
      try {
        await api('/compras/costo', { method: 'PUT', body: JSON.stringify({ empresa: e.data.empresa, producto_id: e.data.producto_id, costo }) })
        setMsg(costo == null ? `${e.data.producto_id}: vuelve al costo de la cotización` : `${e.data.producto_id}: costo $${costo.toLocaleString('es-CO')} guardado (se conserva hasta que se monte la OC)`)
      } catch (x: any) { setErr(x.message) }
      recargar(); return
    }
    if (e.colDef.field !== 'qty_pedir') return
    const nuevo: number | null = e.newValue == null || e.newValue === '' ? null : Number(e.newValue)
    const cantidad = nuevo != null && nuevo === e.data.qty_calculada ? null : nuevo     // si queda igual al cálculo no es una edición
    try {
      await api('/compras/cantidad', { method: 'PUT', body: JSON.stringify({ empresa: e.data.empresa, producto_id: e.data.producto_id, cantidad }) })
      setMsg(cantidad == null ? `${e.data.producto_id}: vuelve a la cantidad calculada` : `${e.data.producto_id}: cantidad a pedir ${cantidad.toLocaleString('es-CO')} guardada (se conserva hasta que se monte la OC)`)
    } catch (x: any) { setErr(x.message) }
    recargar()
  }
  const recalcular = async () => {
    setRecalculando(true); setErr(''); setMsg('')
    try {
      await conProgreso(setMsg, () => api('/compras/recalcular', { method: 'POST' }))
      setMsg('Necesidades recalculadas con el inventario y las órdenes de compra de ahora. Las cantidades que editaste se conservaron.')
      recargar()
    } catch (e: any) { setMsg(''); setErr(e.message) } finally { setRecalculando(false) }
  }

  const t = d.totales
  const colsProv: ColDef[] = useMemo(() => [
    { field: 'proveedor_id', headerName: 'NIT', width: 150, pinned: 'left', filter: true, cellRenderer: CasillaProv,
      headerTooltip: 'La casilla elige TODOS los ítems de este proveedor para la OC. Clic en el NIT: abre el proveedor en el maestro (lead time, correos, redondeo…)' },
    { field: 'proveedor_nombre', headerName: 'Proveedor', width: 280, pinned: 'left', filter: true, cellStyle: ENLACE, headerTooltip: 'Haz clic en un proveedor para ver sus ítems' },
    { field: 'empresa', headerName: 'Emp.', width: 70, filter: true, headerTooltip: 'Empresa (05 Funat, 21 Stores): cada una tiene su CEDI' },
    { field: 'cond_pago', headerName: 'Cond. pago', width: 110, valueFormatter: (p: any) => p.value || 'Falta', cellStyle: (p: any) => p.value ? undefined : { color: '#c62828', fontWeight: 600 },
      headerTooltip: 'Condición de pago de la OC (código de Siesa, ej. C30), del maestro de proveedores. Se pre-llena con la de la última OC; sin ella no se podrá crear la OC' },
    { field: 'leadtime', headerName: 'Lead time (d)', type: 'numericColumn', width: 120, valueFormatter: ent, headerTooltip: 'Lead time del proveedor en el maestro de proveedores (vacío = se usa el del ítem o el general de 8 días)' },
    { field: 'frecuencia', headerName: 'Frecuencia (d)', type: 'numericColumn', width: 120, valueFormatter: ent, headerTooltip: 'Cada cuántos días se le compra a este proveedor (maestro de proveedores; vacío = el general de Configuración de compras, 15). Define el tamaño de la zona verde: más frecuencia, pedidos más grandes' },
    { field: 'items', headerName: 'Ítems', type: 'numericColumn', width: 90, valueFormatter: ent, cellStyle: ENLACE, headerTooltip: 'Ítems con necesidad de este proveedor. Clic para verlos' },
    { headerName: 'Elegidos', width: 100, type: 'numericColumn', headerTooltip: 'Ítems de este proveedor que elegiste para la OC',
      valueGetter: (p: any) => p.data ? (p.context.itemsDeProv.get(kProv(p.data)) ?? []).filter((i: any) => p.context.sel.has(kItem(i))).length : null },
    { field: 'unidades', headerName: 'Unidades', type: 'numericColumn', width: 110, valueFormatter: ent, headerTooltip: 'Unidades a pedir (ya llevadas al múltiplo de pedido, o las que editó compras)' },
    { field: 'valor', headerName: 'Valor sin IVA', type: 'numericColumn', width: 140, valueFormatter: COP, sort: 'desc', headerTooltip: 'Suma de los ítems con costo; los ítems sin cotización no suman' },
    { field: 'iva', headerName: 'IVA estimado', type: 'numericColumn', width: 130, valueFormatter: COP, headerTooltip: 'Tarifa estimada: Siesa calcula el IVA real al crear la OC' },
    { field: 'total', headerName: 'Total', type: 'numericColumn', width: 140, valueFormatter: COP, headerTooltip: 'Valor sin IVA + IVA estimado' },
    { field: 'pedido_minimo', headerName: 'Pedido mínimo', type: 'numericColumn', width: 130, valueFormatter: COP, headerTooltip: 'Valor mínimo de una orden a este proveedor (maestro de proveedores)' },
    { field: 'sin_costo', headerName: 'Sin cotización', type: 'numericColumn', width: 120, valueFormatter: ent, headerTooltip: 'Ítems sin ningún costo: no suman al valor, por eso el total puede quedar corto' },
    { field: 'poca_historia', headerName: 'Poca historia', type: 'numericColumn', width: 120, valueFormatter: ent, headerTooltip: 'Ítems con pocos meses de venta: el ADU puede no ser confiable' },
    { field: 'editadas', headerName: 'Editadas', type: 'numericColumn', width: 100, valueFormatter: ent, headerTooltip: 'Ítems cuya cantidad a pedir editó compras' },
    { field: 'redondeo', headerName: 'Redondeo', width: 100, headerTooltip: 'Cómo se lleva la cantidad al múltiplo de pedido de este proveedor (maestro de proveedores)' },
    { field: 'estado', headerName: 'Estado', width: 230, headerTooltip: 'OK · Bajo el pedido mínimo · Sin condición de pago · Incompleto (ítems sin cotización) · Proveedor inactivo',
      cellStyle: (p: any): Record<string, string | number> => p.value === 'OK' ? { color: '#2e7d32' } : { color: '#b45309', fontWeight: 600 } },
  ], [])
  const colsDet: ColDef[] = useMemo(() => [
    { field: 'producto_id', headerName: 'SKU', width: 140, pinned: 'left', filter: true, cellRenderer: CasillaItem,
      headerTooltip: 'La casilla elige este ítem para la OC. Clic en el SKU: abre el ítem en el maestro de ítems de compras (cotización, unidad de pedido…)' },
    { field: 'descripcion', headerName: 'Ítem', width: 260, pinned: 'left', filter: true, headerTooltip: 'Nombre del ítem' },
    { field: 'empresa', headerName: 'Emp.', width: 70, filter: true, headerTooltip: 'Empresa (05 Funat, 21 Stores)' },
    { field: 'proveedor_nombre', headerName: 'Proveedor', width: 200, filter: true, headerTooltip: 'Proveedor de la cotización vigente (o del ítem si no hay cotización)' },
    { field: 'categoria', headerName: 'Categoría', width: 200, filter: true, headerTooltip: 'Categoría de Siesa (plan 001): productos Funat, de terceros o maquila' },
    { field: 'lab_nombre', headerName: 'Laboratorio', width: 160, filter: true, headerTooltip: 'Laboratorio del ítem' },
    { field: 'zona', headerName: 'Zona', width: 100, filter: true, cellStyle: (p: any) => ({ color: ZONA[p.value] ?? '#333', fontWeight: 700 }), headerTooltip: 'Zona del buffer del CEDI: roja (urgente), amarilla (reponer), verde, exceso' },
    { field: 'adu', headerName: 'ADU (u/mes)', type: 'numericColumn', width: 110, valueFormatter: num, cellStyle: ENLACE,
      headerTooltip: 'Rotación mensual del CEDI: venta de las tiendas que abastece + venta directa. Clic: ver la rotación por tienda y CEDI' },
    { field: 'lead_time', headerName: 'Lead time (d)', type: 'numericColumn', width: 110, valueFormatter: ent, headerTooltip: 'Días de reposición que usa el buffer: ítem, proveedor o general (8)' },
    { field: 'inventario', headerName: 'Inventario', type: 'numericColumn', width: 110, valueFormatter: ent, cellStyle: ENLACE,
      headerTooltip: 'Stock disponible del CEDI. Clic: ver el saldo por tienda y CEDI' },
    { field: 'en_transito', headerName: 'Tránsito', type: 'numericColumn', width: 100, valueFormatter: ent, headerTooltip: 'Saldo de órdenes de compra abiertas hacia el CEDI' },
    { field: 'flujo_neto', headerName: 'Flujo neto', type: 'numericColumn', width: 110, valueFormatter: ent, headerTooltip: 'Inventario + tránsito − demanda calificada. Con esto se decide si se pide' },
    { field: 'tog_aj', headerName: 'TOG aj.', type: 'numericColumn', width: 100, valueFormatter: ent, headerTooltip: 'Tope verde ajustado: hasta donde se repone' },
    { field: 'cobertura_dias', headerName: 'Cobertura (días)', type: 'numericColumn', width: 120, valueFormatter: num, headerTooltip: 'Días que dura el inventario actual al ritmo del ADU' },
    { field: 'qty_buffer', headerName: 'Pide el buffer', type: 'numericColumn', width: 120, valueFormatter: ent, headerTooltip: 'Lo que pide el buffer del CEDI (hasta el tope verde), antes del múltiplo de pedido' },
    { field: 'unidad_pedido', headerName: 'Unidad de pedido', type: 'numericColumn', width: 130, valueFormatter: num, headerTooltip: 'Múltiplo en que se pide al proveedor (maestro de ítems de compras)' },
    { field: 'moq', headerName: 'MOQ (u.)', type: 'numericColumn', width: 100, valueFormatter: num, headerTooltip: 'Cantidad mínima de compra del ítem (maestro de ítems de compras; por defecto 1). Si el pedido queda por debajo, sube a este mínimo' },
    { field: 'qty_calculada', headerName: 'Calculada', type: 'numericColumn', width: 110, valueFormatter: ent, headerTooltip: 'Lo que pide el buffer llevado al múltiplo de pedido con el redondeo del proveedor (sin tus ediciones)' },
    { field: 'qty_pedir', headerName: gestiona ? 'A pedir (editable)' : 'A pedir', type: 'numericColumn', width: 140, valueFormatter: ent, editable: gestiona,
      valueParser: (p: any) => { const t = String(p.newValue ?? '').trim().replace(',', '.'); if (t === '') return null; const n = Number(t); return Number.isFinite(n) && n >= 0 ? n : p.oldValue },
      cellStyle: (p: any): Record<string, string | number> => p.data?.editada ? { fontWeight: 700, background: '#fff4ce' } : { fontWeight: 700 },
      headerTooltip: 'Cantidad que se va a pedir. Haz doble clic para editarla; vacía = vuelve al cálculo. Lo que edites se conserva aunque corra el motor, hasta que se monte la OC' },
    { field: 'costo', headerName: gestiona ? 'Costo (editable)' : 'Costo', type: 'numericColumn', width: 140, editable: gestiona,
      valueParser: (p: any) => { const t = String(p.newValue ?? '').trim().replace(',', '.'); if (t === '') return null; const n = Number(t); return Number.isFinite(n) && n > 0 ? n : p.oldValue },
      headerTooltip: 'Cotización manual › cotización de Siesa › última compra. Sin ninguno: “Sin cotización”. Doble clic para editarlo (vacío = vuelve a la cotización); si sube mucho frente a la cotización, la OC pasa a revisión',
      valueFormatter: (p: any) => p.value == null ? 'Sin cotización' : '$' + Number(p.value).toLocaleString('es-CO', { maximumFractionDigits: 2 }),
      cellStyle: (p: any): Record<string, string | number> | undefined => p.data?.costo_editado ? { fontWeight: 700, background: '#fff4ce' } : p.value == null ? { color: '#b45309', fontWeight: 600 } : undefined },
    { field: 'origen_costo', headerName: 'Origen del costo', width: 130, headerTooltip: 'De dónde sale el costo: Manual, Cotización o Última compra' },
    { field: 'costo_fecha', headerName: 'Costo vigente desde', width: 140, headerTooltip: 'Fecha de la cotización o de la última compra: una fecha muy vieja pide revisar el costo' },
    { field: 'valor', headerName: 'Valor sin IVA', type: 'numericColumn', width: 130, valueFormatter: COP, headerTooltip: 'A pedir × costo' },
    { field: 'iva_tasa', headerName: 'IVA % (est.)', type: 'numericColumn', width: 110, valueFormatter: num, headerTooltip: 'Tarifa estimada del grupo impositivo del ítem' },
    { field: 'total', headerName: 'Total', type: 'numericColumn', width: 130, valueFormatter: COP, headerTooltip: 'Valor + IVA estimado' },
    { field: 'alertas', headerName: 'Alertas', width: 320, cellStyle: (p: any) => p.value ? { color: '#b45309' } : undefined,
      headerTooltip: 'Sin cotización · Poca historia · Proveedor inactivo · Redondeo a 0 · Subió al MOQ · Cantidad editada (no múltiplo, más del doble, menor que el MOQ). No bloquean: son para revisar' },
  ], [gestiona])
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
  const nProvSel = resumenSel.length
  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', height: '100%', gap: 1.25, minHeight: 520 }}>
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, flexWrap: 'wrap' }}>
        <Typography variant="h6" sx={{ fontWeight: 700, flex: 1 }}>Necesidades de compra del CEDI</Typography>
        {d.ejecucion && <Typography variant="caption" color="text.secondary">Corrida del motor: {d.ejecucion.fecha_calculo} · pedido mínimo: {bloquea ? 'bloquea' : 'solo alerta'}</Typography>}
        {gestiona && <Tooltip title="Vuelve a calcular el buffer del CEDI con el inventario y las órdenes de compra de ahora, sin correr el motor completo. Tus cantidades editadas se conservan" placement="top" disableInteractive>
          <span><Button size="small" variant="outlined" startIcon={<Refresh />} onClick={recalcular} disabled={recalculando}>{recalculando ? 'Recalculando…' : 'Recalcular necesidades'}</Button></span></Tooltip>}
        <Tooltip title="Cómo se calcula cada número y cómo leer la pantalla" placement="top" disableInteractive>
          <Button size="small" startIcon={<HelpOutline />} onClick={() => setGuia(true)}>¿Cómo funciona?</Button></Tooltip>
        <Tooltip title="Baja lo filtrado con la hoja “Cálculo CEDI”: todo el cálculo en fórmulas, con las ventas de los últimos meses" placement="top" disableInteractive>
          <span><Button variant="outlined" startIcon={<Download />} onClick={excel} disabled={bajando || !d.filas.length}>{bajando ? 'Preparando…' : 'Descargar Excel'}</Button></span></Tooltip>
      </Box>
      <Typography variant="body2" color="text.secondary">
        Lo que pide el buffer del CEDI de los ítems que se compran en cada empresa, con su proveedor, costo y múltiplo de pedido. Edita la cantidad a pedir si hace falta, elige lo que vas a montar y revisa la OC. Todavía no se envía nada: eso viene con la aprobación.
      </Typography>
      {d.aviso && <Alert severity="warning">{d.aviso}</Alert>}
      {err && <Alert severity="error" onClose={() => setErr('')}>{err}</Alert>}
      {msg && <Alert severity="success" onClose={() => setMsg('')}>{msg}</Alert>}
      {d.truncado && <Alert severity="info">Se muestran los primeros ítems por criticidad: filtra por proveedor, categoría o zona, o baja el Excel.</Alert>}
      <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap' }}>
        <Kpi t="Proveedores" v={(t.proveedores ?? 0).toLocaleString('es-CO')} ayuda="Proveedores con algo que pedir con los filtros actuales" />
        <Kpi t="Ítems a pedir" v={(t.items ?? 0).toLocaleString('es-CO')} sub={`${Math.round(t.unidades ?? 0).toLocaleString('es-CO')} unidades`} ayuda="Ítems comprables con necesidad según el buffer del CEDI (o con cantidad editada), y las unidades a pedir" />
        <Kpi t="Valor sin IVA" v={MM(t.valor ?? 0)} sub="solo ítems con cotización" ayuda="Suma de A pedir × costo de los ítems que tienen costo" />
        <Kpi t="IVA estimado" v={MM(t.iva ?? 0)} ayuda="Tarifa estimada del grupo impositivo; Siesa calcula el IVA real al crear la orden" />
        <Kpi t="Total" v={MM(t.total ?? 0)} ayuda="Valor sin IVA + IVA estimado" />
        <Kpi t="Editadas" v={(t.editadas ?? 0).toLocaleString('es-CO')} sub="cantidad cambiada por compras" color="#1565c0" ayuda="Ítems cuya cantidad a pedir editó compras: se conservan hasta que se monte la OC" />
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
      <Paper variant="outlined" sx={{ p: .75, px: 1.25, display: 'flex', flexWrap: 'wrap', gap: 1, alignItems: 'center' }}>
        <Typography variant="body2" sx={{ fontWeight: 600 }}>OC a montar</Typography>
        <Chip size="small" color={elegidas.length ? 'primary' : 'default'} label={elegidas.length ? `${elegidas.length.toLocaleString('es-CO')} ítems · ${nProvSel} proveedor${nProvSel === 1 ? '' : 'es'}` : 'Nada elegido'} />
        <Tooltip title="Elige todos los ítems que se ven con los filtros actuales" placement="top" disableInteractive>
          <span><Button size="small" disabled={!d.filas.length} onClick={() => setSel(new Set(d.filas.map(kItem)))}>Elegir todo lo filtrado</Button></span></Tooltip>
        <Button size="small" disabled={!sel.size} onClick={() => setSel(new Set())}>Quitar elección</Button>
        <Tooltip title="Vuelve las columnas de las tres pestañas a su orden, ancho y columnas fijas originales (tu vista se guarda sola en este navegador)" placement="top" disableInteractive>
          <Button size="small" onClick={() => { ['necesidades_proveedor', 'necesidades_detalle', 'necesidades_sin_proveedor'].forEach(k => { try { localStorage.removeItem('ddmrp_vista_' + k) } catch { /* nada */ } })
            for (const a of [apiDet.current, apiProv.current]) { try { if (a && !a.isDestroyed()) a.resetColumnState() } catch { /* tabla ya cerrada */ } } }}>Restablecer columnas</Button></Tooltip>
        <Typography variant="caption" color="text.secondary" sx={{ flex: 1 }}>La casilla del NIT elige todo el proveedor; la del SKU, un ítem. Puedes combinar ambas.</Typography>
        <Tooltip title={gestiona ? 'Revisa por proveedor lo que vas a montar: cantidades, valores y alertas' : 'Tu perfil no tiene permiso para enviar órdenes de compra'} placement="top" disableInteractive>
          <span><Button variant="contained" size="small" startIcon={<SendIcon />} disabled={!elegidas.length || !gestiona} onClick={() => setOcAbierta(true)}>Revisar y enviar OC</Button></span></Tooltip>
        <Button size="small" onClick={() => { setHistAbierta(true); cargarHist() }}>OC enviadas a Siesa</Button>
      </Paper>
      <Tabs value={tab} onChange={(_, v) => setTab(v)} sx={{ minHeight: 36, '& .MuiTab-root': { minHeight: 36, textTransform: 'none' } }}>
        <Tab label={<Tooltip title="Total a pedir por proveedor: valor, IVA, lead time, pedido mínimo y estado" placement="top" disableInteractive><span>Por proveedor ({d.proveedores.length})</span></Tooltip>} />
        <Tab label={<Tooltip title="Cada ítem con su cálculo: buffer, múltiplo, costo y valor. Aquí se edita la cantidad a pedir" placement="top" disableInteractive><span>Detalle por ítem ({d.filas.length})</span></Tooltip>} />
        <Tab label={<Tooltip title="Ítems que se compran y tienen necesidad, pero ni su cotización ni el ítem en Siesa traen proveedor: hay que asignarlo para que entren a la compra" placement="top" disableInteractive><span>Sin proveedor ({d.sin_proveedor.total.toLocaleString('es-CO')})</span></Tooltip>} />
        {d.bloqueados.length > 0 && <Tab label={<Tooltip title="Proveedores que quedaron bajo su pedido mínimo y se bloquearon (configuración de compras)" placement="top" disableInteractive><span>Bloqueados por pedido mínimo ({d.bloqueados.length})</span></Tooltip>} />}
      </Tabs>
      <Box className="ag-theme-quartz" sx={{ flex: 1, minHeight: 320 }}>
        {tab === 0 && <Tabla memoria="necesidades_proveedor" textoCargando="Calculando…" vacio="Sin necesidades con estos filtros" rowData={d.proveedores} columnDefs={colsProv} cargando={cargando} tooltipShowDelay={300}
          context={ctx} getRowId={(p: any) => kProv(p.data)} onGridReady={(e: any) => { apiProv.current = e.api }}
          defaultColDef={COL_DEF} onCellClicked={alProveedor} />}
        {tab === 1 && <Tabla memoria="necesidades_detalle" textoCargando="Calculando…" vacio="Sin necesidades con estos filtros" rowData={d.filas} columnDefs={colsDet} cargando={cargando} rowBuffer={20} tooltipShowDelay={300}
          context={ctx} getRowId={(p: any) => kItem(p.data)} onGridReady={(e: any) => { apiDet.current = e.api }} stopEditingWhenCellsLoseFocus
          defaultColDef={COL_DEF} onCellClicked={alDetalle} onCellValueChanged={alEditar} />}
        {tab === 2 && <Tabla memoria="necesidades_sin_proveedor" textoCargando="Calculando…" vacio="Todos los ítems con necesidad tienen proveedor" rowData={d.sin_proveedor.filas} columnDefs={colsSin} cargando={cargando} tooltipShowDelay={300}
          defaultColDef={COL_DEF} />}
        {tab === 3 && <Tabla vacio="Ninguno" rowData={d.bloqueados} columnDefs={colsProv} tooltipShowDelay={300} context={ctx} defaultColDef={COL_DEF} />}
      </Box>
      <Typography variant="caption" color="text.secondary">
        Clic en el nombre del proveedor para ver sus ítems · NIT → maestro de proveedores · SKU → maestro de ítems de compras · inventario o ADU → saldo y rotación en todas las tiendas más el CEDI · doble clic en “A pedir” para editar · arrastra una columna hasta la raya para fijarla.
      </Typography>
      <Dialog open={ocAbierta} onClose={() => setOcAbierta(false)} maxWidth="lg" fullWidth>
        <DialogTitle sx={{ fontWeight: 700 }}>Revisar las OC a montar</DialogTitle>
        <DialogContent dividers>
          <Typography variant="body2" sx={{ mb: 1 }}>Una orden por proveedor y empresa, con los {elegidas.length.toLocaleString('es-CO')} ítems elegidos. Revisa las alertas antes de enviar.</Typography>
          <Table size="small">
            <TableHead><TableRow>{['Emp.', 'NIT', 'Proveedor', 'Cond. pago', 'Ítems', 'Unidades', 'Valor sin IVA', 'IVA estimado', 'Total', 'Alertas'].map(h => <TableCell key={h} sx={{ fontWeight: 700 }} align={['Ítems', 'Unidades', 'Valor sin IVA', 'IVA estimado', 'Total'].includes(h) ? 'right' : 'left'}>{h}</TableCell>)}</TableRow></TableHead>
            <TableBody>
              {resumenSel.map(r => {
                const al = [r.sin_costo ? `${r.sin_costo} sin cotización` : '', r.editadas ? `${r.editadas} editadas` : '', r.no_multiplo ? `${r.no_multiplo} no múltiplo` : '', r.bajo_minimo ? 'Bajo el pedido mínimo' : '', !r.cond_pago ? 'Sin condición de pago: no se podrá crear la OC' : '', !r.activo ? 'Proveedor inactivo' : ''].filter(Boolean)
                return (
                  <TableRow key={kProv(r)}>
                    <TableCell>{r.empresa}</TableCell><TableCell>{r.proveedor_id}</TableCell><TableCell>{r.proveedor_nombre}</TableCell><TableCell sx={{ fontWeight: 600, color: r.cond_pago ? 'inherit' : '#c62828' }}>{r.cond_pago || 'Falta'}</TableCell>
                    <TableCell align="right">{r.items}</TableCell><TableCell align="right">{Math.round(r.unidades).toLocaleString('es-CO')}</TableCell>
                    <TableCell align="right">{COP({ value: r.valor })}</TableCell><TableCell align="right">{COP({ value: r.iva })}</TableCell><TableCell align="right" sx={{ fontWeight: 700 }}>{COP({ value: r.total })}</TableCell>
                    <TableCell sx={{ color: al.length ? '#b45309' : '#2e7d32' }}>{al.length ? al.join(' · ') : 'OK'}</TableCell>
                  </TableRow>)
              })}
            </TableBody>
          </Table>
          <Alert severity="warning" sx={{ mt: 1.5 }}>{ocDestino === 'bpm'
            ? <>Al enviar, la OC pasa al <b>BPM</b>: allí se revisa/aprueba y se crea en Siesa (verás el estado en «OC enviadas»). La cantidad y el costo se recalculan en el servidor. «Vista previa» arma el plano sin enviar nada.</>
            : <>Al enviar, la OC se crea <b>en Siesa real</b> (queda aprobada). Si algo sale mal se anula en Siesa. La cantidad y el costo se recalculan en el servidor al enviar. «Vista previa» arma el plano sin enviar nada.</>}</Alert>
          {ocErr && <Alert severity="error" sx={{ mt: 1 }}>{ocErr}</Alert>}
          {ocRes && (
            <Box sx={{ mt: 1 }}>
              {ocRes.avisos.length > 0 && <Alert severity="info" sx={{ mb: 1 }}>{ocRes.avisos.join(' · ')}</Alert>}
              <Table size="small">
                <TableHead><TableRow>{['Emp.', 'Proveedor', 'Ítems', 'Valor', 'Resultado', 'OC Siesa', 'Detalle', ''].map(h => <TableCell key={h} sx={{ fontWeight: 700 }}>{h}</TableCell>)}</TableRow></TableHead>
                <TableBody>{ocRes.ordenes.map((o, k) => (
                  <TableRow key={k}>
                    <TableCell>{o.empresa}</TableCell><TableCell>{o.proveedor_nombre}</TableCell><TableCell>{o.items}</TableCell><TableCell>{COP({ value: o.valor })}</TableCell>
                    <TableCell sx={{ fontWeight: 700, color: colorOC(o.estado) }}>{o.estado}</TableCell>
                    <TableCell>{o.consecutivo ?? o.referencia ?? ''}</TableCell><TableCell sx={{ maxWidth: 420, wordBreak: 'break-word' }}>{o.mensaje}</TableCell>
                    <TableCell>{o.plano && <Button size="small" onClick={() => bajarPlano(o)}>Bajar plano</Button>}</TableCell>
                  </TableRow>))}</TableBody>
              </Table>
            </Box>)}
        </DialogContent>
        <DialogActions>
          <Box sx={{ flex: 1, pl: 1 }}>{ocExigir && <label style={{ fontSize: 13 }}><Checkbox size="small" checked={ocEntiendo} onChange={e => setOcEntiendo(e.target.checked)} />{ocDestino === 'bpm' ? 'Entiendo que se envía al BPM' : 'Entiendo que se crea en Siesa real'}</label>}</Box>
          {ocRes && !ocRes.ordenes.every(o => o.estado === 'plano') && <Button variant="outlined" onClick={irAEnviadas}>Ir a OC enviadas a Siesa</Button>}
          <Button onClick={() => setOcAbierta(false)}>Cerrar</Button>
          <Button disabled={ocEnviando || !elegidas.length} onClick={() => enviarOC(true)}>Vista previa del plano</Button>
          <Button variant="contained" disabled={ocEnviando || (ocExigir && !ocEntiendo) || !elegidas.length} startIcon={<SendIcon />} onClick={() => enviarOC(false)}>{ocEnviando ? 'Enviando…' : ocDestino === 'bpm' ? 'Enviar al BPM' : 'Crear OC en Siesa'}</Button>
        </DialogActions>
      </Dialog>
      <Dialog open={histAbierta} onClose={() => setHistAbierta(false)} maxWidth="xl" fullWidth>
        <DialogTitle sx={{ fontWeight: 700 }}>OC enviadas a Siesa</DialogTitle>
        <DialogContent dividers>
          <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap', alignItems: 'center', mb: 1.5 }}>
            <TextField size="small" type="date" label="Desde" InputLabelProps={{ shrink: true }} value={histF.desde} onChange={e => setHistF({ ...histF, desde: e.target.value })} sx={{ width: 150 }} />
            <TextField size="small" type="date" label="Hasta" InputLabelProps={{ shrink: true }} value={histF.hasta} onChange={e => setHistF({ ...histF, hasta: e.target.value })} sx={{ width: 150 }} />
            <TextField size="small" select label="Estado" value={histF.estado} onChange={e => setHistF({ ...histF, estado: e.target.value })} sx={{ width: 150 }}>
              <MenuItem value="">Todos</MenuItem>{ESTADOS_OC.map(e => <MenuItem key={e} value={e}>{e}</MenuItem>)}</TextField>
            <TextField size="small" label="Proveedor (NIT o nombre)" value={histF.proveedor} onChange={e => setHistF({ ...histF, proveedor: e.target.value })} sx={{ width: 210 }} />
            <TextField size="small" label="Referencia / OC Siesa / #" value={histF.q} onChange={e => setHistF({ ...histF, q: e.target.value })} sx={{ width: 200 }} />
            <TextField size="small" label="Creó" value={histF.creado_por} onChange={e => setHistF({ ...histF, creado_por: e.target.value })} sx={{ width: 140 }} />
            <Button variant="contained" size="small" onClick={() => cargarHist()}>Filtrar</Button>
            <Button size="small" onClick={() => { const f = { desde: haceDias(histDias), hasta: '', estado: '', proveedor: '', q: '', creado_por: '' }; setHistF(f); cargarHist(f) }}>Últimos {histDias} días</Button>
            <Button size="small" onClick={() => { const f = { desde: '', hasta: '', estado: '', proveedor: '', q: '', creado_por: '' }; setHistF(f); cargarHist(f) }}>Ver todas</Button>
          </Box>
          {histCarga && <Typography variant="body2">Cargando…</Typography>}
          <Table size="small">
            <TableHead><TableRow>{['#', 'Fecha', 'Emp.', 'Proveedor', 'Ítems', 'Total', 'Estado', 'OC Siesa', 'En Siesa', 'Referencia', 'Creó', 'Grupo / tomó', 'Mensaje', ''].map(h => <TableCell key={h} sx={{ fontWeight: 700 }}>{h}</TableCell>)}</TableRow></TableHead>
            <TableBody>{hist.map(o => (
              <TableRow key={o.id}>
                <TableCell>{o.id}</TableCell><TableCell>{String(o.creado).slice(0, 16).replace('T', ' ')}</TableCell><TableCell>{o.empresa}</TableCell><TableCell>{o.proveedor_nombre}</TableCell><TableCell>{o.items}</TableCell>
                <TableCell>{COP({ value: Number(o.total) })}</TableCell>
                <TableCell sx={{ fontWeight: 700, color: colorOC(o.estado) }}>{o.estado}</TableCell>
                <TableCell>{o.siesa_consecutivo ?? ''}</TableCell><TableCell>{o.estado_siesa ?? ''}</TableCell><TableCell>{o.referencia}</TableCell><TableCell>{o.creado_por}</TableCell><TableCell>{[o.grupo, o.tomada_por].filter(Boolean).join(' · ')}</TableCell>
                <TableCell sx={{ maxWidth: 360, wordBreak: 'break-word' }}>{o.mensaje}</TableCell>
                <TableCell sx={{ whiteSpace: 'nowrap' }}>
                  {gestiona && ['incierta', 'error'].includes(o.estado) && <Button size="small" onClick={() => accionOC(o.id, 'reconsultar')}>Reconsultar</Button>}
                  {gestiona && ['incierta', 'error'].includes(o.estado) && <Button size="small" onClick={() => accionOC(o.id, 'reenviar')}>Reenviar</Button>}
                </TableCell>
              </TableRow>))}</TableBody>
          </Table>
          {!hist.length && !histCarga && <Typography variant="body2" sx={{ mt: 1 }}>No hay OC con estos filtros{histF.desde && !histF.hasta && !histF.estado && !histF.proveedor && !histF.q && !histF.creado_por ? ` (se muestran los últimos ${histDias} días: usa «Ver todas» para ampliar)` : ''}.</Typography>}
        </DialogContent>
        <DialogActions><Button onClick={() => cargarHist()}>Actualizar</Button><Button onClick={() => setHistAbierta(false)}>Cerrar</Button></DialogActions>
      </Dialog>
      <GuiaNecesidades abierta={guia} cerrar={() => setGuia(false)} cfg={d.config} />
    </Box>)
}
