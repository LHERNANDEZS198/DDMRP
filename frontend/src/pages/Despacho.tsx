import { useEffect, useState } from 'react'
import { AgGridReact } from 'ag-grid-react'
import { ColDef, GridApi } from 'ag-grid-community'
import { Box, Button, Checkbox, Chip, FormControlLabel, MenuItem, Paper, Stack, TextField, Typography } from '@mui/material'
import Check from '@mui/icons-material/Check'
import Download from '@mui/icons-material/Download'
import { api, descargar } from '../api'
import Aviso from '../Aviso'
import { useYo } from '../Yo'

const cols: ColDef[] = [
  { checkboxSelection: true, headerCheckboxSelection: true, width: 50, pinned: 'left' },
  { field: 'bodega_id', headerName: 'Bodega', filter: true },
  { field: 'producto_id', headerName: 'Producto', filter: true },
  { field: 'descripcion', flex: 1, minWidth: 220, filter: true },
  { field: 'zona', filter: true },
  { field: 'inventario', type: 'numericColumn' },
  { field: 'en_transito', headerName: 'Transito', type: 'numericColumn' },
  { field: 'tog_aj', headerName: 'TOG aj.', type: 'numericColumn' },
  { field: 'unidad_despacho', headerName: 'Und. desp.', type: 'numericColumn' },
  { field: 'vectorizacion', headerName: 'Derrame', type: 'numericColumn' },
  { field: 'cantidad_sugerida', headerName: 'Sugerido', type: 'numericColumn' },
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
  const cargar = () => api('/despacho/matriz' + (filtrar ? '?bodegas=' + encodeURIComponent(tiendas.join(',') || '-') : '')).then(setRows)
  useEffect(() => { cargar() }, [filtrar, tiendas.join(',')])
  const aprobar = async () => {
    const sel = grid?.getSelectedRows() ?? []
    if (!sel.length) { setMsg('Selecciona filas'); return }
    try {
      await api('/despacho/aprobar', { method: 'POST', body: JSON.stringify(sel.map((r: any) => ({
        ejecucion_id: r.ejecucion_id, producto_id: r.producto_id, bodega_id: r.bodega_id,
        cantidad_aprobada: r.cantidad_aprobada ?? r.cantidad_sugerida, aprobar: true }))) })
      setMsg(`Aprobadas ${sel.length}`); cargar()
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
      <Paper variant="outlined" sx={{ p: 1.5, display: 'flex', flexWrap: 'wrap', gap: 1.5, alignItems: 'center' }}>
        {pAprobar && <Button variant="contained" startIcon={<Check />} onClick={aprobar}>Aprobar seleccionados</Button>}
        {pPlano && <><TextField size="small" sx={{ width: 320 }} label="Nota del documento" value={notas} onChange={e => setNotas(e.target.value)}
          placeholder={`ABASTECIMIENTO DEL <dia> DE <MES>${dia ? ` DÍA ${dia}` : ''}`} />
        <TextField size="small" type="number" label="Consecutivo inicial" sx={{ width: 150 }} value={consec}
          slotProps={{ htmlInput: { min: 1 } }} onChange={e => setConsec(Number(e.target.value))} />
        <FormControlLabel control={<Checkbox size="small" checked={marcar} onChange={e => setMarcar(e.target.checked)} />} label="Marcar como enviadas" />
        <Button variant="outlined" startIcon={<Download />} onClick={plano}>Generar archivo plano Siesa</Button>
        <Button disabled title="Fase 3">Enviar a Siesa (web service)</Button></>}
      </Paper>
      <Box className="ag-theme-quartz" sx={{ flex: 1, minHeight: 300 }}>
        <AgGridReact rowData={rows} columnDefs={cols} rowSelection="multiple" rowBuffer={20}
          context={{ aprobar: pAprobar }} onGridReady={e => setGrid(e.api)} defaultColDef={{ resizable: true, sortable: true }} />
      </Box>
      <Aviso msg={msg} onClose={() => setMsg('')} />
    </Box>)
}
