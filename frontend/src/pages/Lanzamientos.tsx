import { useEffect, useState } from 'react'
import { ColDef, ICellRendererParams } from 'ag-grid-community'
import { Autocomplete, Alert, Box, Button, Chip, MenuItem, Paper, TextField, Tooltip, Typography } from '@mui/material'
import Tabla from '../Tabla'
import { api, bajar } from '../api'

const hoy = () => new Date().toISOString().slice(0, 10)
const hace = (d: number) => new Date(Date.now() - d * 86400000).toISOString().slice(0, 10)
const num = (p: { value: any }) => p.value == null ? '' : Math.round(p.value).toLocaleString('es-CO')

const COLS: ColDef[] = [
  { field: 'fecha', headerName: 'Fecha', width: 110, pinned: 'left', sort: 'desc', filter: true },
  { field: 'tipo', headerName: 'Tipo', width: 120, filter: true, cellRenderer: (p: ICellRendererParams) => p.value == null ? '' :
    <Chip size="small" label={p.value === 'PRIMERA' ? 'Lanzamiento' : 'Reingreso'} sx={{ height: 20, fontSize: 11, color: '#fff', bgcolor: p.value === 'PRIMERA' ? '#2e7d32' : '#1565c0' }} /> },
  { field: 'dias_sin_stock', headerName: 'Días sin stock', type: 'numericColumn', width: 125, headerTooltip: 'Días que el CEDI estuvo sin existencia antes de volver (solo reingresos)' },
  { field: 'empresa', headerName: 'Emp.', width: 80, filter: true },
  { field: 'producto_id', headerName: 'Item', width: 100, filter: true },
  { field: 'descripcion', headerName: 'Descripción', flex: 1, minWidth: 240, filter: true },
  { field: 'laboratorio', headerName: 'Lab.', width: 90, filter: true },
  { field: 'existencia', headerName: 'Existencia CEDI', type: 'numericColumn', width: 140, valueFormatter: num },
  { field: 'costo', headerName: 'Costo', type: 'numericColumn', width: 110, valueFormatter: p => p.value == null ? '' : '$' + Math.round(p.value).toLocaleString('es-CO') },
  { field: 'tiendas', headerName: 'Tiendas', type: 'numericColumn', width: 95, headerTooltip: 'Tiendas donde el motor calcula buffer para el item (última corrida)' },
  { field: 'con_stock', headerName: 'Con stock', type: 'numericColumn', width: 105 },
  { field: 'en_rojo', headerName: 'En rojo', type: 'numericColumn', width: 95, cellStyle: { color: '#c62828', fontWeight: 600 } },
  { field: 'sugerido', headerName: 'Sugerido (u.)', type: 'numericColumn', width: 120, valueFormatter: num },
]

export default function Lanzamientos() {
  const [desde, setDesde] = useState(hace(30)); const [hasta, setHasta] = useState(hoy())
  const [tipo, setTipo] = useState(''); const [minDias, setMinDias] = useState(0); const [empresa, setEmpresa] = useState('')
  const [labs, setLabs] = useState<string[]>([]); const [plan, setPlan] = useState(''); const [crit, setCrit] = useState<string[]>([])
  const [q, setQ] = useState(''); const [qd, setQd] = useState('')
  const [opc, setOpc] = useState<any>({ laboratorios: [], criterios: [], base: [] })
  const [d, setD] = useState<{ filas: any[]; total: number; truncado: boolean; historia_desde: string | null }>({ filas: [], total: 0, truncado: false, historia_desde: null })
  const [cargando, setCargando] = useState(false); const [err, setErr] = useState(''); const [bajando, setBajando] = useState(false)

  useEffect(() => { api('/lanzamientos/filtros').then(setOpc).catch(e => setErr(e.message)) }, [])
  useEffect(() => { const t = setTimeout(() => setQ(qd), 400); return () => clearTimeout(t) }, [qd])
  const qs = () => {
    const p = new URLSearchParams({ desde, hasta })
    if (tipo) p.set('tipo', tipo); if (minDias > 0) p.set('min_dias', String(minDias)); if (empresa) p.set('empresa', empresa)
    if (labs.length) p.set('labs', labs.join(',')); if (q.trim()) p.set('q', q.trim())
    if (plan && crit.length) p.set('crit', crit.map(v => `${plan}:${v}`).join(','))
    return p.toString()
  }
  const clave = qs()
  useEffect(() => {
    let vivo = true; setCargando(true); setErr('')
    api('/lanzamientos?limit=5000&' + clave).then(r => vivo && setD(r)).catch(e => vivo && setErr(e.message)).finally(() => vivo && setCargando(false))
    return () => { vivo = false }
  }, [clave])
  const excel = async () => { setBajando(true); try { await bajar('/lanzamientos/excel?' + clave, 'lanzamientos.xlsx') } catch (e: any) { setErr(e.message) } finally { setBajando(false) } }
  const nl = (c: string) => opc.laboratorios.find((x: any) => x.codigo === c)?.nombre
  const valores = opc.criterios.find((p: any) => p.plan_id === plan)?.valores ?? []

  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', height: '100%', gap: 1.5, minHeight: 600 }}>
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
        <Typography variant="h6" sx={{ fontWeight: 700, flex: 1 }}>Lanzamientos y reingresos del CEDI</Typography>
        <Button size="small" variant="outlined" disabled={bajando} onClick={excel}>{bajando ? 'Generando…' : 'Descargar Excel'}</Button>
      </Box>
      <Alert severity="info" sx={{ flexShrink: 0 }}>
        El ETL compara la existencia del CEDI en cada corrida. <b>Lanzamiento</b> = el item aparece con existencia por primera vez; <b>Reingreso</b> = vuelve a tener existencia después de días sin stock (agotado, cartera, etc.).
        {d.historia_desde ? <> La historia empieza el {String(d.historia_desde).slice(0, 10)} (la primera lectura es la base y no genera eventos).</> : <> Aún no hay lectura base: corre el ETL; los eventos aparecen desde la segunda corrida.</>}
      </Alert>
      <Paper variant="outlined" sx={{ flexShrink: 0, p: 1.25, display: 'flex', flexWrap: 'wrap', gap: 1, alignItems: 'center' }}>
        <TextField size="small" type="date" label="Desde" value={desde} onChange={e => e.target.value && setDesde(e.target.value)} slotProps={{ inputLabel: { shrink: true } }} />
        <TextField size="small" type="date" label="Hasta" value={hasta} onChange={e => e.target.value && setHasta(e.target.value)} slotProps={{ inputLabel: { shrink: true } }} />
        {[['7 días', 7], ['30 días', 30], ['90 días', 90], ['12 meses', 365]].map(([l, n]) =>
          <Button key={l as string} size="small" variant="outlined" onClick={() => { setDesde(hace(n as number)); setHasta(hoy()) }}>{l}</Button>)}
        <TextField select size="small" label="Tipo" value={tipo} onChange={e => setTipo(e.target.value)} sx={{ width: 150 }}>
          <MenuItem value="">Todos</MenuItem><MenuItem value="PRIMERA">Lanzamientos</MenuItem><MenuItem value="REINGRESO">Reingresos</MenuItem></TextField>
        <Tooltip title="Solo reingresos que estuvieron al menos estos días sin stock (los lanzamientos siempre salen)"><TextField size="small" type="number" label="Mín. días sin stock" value={minDias} onChange={e => setMinDias(Math.max(0, Number(e.target.value)))} sx={{ width: 160 }} /></Tooltip>
        <TextField select size="small" label="Empresa" value={empresa} onChange={e => setEmpresa(e.target.value)} sx={{ width: 140 }}>
          <MenuItem value="">Todas</MenuItem><MenuItem value="05">05 · Funat</MenuItem><MenuItem value="21">21 · Stores</MenuItem></TextField>
        <Autocomplete multiple size="small" limitTags={2} sx={{ minWidth: 240, flex: '2 1 240px' }} options={opc.laboratorios.map((l: any) => l.codigo)} value={labs}
          getOptionLabel={(o: string) => nl(o) ? `${o} · ${nl(o)}` : o} onChange={(_, v) => setLabs(v)} renderInput={p => <TextField {...p} label="Laboratorio" />} />
        {opc.criterios.length > 0 && <>
          <TextField select size="small" label="Criterio de items" value={plan} onChange={e => { setPlan(e.target.value); setCrit([]) }} sx={{ minWidth: 190 }} slotProps={{ select: { displayEmpty: true }, inputLabel: { shrink: true } }}>
            <MenuItem value="">(elige un criterio)</MenuItem>{opc.criterios.map((p: any) => <MenuItem key={p.plan_id} value={p.plan_id}>{p.nombre}</MenuItem>)}</TextField>
          {plan && <Autocomplete multiple size="small" limitTags={2} sx={{ minWidth: 220, flex: '2 1 220px' }} options={valores.map((v: any) => v.id)} value={crit}
            getOptionLabel={(o: string) => valores.find((v: any) => v.id === o)?.nombre ?? o} onChange={(_, v) => setCrit(v)} renderInput={p => <TextField {...p} label="Valores" />} />}
        </>}
        <TextField size="small" label="Item (código o nombre)" value={qd} onChange={e => setQd(e.target.value)} sx={{ minWidth: 200, flex: '1 1 200px' }} />
      </Paper>
      {err && <Typography color="error" variant="body2">{err}</Typography>}
      <Typography variant="caption" color="text.secondary">{d.truncado ? `Mostrando ${d.filas.length.toLocaleString()} de ${d.total.toLocaleString()} eventos; filtra o baja el Excel` : `${d.total.toLocaleString()} eventos`} · solo items activos</Typography>
      <Box className="ag-theme-quartz" sx={{ flex: 1, minHeight: 320 }}>
        <Tabla textoCargando="Buscando…" vacio="Sin lanzamientos ni reingresos en este rango" rowData={d.filas} columnDefs={COLS} cargando={cargando} defaultColDef={{ resizable: true, sortable: true }} />
      </Box>
    </Box>)
}
