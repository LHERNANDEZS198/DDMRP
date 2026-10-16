import { useEffect, useRef, useState } from 'react'
import { AgGridReact } from 'ag-grid-react'
import { ColDef, GridApi, ICellRendererParams } from 'ag-grid-community'
import { Alert, Box, Button, Checkbox, Chip, FormControlLabel, IconButton, MenuItem, Paper, Stack, TextField, Tooltip, Typography } from '@mui/material'
import Insights from '@mui/icons-material/Insights'
import Check from '@mui/icons-material/Check'
import Download from '@mui/icons-material/Download'
import Undo from '@mui/icons-material/Undo'
import { api, descargar } from '../api'
import Aviso from '../Aviso'
import { ayudar } from '../ayuda'
import { useYo } from '../Yo'

const verEnControl = (p: ICellRendererParams) => (
  <Tooltip title="Ver esta tienda y este item en Control DDMRP (foto actual), en una pestaña nueva">
    <IconButton size="small" component="a" target="_blank" rel="noopener" href={`/control?tienda=${encodeURIComponent(p.data.bodega_id)}&item=${encodeURIComponent(p.data.producto_id)}`}>
      <Insights fontSize="small" /></IconButton></Tooltip>)
const cols: ColDef[] = [
  { checkboxSelection: true, headerCheckboxSelection: true, width: 50, pinned: 'left' },
  { headerName: 'Control', width: 80, cellRenderer: verEnControl, sortable: false, pinned: 'left' },
  { field: 'bodega_id', headerName: 'Bodega', filter: true },
  { field: 'producto_id', headerName: 'Producto', filter: true },
  { field: 'descripcion', flex: 1, minWidth: 220, filter: true },
  { field: 'zona', filter: true },
  { field: 'estado', filter: true, width: 115 },
  { field: 'inventario', type: 'numericColumn' },
  { field: 'en_transito', headerName: 'Transito', type: 'numericColumn' },
  { field: 'tog_aj', headerName: 'TOG aj.', type: 'numericColumn' },
  { field: 'unidad_despacho', headerName: 'Und. desp.', type: 'numericColumn' },
  { field: 'vectorizacion', headerName: 'Derrame', type: 'numericColumn' },
  { field: 'cantidad_necesaria', headerName: 'Necesario', type: 'numericColumn' },
  { field: 'stock_cedi', headerName: 'Stock CEDI', type: 'numericColumn', valueFormatter: p => p.value == null ? '' : Math.round(p.value).toLocaleString() },
  { field: 'cantidad_sugerida', headerName: 'Asignado', type: 'numericColumn',
    cellStyle: p => p.data?.limitado ? { color: '#c62828', fontWeight: 700 } : null },
  { field: 'cantidad_aprobada', headerName: 'A enviar', editable: (p: any) => !!p.context?.aprobar, type: 'numericColumn',
    valueGetter: p => p.data.cantidad_aprobada ?? p.data.cantidad_sugerida,
    valueSetter: p => { p.data.cantidad_aprobada = Number(p.newValue); return true } },
]

export default function Despacho() {
  const { puede } = useYo(); const pAprobar = puede('aprobar_despacho'); const pPlano = puede('descargar_planos')
  const [rows, setRows] = useState<any[]>([])
  const [grid, setGrid] = useState<GridApi | null>(null)
  const [msg, setMsg] = useState('')
  const [notas, setNotas] = useState('')
  const [consec, setConsec] = useState(1)
  const [marcar, setMarcar] = useState(false)
  const [cedi, setCedi] = useState<any>(null)
  useEffect(() => { api('/despacho/cedi').then(setCedi).catch(() => {}) }, [])
  const [ver, setVer] = useState<'pendiente' | 'aprobada' | 'enviada'>('pendiente')
  // Corrida del dia: DIA de abastecimiento + tiendas elegidas (se pueden poner o quitar antes de generar)
  const [dias, setDias] = useState<{ dia: number; bodegas: string[] }[]>([])
  const [todas, setTodas] = useState<string[]>([])
  const [dia, setDia] = useState('')            // '' = sin DIA
  const [filtrar, setFiltrar] = useState(false) // false = todas las tiendas
  const [tiendas, setTiendas] = useState<string[]>([])
  const [nueva, setNueva] = useState('')
  useEffect(() => { api('/despacho/dias').then(x => { setDias(x.dias); setTodas(x.bodegas) }) }, [])
  const elegirDia = (v: string) => {
    setDia(v)
    if (v === '') { setFiltrar(false); setTiendas([]); return }
    setFiltrar(true); setTiendas(dias.find(d => String(d.dia) === v)?.bodegas ?? [])
  }
  const quitar = (b: string) => { setFiltrar(true); setTiendas(t => t.filter(x => x !== b)) }
  const poner = (b: string) => { if (!b) return; setFiltrar(true); setTiendas(t => t.includes(b) ? t : [...t, b].sort()); setNueva('') }
  // Solo vale la respuesta de la última petición: si cambias de "Ver" mientras llega una lista grande, la vieja no debe pisar la nueva
  const peticion = useRef(0)
  const cargar = () => {
    const n = ++peticion.current
    return api('/despacho/matriz?estado=' + ver + (filtrar ? '&bodegas=' + encodeURIComponent(tiendas.join(',') || '-') : ''))
      .then(r => { if (n === peticion.current) setRows(r) })
  }
  useEffect(() => { setRows([]); cargar() }, [filtrar, tiendas.join(','), ver])
  const aprobar = async () => {
    const sel = grid?.getSelectedRows() ?? []
    if (!sel.length) { setMsg('Selecciona filas'); return }
    try {
      await api('/despacho/aprobar', { method: 'POST', body: JSON.stringify(sel.map((r: any) => ({
        ejecucion_id: r.ejecucion_id, producto_id: r.producto_id, bodega_id: r.bodega_id,
        cantidad_aprobada: r.cantidad_aprobada ?? r.cantidad_sugerida, aprobar: true }))) })
      setMsg(`Aprobadas ${sel.length}. Las ves en “Aprobadas”, desde donde puedes devolverlas a pendiente.`); cargar()
    } catch (x: any) { setMsg('Error: ' + x.message) }
  }
  const devolver = async () => {
    const sel = grid?.getSelectedRows() ?? []
    if (!sel.length) { setMsg('Selecciona filas aprobadas'); return }
    try {
      const r = await api('/despacho/desaprobar', { method: 'POST', body: JSON.stringify(sel.map((x: any) => ({ ejecucion_id: x.ejecucion_id, producto_id: x.producto_id, bodega_id: x.bodega_id }))) })
      setMsg(r.devueltas ? `Devueltas a pendiente: ${r.devueltas}` + (r.omitidas ? ` (${r.omitidas} no estaban aprobadas)` : '')
        : 'Ninguna se devolvió: las filas elegidas no están aprobadas en la corrida actual.'); grid?.deselectAll(); cargar()
    } catch (x: any) { setMsg('Error: ' + x.message) }
  }
  const plano = async () => {
    try {
      setMsg('Generando el archivo plano de Siesa…')
      const r = await descargar('/despacho/exportar-plano', { notas: notas || null, consec_inicial: consec, marcar_enviadas: marcar,
        bodegas: filtrar ? tiendas : null, dia: dia ? Number(dia) : null })
      setMsg(`Descargado ${r.nombre}` + (r.derivado ? ` · centro de operacion deducido para: ${r.derivado}` : ''))
      if (marcar) cargar()
    } catch (x: any) { setMsg('Error: ' + x.message) }
  }
  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', height: '100%', gap: 1.5, minHeight: 500 }}>
      <Paper variant="outlined" sx={{ p: 1.5, display: 'flex', flexWrap: 'wrap', gap: 1, alignItems: 'center' }}>
        <Typography sx={{ fontWeight: 700 }}>Corrida</Typography>
        <TextField select size="small" value={dia} onChange={e => elegirDia(e.target.value)} sx={{ minWidth: 220 }} slotProps={{ select: { displayEmpty: true } }}>
          <MenuItem value="">Todas las tiendas</MenuItem>
          {dias.map(d => <MenuItem key={d.dia} value={String(d.dia)}>DIA {d.dia} ({d.bodegas.length} tiendas)</MenuItem>)}
        </TextField>
        {filtrar && tiendas.map(b => <Chip key={b} label={b} size="small" color="primary" variant="outlined" onDelete={() => quitar(b)} />)}
        <TextField select size="small" value={nueva} onChange={e => poner(e.target.value)} sx={{ minWidth: 170 }} label="+ agregar tienda">
          {todas.filter(b => !tiendas.includes(b)).map(b => <MenuItem key={b} value={b}>{b}</MenuItem>)}
        </TextField>
        {filtrar && <Button size="small" onClick={() => { setDia(''); setFiltrar(false); setTiendas([]) }}>Ver todas</Button>}
      </Paper>
      {cedi && (
        <Alert severity={cedi.activo ? 'info' : 'warning'} sx={{ py: 0 }}>
          {cedi.regla === 0 ? 'El reparto del inventario del CEDI está apagado: se sugiere todo lo que pide el buffer.'
            : cedi.productos === 0 ? `Sin inventario del CEDI (${cedi.bodega}): corre el ETL para traerlo. Mientras tanto no se limita lo sugerido.`
            : `CEDI ${cedi.bodega}: ${cedi.con_stock.toLocaleString()} items con stock (corte ${cedi.corte}) · si no alcanza: ${cedi.regla_nombre.toLowerCase()}`
              + (cedi.limitadas ? ` · ${cedi.limitadas.toLocaleString()} combinaciones con menos de lo necesario` : '')
              + (cedi.items_con_reserva ? ` · ${cedi.items_con_reserva} items con reserva` : '')}
        </Alert>)}
      <Paper variant="outlined" sx={{ p: 1.5, display: 'flex', flexWrap: 'wrap', gap: 1.5, alignItems: 'center' }}>
        <TextField select size="small" label="Ver" value={ver} onChange={e => setVer(e.target.value as any)} sx={{ minWidth: 130 }}>
          <MenuItem value="pendiente">Pendientes</MenuItem><MenuItem value="aprobada">Aprobadas</MenuItem><MenuItem value="enviada">Enviadas</MenuItem>
        </TextField>
        {pAprobar && ver === 'pendiente' && <Button variant="contained" startIcon={<Check />} onClick={aprobar}>Aprobar seleccionados</Button>}
        {pAprobar && ver === 'aprobada' && <Button variant="outlined" color="warning" startIcon={<Undo />} onClick={devolver}>Devolver a pendiente</Button>}
        {pPlano && <><TextField size="small" sx={{ width: 320 }} label="Nota del documento" value={notas} onChange={e => setNotas(e.target.value)}
          placeholder={`ABASTECIMIENTO DEL <dia> DE <MES>${dia ? ` DÍA ${dia}` : ''}`} />
        <TextField size="small" type="number" label="Consecutivo inicial" sx={{ width: 150 }} value={consec}
          slotProps={{ htmlInput: { min: 1 } }} onChange={e => setConsec(Number(e.target.value))} />
        <FormControlLabel control={<Checkbox size="small" checked={marcar} onChange={e => setMarcar(e.target.checked)} />} label="Marcar como enviadas" />
        <Button variant="outlined" startIcon={<Download />} onClick={plano}>Generar archivo plano Siesa</Button>
        <Button disabled title="Fase 3">Enviar a Siesa (web service)</Button></>}
      </Paper>
      <Box className="ag-theme-quartz" sx={{ flex: 1, minHeight: 300 }}>
        <AgGridReact rowData={rows} columnDefs={ayudar(cols)} tooltipShowDelay={300} rowSelection="multiple" rowBuffer={20}
          context={{ aprobar: pAprobar }} onGridReady={e => setGrid(e.api)} defaultColDef={{ resizable: true, sortable: true }} />
      </Box>
      <Aviso msg={msg} onClose={() => setMsg('')} />
    </Box>)
}
