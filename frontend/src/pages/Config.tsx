import { useEffect, useMemo, useRef, useState } from 'react'
import { AgGridReact } from 'ag-grid-react'
import { CellValueChangedEvent, ColDef, GridApi } from 'ag-grid-community'
import { Box, Button, Chip, MenuItem, Paper, Stack, TextField, Typography } from '@mui/material'
import Download from '@mui/icons-material/Download'
import Upload from '@mui/icons-material/Upload'
import ContentPaste from '@mui/icons-material/ContentPaste'
import DeleteOutline from '@mui/icons-material/DeleteOutline'
import CloudSync from '@mui/icons-material/CloudSync'
import { api, bajar, subir } from '../api'
import Aviso from '../Aviso'

type Def = { clave: string; label: string; llave: string[]; editable: string[]; tipos: Record<string, string>; sin_reemplazo: boolean }

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
  (r.ignoradas ? ` · ${r.ignoradas} ignoradas (no existen)` : '')

export default function Config() {
  const [defs, setDefs] = useState<Def[]>([])
  const [sel, setSel] = useState('bitacora')
  const [rows, setRows] = useState<any[]>([])
  const [msg, setMsg] = useState('')
  const [pegar, setPegar] = useState(false)
  const [txt, setTxt] = useState('')
  const [modo, setModo] = useState<'actualizar' | 'reemplazar'>('actualizar')
  const [grid, setGrid] = useState<GridApi | null>(null)
  const fileRef = useRef<HTMLInputElement>(null)
  const def = defs.find(d => d.clave === sel)

  useEffect(() => { api('/maestros').then(setDefs) }, [])
  const cargar = () => api('/maestros/' + sel).then(setRows).catch(e => setMsg('Error: ' + e.message))
  useEffect(() => { setRows([]); setMsg(''); setModo('actualizar'); cargar() }, [sel])

  const cols: ColDef[] = useMemo(() => {
    if (!def) return []
    const llave = def.llave.map(k => ({ field: k, filter: true, pinned: k === def.llave[0] ? ('left' as const) : undefined,
      checkboxSelection: k === def.llave[0] && !def.sin_reemplazo, headerCheckboxSelection: k === def.llave[0] && !def.sin_reemplazo }))
    const desc: ColDef[] = [
      ...(rows[0] && 'bodega_nombre' in rows[0] ? [{ field: 'bodega_nombre', headerName: 'Tienda', filter: true, width: 200 }] : []),
      ...(rows[0] && 'descripcion' in rows[0] && !def.editable.includes('descripcion') ? [{ field: 'descripcion', filter: true, width: 240 }] : []),
    ]
    const ed = def.editable.map(k => def.tipos[k] === 'txt'
      ? { field: k, editable: true, filter: true }
      : { field: k, editable: true, type: 'numericColumn', filter: 'agNumberColumnFilter' })
    return [...llave, ...desc, ...ed]
  }, [def, rows])

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
    try { await bajar(`/maestros/${sel}/excel`, `${sel}.xlsx`); setMsg('Descargado ' + sel + '.xlsx') }
    catch (x: any) { setMsg('Error: ' + x.message) }
  }
  const subirArchivo = async (f: File | undefined) => {
    if (!f) return
    if (!confirmarModo()) { if (fileRef.current) fileRef.current.value = ''; return }
    try { setMsg('Cargando...'); setMsg(resumen(await subir(`/maestros/${sel}/excel?modo=${modo}`, f))); cargar() }
    catch (x: any) { setMsg('Error: ' + x.message) }
    if (fileRef.current) fileRef.current.value = ''
  }
  const enviar = async () => {
    const filas = parsear(txt)
    if (!filas.length) { setMsg('Pega encabezados y al menos una fila'); return }
    if (!confirmarModo()) return
    try {
      const r = await api('/maestros/' + sel + '/carga', { method: 'POST', body: JSON.stringify({ filas, modo }) })
      setMsg(resumen(r)); setPegar(false); setTxt(''); cargar()
    } catch (x: any) { setMsg('Error: ' + x.message) }
  }
  const traerTiendas = async () => {
    try { setMsg('Trayendo tiendas de Siesa...'); const r = await api('/admin/sincronizar-bodegas', { method: 'POST' }); setMsg(`Tiendas sincronizadas: ${r.tiendas}`) }
    catch (x: any) { setMsg('Error: ' + x.message) }
  }
  const eliminar = async () => {
    const s = grid?.getSelectedRows() ?? []
    if (!def || !s.length) { setMsg('Selecciona filas para eliminar'); return }
    if (!window.confirm(`Eliminar ${s.length} fila(s) de “${def.label}”?`)) return
    try {
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
        <Button variant="outlined" startIcon={<Download />} onClick={descargar}>Descargar Excel</Button>
        <Box sx={{ borderLeft: '1px solid #ccc', height: 28, mx: .5 }} />
        <TextField select size="small" label="Al cargar" value={modo} onChange={e => setModo(e.target.value as any)} sx={{ minWidth: 270 }}>
          <MenuItem value="actualizar">Crear nuevos y actualizar existentes</MenuItem>
          {!def?.sin_reemplazo && <MenuItem value="reemplazar">Reemplazar todo el maestro</MenuItem>}
        </TextField>
        <Button variant="contained" startIcon={<Upload />} onClick={() => fileRef.current?.click()}>Subir Excel / CSV</Button>
        <input ref={fileRef} type="file" accept=".xlsx,.csv,.txt" hidden onChange={e => subirArchivo(e.target.files?.[0])} />
        <Button startIcon={<ContentPaste />} onClick={() => setPegar(!pegar)}>Pegar desde Excel</Button>
        {def && !def.sin_reemplazo && <Button color="error" startIcon={<DeleteOutline />} onClick={eliminar}>Eliminar seleccionadas</Button>}
        <Box sx={{ flex: 1 }} />
        <Button size="small" startIcon={<CloudSync />} onClick={traerTiendas} title="Lee de Siesa las tiendas (código y nombre)">Traer tiendas de Siesa</Button>
      </Paper>
      {def && (
        <Typography variant="body2" color="text.secondary">
          “Descargar Excel” te da la plantilla con los datos actuales. La tienda se identifica por código de Siesa (ej. SV021) y la empresa se deduce sola.
          Las referencias van como texto de 6 dígitos. Columnas a cargar:{' '}
          {def.editable.length ? def.editable.map(c => <Chip key={c} size="small" label={c} sx={{ mr: .5 }} />) : '(solo existencia de la fila)'}
        </Typography>)}
      {pegar && def && (
        <Stack spacing={1}>
          <TextField multiline minRows={4} fullWidth value={txt} onChange={e => setTxt(e.target.value)} placeholder="Pega aquí con la fila de encabezados" />
          <Box><Button variant="contained" onClick={enviar}>Cargar</Button></Box>
        </Stack>)}
      <Box className="ag-theme-quartz" sx={{ flex: 1, minHeight: 300 }}>
        <AgGridReact rowData={rows} columnDefs={cols} onCellValueChanged={onChange} rowBuffer={20} rowSelection="multiple"
          onGridReady={e => setGrid(e.api)} defaultColDef={{ resizable: true, sortable: true }} />
      </Box>
      <Aviso msg={msg} onClose={() => setMsg('')} />
    </Box>)
}
