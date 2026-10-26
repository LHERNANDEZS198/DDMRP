import { useEffect, useMemo, useRef, useState } from 'react'
import Tabla from '../Tabla'
import { CellValueChangedEvent, ColDef, GridApi } from 'ag-grid-community'
import { Alert, Autocomplete, Box, Button, Checkbox, Chip, Dialog, DialogActions, DialogContent, DialogTitle, FormControlLabel, MenuItem, Paper, Stack, TextField, Tooltip, Typography } from '@mui/material'
import AddCircleOutline from '@mui/icons-material/AddCircleOutline'
import Download from '@mui/icons-material/Download'
import Upload from '@mui/icons-material/Upload'
import ContentPaste from '@mui/icons-material/ContentPaste'
import DeleteOutline from '@mui/icons-material/DeleteOutline'
import DeleteSweep from '@mui/icons-material/DeleteSweep'
import CloudSync from '@mui/icons-material/CloudSync'
import { api, apiLista, bajar, subir, conProgreso } from '../api'
import Aviso from '../Aviso'
import { useYo } from '../Yo'
import { confirmar, confirmarEscribiendo, esc } from '../alertas'
import PegarGrilla, { ColPegar } from '../PegarGrilla'
import { useEmpresa } from '../Empresa'

type Filtros = { tienda: boolean; item: boolean; lab: boolean; texto: boolean; empresa?: boolean; empresa_opc?: boolean; mes?: boolean }
type Tienda = { bodega_id: string; nombre: string | null; empresa: string | null }
type Lab = { codigo: string; nombre: string | null }
type Def = { grupo?: string; ayuda: string; filtros: Filtros; todas?: boolean; clave: string; label: string; llave: string[]; editable: string[]; tipos: Record<string, string>; sin_reemplazo: boolean; puede_vaciar?: boolean }


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
export default function Config({ grupo = 'ddmrp' }: { grupo?: 'ddmrp' | 'compras' }) {
  const { puede } = useYo(); const pCarga = puede(grupo === 'compras' ? 'cargar_maestros_compras' : 'cargar_maestros'); const pSync = grupo === 'ddmrp' && puede('sincronizar_siesa')
  const [defs, setDefs] = useState<Def[]>([])
  const inicial = grupo === 'compras' ? 'leadtime-cedi' : 'bitacora'
  const [sel, setSel] = useState(inicial)
  const [rows, setRows] = useState<any[]>([])
  const [cargando, setCargando] = useState(true)
  const [total, setTotal] = useState(0)
  // Filtros de la pantalla. Se resuelven en el SERVIDOR (el maestro puede tener cientos de miles de filas y la pantalla solo trae un pedazo),
  // y son los mismos para la descarga a Excel y para "Eliminar todo lo filtrado". Van atados al maestro con que se escribieron
  const VACIO = { tienda: [] as string[], texto: '', lab: [] as string[], mes: '', emp: '', col: '', op: 'eq', val: '' }
  const [fRaw, setFRaw] = useState({ sel: inicial, ...VACIO })
  const f = fRaw.sel === sel ? fRaw : { sel, ...VACIO }
  const setF = (c: Partial<typeof VACIO>) => setFRaw({ ...f, ...c, sel })
  const colActiva = !!(f.col && (f.op === 'vacio' || f.op === 'lleno' || f.val.trim()))
  const hayFiltro = !!(f.tienda.length || f.texto || f.lab.length || f.mes || colActiva)
  const [ordenRaw, setOrdenRaw] = useState({ sel: '', col: '', desc: false })   // orden pedido al servidor (columna de la tabla)
  const orden = ordenRaw.sel === sel ? ordenRaw : { sel, col: '', desc: false }
  const filtros = () => {
    const p = new URLSearchParams()
    if (f.tienda.length) p.set('bodega_id', f.tienda.join(','))
    if (f.texto.trim()) p.set('q', f.texto.trim())
    if (f.lab.length) p.set('lab', f.lab.join(','))
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
    const conocidas = new Set([...def.llave, ...def.editable, 'descripcion', 'bodega_nombre', 'costo', 'estado'])
    const extra: ColDef[] = def.clave === 'items' && rows[0]
      ? Object.keys(rows[0]).filter(k => !conocidas.has(k)).map(k => ({ field: k, headerName: k, width: 190 })) : []
    const ed2 = def.clave === 'bitacora' ? ed.map(c => c.field === 'descripcion' ? { ...c, headerName: 'Tienda (nombre)', width: 240 } : c) : def.clave === 'items' ? ed.map(c => c.field === 'categoria' ? { ...c, headerName: 'Laboratorio (código)', width: 150 } : c.field === 'descripcion' ? { ...c, width: 300 } : c) : ed
    const costo: ColDef[] = def.clave === 'items' ? [{ field: 'costo', headerName: 'Costo promedio', type: 'numericColumn', width: 140,
      valueFormatter: p => p.value == null ? '' : '$' + Math.round(p.value).toLocaleString('es-CO'), headerTooltip: 'Costo promedio por instalación (lo trae el ETL desde Siesa). Solo lectura.' }] : []
    const est: ColDef[] = def.clave === 'items' ? [{ field: 'estado', headerName: 'Estado Siesa', width: 120, headerTooltip: 'Estado del item en Siesa (extensión del item). Solo lectura; sin dato = activo.' }] : []
    return [...llave, ...desc, ...ed2, ...costo, ...est, ...extra]
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
      const r = await conProgreso(setMsg, () => api('/admin/sincronizar-items', { method: 'POST' }))
      const a = r['05'] ?? r['21'] ?? {}
      setMsg(`Items traídos de Siesa: ${a.items ?? 0} items` + (a.eliminados ? ` (${a.eliminados} viejos eliminados)` : '') + ` · `+ `${a.criterios ?? 0} asignaciones de criterio en ${a.planes ?? 0} criterios`)
      if (sel === 'items') cargar()
    } catch (x: any) { setMsg('Error: ' + x.message) }
  }
  const traerVentas = async () => {
    if (!(await confirmar('Traer las ventas por mes de Siesa', 'Reemplaza la ventana de meses (los meses anteriores no se tocan). Puede tardar varios minutos.', { si: 'Traer ventas' }))) return
    try {
      setMsg('Trayendo las ventas por mes de Siesa… puede tardar varios minutos')
      const r = await conProgreso(setMsg, () => api('/admin/sincronizar-ventas', { method: 'POST' }))
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
      <Paper variant="outlined" sx={{ p: 1.5, display: 'flex', flexWrap: 'wrap', gap: 1, alignItems: 'center' }}>
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
        <Button startIcon={<AddCircleOutline />} onClick={() => { setNueva({}); setAgregar(true) }}>Agregar fila</Button>
        {def && !def.sin_reemplazo && <Button color="error" startIcon={<DeleteOutline />} onClick={eliminar}>Eliminar seleccionadas</Button>}
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
        </Typography>)}
      {def?.ayuda && <Alert severity="info" icon={false} sx={{ py: 0.5 }}><b>Qué hace este maestro:</b> {def.ayuda}</Alert>}
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
          {def.filtros.empresa && <TextField select size="small" label="Estado en Siesa" value={estado} onChange={e => setEstado(e.target.value)} sx={{ width: 160 }}>
            <MenuItem value="activo">Activos</MenuItem><MenuItem value="inactivo">Inactivos</MenuItem><MenuItem value="bloqueado">Bloqueados</MenuItem><MenuItem value="todos">Todos</MenuItem></TextField>}
          {def.filtros.mes && <TextField size="small" type="month" label="Mes" value={f.mes} onChange={e => setF({ mes: e.target.value })} slotProps={{ inputLabel: { shrink: true } }} sx={{ width: 170 }} />}
          <Tooltip title="Filtra por el valor de una columna, en el servidor (sirve con cientos de miles de filas). Ej.: cota_maxima mayor que 1">
            <Box sx={{ display: 'flex', gap: .5, alignItems: 'center' }}>
              <TextField select size="small" label="Columna" value={f.col} onChange={e => setF({ col: e.target.value, op: colTexto(e.target.value) ? 'contiene' : 'eq', val: '' })} sx={{ width: 150 }}
                slotProps={{ select: { displayEmpty: true }, inputLabel: { shrink: true } }}>
                <MenuItem value="">(ninguna)</MenuItem>{columnasFiltro.map(c => <MenuItem key={c} value={c}>{c}</MenuItem>)}</TextField>
              {f.col && <TextField select size="small" label="Condición" value={f.op} onChange={e => setF({ op: e.target.value })} sx={{ width: 150 }}>
                {OPERADORES.filter(o => !o.solo || (o.solo === 'txt') === colTexto(f.col)).map(o => <MenuItem key={o.v} value={o.v}>{o.t}</MenuItem>)}</TextField>}
              {f.col && f.op !== 'vacio' && f.op !== 'lleno' && <TextField size="small" label="Valor" value={f.val} onChange={e => setF({ val: e.target.value })} sx={{ width: 130 }} />}
            </Box></Tooltip>
          {hayFiltro && <Button size="small" onClick={() => setF(VACIO)}>Quitar filtros</Button>}
          <Box sx={{ flex: 1 }} />
          <Chip size="small" label={total > rows.length ? `Mostrando ${rows.length.toLocaleString('es-CO')} de ${total.toLocaleString('es-CO')} filas` : `${rows.length.toLocaleString('es-CO')} ${rows.length === 1 ? 'fila' : 'filas'}`} color={total > rows.length ? 'warning' : 'default'} />
        </Paper>)}
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
      <Aviso msg={msg} onClose={() => setMsg('')} />
    </Box>)
}
