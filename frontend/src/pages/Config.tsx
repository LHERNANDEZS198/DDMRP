import { useEffect, useMemo, useRef, useState } from 'react'
import Tabla from '../Tabla'
import { CellValueChangedEvent, ColDef, GridApi } from 'ag-grid-community'
import { Alert, Box, Button, Checkbox, Chip, Dialog, DialogActions, DialogContent, DialogTitle, FormControlLabel, MenuItem, Paper, Stack, TextField, Typography } from '@mui/material'
import AddCircleOutline from '@mui/icons-material/AddCircleOutline'
import Download from '@mui/icons-material/Download'
import Upload from '@mui/icons-material/Upload'
import ContentPaste from '@mui/icons-material/ContentPaste'
import DeleteOutline from '@mui/icons-material/DeleteOutline'
import CloudSync from '@mui/icons-material/CloudSync'
import { api, apiLista, bajar, subir, conProgreso } from '../api'
import Aviso from '../Aviso'
import { useYo } from '../Yo'

type Filtros = { tienda: boolean; item: boolean; lab: boolean; texto: boolean }
type Def = { ayuda: string; filtros: Filtros; todas?: boolean; clave: string; label: string; llave: string[]; editable: string[]; tipos: Record<string, string>; sin_reemplazo: boolean }

// Pega filas desde Excel (con encabezados). Separador: tab, ; o coma.
function parsear(txt: string): Record<string, string>[] {
  const lineas = txt.split(/\r?\n/).map(l => l.trim()).filter(Boolean)
  if (lineas.length < 2) return []
  const sep = lineas[0].includes('\t') ? '\t' : lineas[0].includes(';') ? ';' : ','
  const cab = lineas[0].split(sep).map(c => c.trim())
  return lineas.slice(1).map(l => {
    const v = l.split(sep).map(c => c.trim())
    return Object.fromEntries(cab.map((c, i) => [c, v[i] ?? '']))
  })
}

const resumen = (r: any) =>
  `${r.modo === 'reemplazar' ? 'Reemplazado' : 'Cargado'}: ${r.unicas} filas · ${r.creadas} nuevas · ${r.actualizadas} actualizadas` +
  (r.ignoradas ? ` · ${r.ignoradas} ignoradas (no existen)` : '') +
  (r.omitidas ? ` · ${r.omitidas} filas omitidas por datos inválidos (ej. ${r.ejemplos_omitidas?.[0] ?? ''})` : '')

export default function Config() {
  const { puede } = useYo(); const pCarga = puede('cargar_maestros'); const pSync = puede('sincronizar_siesa')
  const [defs, setDefs] = useState<Def[]>([])
  const [sel, setSel] = useState('bitacora')
  const [rows, setRows] = useState<any[]>([])
  const [cargando, setCargando] = useState(true)
  const [total, setTotal] = useState(0)
  // filtros de la pantalla; sirven igual para la descarga a Excel. Van atados al maestro con que se escribieron
  const VACIO = { tienda: '', texto: '', lab: '' }
  const [fRaw, setFRaw] = useState({ sel: 'bitacora', ...VACIO })
  const f = fRaw.sel === sel ? fRaw : { sel, ...VACIO }
  const setF = (c: Partial<typeof VACIO>) => setFRaw({ ...f, ...c, sel })
  const hayFiltro = !!(f.tienda || f.texto || f.lab)
  const consulta = () => { const p = new URLSearchParams(); if (f.tienda.trim()) p.set('bodega_id', f.tienda.trim().replace(/\s+/g, '')); if (f.texto.trim()) p.set('q', f.texto.trim()); if (f.lab.trim()) p.set('lab', f.lab.trim()); const s = p.toString(); return s ? '?' + s : '' }
  const [agregar, setAgregar] = useState(false)
  const [nueva, setNueva] = useState<Record<string, string>>({})
  const [msg, setMsg] = useState('')
  const [pegar, setPegar] = useState(false)
  const [txt, setTxt] = useState('')
  const [modo, setModo] = useState<'actualizar' | 'reemplazar'>('actualizar')
  const [omitir, setOmitir] = useState(false)
  const [grid, setGrid] = useState<GridApi | null>(null)
  const fileRef = useRef<HTMLInputElement>(null)
  const def = defs.find(d => d.clave === sel)

  useEffect(() => { api('/maestros').then(setDefs) }, [])
  // solo vale la respuesta de la ultima peticion (el usuario sigue escribiendo o cambia de maestro mientras llegan las anteriores)
  const peticion = useRef(0)
  const cargar = () => {
    const n = ++peticion.current; setCargando(true)
    return apiLista('/maestros/' + sel + consulta()).then(r => { if (n === peticion.current) { setRows(r.datos); setTotal(r.total) } })
      .catch(e => { if (n === peticion.current) setMsg('Error: ' + e.message) }).finally(() => { if (n === peticion.current) setCargando(false) })
  }
  useEffect(() => { setRows([]); setMsg(''); setModo('actualizar') }, [sel])
  useEffect(() => { const t = setTimeout(cargar, f.texto || f.tienda || f.lab ? 350 : 0); return () => clearTimeout(t) }, [sel, f.tienda, f.texto, f.lab])

  const cols: ColDef[] = useMemo(() => {
    if (!def) return []
    const llave = def.llave.map(k => ({ field: k, filter: true, pinned: k === def.llave[0] ? ('left' as const) : undefined,
      checkboxSelection: pCarga && k === def.llave[0] && !def.sin_reemplazo, headerCheckboxSelection: pCarga && k === def.llave[0] && !def.sin_reemplazo }))
    const desc: ColDef[] = [
      ...(rows[0] && 'bodega_nombre' in rows[0] ? [{ field: 'bodega_nombre', headerName: 'Tienda', filter: true, width: 200 }] : []),
      ...(rows[0] && 'descripcion' in rows[0] && !def.editable.includes('descripcion') ? [{ field: 'descripcion', filter: true, width: 240 }] : []),
    ]
    const ed = def.editable.map(k => def.tipos[k] === 'txt'
      ? { field: k, editable: pCarga, filter: true }
      : { field: k, editable: pCarga, type: 'numericColumn', filter: 'agNumberColumnFilter' })
    // items: una columna por plan de criterios (el nombre del plan es el encabezado, el criterio es el valor)
    const conocidas = new Set([...def.llave, ...def.editable, 'descripcion', 'bodega_nombre'])
    const extra: ColDef[] = def.clave === 'items' && rows[0]
      ? Object.keys(rows[0]).filter(k => !conocidas.has(k)).map(k => ({ field: k, headerName: k, filter: true, width: 190 })) : []
    const ed2 = def.clave === 'items' ? ed.map(c => c.field === 'categoria' ? { ...c, headerName: 'Laboratorio (código)', width: 150 } : c.field === 'descripcion' ? { ...c, width: 300 } : c) : ed
    return [...llave, ...desc, ...ed2, ...extra]
  }, [def, rows, pCarga])

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

  const confirmarModo = () => modo !== 'reemplazar' ||
    window.confirm(`REEMPLAZAR borra todo “${def?.label}” y deja exactamente lo que cargues. ¿Continuar?`)

  const descargar = async () => {
    try { setMsg(`Preparando ${sel}.xlsx… los maestros grandes tardan un poco`); await bajar(`/maestros/${sel}/excel${consulta()}`, `${sel}.xlsx`); setMsg('Descargado ' + sel + '.xlsx' + (hayFiltro ? ' (solo lo filtrado)' : '')) }
    catch (x: any) { setMsg('Error: ' + x.message) }
  }
  const subirArchivo = async (f: File | undefined) => {
    if (!f) return
    if (!confirmarModo()) { if (fileRef.current) fileRef.current.value = ''; return }
    const mb = (f.size / 1048576).toFixed(1)
    try { setMsg(`Subiendo ${f.name} (${mb} MB) y validando cada fila… con cientos de miles de filas puede tardar varios minutos, no cierres esta pantalla`); setMsg(resumen(await subir(`/maestros/${sel}/excel?modo=${modo}&omitir_invalidas=${omitir}`, f))); cargar() }
    catch (x: any) { setMsg('Error: ' + x.message) }
    if (fileRef.current) fileRef.current.value = ''
  }
  const enviar = async () => {
    const filas = parsear(txt)
    if (!filas.length) { setMsg('Pega encabezados y al menos una fila'); return }
    if (!confirmarModo()) return
    try {
      setMsg(`Cargando ${filas.length.toLocaleString()} filas pegadas…`)
      const r = await api('/maestros/' + sel + '/carga', { method: 'POST', body: JSON.stringify({ filas, modo, omitir_invalidas: omitir }) })
      setMsg(resumen(r)); setPegar(false); setTxt(''); cargar()
    } catch (x: any) { setMsg('Error: ' + x.message) }
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
    if (!window.confirm('Traer las ventas por mes de Siesa? Reemplaza la ventana de meses (los meses anteriores no se tocan). Puede tardar varios minutos.')) return
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
    if (!window.confirm(`Eliminar ${s.length} fila(s) de “${def.label}”?`)) return
    try {
      setMsg(`Eliminando ${s.length.toLocaleString()} fila(s)…`)
      const r = await api(`/maestros/${sel}/eliminar`, { method: 'POST',
        body: JSON.stringify({ llaves: s.map(x => Object.fromEntries(def.llave.map(k => [k, String(x[k])]))) }) })
      setMsg(`Eliminadas ${r.eliminadas}`); cargar()
    } catch (x: any) { setMsg('Error: ' + x.message) }
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
        {def && !def.sin_reemplazo && <Button color="error" startIcon={<DeleteOutline />} onClick={eliminar}>Eliminar seleccionadas</Button>}</>}
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
          {def.filtros.tienda && <TextField size="small" label="Tienda(s)" placeholder="SV021, GN408" value={f.tienda} onChange={e => setF({ tienda: e.target.value })} sx={{ width: 190 }} />}
          <TextField size="small" label={def.filtros.item ? 'Item o descripción' : 'Buscar'} value={f.texto} onChange={e => setF({ texto: e.target.value })} sx={{ width: 220 }} />
          {def.filtros.lab && <TextField size="small" label="Laboratorio (código)" value={f.lab} onChange={e => setF({ lab: e.target.value })} sx={{ width: 170 }} />}
          {hayFiltro && <Button size="small" onClick={() => setF(VACIO)}>Quitar filtros</Button>}
          <Box sx={{ flex: 1 }} />
          <Chip size="small" label={total > rows.length ? `Mostrando ${rows.length.toLocaleString('es-CO')} de ${total.toLocaleString('es-CO')} filas` : `${rows.length.toLocaleString('es-CO')} ${rows.length === 1 ? 'fila' : 'filas'}`} color={total > rows.length ? 'warning' : 'default'} />
        </Paper>)}
      {total > rows.length && <Alert severity="warning" sx={{ py: 0 }}>Este maestro tiene {total.toLocaleString('es-CO')} filas y la pantalla solo muestra las primeras {rows.length.toLocaleString('es-CO')}: filtra por tienda o item para verlas y editarlas. “Descargar Excel” baja todo lo filtrado, sin ese tope.</Alert>}
      {pegar && def && (
        <Stack spacing={1}>
          <TextField multiline minRows={4} fullWidth value={txt} onChange={e => setTxt(e.target.value)} placeholder="Pega aquí con la fila de encabezados" />
          <Box><Button variant="contained" onClick={enviar}>Cargar</Button></Box>
        </Stack>)}
      <Box className="ag-theme-quartz" sx={{ flex: 1, minHeight: 300 }}>
        <Tabla cargando={cargando} vacio="Este maestro está vacío: carga datos con Excel, pegando o trayendo de Siesa" rowData={rows} columnDefs={cols} onCellValueChanged={onChange} rowBuffer={20} rowSelection="multiple"
          onGridReady={e => setGrid(e.api)} defaultColDef={{ resizable: true, sortable: true }} />
      </Box>
      <Dialog open={agregar} onClose={() => setAgregar(false)} maxWidth="xs" fullWidth>
        <DialogTitle>Agregar fila · {def?.label}</DialogTitle>
        <DialogContent sx={{ display: 'grid', gap: 1.5, pt: '8px !important' }}>
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
