import { useEffect, useMemo, useState } from 'react'
import Tabla from '../Tabla'
import { ColDef } from 'ag-grid-community'
import { Autocomplete, Box, Card, CardActionArea, Chip, MenuItem, Paper, TextField, Typography } from '@mui/material'
import { api } from '../api'
import { ayudar } from '../ayuda'

const num = (p: any) => p.value == null ? '' : Number(p.value).toLocaleString('es-CO', { maximumFractionDigits: 2 })
const cols: ColDef[] = [
  { field: 'bodega_id', headerName: 'Bodega', filter: true, width: 110 },
  { field: 'producto_id', headerName: 'Producto', filter: true, width: 110 },
  { field: 'descripcion', headerName: 'Descripción', filter: true, flex: 1, minWidth: 200 },
  { field: 'inventario', headerName: 'Inventario', type: 'numericColumn', valueFormatter: num },
  { field: 'en_transito', headerName: 'Tránsito', type: 'numericColumn', valueFormatter: num },
  { field: 'flujo_neto', headerName: 'Flujo neto', type: 'numericColumn', valueFormatter: num },
  { field: 'tor', headerName: 'TOR', type: 'numericColumn', valueFormatter: num },
  { field: 'tog_aj', headerName: 'TOG aj.', type: 'numericColumn', valueFormatter: num },
  { field: 'pct_buffer', headerName: '% buffer', type: 'numericColumn', sort: 'asc', valueFormatter: num },
  { field: 'cantidad_sugerida', headerName: 'Sugerido', type: 'numericColumn', valueFormatter: num },
]
const color: Record<string, string> = { ROJA: '#c62828', AMARILLA: '#f9a825', VERDE: '#2e7d32', EXCESO: '#1565c0' }

export default function Dashboard() {
  const [res, setRes] = useState<{ zona: string; n: number }[]>([])
  const [d, setD] = useState<{ total: number; filas: any[] }>({ total: 0, filas: [] })
  const [cargando, setCargando] = useState(true)
  const [opc, setOpc] = useState<any>({ tiendas: [], laboratorios: [], empresas: [], criterios: [] })
  const [empresa, setEmpresa] = useState<string[]>([]); const [bodegas, setBodegas] = useState<string[]>([]); const [labs, setLabs] = useState<string[]>([])
  const [plan, setPlan] = useState(''); const [crit, setCrit] = useState<string[]>([]); const [qd, setQd] = useState(''); const [q, setQ] = useState('')
  useEffect(() => { api('/control/filtros').then(setOpc).catch(() => {}) }, [])
  useEffect(() => { const t = setTimeout(() => setQ(qd), 400); return () => clearTimeout(t) }, [qd])
  // los filtros se resuelven en el servidor (mismos que Control DDMRP) y valen para las tarjetas y para la lista
  const qs = useMemo(() => {
    const p = new URLSearchParams()
    if (empresa.length) p.set('empresa', empresa.join(',')); if (bodegas.length) p.set('bodegas', bodegas.join(',')); if (labs.length) p.set('labs', labs.join(','))
    if (q.trim()) p.set('q', q.trim()); if (plan && crit.length) p.set('crit', crit.map(v => `${plan}:${v}`).join(','))
    return p.toString()
  }, [empresa, bodegas, labs, q, plan, crit])
  useEffect(() => {
    let vivo = true; setCargando(true)
    Promise.all([api('/alertas/resumen?' + qs), api('/alertas/zona-roja?' + qs)])
      .then(([r, z]) => { if (vivo) { setRes(r); setD(z) } }).catch(() => {}).finally(() => vivo && setCargando(false))
    return () => { vivo = false }
  }, [qs])
  const hayFiltro = !!qs
  const total = res.reduce((a, r) => a + r.n, 0) || 1
  const nl = (c: string) => opc.laboratorios.find((l: any) => l.codigo === c)?.nombre
  const nt = (id: string) => opc.tiendas.find((t: any) => t.bodega_id === id)?.nombre
  const valores = opc.criterios.find((p: any) => p.plan_id === plan)?.valores ?? []
  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', height: '100%', gap: 2 }}>
      <Paper variant="outlined" sx={{ flexShrink: 0, p: 1.25, display: 'flex', flexWrap: 'wrap', gap: 1, alignItems: 'center' }}>
        <Autocomplete multiple size="small" limitTags={1} sx={{ minWidth: 170, flex: '1 1 170px' }} options={opc.empresas} value={empresa}
          getOptionLabel={(o: string) => o === '05' ? 'Funat (05)' : o === '21' ? 'Stores (21)' : o} onChange={(_, v) => setEmpresa(v)} renderInput={p => <TextField {...p} label="Empresa" />} />
        <Autocomplete multiple size="small" limitTags={2} sx={{ minWidth: 230, flex: '2 1 230px' }} options={opc.tiendas.map((t: any) => t.bodega_id)} value={bodegas}
          getOptionLabel={(o: string) => nt(o) ? `${o} · ${nt(o)}` : o} onChange={(_, v) => setBodegas(v)} renderInput={p => <TextField {...p} label="Tienda" />} />
        <Autocomplete multiple size="small" limitTags={2} sx={{ minWidth: 230, flex: '2 1 230px' }} options={opc.laboratorios.map((l: any) => l.codigo)} value={labs}
          getOptionLabel={(o: string) => nl(o) ? `${o} · ${nl(o)}` : o} onChange={(_, v) => setLabs(v)} renderInput={p => <TextField {...p} label="Laboratorio" />} />
        {opc.criterios.length > 0 && <>
          <TextField select size="small" label="Criterio de items" value={plan} onChange={e => { setPlan(e.target.value); setCrit([]) }} sx={{ minWidth: 190 }} slotProps={{ select: { displayEmpty: true }, inputLabel: { shrink: true } }}>
            <MenuItem value="">(elige un criterio)</MenuItem>{opc.criterios.map((p: any) => <MenuItem key={p.plan_id} value={p.plan_id}>{p.nombre}</MenuItem>)}</TextField>
          {plan && <Autocomplete multiple size="small" limitTags={2} sx={{ minWidth: 220, flex: '2 1 220px' }} options={valores.map((v: any) => v.id)} value={crit}
            getOptionLabel={(o: string) => valores.find((v: any) => v.id === o)?.nombre ?? o} onChange={(_, v) => setCrit(v)} renderInput={p => <TextField {...p} label="Valores" />} />}
        </>}
        <TextField size="small" label="Item (código o nombre)" value={qd} onChange={e => setQd(e.target.value)} sx={{ minWidth: 190, flex: '1 1 190px' }} />
        {hayFiltro && <Chip size="small" label="Quitar filtros" onClick={() => { setEmpresa([]); setBodegas([]); setLabs([]); setPlan(''); setCrit([]); setQd(''); setQ('') }} />}
      </Paper>
      <Box sx={{ display: 'grid', gridTemplateColumns: { xs: 'repeat(2, 1fr)', md: 'repeat(4, 1fr)' }, gap: 2 }}>
        {res.map(r => (
          <Card key={r.zona} variant="outlined" sx={{ borderLeft: `6px solid ${color[r.zona] ?? '#999'}` }}>
            <CardActionArea sx={{ p: 1.5 }} disableRipple>
              <Typography variant="caption" color="text.secondary">Zona {r.zona.toLowerCase()}</Typography>
              <Typography variant="h5" sx={{ fontWeight: 700 }}>{r.n.toLocaleString()}</Typography>
              <Typography variant="caption" color="text.secondary">{((r.n / total) * 100).toFixed(1)}% de las combinaciones</Typography>
            </CardActionArea>
          </Card>))}
      </Box>
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
        <Typography variant="subtitle1" sx={{ fontWeight: 600 }}>Productos en zona roja</Typography>
        <Chip size="small" color={d.total > d.filas.length ? 'warning' : 'default'}
          label={d.total > d.filas.length ? `Mostrando ${d.filas.length.toLocaleString('es-CO')} de ${d.total.toLocaleString('es-CO')}: filtra para ver el resto` : `${d.total.toLocaleString('es-CO')} combinaciones`} />
      </Box>
      <Box className="ag-theme-quartz" sx={{ flex: 1, minHeight: 300 }}>
        <Tabla cargando={cargando} vacio="Sin productos en zona roja con estos filtros" rowData={d.filas} columnDefs={ayudar(cols)} rowBuffer={20} animateRows={false} tooltipShowDelay={300} defaultColDef={{ resizable: true, sortable: true }} />
      </Box>
    </Box>)
}
