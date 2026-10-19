import { useEffect, useMemo, useState } from 'react'
import Tabla from '../Tabla'
import { ColDef } from 'ag-grid-community'
import { Alert, Autocomplete, Box, Button, Chip, FormControlLabel, MenuItem, Paper, Stack, Switch, TextField, Typography } from '@mui/material'
import Download from '@mui/icons-material/Download'
import { api, bajar } from '../api'
import Aviso from '../Aviso'
import { ayudar } from '../ayuda'

const ZONAS = ['ROJA', 'AMARILLA', 'VERDE', 'EXCESO']
const COLOR: Record<string, string> = { ROJA: '#c62828', AMARILLA: '#b78103', VERDE: '#2e7d32', EXCESO: '#1565c0' }
const num = (p: any) => p.value == null ? '' : Number(p.value).toLocaleString('es-CO', { maximumFractionDigits: 2 })
const cols: ColDef[] = [
  { field: 'bodega_id', headerName: 'Bodega', filter: true, width: 100, pinned: 'left' },
  { field: 'producto_id', headerName: 'Producto', filter: true, width: 110, pinned: 'left' },
  { field: 'descripcion', headerName: 'Descripcion', flex: 1, minWidth: 220, filter: true },
  { field: 'adu', headerName: 'ADU', type: 'numericColumn', width: 90, valueFormatter: num },
  { field: 'forecast', headerName: 'Forecast', type: 'numericColumn', width: 100, valueFormatter: num },
  { field: 'tor', headerName: 'TOR', type: 'numericColumn', width: 90, valueFormatter: num },
  { field: 'toy_aj', headerName: 'TOY aj.', type: 'numericColumn', width: 95, valueFormatter: num },
  { field: 'tog_aj', headerName: 'TOG aj.', type: 'numericColumn', width: 95, valueFormatter: num },
  { field: 'inventario', headerName: 'Inventario', type: 'numericColumn', width: 105, valueFormatter: num },
  { field: 'en_transito', headerName: 'Transito', type: 'numericColumn', width: 95, valueFormatter: num },
  { field: 'flujo_neto', headerName: 'Flujo neto', type: 'numericColumn', width: 105, valueFormatter: num },
  { field: 'zona', headerName: 'Zona', width: 105, cellStyle: p => ({ color: COLOR[p.value] ?? undefined, fontWeight: 700 }) },
  { field: 'necesidad', headerName: 'Necesario', type: 'numericColumn', width: 105, valueFormatter: num },
  { field: 'stock_cedi', headerName: 'Stock CEDI', type: 'numericColumn', width: 105, valueFormatter: num },
  { field: 'cantidad_sugerida', headerName: 'Asignado', type: 'numericColumn', width: 105, valueFormatter: num },
  { field: 'estado', headerName: 'Estado', width: 110 },
]

type Opc = { tiendas: { bodega_id: string; nombre: string }[]; laboratorios: { codigo: string; nombre: string }[]; empresas: string[]; ejecucion: any }

export default function Auditoria() {
  const [opc, setOpc] = useState<Opc>({ tiendas: [], laboratorios: [], empresas: [], ejecucion: null })
  const [f, setF] = useState({ empresas: [] as string[], bodegas: [] as string[], labs: [] as string[], q: '', zonas: [] as string[], solo: true, limite: 10000 })
  const [d, setD] = useState<{ total: number; filas: any[]; tope_excel: number; ejecucion: any } | null>(null)
  const [cargando, setCargando] = useState(true)
  const [msg, setMsg] = useState(''); const [bajando, setBajando] = useState(false)
  useEffect(() => { api('/control/filtros').then(setOpc).catch(() => {}) }, [])
  const qs = useMemo(() => {
    const p = new URLSearchParams()
    if (f.empresas.length) p.set('empresa', f.empresas.join(','))
    if (f.bodegas.length) p.set('bodegas', f.bodegas.join(','))
    if (f.labs.length) p.set('labs', f.labs.join(','))
    if (f.q.trim()) p.set('q', f.q.trim())
    if (f.zonas.length) p.set('zonas', f.zonas.join(','))
    p.set('solo_sugerido', String(f.solo))
    return p
  }, [f])
  useEffect(() => {
    setCargando(true)
    let vivo = true
    const h = setTimeout(() => api('/auditoria/vista?' + qs.toString()).then(r => vivo && setD(r)).catch(e => vivo && setMsg('Error: ' + e.message)).finally(() => vivo && setCargando(false)), 300)
    return () => { vivo = false; clearTimeout(h) }
  }, [qs])
  const descargar = async () => {
    setBajando(true); setMsg('Armando el Excel con las fórmulas… puede tardar un minuto si son muchas filas')
    try {
      const p = new URLSearchParams(qs); p.set('limite', String(f.limite))
      await bajar('/auditoria/excel?' + p.toString(), 'Auditoria_DDMRP.xlsx'); setMsg('Excel descargado')
    } catch (e: any) { setMsg('Error: ' + e.message) } finally { setBajando(false) }
  }
  const total = d?.total ?? 0
  const sobra = total > f.limite
  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', height: '100%', gap: 1.5, minHeight: 500 }}>
      <Box>
        <Typography variant="h6" sx={{ fontWeight: 700 }}>Auditoría del cálculo</Typography>
        <Typography variant="body2" color="text.secondary">
          Elige las tiendas e items que quieres revisar y descarga el Excel: trae los datos de entrada y todo el cálculo hasta lo sugerido como fórmulas, igual que tu hoja “Modelo”,
          y una columna que compara con lo que calculó el motor{opc.ejecucion ? ` (corrida del ${String(opc.ejecucion.fecha_calculo).slice(0, 10)})` : ''}.
        </Typography>
      </Box>
      <Paper variant="outlined" sx={{ p: 1.5, display: 'flex', flexWrap: 'wrap', gap: 1.5, alignItems: 'center' }}>
        <Autocomplete multiple size="small" limitTags={1} sx={{ minWidth: 170, flex: '1 1 170px' }} options={opc.empresas} value={f.empresas}
          getOptionLabel={o => o === '05' ? 'Funat (05)' : o === '21' ? 'Stores (21)' : o} onChange={(_, v) => setF(x => ({ ...x, empresas: v }))} renderInput={p => <TextField {...p} label="Empresa" />} />
        <Autocomplete multiple size="small" limitTags={2} sx={{ minWidth: 240, flex: '2 1 240px' }} options={opc.tiendas.map(t => t.bodega_id)} value={f.bodegas}
          getOptionLabel={id => { const t = opc.tiendas.find(x => x.bodega_id === id); return t?.nombre ? `${id} · ${t.nombre}` : id }}
          onChange={(_, v) => setF(x => ({ ...x, bodegas: v }))} renderInput={p => <TextField {...p} label="Tienda" />} />
        <Autocomplete multiple size="small" limitTags={2} sx={{ minWidth: 240, flex: '2 1 240px' }} options={opc.laboratorios.map(l => l.codigo)} value={f.labs}
          getOptionLabel={c => { const l = opc.laboratorios.find(x => x.codigo === c); return l?.nombre ? `${c} · ${l.nombre}` : c }}
          onChange={(_, v) => setF(x => ({ ...x, labs: v }))} renderInput={p => <TextField {...p} label="Laboratorio" />} />
        <TextField size="small" label="Item (código o nombre)" value={f.q} onChange={e => setF(x => ({ ...x, q: e.target.value }))} sx={{ minWidth: 200, flex: '1 1 200px' }} />
        <Autocomplete multiple size="small" sx={{ minWidth: 200, flex: '1 1 200px' }} options={ZONAS} value={f.zonas}
          onChange={(_, v) => setF(x => ({ ...x, zonas: v }))} renderInput={p => <TextField {...p} label="Zona" />} />
        <FormControlLabel control={<Switch checked={f.solo} onChange={e => setF(x => ({ ...x, solo: e.target.checked }))} />} label="Solo con necesidad" />
        <TextField select size="small" label="Filas máx. en el Excel" value={f.limite} onChange={e => setF(x => ({ ...x, limite: Number(e.target.value) }))} sx={{ width: 170 }}>
          {[1000, 5000, 10000, 20000].map(n => <MenuItem key={n} value={n}>{n.toLocaleString('es-CO')}</MenuItem>)}
        </TextField>
        <Button variant="contained" startIcon={<Download />} onClick={descargar} disabled={bajando || !total}>Descargar Excel con fórmulas</Button>
      </Paper>
      {d && (
        <Stack direction="row" spacing={1} alignItems="center" useFlexGap flexWrap="wrap">
          <Chip label={`${total.toLocaleString('es-CO')} combinaciones tienda × item`} />
          {d.filas.length < total && <Typography variant="caption" color="text.secondary">La vista previa muestra las primeras {d.filas.length}.</Typography>}
          {sobra && <Alert severity="warning" sx={{ py: 0 }}>El Excel incluirá solo las primeras {f.limite.toLocaleString('es-CO')}: filtra más o sube el máximo.</Alert>}
        </Stack>)}
      <Box className="ag-theme-quartz" sx={{ flex: 1, minHeight: 300 }}>
        <Tabla cargando={cargando} textoCargando="Calculando la auditoría…" vacio="Ningún ítem cumple los filtros" rowData={d?.filas ?? []} columnDefs={ayudar(cols)} tooltipShowDelay={300} defaultColDef={{ resizable: true, sortable: true }} />
      </Box>
      <Aviso msg={msg} onClose={() => setMsg('')} />
    </Box>)
}
