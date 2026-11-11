import Plegable from '../Plegable'
import { useEffect, useMemo, useRef, useState } from 'react'
import Tabla from '../Tabla'
import { CellValueChangedEvent, ColDef, GridApi } from 'ag-grid-community'
import { Alert, Autocomplete, Box, Button, Checkbox, Chip, Dialog, DialogActions, DialogContent, DialogTitle, FormControlLabel, MenuItem, Paper, Stack, Table, TableBody, TableCell, TableHead, TableRow, TextField, Tooltip, Typography } from '@mui/material'
import AddCircleOutline from '@mui/icons-material/AddCircleOutline'
import Download from '@mui/icons-material/Download'
import Upload from '@mui/icons-material/Upload'
import ContentPaste from '@mui/icons-material/ContentPaste'
import DeleteOutline from '@mui/icons-material/DeleteOutline'
import DeleteSweep from '@mui/icons-material/DeleteSweep'
import CloudSync from '@mui/icons-material/CloudSync'
import Insights from '@mui/icons-material/Insights'
import { api, apiLista, bajar, subir, conProgreso } from '../api'
import Aviso from '../Aviso'
import { useYo } from '../Yo'
import { confirmar, confirmarEscribiendo, esc } from '../alertas'
import PegarGrilla, { ColPegar } from '../PegarGrilla'
import { useEmpresa } from '../Empresa'
import AvisoInfo from '../AvisoInfo'
import { useNavigate, useSearchParams } from 'react-router-dom'
import ArrowBack from '@mui/icons-material/ArrowBack'
import MaestrosHome from './MaestrosHome'

type Filtros = { tienda: boolean; item: boolean; lab: boolean; texto: boolean; empresa?: boolean; empresa_opc?: boolean; mes?: boolean }
type Tienda = { bodega_id: string; nombre: string | null; empresa: string | null }
type Lab = { codigo: string; nombre: string | null }
type Def = { grupo?: string; solo_existentes?: boolean; lectura?: { k: string; t: string }[]; ayuda: string; filtros: Filtros; todas?: boolean; clave: string; label: string; llave: string[]; editable: string[]; tipos: Record<string, string>; sin_reemplazo: boolean; puede_vaciar?: boolean }


const OPERADORES: { v: string; t: string; solo?: 'txt' | 'num' }[] = [
  { v: 'contiene', t: 'contiene', solo: 'txt' }, { v: 'eq', t: '=' }, { v: 'ne', t: '≠' },
  { v: 'gt', t: '>', solo: 'num' }, { v: 'ge', t: '≥', solo: 'num' }, { v: 'lt', t: '<', solo: 'num' }, { v: 'le', t: '≤', solo: 'num' },
  { v: 'vacio', t: 'está vacío' }, { v: 'lleno', t: 'tiene valor' },
]

const resumen = (r: any) =>
  `${r.modo === 'reemplazar' ? 'Reemplazado' : 'Cargado'}: ${r.unicas} filas · ${r.creadas} nuevas · ${r.actualizadas} actualizadas` +
  (r.ignoradas ? ` · ${r.ignoradas} ignoradas (no existen)` : '') +
  (r.repetidas ? ` · ${r.repetidas} repetidas en el archivo (misma llave: se usó la última)` : '') +
  (r.omitidas ? ` · ${r.omitidas} filas omitidas por datos inválidos (ej. ${r.ejemplos_omitidas?.[0] ?? ''})` : '')

/** `grupo`: 'ddmrp' (maestros de abastecimiento a tiendas) o 'compras' (maestros del area de compras): dos pantallas con la misma tabla. */
function ConfigTabla({ grupo = 'ddmrp' }: { grupo?: 'ddmrp' | 'compras' }) {
  const { puede } = useYo(); const pCarga = puede(grupo === 'compras' ? 'cargar_maestros_compras' : 'cargar_maestros'); const pSync = grupo === 'ddmrp' && puede('sincronizar_siesa')
  const [defs, setDefs] = useState<Def[]>([])
  // ?maestro=proveedores&q=900123456 (enlaces desde Necesidades de compra): abre ese maestro ya filtrado por el texto
  const nav = useNavigate()
  const [sp] = useSearchParams(); const maestroUrl = sp.get('maestro') ?? '', qUrl = sp.get('q') ?? ''
  const inicial = maestroUrl || (grupo === 'compras' ? 'items-compras' : 'bitacora')
  const [sel, setSel] = useState(inicial)
  const [rows, setRows] = useState<any[]>([])
  const [cargando, setCargando] = useState(true)
  const [total, setTotal] = useState(0)
  // Filtros de la pantalla. Se resuelven en el SERVIDOR (el maestro puede tener cientos de miles de filas y la pantalla solo trae un pedazo),
  // y son los mismos para la descarga a Excel y para "Eliminar todo lo filtrado". Van atados al maestro con que se escribieron
  const VACIO = { tienda: [] as string[], texto: '', lab: [] as string[], cat: [] as string[], abas: [] as string[], mes: '', emp: '', col: '', op: 'eq', val: '' }
  const [fRaw, setFRaw] = useState({ sel: inicial, ...VACIO, texto: qUrl })
  const f = fRaw.sel === sel ? fRaw : { sel, ...VACIO }
  const setF = (c: Partial<typeof VACIO>) => setFRaw({ ...f, ...c, sel })
  const colActiva = !!(f.col && (f.op === 'vacio' || f.op === 'lleno' || f.val.trim()))
  const hayFiltro = !!(f.tienda.length || f.texto || f.lab.length || f.cat.length || f.abas.length || f.mes || colActiva)
  const [ordenRaw, setOrdenRaw] = useState({ sel: '', col: '', desc: false })   // orden pedido al servidor (columna de la tabla)
  const orden = ordenRaw.sel === sel ? ordenRaw : { sel, col: '', desc: false }
  const filtros = () => {
    const p = new URLSearchParams()
    if (f.tienda.length) p.set('bodega_id', f.tienda.join(','))
    if (f.texto.trim()) p.set('q', f.texto.trim())
    if (f.lab.length) p.set('lab', f.lab.join(','))
    if (f.cat.length) p.set('categoria', f.cat.join(','))
    if (f.abas.length) p.set('abastecimiento', f.abas.join(','))
    if (def?.filtros.mes && f.mes) p.set('mes', f.mes)
    if (def?.filtros.empresa) { p.set('empresa', empresa); p.set('estado', estado) } else if (def?.filtros.empresa_opc && empG) p.set('empresa', empG)
    if (colActiva) { p.set('col', f.col); p.set('op', f.op); if (f.val.trim()) p.set('val', f.val.trim()) }
    return p
  }
  const consulta = () => { const p = filtros(); if (orden.col) { p.set('orden', orden.col); if (orden.desc) p.set('desc', 'true') }; const s = p.toString(); return s ? '?' + s : '' }
  const consultaExcel = () => { const s = filtros().toString(); return s ? '?' + s : '' }
  const [estado, setEstado] = useState('activo')   // items: estado en Siesa
  const { una: empG } = useEmpresa(); const empresa = empG || '05'   // items: se trabaja una empresa a la vez
  const [agregar, setAgregar] = useState(false)
  // «Aplicar configuración sugerida» (maestro de proveedores): análisis del cumplimiento del proveedor en Siesa y lo que se propone
  const [cump, setCump] = useState<null | { cargando: boolean; res: any[]; avisos: string[]; desde: string; marcas: Record<string, boolean> }>(null)
  const [colAbierta, setColAbierta] = useState(false)   // con la lista de columnas abierta el tooltip se apaga: tapaba las primeras opciones
  const [nueva, setNueva] = useState<Record<string, string>>({})
  const [msg, setMsg] = useState('')
  const [pegar, setPegar] = useState(false)
  const [enviando, setEnviando] = useState(false)
  const [modo, setModo] = useState<'actualizar' | 'reemplazar'>('actualizar')
  const [omitir, setOmitir] = useState(false)
  const [grid, setGrid] = useState<GridApi | null>(null)
  const fileRef = useRef<HTMLInputElement>(null)
  const def = defs.find(d => d.clave === sel)

  const [opc, setOpc] = useState<{ tiendas: Tienda[]; laboratorios: Lab[] }>({ tiendas: [], laboratorios: [] })
  useEffect(() => { api('/maestros').then((x: Def[]) => { const mios = x.filter(d => (d.grupo ?? 'ddmrp') === grupo); setDefs(mios); if (mios.length && !mios.some(d => d.clave === inicial)) setSel(mios[0].clave) }); api('/maestros/_opciones').then(setOpc).catch(() => {}) }, [])
  // solo vale la respuesta de la ultima peticion (el usuario sigue escribiendo o cambia de maestro mientras llegan las anteriores)
  const peticion = useRef(0)
  const cargar = () => {
    if (!def) return Promise.resolve()   // aun no llegan las definiciones de los maestros
    const n = ++peticion.current; setCargando(true)
    return apiLista('/maestros/' + sel + consulta()).then(r => { if (n === peticion.current) { setRows(r.datos); setTotal(r.total) } })
      .catch(e => { if (n === peticion.current) setMsg('Error: ' + e.message) }).finally(() => { if (n === peticion.current) setCargando(false) })
  }
  useEffect(() => { setRows([]); setMsg(''); setModo('actualizar') }, [sel])
  useEffect(() => { const t = setTimeout(cargar, f.texto || f.val ? 350 : 0); return () => clearTimeout(t) }, [sel, JSON.stringify(f), empresa, estado, defs.length, orden.col, orden.desc])

  const columnasFiltro = useMemo(() => def ? [...new Set([...def.llave, ...def.editable])] : [], [def])
  const colTexto = (c: string) => !def || def.tipos[c] === 'txt' || (!(c in def.tipos) && c !== 'dia')   // columna de texto (las numéricas son editables num/int o la llave dia)
  const rowKeys = rows[0] ? Object.keys(rows[0]).join(',') : ''   // las columnas solo cambian si cambian los campos, no con cada recarga (así no se pierde el orden elegido)
  const cols: ColDef[] = useMemo(() => {
    if (!def) return []
    const srt = (k: string) => orden.col === k ? (orden.desc ? 'desc' as const : 'asc' as const) : null
    const llave = def.llave.map(k => ({ field: k, sort: srt(k), pinned: k === def.llave[0] ? ('left' as const) : undefined,
      checkboxSelection: pCarga && k === def.llave[0] && !def.sin_reemplazo, headerCheckboxSelection: pCarga && k === def.llave[0] && !def.sin_reemplazo }))
    const desc: ColDef[] = [
      ...(rows[0] && 'bodega_nombre' in rows[0] ? [{ field: 'bodega_nombre', headerName: 'Tienda', width: 200 }] : []),
      ...(rows[0] && 'descripcion' in rows[0] && !def.editable.includes('descripcion') ? [{ field: 'descripcion', width: 240 }] : []),
    ]
    const ed = def.editable.map(k => def.tipos[k] === 'txt'
      ? { field: k, editable: pCarga, sort: srt(k) }
      : { field: k, editable: pCarga, type: 'numericColumn', sort: srt(k) })
    // items: una columna por plan de criterios (el nombre del plan es el encabezado, el criterio es el valor)
    const conocidas = new Set([...def.llave, ...def.editable, 'descripcion', 'bodega_nombre', 'costo', 'estado', 'clase_calc', 'clase', 'venta', 'venta_prom', 'pct_venta', 'pct_acum', ...(def.lectura ?? []).map(c => c.k)])
    const extra: ColDef[] = def.clave === 'items' && rows[0]
      ? Object.keys(rows[0]).filter(k => !conocidas.has(k)).map(k => ({ field: k, headerName: k, width: 190 })) : []
    const ed2 = def.clave === 'items-compras' ? ed.map(c => ayudaItemCompra(c)) : def.clave === 'bitacora' ? ed.map(c => c.field === 'descripcion' ? { ...c, headerName: 'Tienda (nombre)', width: 240 } : c) : def.clave === 'items' ? ed.map(c => c.field === 'categoria' ? { ...c, headerName: 'Laboratorio (código)', width: 150 } : c.field === 'descripcion' ? { ...c, width: 300 } : c) : ed
    const costo: ColDef[] = def.clave === 'items' ? [{ field: 'costo', headerName: 'Costo promedio', type: 'numericColumn', width: 140,
      valueFormatter: p => p.value == null ? '' : '$' + Math.round(p.value).toLocaleString('es-CO'), headerTooltip: 'Costo promedio por instalación (lo trae el ETL desde Siesa). Solo lectura.' }] : []
    const est: ColDef[] = def.clave === 'items' ? [{ field: 'estado', headerName: 'Estado Siesa', width: 120, headerTooltip: 'Estado del item en Siesa (extensión del item). Solo lectura; sin dato = activo.' }] : []
    const clasT: ColDef[] = def.clave === 'clase-tienda' ? [
      { field: 'clase_calc', headerName: 'Clase calculada', width: 130, headerTooltip: 'La que sale de la venta: se ordenan las tiendas de su empresa de la que más vende a la que menos y se acumula el % de la venta. A = hasta el 80 % acumulado, B = hasta el 95 %, C = el resto (cortes y meses en Reglas de pedido). La recalcula el motor en cada corrida. Solo lectura.' },
      { field: 'clase', headerName: 'Clase vigente', width: 120, headerTooltip: 'La que realmente se usa en el reparto del CEDI, los reportes y los filtros: la «Clase fija» si la escribiste; si no, la calculada. Si coinciden, no hay clase fija.' },
      { field: 'venta', headerName: 'Venta medida', type: 'numericColumn', width: 150, headerTooltip: 'Venta neta (sin IVA) de la tienda en los meses cerrados que se miden (Reglas de pedido).', valueFormatter: p => p.value == null ? '' : '$' + Math.round(p.value).toLocaleString('es-CO') },
      { field: 'venta_prom', headerName: 'Venta promedio / mes', type: 'numericColumn', width: 160, headerTooltip: 'Venta medida ÷ los meses cerrados que se midieron: lo que vende la tienda en un mes típico (neta, sin IVA).', valueFormatter: p => p.value == null ? '' : '$' + Math.round(p.value).toLocaleString('es-CO') },
      { field: 'pct_venta', headerName: '% de la venta', type: 'numericColumn', width: 125, headerTooltip: 'Lo que esta tienda vende frente al total de las tiendas de su empresa en los meses medidos.', valueFormatter: p => p.value == null ? '' : Number(p.value).toFixed(1) + ' %' },
      { field: 'pct_acum', headerName: '% acumulado', type: 'numericColumn', width: 120, headerTooltip: 'Suma del % de la venta de esta tienda y de todas las que venden más que ella. Con él se corta A / B / C.', valueFormatter: p => p.value == null ? '' : Number(p.value).toFixed(1) + ' %' }] : []
    // columnas de solo lectura que declara el maestro (p.ej. items de compras: laboratorio, línea, exhibición, costo, proveedor)
    const lect: ColDef[] = (def.lectura ?? []).map((c): ColDef => {
      const base = { field: c.k, headerName: c.t, headerTooltip: (def.clave === 'items-compras' && AYUDA_LECTURA_COMPRA[c.k]) || 'Solo lectura (viene de Siesa)' }
      if (['costo', 'cotizacion_siesa', 'costo_compra', 'costo_otro', 'ultimo_costo'].includes(c.k))
        return { ...base, type: 'numericColumn', width: 130, valueFormatter: (p: any) => p.value == null ? '' : '$' + Math.round(p.value).toLocaleString('es-CO') }
      if (c.k === 'iva_tasa') return { ...base, type: 'numericColumn', width: 120, valueFormatter: (p: any) => p.value == null ? '' : Number(p.value).toLocaleString('es-CO', { maximumFractionDigits: 2 }) + '%',
        headerTooltip: 'Tarifa estimada del grupo impositivo del item; Siesa calcula el IVA real al crear la OC' }
      return { ...base, width: ['proveedor', 'cotizacion_vigencia', 'ultimo_costo_fecha'].includes(c.k) ? 130 : 180 }
    })
    const todas = [...llave, ...desc, ...ed2.map(c => def.clave === 'clase-tienda' && c.field === 'clase_manual' ? { ...c, headerName: 'Clase fija (A/B/C)', width: 150, headerTooltip: 'Opcional: escribe A, B o C para forzar la clase de esta tienda sin importar su venta. Vacía = se usa la calculada.' } : c), ...clasT, ...lect, ...costo, ...est, ...extra]
    if (def.clave === 'proveedores') {   // NIT y nombre fijos a la izquierda; la empresa y la sucursal van después
      const g = (f: string) => todas.find(c => c.field === f) as ColDef
      const nit: ColDef = { ...g('proveedor_id'), headerName: 'NIT', width: 130, pinned: 'left', headerTooltip: 'NIT del proveedor en Siesa. No se edita.', checkboxSelection: pCarga && !def.sin_reemplazo, headerCheckboxSelection: pCarga && !def.sin_reemplazo }
      const nom: ColDef = { ...g('nombre'), headerName: 'Proveedor', width: 280, pinned: 'left', headerTooltip: 'Razón social del proveedor (viene de Siesa). Si la cambias aquí, solo cambia como se ve en DDMRP.' }
      const resto: ColDef[] = todas.filter(c => c.field !== 'proveedor_id' && c.field !== 'nombre').map(c => ({ ...c, pinned: undefined, checkboxSelection: undefined, headerCheckboxSelection: undefined,
        ...(c.field === 'frecuencia' ? { headerName: 'Frecuencia de compra (d)', width: 170, headerTooltip: 'Cada cuántos días se le compra a este proveedor: define el tamaño de la zona verde del CEDI (vacío = el general de Configuración de compras, 15 días)' } : {}),
        ...(c.field === 'cond_pago' ? { headerName: 'Condición de pago', width: 150, headerTooltip: 'Código de Siesa que lleva la OC (ej. C30). Se pre-llena con la de la última OC del proveedor y lo que escribas no se pisa; sin ella no se crea la OC' } : {}),
        ...(c.field === 'leadtime' ? { headerName: 'Lead time (d)', width: 120, headerTooltip: 'Días que tarda en llegar lo que se le pide (vacío = el del ítem o el general, 8 días)' } : {}),
        ...(AYUDA_PROVEEDOR[c.field as string] ?? {}) }))
      return [nit, nom, ...resto]
    }
    return todas
  }, [def, rowKeys, pCarga, orden.col, orden.desc])

  const onChange = async (e: CellValueChangedEvent) => {
    if (!def) return
    try {
      const llave = Object.fromEntries(def.llave.map(k => [k, String(e.data[k])]))
      const txt = def.tipos[e.colDef.field!] === 'txt'
      const valor = e.newValue === '' || e.newValue == null ? null : txt ? String(e.newValue) : Number(e.newValue)
      await api('/maestros/' + sel, { method: 'PATCH', body: JSON.stringify([{ llave, campo: e.colDef.field, valor }]) })
      setMsg('Guardado')
    } catch (x: any) { e.node.setDataValue(e.colDef.field!, e.oldValue); setMsg('Error: ' + x.message) }
  }

  const confirmarModo = async () => modo !== 'reemplazar' ||
    await confirmar('Reemplazar todo el maestro', `Se borra todo “${def?.label}” y queda exactamente lo que cargues. No se puede deshacer.`, { peligro: true, si: 'Sí, reemplazar' })

  const descargar = async () => {
    try { setMsg(`Preparando ${sel}.xlsx… los maestros grandes tardan un poco`); await bajar(`/maestros/${sel}/excel${consultaExcel()}`, `${sel}.xlsx`); setMsg('Descargado ' + sel + '.xlsx' + (hayFiltro ? ' (solo lo filtrado)' : '')) }
    catch (x: any) { setMsg('Error: ' + x.message) }
  }
  const subirArchivo = async (f: File | undefined) => {
    if (!f) return
    if (!(await confirmarModo())) { if (fileRef.current) fileRef.current.value = ''; return }
    const mb = (f.size / 1048576).toFixed(1)
    try { setMsg(`Subiendo ${f.name} (${mb} MB) y validando cada fila… con cientos de miles de filas puede tardar varios minutos, no cierres esta pantalla`); setMsg(resumen(await subir(`/maestros/${sel}/excel?modo=${modo}&omitir_invalidas=${omitir}`, f))); cargar() }
    catch (x: any) { setMsg('Error: ' + x.message) }
    if (fileRef.current) fileRef.current.value = ''
  }
  // columnas de la grilla de pegado: las mismas que acepta el Excel (tienda, empresa, resto de la llave y los campos editables)
  const colsPegar = useMemo<ColPegar[]>(() => !def ? [] : [
    ...(def.filtros.tienda ? [{ key: 'bodega_id', titulo: 'Tienda (código)', obligatoria: !def.todas, ayuda: def.todas ? 'Código de Siesa (ej. SV021). Vacía o * = todas las tiendas' : 'Código de Siesa (ej. SV021)' }] : []),
    ...(def.llave.includes('empresa') ? [{ key: 'empresa', titulo: 'Empresa', ayuda: '05 Funat · 21 Stores. Vacía = se deduce de la tienda (obligatoria si el código existe en las dos empresas, ej. Melonn)' }] : []),
    ...def.llave.filter(k => k !== 'empresa' && !(def.filtros.tienda && k === 'bodega_id')).map(k => ({ key: k, titulo: k.replace(/_/g, ' '), obligatoria: true,
      ayuda: k === 'producto_id' ? 'Referencia de 6 dígitos (ej. 019901)' : undefined })),
    ...def.editable.map(k => ({ key: k, titulo: k.replace(/_/g, ' ') })),
  ], [def])
  const enviarGrilla = async (filas: Record<string, string>[]) => {
    if (!filas.length) { setMsg('Pega al menos una fila'); return }
    if (!(await confirmarModo())) return
    setEnviando(true)
    try {
      setMsg(`Cargando ${filas.length.toLocaleString()} filas pegadas…`)
      const r = await api('/maestros/' + sel + '/carga', { method: 'POST', body: JSON.stringify({ filas, modo, omitir_invalidas: omitir }) })
      setMsg(resumen(r)); setPegar(false); cargar()
    } catch (x: any) { setMsg('Error: ' + x.message) } finally { setEnviando(false) }
  }
  const traerTiendas = async () => {
    try { setMsg('Trayendo las tiendas de Siesa…'); const r = await conProgreso(setMsg, () => api('/admin/sincronizar-bodegas', { method: 'POST' })); setMsg(`Tiendas sincronizadas: ${r.tiendas}`) }
    catch (x: any) { setMsg('Error: ' + x.message) }
  }
  const traerItems = async () => {
    try {
      setMsg('Trayendo los items de Siesa con todos sus criterios… puede tardar un par de minutos')
      const r = await conProgreso(setMsg, () => api('/admin/sincronizar-items?empresa=' + empresa, { method: 'POST' }))
      const a = r[empresa] ?? r['05'] ?? r['21'] ?? {}
      setMsg(`Items traídos de Siesa: ${a.items ?? 0} items` + (a.eliminados ? ` (${a.eliminados} viejos eliminados)` : '') + ` · `+ `${a.criterios ?? 0} asignaciones de criterio en ${a.planes ?? 0} criterios`)
      if (sel === 'items') cargar()
    } catch (x: any) { setMsg('Error: ' + x.message) }
  }
  const traerVentas = async () => {
    if (!(await confirmar('Traer las ventas por mes de Siesa', 'Reemplaza la ventana de meses (los meses anteriores no se tocan). Puede tardar varios minutos.', { si: 'Traer ventas' }))) return
    try {
      setMsg('Trayendo las ventas por mes de Siesa… puede tardar varios minutos')
      const r = await conProgreso(setMsg, () => api('/admin/sincronizar-ventas?empresa=' + empresa, { method: 'POST' }))
      const n = (r.ventas_05 ?? 0) + (r.ventas_21 ?? 0)
      setMsg(`Ventas traídas de Siesa: ${n.toLocaleString()} filas desde ${r.meses_desde}`)
      if (sel === 'ventas-mensual') cargar()
    } catch (x: any) { setMsg('Error: ' + x.message) }
  }
  const guardarNueva = async () => {
    if (!def) return
    const fila = Object.fromEntries(Object.entries(nueva).filter(([, v]) => v.trim() !== ''))
    try {
      const r = await api('/maestros/' + sel + '/carga', { method: 'POST', body: JSON.stringify({ filas: [fila], modo: 'actualizar' }) })
      setMsg(r.creadas ? 'Fila agregada' : 'Esa llave ya existía: se actualizó'); setAgregar(false); setNueva({}); cargar()
    } catch (x: any) { setMsg('Error: ' + x.message) }
  }
  const eliminar = async () => {
    const s = grid?.getSelectedRows() ?? []
    if (!def || !s.length) { setMsg('Selecciona filas para eliminar'); return }
    if (!(await confirmar(`Eliminar ${s.length.toLocaleString('es-CO')} fila(s)`, `Se borran de “${def.label}”. No se puede deshacer.`, { peligro: true, si: 'Sí, eliminar' }))) return
    try {
      setMsg(`Eliminando ${s.length.toLocaleString()} fila(s)…`)
      const r = await api(`/maestros/${sel}/eliminar`, { method: 'POST',
        body: JSON.stringify({ llaves: s.map(x => Object.fromEntries(def.llave.map(k => [k, String(x[k])]))) }) })
      setMsg(`Eliminadas ${r.eliminadas}`); cargar()
    } catch (x: any) { setMsg('Error: ' + x.message) }
  }

  const kProv = (r: any) => `${r.empresa}|${r.proveedor_id}|${r.sucursal}`
  // qué campos cambiarían de verdad (sugerido distinto del actual); lo que ya está igual no se toca
  const cambiosDe = (x: any) => {
    const sg = x.sugerido, ac = x.actual
    return {
      leadtime: sg.leadtime != null && Number(sg.leadtime) !== Number(ac.leadtime ?? NaN),
      factor_tor: sg.factor_tor != null && Number(sg.factor_tor) !== Number(ac.factor_tor ?? 1),
      pedir_verde: sg.pedir_verde != null && (ac.pedir_verde == null || Number(sg.pedir_verde) !== Number(ac.pedir_verde)),
    }
  }
  const hayCambio = (x: any) => { const c = cambiosDe(x); return c.leadtime || c.factor_tor || c.pedir_verde }
  const analizarCumplimiento = async () => {
    const s = grid?.getSelectedRows() ?? []
    const todos = (s.length ? s : rows).filter((r: any) => r.proveedor_id)
    const base = todos.slice(0, 2000)
    if (!base.length) { setMsg('No hay proveedores para analizar'); return }
    if (todos.length > base.length) setMsg(`Hay ${todos.length.toLocaleString()} proveedores: se analizan los primeros 2.000. Filtra más para el resto.`)
    setCump({ cargando: true, res: [], avisos: [], desde: '', marcas: {} })
    try {
      const r = await api('/compras/cumplimiento/analizar', { method: 'POST', body: JSON.stringify({ meses: 12, proveedores: base.map((x: any) => ({ empresa: String(x.empresa), proveedor_id: String(x.proveedor_id), sucursal: String(x.sucursal ?? '001') })) }) })
      const marcas: Record<string, boolean> = {}
      r.resultados.forEach((x: any) => { marcas[kProv(x)] = !!hayCambio(x) })
      setCump({ cargando: false, res: r.resultados, avisos: r.avisos ?? [], desde: r.desde, marcas })
    } catch (x: any) { setCump(null); setMsg('Error: ' + x.message) }
  }
  const aplicarCumplimiento = async () => {
    if (!cump) return
    const items = cump.res.filter(x => cump.marcas[kProv(x)] && hayCambio(x)).map(x => { const c = cambiosDe(x); return { empresa: x.empresa, proveedor_id: x.proveedor_id, sucursal: x.sucursal,
      leadtime: c.leadtime ? x.sugerido.leadtime : undefined, factor_tor: c.factor_tor ? x.sugerido.factor_tor : undefined, pedir_verde: c.pedir_verde ? x.sugerido.pedir_verde : undefined } })
    if (!items.length) { setMsg('No marcaste ningún proveedor'); return }
    try {
      const r = await api('/compras/cumplimiento/aplicar', { method: 'POST', body: JSON.stringify({ items }) })
      setCump(null); setMsg(`Configuración aplicada a ${r.actualizados} proveedor(es). Recalcula el CEDI (o corre el motor) para ver el efecto en Necesidades de compra.`); cargar()
    } catch (x: any) { setMsg('Error: ' + x.message) }
  }

  const describirFiltros = () => {
    const x: string[] = []
    if (f.tienda.length) x.push(`Tienda(s): ${f.tienda.join(', ')}`)
    if (empG) x.push(`Empresa: ${empG}`)
    if (f.lab.length) x.push(`Laboratorio(s): ${f.lab.join(', ')}`)
    if (f.texto.trim()) x.push(`Texto: “${f.texto.trim()}”`)
    if (f.mes) x.push(`Mes: ${f.mes}`)
    if (colActiva) x.push(`${f.col} ${OPERADORES.find(o => o.v === f.op)?.t ?? f.op} ${f.val.trim()}`.trim())
    return x
  }
  // Borra todo lo que cumple los filtros (no solo lo que se ve o está seleccionado): así se limpia un maestro de cientos de miles de filas para volverlo a subir
  const vaciar = async () => {
    if (!def) return
    const body = { bodega_id: f.tienda.join(',') || null, q: f.texto.trim() || null, lab: f.lab.join(',') || null, empresa: def.filtros.empresa_opc ? (empG || null) : null,
      mes: def.filtros.mes ? (f.mes || null) : null, col: colActiva ? f.col : null, op: colActiva ? f.op : null, val: colActiva ? f.val.trim() || null : null }
    let n = 0
    try { n = (await api(`/maestros/${sel}/vaciar`, { method: 'POST', body: JSON.stringify({ ...body, solo_contar: true }) })).filas } catch (x: any) { setMsg('Error: ' + x.message); return }
    if (!n) { setMsg('No hay filas con estos filtros: no se eliminó nada'); return }
    const cuantas = n.toLocaleString('es-CO')
    const ok = hayFiltro
      ? await confirmar(`Eliminar ${cuantas} filas`, '', { peligro: true, si: `Sí, eliminar ${cuantas}`,
          html: `Se borran <b>${cuantas}</b> filas de “${esc(def.label)}” que cumplen:<ul style="text-align:left">${describirFiltros().map(l => `<li>${esc(l)}</li>`).join('')}</ul>No se puede deshacer. Después puedes volver a subir el Excel.` })
      : await confirmarEscribiendo('Vaciar el maestro completo', `Se borran <b>las ${cuantas} filas</b> de “${esc(def.label)}”. No se puede deshacer.<br>Después puedes subir el Excel de nuevo.`, 'VACIAR', 'Vaciar maestro')
    if (!ok) return
    try {
      setMsg(`Eliminando ${cuantas} filas…`)
      const r = await api(`/maestros/${sel}/vaciar`, { method: 'POST', body: JSON.stringify({ ...body, todo: !hayFiltro }) })
      setMsg(`Eliminadas ${r.eliminadas.toLocaleString('es-CO')} filas`); grid?.deselectAll(); cargar()
    } catch (x: any) { setMsg('Error: ' + x.message) }
  }
  const onSort = (e: any) => {   // el orden también lo resuelve el servidor (en un maestro grande la pantalla solo tiene un pedazo)
    if (!def) return
    const c = e.api.getColumnState().find((x: any) => x.sort)
    const col = c && (def.llave.includes(c.colId) || def.editable.includes(c.colId)) ? c.colId : ''
    const desc = c?.sort === 'desc'
    if (col !== orden.col || (col && desc !== orden.desc)) setOrdenRaw({ sel, col, desc })
  }

  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', height: '100%', gap: 1.5, minHeight: 500 }}>
      <Plegable id="maestros" titulo="acciones y filtros" resumen={<>
        {def && <Chip size="small" color="primary" label={def.label.split(':')[0]} />}
        <Chip size="small" label={`${(total ?? 0).toLocaleString('es-CO')} filas`} />
        {hayFiltro && <Chip size="small" variant="outlined" label="con filtros" />}</>}>
      <Paper variant="outlined" sx={{ p: 1.5, display: 'flex', flexWrap: 'wrap', gap: 1, alignItems: 'center' }}>
        {grupo === 'ddmrp' && <Button size="small" startIcon={<ArrowBack />} onClick={() => nav('/config')}>Todos los maestros</Button>}
        <TextField select size="small" label="Maestro" value={sel} onChange={e => setSel(e.target.value)} sx={{ minWidth: 260 }}>
          {defs.map(d => <MenuItem key={d.clave} value={d.clave}>{d.label}</MenuItem>)}
        </TextField>
        <Button variant="outlined" startIcon={<Download />} onClick={descargar}>{hayFiltro ? 'Descargar Excel (filtrado)' : 'Descargar Excel'}</Button>
        <Box sx={{ borderLeft: '1px solid #ccc', height: 28, mx: .5 }} />
        {pCarga && <><TextField select size="small" label="Al cargar" value={modo} onChange={e => setModo(e.target.value as any)} sx={{ minWidth: 270 }}>
          <MenuItem value="actualizar">Crear nuevos y actualizar existentes</MenuItem>
          {!def?.sin_reemplazo && <MenuItem value="reemplazar">Reemplazar todo el maestro</MenuItem>}
        </TextField>
        <FormControlLabel control={<Checkbox size="small" checked={omitir} onChange={e => setOmitir(e.target.checked)} />}
          label="Omitir filas con datos inválidos" title="Carga las filas buenas y te dice cuántas omitió (en vez de rechazar todo el archivo)" />
        <Button variant="contained" startIcon={<Upload />} onClick={() => fileRef.current?.click()}>Subir Excel / CSV</Button>
        <input ref={fileRef} type="file" accept=".xlsx,.csv,.txt" hidden onChange={e => subirArchivo(e.target.files?.[0])} />
        <Button startIcon={<ContentPaste />} onClick={() => setPegar(!pegar)}>Pegar desde Excel</Button>
        {!def?.solo_existentes && <Button startIcon={<AddCircleOutline />} onClick={() => { setNueva({}); setAgregar(true) }}>Agregar fila</Button>}
        {def && !def.sin_reemplazo && <Button color="error" startIcon={<DeleteOutline />} onClick={eliminar}>Eliminar seleccionadas</Button>}
        {def?.clave === 'proveedores' && <Tooltip title="Mide el cumplimiento de los proveedores seleccionados (o de los que se ven) con su historial de OC en Siesa y propone lead time, colchón de la zona roja y si pedir también en verde"><span><Button color="secondary" variant="outlined" startIcon={<Insights />} onClick={analizarCumplimiento}>Aplicar configuración sugerida</Button></span></Tooltip>}
        {def?.puede_vaciar && <Tooltip title="Borra TODAS las filas que cumplen los filtros de abajo (sin filtros: el maestro completo), no solo las que ves. Sirve para limpiar y volver a subir.">
          <span><Button color="error" variant="outlined" startIcon={<DeleteSweep />} onClick={vaciar} disabled={!total}>{hayFiltro ? `Eliminar todo lo filtrado (${total.toLocaleString('es-CO')})` : 'Vaciar maestro'}</Button></span></Tooltip>}</>}
        <Box sx={{ flex: 1 }} />
        {pSync && <Button size="small" startIcon={<CloudSync />} onClick={traerItems} title="Descripción, laboratorio y todos los criterios de items desde Siesa">Traer items de Siesa</Button>}
        {pSync && <Button size="small" startIcon={<CloudSync />} onClick={traerVentas} title="Ventas por mes desde Siesa, a demanda (es la consulta pesada)">Traer ventas por mes</Button>}
        {pSync && <Button size="small" startIcon={<CloudSync />} onClick={traerTiendas} title="Lee de Siesa las tiendas (código y nombre)">Traer tiendas de Siesa</Button>}
      </Paper>
      {def && (
        <Typography variant="body2" color="text.secondary">
          “Descargar Excel” te da la plantilla con los datos actuales. La tienda se identifica por código de Siesa (ej. SV021) y la empresa se deduce sola.
          Las referencias van como texto de 6 dígitos.{def.todas ? ' Para condenar el item en todas las tiendas deja la tienda vacía o escribe *.' : ''} Columnas a cargar:{' '}
          {def.editable.length ? def.editable.map(c => <Chip key={c} size="small" label={c} sx={{ mr: .5 }} />) : '(solo existencia de la fila)'}
          {def.ayuda && <AvisoInfo titulo="Qué hace este maestro"><b>Qué hace este maestro:</b> {def.ayuda}</AvisoInfo>}
        </Typography>)}
      {def && (
        <Paper variant="outlined" sx={{ p: 1, display: 'flex', flexWrap: 'wrap', gap: 1, alignItems: 'center' }}>
          <Typography variant="body2" sx={{ fontWeight: 600 }}>Filtrar</Typography>
          {def.filtros.tienda && <Autocomplete multiple size="small" limitTags={2} sx={{ minWidth: 260, flex: '1 1 260px', maxWidth: 460 }} value={f.tienda}
            options={opc.tiendas.filter(t => !def.filtros.empresa_opc || !empG || (t.empresa ?? '').split(',').includes(empG)).map(t => t.bodega_id)}
            getOptionLabel={(id: string) => { const t = opc.tiendas.find(x => x.bodega_id === id); return t?.nombre ? `${id} · ${t.nombre}` : id }}
            onChange={(_, v) => setF({ tienda: v })} renderInput={p => <TextField {...p} label="Tienda(s)" />} />}
          <TextField size="small" label={def.filtros.item ? 'Item o descripción' : 'Buscar'} value={f.texto} onChange={e => setF({ texto: e.target.value })} sx={{ width: 200 }} />
          {def.filtros.lab && <Autocomplete multiple size="small" limitTags={2} sx={{ minWidth: 220, flex: '1 1 220px', maxWidth: 400 }} value={f.lab} options={opc.laboratorios.map(l => l.codigo)}
            getOptionLabel={(c: string) => { const l = opc.laboratorios.find(x => x.codigo === c); return l?.nombre ? `${c} · ${l.nombre}` : c }}
            onChange={(_, v) => setF({ lab: v })} renderInput={p => <TextField {...p} label="Laboratorio" />} />}
          {def.clave === 'items-compras' && <>
            <Autocomplete multiple size="small" limitTags={2} sx={{ minWidth: 200, flex: '0 1 240px' }} value={f.cat} options={['0001', '0002', '0003']}
              getOptionLabel={(c: string) => ({ '0001': '0001 · Productos Funat', '0002': '0002 · Productos de terceros', '0003': '0003 · Maquila Funat' } as Record<string, string>)[c] ?? c}
              onChange={(_, v) => setF({ cat: v })} renderInput={p => <TextField {...p} label="Categoría" />} />
            <Autocomplete multiple size="small" limitTags={2} sx={{ minWidth: 220, flex: '0 1 280px' }} value={f.abas} options={['Compra', 'Producción propia', 'Sin proveedor']}
              onChange={(_, v) => setF({ abas: v })} renderInput={p => <TextField {...p} label="Abastecimiento" />} />
          </>}
          {def.filtros.empresa && <TextField select size="small" label="Estado en Siesa" value={estado} onChange={e => setEstado(e.target.value)} sx={{ width: 160 }}>
            <MenuItem value="activo">Activos</MenuItem><MenuItem value="inactivo">Inactivos</MenuItem><MenuItem value="bloqueado">Bloqueados</MenuItem><MenuItem value="todos">Todos</MenuItem></TextField>}
          {def.filtros.mes && <TextField size="small" type="month" label="Mes" value={f.mes} onChange={e => setF({ mes: e.target.value })} slotProps={{ inputLabel: { shrink: true } }} sx={{ width: 170 }} />}
          <Tooltip disableInteractive title={colAbierta ? '' : 'Filtra por el valor de una columna, en el servidor (sirve con cientos de miles de filas). Ej.: cota_maxima mayor que 1'}>
            <Box sx={{ display: 'flex', gap: .5, alignItems: 'center' }}>
              <TextField select size="small" label="Columna" value={f.col} onChange={e => setF({ col: e.target.value, op: colTexto(e.target.value) ? 'contiene' : 'eq', val: '' })} sx={{ width: 150 }}
                slotProps={{ select: { displayEmpty: true, open: colAbierta, onOpen: () => setColAbierta(true), onClose: () => setColAbierta(false) }, inputLabel: { shrink: true } }}>
                <MenuItem value="">(ninguna)</MenuItem>{columnasFiltro.map(c => <MenuItem key={c} value={c}>{c}</MenuItem>)}</TextField>
              {f.col && <TextField select size="small" label="Condición" value={f.op} onChange={e => setF({ op: e.target.value })} sx={{ width: 150 }}>
                {OPERADORES.filter(o => !o.solo || (o.solo === 'txt') === colTexto(f.col)).map(o => <MenuItem key={o.v} value={o.v}>{o.t}</MenuItem>)}</TextField>}
              {f.col && f.op !== 'vacio' && f.op !== 'lleno' && <TextField size="small" label="Valor" value={f.val} onChange={e => setF({ val: e.target.value })} sx={{ width: 130 }} />}
            </Box></Tooltip>
          {hayFiltro && <Button size="small" onClick={() => setF(VACIO)}>Quitar filtros</Button>}
          <Box sx={{ flex: 1 }} />
          <Chip size="small" label={total > rows.length ? `Mostrando ${rows.length.toLocaleString('es-CO')} de ${total.toLocaleString('es-CO')} filas` : `${rows.length.toLocaleString('es-CO')} ${rows.length === 1 ? 'fila' : 'filas'}`} color={total > rows.length ? 'warning' : 'default'} />
        </Paper>)}
      </Plegable>
      {total > rows.length && <Alert severity="warning" sx={{ py: 0 }}>Este maestro tiene {total.toLocaleString('es-CO')} filas y la pantalla solo muestra las primeras {rows.length.toLocaleString('es-CO')}: usa los filtros de arriba (tienda, item, empresa, columna…: los resuelve el servidor sobre todas las filas) para ver y editar lo que buscas. “Descargar Excel” baja todo lo filtrado, sin ese tope, y “Eliminar todo lo filtrado” borra todo lo filtrado.</Alert>}
      {pegar && def && <PegarGrilla key={sel} titulo={def.label} columnas={colsPegar} ocupado={enviando} onFinalizar={enviarGrilla} onCancelar={() => setPegar(false)} />}
      <Box className="ag-theme-quartz" sx={{ flex: 1, minHeight: 300 }}>
        <Tabla cargando={cargando} vacio="Este maestro está vacío: carga datos con Excel, pegando o trayendo de Siesa" rowData={rows} columnDefs={cols} onCellValueChanged={onChange} rowBuffer={20} rowSelection="multiple"
          onGridReady={e => setGrid(e.api)} onSortChanged={onSort} defaultColDef={{ resizable: true, sortable: true, filter: false }} />
      </Box>
      <Dialog open={agregar} onClose={() => setAgregar(false)} maxWidth="xs" fullWidth>
        <DialogTitle>Agregar fila · {def?.label}</DialogTitle>
        <DialogContent sx={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr)', gap: 1.5, pt: '8px !important' }}>
          {def && [...def.llave, ...def.editable].map(k => (
            <TextField key={k} size="small" label={k + (def.llave.includes(k) ? (k === 'empresa' ? ' (vacío = se deduce)' : k === 'bodega_id' && def.todas ? ' (vacío o * = todas)' : '') : '')}
              value={nueva[k] ?? ''} onChange={e => setNueva({ ...nueva, [k]: e.target.value })} />))}
          <Typography variant="caption" color="text.secondary">Si la llave ya existe, se actualizan los valores. Las referencias van de 6 dígitos (ej. 019901).</Typography>
        </DialogContent>
        <DialogActions><Button onClick={() => setAgregar(false)}>Cancelar</Button><Button variant="contained" onClick={guardarNueva}>Guardar</Button></DialogActions>
      </Dialog>
      <Dialog open={!!cump} onClose={() => setCump(null)} maxWidth="lg" fullWidth>
        <DialogTitle>Configuración sugerida por proveedor · revisa y aprueba</DialogTitle>
        <DialogContent>
          {cump?.cargando ? <Typography sx={{ py: 3 }}>Analizando el historial de OC en Siesa…</Typography> : <>
            <Alert severity="info" sx={{ mb: 1 }}>Se mide con las OC de los últimos 12 meses (desde {cump?.desde}) y sus entradas reales de mercancía: cuánto demora de verdad desde la OC hasta la primera entrada (las OC montadas el mismo día de la entrada no cuentan), qué % llega a tiempo frente a la fecha pactada, qué parte de lo pedido llega (surtido) y el OTIF (a tiempo y completa). Es una sugerencia: marca los que quieres aplicar y después puedes ajustar cada valor en la tabla.</Alert>
            {cump?.avisos.map(a => <Alert key={a} severity="warning" sx={{ mb: 1 }}>{a}</Alert>)}
            <Table size="small">
              <TableHead><TableRow>
                <TableCell>Aplicar</TableCell><TableCell>Proveedor</TableCell><TableCell align="right">OC (cumplidas / total)</TableCell><TableCell align="right">Surtido</TableCell>
                <TableCell align="right">OC completas</TableCell><TableCell align="right">Lead time real (mediana / p75) · pactado</TableCell><TableCell align="right">A tiempo / OTIF</TableCell>
                <TableCell>Lead time (actual → sugerido)</TableCell><TableCell>Colchón zona roja (actual → sugerido)</TableCell><TableCell>Pedir en verde (actual → sugerido)</TableCell>
              </TableRow></TableHead>
              <TableBody>
                {cump?.res.filter(x => hayCambio(x)).map(x => {
                  const cb = cambiosDe(x)
                  const sug = x.sugerido, m = x.metricas, hay = sug.factor_tor != null || sug.pedir_verde != null || sug.leadtime != null
                  const pv = (v: any) => v == null ? 'regla general' : v ? 'Sí' : 'No'
                  return <TableRow key={kProv(x)} hover>
                    <TableCell><Checkbox size="small" checked={!!cump!.marcas[kProv(x)]} disabled={!hay} onChange={e => setCump({ ...cump!, marcas: { ...cump!.marcas, [kProv(x)]: e.target.checked } })} /></TableCell>
                    <TableCell><Tooltip title={<Box>{x.motivos.map((t: string) => <div key={t}>• {t}</div>)}</Box>}><span>{x.nombre ?? x.proveedor_id}<Typography variant="caption" display="block" color="text.secondary">{x.empresa} · {x.proveedor_id}-{x.sucursal}</Typography></span></Tooltip></TableCell>
                    <TableCell align="right">{m.oc_maduras} / {m.oc_total}</TableCell>
                    <TableCell align="right">{m.surtido_pct == null ? '—' : m.surtido_pct + '%'}</TableCell>
                    <TableCell align="right">{m.oc_completas_pct == null ? '—' : m.oc_completas_pct + '%'}</TableCell>
                    <TableCell align="right">{m.lt_real_p50 == null ? (m.plazo_p50 == null ? '—' : `pactado ${m.plazo_p50} / ${m.plazo_p75} d`) : `${m.lt_real_p50} / ${m.lt_real_p75} d · pactado ${m.plazo_p75 ?? '—'} d`}</TableCell>
                    <TableCell align="right">{m.a_tiempo_pct == null ? '—' : `${m.a_tiempo_pct}% / ${m.otif_pct}%`}</TableCell>
                    <TableCell>{cb.leadtime ? <>{x.actual.leadtime ?? 'general'} → <b>{sug.leadtime}</b></> : <Typography variant="caption" color="text.secondary">sin cambio</Typography>}</TableCell>
                    <TableCell>{cb.factor_tor ? <>{x.actual.factor_tor ?? 1} → <b>{sug.factor_tor}</b></> : <Typography variant="caption" color="text.secondary">sin cambio</Typography>}</TableCell>
                    <TableCell>{cb.pedir_verde ? <>{pv(x.actual.pedir_verde)} → <b>{sug.pedir_verde ? 'Sí' : 'No'}</b></> : <Typography variant="caption" color="text.secondary">sin cambio</Typography>}</TableCell>
                  </TableRow>
                })}
              </TableBody>
            </Table>
            {cump && !cump.res.some(hayCambio) && <Alert severity="success" sx={{ mt: 1 }}>Ningún proveedor cambia: lo sugerido ya es lo que tienen configurado (o no hay OC suficientes).</Alert>}
            {cump && cump.res.some(x => !hayCambio(x)) && <Typography variant="caption" color="text.secondary" sx={{ mt: 1, display: 'block' }}>{cump.res.filter(x => !hayCambio(x)).length} proveedor(es) no se muestran porque no cambian o tienen menos de 5 OC cumplidas (sin base para sugerir).</Typography>}
            <Typography variant="caption" color="text.secondary" sx={{ mt: 1, display: 'block' }}>Pasa el mouse sobre el proveedor para ver el motivo de cada sugerencia. «—» = pocas OC cumplidas (menos de 5): no hay base para sugerir.</Typography>
          </>}
        </DialogContent>
        <DialogActions><Button onClick={() => setCump(null)}>Cancelar</Button><Button variant="contained" color="success" disabled={!cump || cump.cargando || !cump.res.some(x => hayCambio(x) && cump.marcas[kProv(x)])} onClick={aplicarCumplimiento}>Aprobar y aplicar ({cump ? cump.res.filter(x => hayCambio(x) && cump.marcas[kProv(x)]).length : 0})</Button></DialogActions>
      </Dialog>
      <Aviso msg={msg} onClose={() => setMsg('')} />
    </Box>)
}

// Proveedores: ayuda (tooltip) de cada columna editable. Frecuencia y condición de pago ya tienen la suya más abajo.
const AYUDA_PROVEEDOR: Record<string, { headerName?: string; width?: number; headerTooltip: string }> = {
  empresa: { headerTooltip: 'Empresa de Siesa: 05 Funat, 21 Stores. Cada proveedor se configura por separado en cada empresa.' },
  sucursal: { headerTooltip: 'Sucursal del proveedor en Siesa (001 por defecto). Un mismo NIT puede tener varias sucursales, cada una con sus propios datos.' },
  leadtime: { headerName: 'Lead time (d)', width: 120, headerTooltip: 'Días que tarda en llegar lo que se le pide. Al calcular el CEDI manda primero el del item (maestro «Lead time del CEDI»), luego este del proveedor y, si no hay ninguno, el general. «Aplicar configuración sugerida» puede proponerlo según el historial de OC.' },
  email_para: { headerName: 'Correo(s) para la OC', width: 230, headerTooltip: 'Correo(s) del proveedor a donde se envía su orden de pedido. Varios separados por «;». Sin correo, el proveedor sale en Necesidades de compra marcado «Sin correo» y no se le puede montar la OC.' },
  email_cc: { headerName: 'Con copia (CC)', width: 200, headerTooltip: 'Correo(s) que reciben copia de la orden de pedido (por ejemplo el negociador o contabilidad). Varios separados por «;». Opcional.' },
  activo: { headerName: 'Activo', width: 100, headerTooltip: '1 = se le compra con normalidad. 0 = proveedor inactivo: sus items siguen saliendo en Necesidades de compra pero marcados «Proveedor inactivo» (alerta, para no montarle OC). Acepta 1/0 o sí/no; vacío = activo.' },
  redondeo: { headerName: 'Redondeo', width: 120, headerTooltip: 'Cómo se lleva la cantidad a pedir al múltiplo de la Unidad de pedido de cada item: arriba (por defecto), cercano o abajo. Ejemplo con unidad 12 y el buffer pide 40: arriba = 48, cercano = 36, abajo = 36. El MOQ del item siempre sube hacia arriba.' },
  pedido_minimo: { headerName: 'Pedido mínimo ($)', width: 150, headerTooltip: 'Valor mínimo (sin IVA) que acepta el proveedor por OC. Si el total de lo que se le va a pedir queda por debajo, sale «Bajo el pedido mínimo». Por defecto solo es una alerta; si en Configuración de compras pedido_minimo_bloquea = 1, ese proveedor no se muestra. Vacío o 0 = sin mínimo.' },
  pedir_verde: { headerName: 'Pedir en verde (1/0)', width: 150, headerTooltip: '1 = pedirle también cuando el CEDI está en zona verde, hasta el tope verde (compras más grandes y menos frecuentes). 0 = no. Vacío = rige la regla general «Pedir también en zona verde» de Reglas de compras. «Aplicar configuración sugerida» lo puede proponer.' },
  factor_tor: { headerName: 'Colchón zona roja (×)', width: 160, headerTooltip: 'Para proveedores que no surten completo o se atrasan: multiplica la zona roja del CEDI (1 o más) y por eso se pide antes y más. Ejemplo: 1,25 = zona roja 25 % más grande. Vacío = sin cambio. «Aplicar configuración sugerida» lo calcula del historial de OC.' },
  contacto: { headerName: 'Contacto', width: 150, headerTooltip: 'Persona de contacto en el proveedor. Solo informativo.' },
  telefono: { headerName: 'Teléfono', width: 130, headerTooltip: 'Teléfono del proveedor o del contacto. Solo informativo.' },
  notas: { headerName: 'Notas', width: 220, headerTooltip: 'Notas internas de compras sobre el proveedor (condiciones, horarios, recomendaciones). Solo informativo.' },
}
// Items de compras: encabezado y ayuda (tooltip) de cada columna editable. Los ejemplos usan los mismos números que el cálculo de Necesidades de compra (routers/compras.py).
const AYUDA_ITEM_COMPRA: Record<string, { headerName: string; width: number; headerTooltip: string }> = {
  activo: { headerName: 'Activo', width: 100, headerTooltip: '1 = el item se compra y aparece en Necesidades de compra. 0 = no se compra (descontinuado, lo hace otra empresa, etc.): no sale aunque el buffer lo pida. Acepta 1/0 o sí/no.' },
  cotizacion: { headerName: 'Cotización manual', width: 150, headerTooltip: 'Precio unitario con el que se valora el pedido. Llénalo solo si quieres pisar el precio de Siesa. Vacía = se usa, en este orden: la cotización de Siesa, el último costo de compra. La columna «Costo a usar» muestra cuál queda.' },
  unidad_pedido: { headerName: 'Unidad de pedido', width: 140, headerTooltip: 'Múltiplo en que el proveedor permite pedir este item (ej. 12 = solo de a docenas; por defecto 1 = sin restricción). La cantidad a pedir se redondea a un múltiplo de este número; hacia arriba, salvo que el proveedor tenga otro redondeo en Maestros → Proveedores. Ejemplo: el buffer pide 50 y la unidad es 12 → se pide 60. Si editas la cantidad a mano y no es múltiplo, el pedido sale con alerta.' },
  unidad_empaque: { headerName: 'Unidad de empaque', width: 150, headerTooltip: 'Unidades que trae una caja o empaque (por defecto 1). Es un dato de referencia: hoy NO cambia la cantidad a pedir ni la OC; lo que ajusta el pedido es la Unidad de pedido. Si el proveedor solo vende cajas completas, pon el mismo número aquí y en Unidad de pedido.' },
  moq: { headerName: 'MOQ (u.)', width: 110, headerTooltip: 'Mínimo de compra de este item, en unidades (por defecto 1). Si el buffer pide algo mayor que 0 pero menor al MOQ, se sube al MOQ (llevado hacia arriba al múltiplo de la Unidad de pedido) y sale la alerta «Subió al MOQ». Si no hay necesidad no se pide nada. Ejemplo: MOQ 100, unidad 12, el buffer pide 30 → se pide 108. Es por item; el pedido mínimo del proveedor (total en $) se configura en Proveedores. Si editas la cantidad por debajo del MOQ, solo sale una alerta, no se bloquea.' },
}
const ayudaItemCompra = (c: ColDef): ColDef => { const a = AYUDA_ITEM_COMPRA[c.field as string]; return a ? { ...c, ...a } : c }
// Items de compras, columnas de solo lectura: qué significa cada una
const AYUDA_LECTURA_COMPRA: Record<string, string> = {
  laboratorio: 'Laboratorio del item en Siesa (criterio del plan de laboratorios). Solo lectura.',
  categoria: 'Criterio del plan 001 de Siesa: 0001 Productos Funat, 0002 Productos de terceros, 0003 Maquila Funat. Solo lectura.',
  linea: 'Línea del item en Siesa. Solo lectura.',
  exhibicion: 'Exhibición del item en Siesa. Solo lectura.',
  costo: 'Costo promedio del item en Siesa. Solo lectura.',
  cotizacion_siesa: 'Precio de la última cotización vigente al proveedor en Siesa. Solo lectura.',
  cotizacion_vigencia: 'Desde cuándo rige la cotización de Siesa. Solo lectura.',
  ultimo_costo: 'Costo de la última compra (entrada) de este item. Se usa solo si no hay cotización manual ni de Siesa. Solo lectura.',
  ultimo_costo_fecha: 'Fecha de esa última compra. Solo lectura.',
  costo_compra: 'Precio unitario con el que se valora el pedido: la cotización manual, si no la de Siesa, si no el último costo de compra. Solo lectura (para cambiarlo usa «Cotización manual»).',
  origen_costo: 'De dónde sale el «Costo a usar»: Manual, Cotización (Siesa) o Última compra.',
  proveedor: 'NIT del proveedor al que se le compra este item (el de la cotización o última compra). Solo lectura.',
  proveedor_nombre: 'Nombre del proveedor al que se le compra este item. Solo lectura.',
}

/** Maestros DDMRP: sin `?maestro=` se ve el home de tarjetas con buscador; con él, la tabla de ese maestro. Compras abre directo la tabla. */
export default function Config({ grupo = 'ddmrp' }: { grupo?: 'ddmrp' | 'compras' }) {
  const [sp] = useSearchParams()
  if (grupo === 'ddmrp' && !sp.get('maestro')) return <MaestrosHome />
  return <ConfigTabla key={sp.get('maestro') ?? ''} grupo={grupo} />
}
