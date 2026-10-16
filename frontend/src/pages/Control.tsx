import { useEffect, useMemo, useState } from 'react'
import { AgGridReact } from 'ag-grid-react'
import { ColDef, ICellRendererParams } from 'ag-grid-community'
import { Autocomplete, Box, Button, Card, CardActionArea, Chip, Paper, Tab, Tabs, TextField, Tooltip, Typography } from '@mui/material'
import { api } from '../api'

const COLOR: Record<string, string> = { ROJA: '#c62828', AMARILLA: '#f9a825', VERDE: '#2e7d32', EXCESO: '#1565c0' }
const ZONAS = ['ROJA', 'AMARILLA', 'VERDE', 'EXCESO']
const KEY: Record<string, string> = { ROJA: 'roja', AMARILLA: 'amarilla', VERDE: 'verde', EXCESO: 'exceso' }
const NIVELES = [
  { k: 'empresa', label: 'Empresa' }, { k: 'bodega', label: 'Tienda' }, { k: 'laboratorio', label: 'Laboratorio' },
  { k: 'item', label: 'Item' }, { k: 'detalle', label: 'Tienda × item' },
] as const
type Nivel = typeof NIVELES[number]['k']
const SIGUIENTE: Record<Nivel, Nivel> = { empresa: 'bodega', bodega: 'laboratorio', laboratorio: 'item', item: 'detalle', detalle: 'detalle' }
type F = { empresa: string[]; bodegas: string[]; labs: string[]; q: string; zonas: string[]; dia: string }
const VACIO: F = { empresa: [], bodegas: [], labs: [], q: '', zonas: [], dia: '' }

const qs = (f: F, sinZonas = false) => {
  const p = new URLSearchParams()
  if (f.empresa.length) p.set('empresa', f.empresa.join(','))
  if (f.bodegas.length) p.set('bodegas', f.bodegas.join(','))
  if (f.labs.length) p.set('labs', f.labs.join(','))
  if (f.q.trim()) p.set('q', f.q.trim())
  if (!sinZonas && f.zonas.length) p.set('zonas', f.zonas.join(','))
  if (f.dia) p.set('dia', f.dia)
  return p
}

/** Barra apilada con el % de combinaciones en cada zona. */
function ZonaBar(p: ICellRendererParams) {
  const g = p.data; if (!g?.n) return null
  return (
    <Box sx={{ display: 'flex', height: 18, width: '100%', borderRadius: 1, overflow: 'hidden', alignSelf: 'center', mt: '9px' }}>
      {ZONAS.map(z => g[KEY[z]] > 0 && (
        <Tooltip key={z} title={`${z}: ${g[KEY[z]].toLocaleString()} (${((g[KEY[z]] / g.n) * 100).toFixed(1)}%)`}>
          <Box sx={{ width: `${(g[KEY[z]] / g.n) * 100}%`, bgcolor: COLOR[z], color: '#fff', fontSize: 10, textAlign: 'center', lineHeight: '18px' }}>
            {(g[KEY[z]] / g.n) * 100 >= 9 ? Math.round((g[KEY[z]] / g.n) * 100) + '%' : ''}</Box>
        </Tooltip>))}
    </Box>)
}

/** Barra del buffer: rojo hasta TOR, amarillo hasta TOY aj., verde hasta TOG aj.; la raya negra es el flujo neto. */
function BufferBar(p: ICellRendererParams) {
  const d = p.data; if (!d) return null
  const tor = +d.tor, toy = +d.toy_aj, tog = +d.tog_aj, nfp = +d.flujo_neto
  const max = Math.max(tog * 1.25, nfp, 1)
  const w = (v: number) => `${(Math.max(v, 0) / max) * 100}%`
  const pos = `${(Math.min(Math.max(nfp, 0), max) / max) * 100}%`
  return (
    <Tooltip title={`Flujo neto ${nfp} · TOR ${tor} · TOY aj. ${toy} · TOG aj. ${tog}`}>
      <Box sx={{ position: 'relative', display: 'flex', height: 14, width: '100%', mt: '13px', borderRadius: .5, overflow: 'hidden', bgcolor: '#cfd8dc' }}>
        <Box sx={{ width: w(tor), bgcolor: COLOR.ROJA }} />
        <Box sx={{ width: w(toy - tor), bgcolor: COLOR.AMARILLA }} />
        <Box sx={{ width: w(tog - toy), bgcolor: COLOR.VERDE }} />
        <Box sx={{ position: 'absolute', left: pos, top: -2, bottom: -2, width: 3, bgcolor: '#000', transform: 'translateX(-1px)' }} />
      </Box>
    </Tooltip>)
}

const pill = (p: ICellRendererParams) => p.value == null ? '' :
  <Chip size="small" label={p.value} sx={{ bgcolor: COLOR[p.value] ?? '#999', color: '#fff', height: 20, fontSize: 11 }} />
const pctCell = (p: { value: any }) => p.value == null ? '' : Number(p.value).toFixed(0) + '%'

export default function Control() {
  const [f, setF] = useState<F>(VACIO)
  const [qTxt, setQTxt] = useState('')
  const [nivel, setNivel] = useState<Nivel>('empresa')
  const [opc, setOpc] = useState<any>({ tiendas: [], laboratorios: [], dias: [], empresas: [], ejecucion: null })
  const [kpi, setKpi] = useState<any>(null)
  const [grupos, setGrupos] = useState<any[]>([])
  const [det, setDet] = useState<{ filas: any[]; total: number; truncado: boolean }>({ filas: [], total: 0, truncado: false })
  const [cargando, setCargando] = useState(false)
  const [err, setErr] = useState('')

  useEffect(() => { api('/control/filtros').then(r => setOpc((o: any) => ({ ...o, ...r }))).catch(e => setErr(e.message)) }, [])
  useEffect(() => { const t = setTimeout(() => setF(x => x.q === qTxt ? x : { ...x, q: qTxt }), 400); return () => clearTimeout(t) }, [qTxt])

  const clave = qs(f).toString()
  useEffect(() => {
    let vivo = true; setCargando(true); setErr('')
    api('/control/resumen?agrupar=empresa&' + qs(f, true)).then(r => vivo && setKpi(r.total)).catch(e => vivo && setErr(e.message))
    const p = nivel === 'detalle' ? api('/control/detalle?limit=5000&' + qs(f)).then(r => vivo && setDet(r))
      : api(`/control/resumen?agrupar=${nivel}&` + qs(f)).then(r => vivo && setGrupos(r.grupos))
    p.catch(e => vivo && setErr(e.message)).finally(() => vivo && setCargando(false))
    return () => { vivo = false }
  }, [clave, nivel])

  const total = kpi?.n || 1
  const nombreTienda = (id: string) => opc.tiendas.find((t: any) => t.bodega_id === id)?.nombre
  const entrar = (clave: string) => {   // zoom in: aplica el filtro del grupo y baja un nivel
    setF(x => nivel === 'empresa' ? { ...x, empresa: [clave] } : nivel === 'bodega' ? { ...x, bodegas: [clave] }
      : nivel === 'laboratorio' ? { ...x, labs: [clave] } : nivel === 'item' ? { ...x, q: clave } : x)
    if (nivel === 'item') setQTxt(clave)
    setNivel(SIGUIENTE[nivel])
  }
  const quitar = (k: keyof F, v?: string) => {   // zoom out: quita un filtro
    setF(x => ({ ...x, [k]: Array.isArray(x[k]) ? (x[k] as string[]).filter(y => y !== v) : '' }))
    if (k === 'q') setQTxt('')
  }
  const hayFiltros = f.empresa.length + f.bodegas.length + f.labs.length + f.zonas.length > 0 || !!f.q || !!f.dia

  const colsGrupo: ColDef[] = useMemo(() => [
    { field: 'clave', headerName: NIVELES.find(n => n.k === nivel)?.label, width: 130, pinned: 'left' },
    { field: 'nombre', headerName: 'Nombre', flex: 1, minWidth: 180 },
    { field: 'n', headerName: 'Combinaciones', type: 'numericColumn', width: 130 },
    { headerName: 'Zonas del buffer', cellRenderer: ZonaBar, width: 260, sortable: false },
    { field: 'roja', headerName: 'Rojo', type: 'numericColumn', width: 85, cellStyle: { color: COLOR.ROJA, fontWeight: 600 } },
    { field: 'amarilla', headerName: 'Amarillo', type: 'numericColumn', width: 95 },
    { field: 'verde', headerName: 'Verde', type: 'numericColumn', width: 85 },
    { field: 'exceso', headerName: 'Exceso', type: 'numericColumn', width: 90 },
    { field: 'pct_prom', headerName: '% buffer prom.', type: 'numericColumn', width: 130, valueFormatter: p => p.value == null ? '' : p.value + '%' },
    { field: 'a_pedir', headerName: 'A pedir', type: 'numericColumn', width: 100 },
    { field: 'unidades', headerName: 'Unidades sug.', type: 'numericColumn', width: 130, valueFormatter: p => Math.round(p.value).toLocaleString() },
  ], [nivel])
  const colsDet: ColDef[] = [
    { field: 'bodega_id', headerName: 'Tienda', width: 100, pinned: 'left', filter: true },
    { field: 'bodega_nombre', headerName: 'Nombre tienda', width: 160, filter: true },
    { field: 'producto_id', headerName: 'Item', width: 100, filter: true },
    { field: 'descripcion', headerName: 'Descripción', flex: 1, minWidth: 220, filter: true },
    { field: 'laboratorio', headerName: 'Lab.', width: 90, filter: true },
    { field: 'zona', width: 110, cellRenderer: pill, filter: true },
    { field: 'pct_buffer', headerName: '% buffer', type: 'numericColumn', width: 100, valueFormatter: pctCell },
    { headerName: 'Buffer', cellRenderer: BufferBar, width: 220, sortable: false },
    { field: 'inventario', type: 'numericColumn', width: 100 },
    { field: 'en_transito', headerName: 'Tránsito', type: 'numericColumn', width: 95 },
    { field: 'flujo_neto', headerName: 'Flujo neto', type: 'numericColumn', width: 105 },
    { field: 'adu', headerName: 'ADU', type: 'numericColumn', width: 90 },
    { field: 'cantidad_sugerida', headerName: 'Sugerido', type: 'numericColumn', width: 100 },
  ]

  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', height: '100%', gap: 1.5, minHeight: 600 }}>
      {/* Indicadores del alcance actual: clic en una zona = filtrar por ella */}
      <Box sx={{ display: 'grid', gridTemplateColumns: { xs: 'repeat(2, 1fr)', md: 'repeat(5, 1fr)' }, gap: 1.5 }}>
        <Card variant="outlined" sx={{ borderLeft: '6px solid #6e8a37' }}>
          <Box sx={{ p: 1.25 }}>
            <Typography variant="caption" color="text.secondary">Alcance actual</Typography>
            <Typography variant="h6" sx={{ fontWeight: 700, lineHeight: 1.2 }}>{kpi ? kpi.n.toLocaleString() : '…'}</Typography>
            <Typography variant="caption" color="text.secondary">combinaciones · buffer prom. {kpi?.pct_prom ?? '–'}%</Typography>
          </Box>
        </Card>
        {ZONAS.map(z => {
          const n = kpi?.[KEY[z]] ?? 0, activo = f.zonas.includes(z)
          return (
            <Card key={z} variant="outlined" sx={{ borderLeft: `6px solid ${COLOR[z]}`, outline: activo ? `2px solid ${COLOR[z]}` : 'none' }}>
              <CardActionArea sx={{ p: 1.25 }} onClick={() => setF(x => ({ ...x, zonas: activo ? x.zonas.filter(y => y !== z) : [...x.zonas, z] }))}>
                <Typography variant="caption" color="text.secondary">{z === 'ROJA' ? 'Rojo' : z === 'AMARILLA' ? 'Amarillo' : z === 'VERDE' ? 'Verde' : 'Exceso'}</Typography>
                <Typography variant="h6" sx={{ fontWeight: 700, lineHeight: 1.2 }}>{n.toLocaleString()}</Typography>
                <Typography variant="caption" color="text.secondary">{((n / total) * 100).toFixed(1)}% del alcance</Typography>
              </CardActionArea>
            </Card>)
        })}
      </Box>

      {/* Filtros */}
      <Paper variant="outlined" sx={{ p: 1.25, display: 'flex', flexWrap: 'wrap', gap: 1, alignItems: 'center' }}>
        <Autocomplete multiple size="small" limitTags={1} sx={{ minWidth: 200, flex: '1 1 200px' }} options={opc.empresas} value={f.empresa}
          getOptionLabel={(o: string) => o === '05' ? 'Funat (05)' : o === '21' ? 'Stores (21)' : o}
          onChange={(_, v) => setF(x => ({ ...x, empresa: v }))} renderInput={p => <TextField {...p} label="Empresa" />} />
        <Autocomplete multiple size="small" limitTags={2} sx={{ minWidth: 240, flex: '2 1 240px' }} options={opc.tiendas.map((t: any) => t.bodega_id)} value={f.bodegas}
          getOptionLabel={(o: string) => nombreTienda(o) ? `${o} · ${nombreTienda(o)}` : o}
          onChange={(_, v) => setF(x => ({ ...x, bodegas: v }))} renderInput={p => <TextField {...p} label="Tienda" />} />
        <Autocomplete multiple size="small" limitTags={2} sx={{ minWidth: 240, flex: '2 1 240px' }} options={opc.laboratorios.map((l: any) => l.codigo)} value={f.labs}
          getOptionLabel={(o: string) => { const l = opc.laboratorios.find((x: any) => x.codigo === o); return l?.nombre ? `${o} · ${l.nombre}` : o }}
          onChange={(_, v) => setF(x => ({ ...x, labs: v }))} renderInput={p => <TextField {...p} label="Laboratorio" />} />
        <TextField size="small" label="Item (código o nombre)" value={qTxt} onChange={e => setQTxt(e.target.value)} sx={{ minWidth: 200, flex: '1 1 200px' }} />
        <TextField select size="small" label="DIA" value={f.dia} onChange={e => setF(x => ({ ...x, dia: e.target.value }))} sx={{ width: 100 }}
          slotProps={{ select: { native: true }, inputLabel: { shrink: true } }}>
          <option value="">Todos</option>{opc.dias.map((d: number) => <option key={d} value={d}>{d}</option>)}
        </TextField>
        {hayFiltros && <Button size="small" onClick={() => { setF(VACIO); setQTxt('') }}>Toda la empresa</Button>}
      </Paper>

      {/* Zoom: nivel de agrupación + migas de pan para alejarse */}
      <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 1, alignItems: 'center' }}>
        <Tabs value={nivel} onChange={(_, v) => setNivel(v)} variant="scrollable" sx={{ minHeight: 36, '& .MuiTab-root': { minHeight: 36, textTransform: 'none' } }}>
          {NIVELES.map(n => <Tab key={n.k} value={n.k} label={n.label} />)}
        </Tabs>
        <Box sx={{ flex: 1 }} />
        {f.empresa.map(v => <Chip key={'e' + v} size="small" color="primary" label={`Empresa ${v}`} onDelete={() => quitar('empresa', v)} />)}
        {f.bodegas.map(v => <Chip key={'b' + v} size="small" color="primary" label={`Tienda ${v}`} onDelete={() => quitar('bodegas', v)} />)}
        {f.labs.map(v => <Chip key={'l' + v} size="small" color="primary" label={`Lab ${v}`} onDelete={() => quitar('labs', v)} />)}
        {f.zonas.map(v => <Chip key={'z' + v} size="small" sx={{ bgcolor: COLOR[v], color: '#fff' }} label={v} onDelete={() => quitar('zonas', v)} />)}
        {f.q && <Chip size="small" color="primary" label={`Item “${f.q}”`} onDelete={() => quitar('q')} />}
        {f.dia && <Chip size="small" color="primary" label={`DIA ${f.dia}`} onDelete={() => quitar('dia')} />}
      </Box>
      {err && <Typography color="error" variant="body2">{err}</Typography>}
      {opc.ejecucion && <Typography variant="caption" color="text.secondary">
        Corte del motor: {String(opc.ejecucion.fecha_calculo).slice(0, 10)}
        {nivel !== 'detalle' ? ' · clic en una fila para acercarte' : det.truncado ? ` · mostrando ${det.filas.length.toLocaleString()} de ${det.total.toLocaleString()} (las más críticas); filtra para ver el resto` : ` · ${det.total.toLocaleString()} filas`}
      </Typography>}

      <Box className="ag-theme-quartz" sx={{ flex: 1, minHeight: 320 }}>
        {nivel === 'detalle'
          ? <AgGridReact key="det" rowData={det.filas} columnDefs={colsDet} rowBuffer={20} loading={cargando} defaultColDef={{ resizable: true, sortable: true }} />
          : <AgGridReact key={nivel} rowData={grupos} columnDefs={colsGrupo} rowBuffer={20} loading={cargando} defaultColDef={{ resizable: true, sortable: true }}
              onRowClicked={e => e.data && entrar(String(e.data.clave))} rowStyle={{ cursor: 'pointer' }} rowHeight={40} />}
      </Box>
    </Box>)
}
