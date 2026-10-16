import { useEffect, useMemo, useState } from 'react'
import { AgGridReact } from 'ag-grid-react'
import { ColDef, ICellRendererParams } from 'ag-grid-community'
import { Autocomplete, Box, Button, Card, CardActionArea, Chip, MenuItem, Paper, Tab, Tabs, TextField, Tooltip, Typography } from '@mui/material'
import { useLocation, useSearchParams } from 'react-router-dom'
import { BufferTrend, ZonaShare, Punto } from '../TrendCharts'
import { api } from '../api'
import { AYUDA, ayudar } from '../ayuda'

const COLOR: Record<string, string> = { ROJA: '#c62828', AMARILLA: '#f9a825', VERDE: '#2e7d32', EXCESO: '#1565c0' }
const ZONAS = ['ROJA', 'AMARILLA', 'VERDE', 'EXCESO']
const KEY: Record<string, string> = { ROJA: 'roja', AMARILLA: 'amarilla', VERDE: 'verde', EXCESO: 'exceso' }
const NIVELES = [
  { k: 'empresa', label: 'Empresa' }, { k: 'bodega', label: 'Tienda' }, { k: 'laboratorio', label: 'Laboratorio' }, { k: 'criterio', label: 'Criterio de items' },
  { k: 'item', label: 'Item' }, { k: 'detalle', label: 'Tienda × item' },
] as const
type Nivel = typeof NIVELES[number]['k']
const SIGUIENTE: Record<Nivel, Nivel> = { empresa: 'bodega', bodega: 'laboratorio', laboratorio: 'item', criterio: 'item', item: 'detalle', detalle: 'detalle' }
type F = { empresa: string[]; bodegas: string[]; labs: string[]; q: string; zonas: string[]; dia: string; plan: string; crit: string[] }
const VACIO: F = { empresa: [], bodegas: [], labs: [], q: '', zonas: [], dia: '', plan: '', crit: [] }

const qs = (f: F, sinZonas = false) => {
  const p = new URLSearchParams()
  if (f.empresa.length) p.set('empresa', f.empresa.join(','))
  if (f.bodegas.length) p.set('bodegas', f.bodegas.join(','))
  if (f.labs.length) p.set('labs', f.labs.join(','))
  if (f.q.trim()) p.set('q', f.q.trim())
  if (!sinZonas && f.zonas.length) p.set('zonas', f.zonas.join(','))
  if (f.dia) p.set('dia', f.dia)
  if (f.plan && f.crit.length) p.set('crit', f.crit.map(v => `${f.plan}:${v}`).join(','))
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

const hoy = () => new Date().toISOString().slice(0, 10)
const hace = (d: number) => new Date(Date.now() - d * 86400000).toISOString().slice(0, 10)
const MOVS = [
  { k: '', label: 'Todos los cambios' }, { k: 'entraron_rojo', label: 'Entraron a rojo' }, { k: 'salieron_rojo', label: 'Salieron de rojo' },
  { k: 'empeoraron', label: 'Empeoraron' }, { k: 'mejoraron', label: 'Mejoraron' }, { k: 'entraron_exceso', label: 'Entraron a exceso' },
]
const delta = (a: number, b: number, malo: 'sube' | 'baja' | null) => {   // flecha con color segun si subir es bueno o malo
  const d = b - a; if (!d) return <span style={{ color: '#777' }}>= 0</span>
  const mal = malo === null ? false : (malo === 'sube') === (d > 0)
  return <span style={{ color: malo === null ? '#555' : mal ? '#c62828' : '#2e7d32', fontWeight: 600 }}>{d > 0 ? '▲' : '▼'} {Math.abs(d).toLocaleString(undefined, { maximumFractionDigits: 1 })}</span>
}
function Antes({ p, ini, fin, malo }: { p: ICellRendererParams; ini: string; fin: string; malo: 'sube' | 'baja' | null }) {
  const a = +p.data[ini], b = +p.data[fin]
  return <span>{a.toLocaleString()} → <b>{b.toLocaleString()}</b> {delta(a, b, malo)}</span>
}
/** Dos barras finas: zonas al inicio y al final del periodo. */
function ZonaBar2(p: ICellRendererParams) {
  const g = p.data; if (!g) return null
  const una = (suf: string, n: number) => (
    <Box sx={{ display: 'flex', height: 9, width: '100%', borderRadius: .5, overflow: 'hidden', bgcolor: '#eee' }}>
      {ZONAS.map(z => g[KEY[z] + suf] > 0 && n > 0 && <Box key={z} sx={{ width: `${(g[KEY[z] + suf] / n) * 100}%`, bgcolor: COLOR[z] }} />)}
    </Box>)
  return <Box sx={{ display: 'grid', gap: '3px', alignSelf: 'center', width: '100%', mt: '9px' }}>{una('_ini', g.n_ini)}{una('_fin', g.n_fin)}</Box>
}

export default function Control() {
  const ruta = useLocation().pathname
  const cambiosModo = ruta.startsWith('/control/cambios')
  const tendModo = ruta.startsWith('/control/tendencia')
  const [serie, setSerie] = useState<Punto[]>([])
  const [desde, setDesde] = useState(hace(ruta.startsWith('/control/tendencia') ? 90 : 7)); const [hasta, setHasta] = useState(hoy())
  const [mov, setMov] = useState('')
  const [periodo, setPeriodo] = useState<{ desde: string; hasta: string } | null>(null)
  const [matriz, setMatriz] = useState<{ de: string; a: string; n: number }[]>([])
  // ?tienda=SV011&item=058076 (viene del boton de la matriz de despacho): abre filtrado en el detalle de esa tienda e item
  const [sp] = useSearchParams()
  const tiendaUrl = sp.get('tienda') ?? '', itemUrl = sp.get('item') ?? ''
  const [f, setF] = useState<F>(() => ({ ...VACIO, bodegas: tiendaUrl ? [tiendaUrl] : [], q: itemUrl }))
  const [qTxt, setQTxt] = useState(itemUrl)
  const [nivel, setNivel] = useState<Nivel>(tiendaUrl || itemUrl ? 'detalle' : 'empresa')
  const [opc, setOpc] = useState<any>({ tiendas: [], laboratorios: [], dias: [], empresas: [], criterios: [], ejecucion: null })
  const [kpi, setKpi] = useState<any>(null)
  const [grupos, setGrupos] = useState<any[]>([])
  const [det, setDet] = useState<{ filas: any[]; total: number; truncado: boolean }>({ filas: [], total: 0, truncado: false })
  const [cargando, setCargando] = useState(false)
  const [err, setErr] = useState('')

  useEffect(() => { api('/control/filtros').then(r => setOpc((o: any) => ({ ...o, ...r }))).catch(e => setErr(e.message)) }, [])
  useEffect(() => { const t = setTimeout(() => setF(x => x.q === qTxt ? x : { ...x, q: qTxt }), 400); return () => clearTimeout(t) }, [qTxt])

  const clave = qs(f).toString()
  const per = `desde=${desde}&hasta=${hasta}`
  useEffect(() => { setNivel(n => n === 'empresa' ? n : n) }, [cambiosModo])
  useEffect(() => {
    let vivo = true; setCargando(true); setErr('')
    if (tendModo) {
      api(`/control/tendencia?${qs(f, true)}&${per}`).then(r => vivo && setSerie(r.serie)).catch(e => vivo && setErr(e.message)).finally(() => vivo && setCargando(false))
      return () => { vivo = false }
    }
    const base = cambiosModo ? '/control/cambios' : '/control/resumen'
    const extra = (cambiosModo ? '&' + per : '') + (nivel === 'criterio' ? '&plan=' + encodeURIComponent(f.plan || opc.criterios?.[0]?.plan_id || '') : '')
    api(`${base}?agrupar=empresa&${qs(f, true)}${extra}`).then(r => { if (!vivo) return; setKpi(r.total); if (cambiosModo) { setPeriodo(r.periodo); setMatriz(r.matriz) } })
      .catch(e => vivo && setErr(e.message))
    const p = nivel === 'detalle'
      ? api(cambiosModo ? `/control/cambios/detalle?limit=5000&mov=${mov}&${qs(f)}&${per}` : '/control/detalle?limit=5000&' + qs(f)).then(r => vivo && setDet(r))
      : api(`${base}?agrupar=${nivel}&${qs(f)}${extra}`).then(r => vivo && setGrupos(r.grupos))
    p.catch(e => vivo && setErr(e.message)).finally(() => vivo && setCargando(false))
    return () => { vivo = false }
  }, [clave, f.plan, opc.criterios, nivel, cambiosModo, tendModo, desde, hasta, mov])

  const total = (cambiosModo ? kpi?.n_fin : kpi?.n) || 1
  const planNombre = (p: string) => opc.criterios?.find((x: any) => x.plan_id === p)?.nombre ?? p
  const critNombre = (p: string, v: string) => opc.criterios?.find((x: any) => x.plan_id === p)?.valores.find((y: any) => y.id === v)?.nombre ?? v
  const nombreTienda = (id: string) => opc.tiendas.find((t: any) => t.bodega_id === id)?.nombre
  const entrar = (clave: string) => {   // zoom in: aplica el filtro del grupo y baja un nivel
    setF(x => nivel === 'empresa' ? { ...x, empresa: [clave] } : nivel === 'bodega' ? { ...x, bodegas: [clave] }
      : nivel === 'laboratorio' ? { ...x, labs: [clave] } : nivel === 'criterio' ? { ...x, plan: x.plan || opc.criterios?.[0]?.plan_id || '', crit: [clave] } : nivel === 'item' ? { ...x, q: clave } : x)
    if (nivel === 'item') setQTxt(clave)
    setNivel(SIGUIENTE[nivel])
  }
  const quitar = (k: keyof F, v?: string) => {   // zoom out: quita un filtro
    setF(x => ({ ...x, [k]: Array.isArray(x[k]) ? (x[k] as string[]).filter(y => y !== v) : '' }))
    if (k === 'q') setQTxt('')
  }
  const hayFiltros = f.empresa.length + f.bodegas.length + f.labs.length + f.zonas.length + f.crit.length > 0 || !!f.q || !!f.dia

  const colsGrupo: ColDef[] = useMemo(() => [
    { field: 'clave', headerName: NIVELES.find(n => n.k === nivel)?.label, width: 130, pinned: 'left' },
    { field: 'nombre', headerName: 'Nombre', flex: 1, minWidth: 180 },
    { field: 'n', headerName: 'Combinaciones', type: 'numericColumn', width: 130, headerTooltip: 'Pares tienda × item que tiene el motor en este grupo: cada fila de buffer que calcula' },
    { field: 'inventario', headerName: 'Inventario', type: 'numericColumn', width: 115, valueFormatter: p => Math.round(p.value ?? 0).toLocaleString(), headerTooltip: 'Unidades en inventario hoy (suma de lo filtrado)' },
    { field: 'en_transito', headerName: 'Tránsito', type: 'numericColumn', width: 100, valueFormatter: p => Math.round(p.value ?? 0).toLocaleString() },
    { field: 'tog_aj', headerName: 'Buffer (TOG)', type: 'numericColumn', width: 120, valueFormatter: p => Math.round(p.value ?? 0).toLocaleString(), headerTooltip: 'Tope verde ajustado: hasta donde se repone' },
    { headerName: 'Zonas del buffer', cellRenderer: ZonaBar, width: 260, sortable: false },
    { field: 'roja', headerName: 'Rojo', type: 'numericColumn', width: 85, cellStyle: { color: COLOR.ROJA, fontWeight: 600 } },
    { field: 'amarilla', headerName: 'Amarillo', type: 'numericColumn', width: 95 },
    { field: 'verde', headerName: 'Verde', type: 'numericColumn', width: 85 },
    { field: 'exceso', headerName: 'Exceso', type: 'numericColumn', width: 90 },
    { field: 'pct_prom', headerName: '% buffer prom.', type: 'numericColumn', width: 130, valueFormatter: p => p.value == null ? '' : p.value + '%' },
    { field: 'a_pedir', headerName: 'A pedir', type: 'numericColumn', width: 100 },
    { field: 'unidades', headerName: 'Unidades sug.', type: 'numericColumn', width: 130, valueFormatter: p => Math.round(p.value).toLocaleString() },
  ], [nivel])
  const colsCambios: ColDef[] = useMemo(() => [
    { field: 'clave', headerName: NIVELES.find(n => n.k === nivel)?.label, width: 130, pinned: 'left' },
    { field: 'nombre', headerName: 'Nombre', flex: 1, minWidth: 170 },
    { headerName: 'Antes / ahora', cellRenderer: ZonaBar2, width: 200, sortable: false },
    { headerName: 'Rojo', width: 180, cellRenderer: (p: ICellRendererParams) => <Antes p={p} ini="roja_ini" fin="roja_fin" malo="sube" /> },
    { headerName: 'Amarillo', width: 170, cellRenderer: (p: ICellRendererParams) => <Antes p={p} ini="amarilla_ini" fin="amarilla_fin" malo={null} /> },
    { headerName: 'Verde', width: 180, cellRenderer: (p: ICellRendererParams) => <Antes p={p} ini="verde_ini" fin="verde_fin" malo="baja" /> },
    { headerName: 'Exceso', width: 170, cellRenderer: (p: ICellRendererParams) => <Antes p={p} ini="exceso_ini" fin="exceso_fin" malo="sube" /> },
    { headerName: '% buffer prom.', width: 190, cellRenderer: (p: ICellRendererParams) => <Antes p={p} ini="pct_ini" fin="pct_fin" malo="baja" /> },
    { field: 'entraron_rojo', headerName: 'Entraron a rojo', type: 'numericColumn', width: 130, cellStyle: { color: COLOR.ROJA, fontWeight: 600 } },
    { field: 'salieron_rojo', headerName: 'Salieron de rojo', type: 'numericColumn', width: 135, cellStyle: { color: COLOR.VERDE, fontWeight: 600 } },
    { field: 'empeoraron', headerName: 'Empeoraron', type: 'numericColumn', width: 115 },
    { field: 'mejoraron', headerName: 'Mejoraron', type: 'numericColumn', width: 110 },
  ], [nivel])
  const colsDetCambios: ColDef[] = [
    { field: 'bodega_id', headerName: 'Tienda', width: 100, pinned: 'left', filter: true },
    { field: 'bodega_nombre', headerName: 'Nombre tienda', width: 160, filter: true },
    { field: 'producto_id', headerName: 'Item', width: 100, filter: true },
    { field: 'descripcion', headerName: 'Descripción', flex: 1, minWidth: 220, filter: true },
    { field: 'laboratorio', headerName: 'Lab.', width: 90, filter: true },
    { field: 'zona_ini', headerName: 'Antes', width: 115, cellRenderer: pill, filter: true },
    { field: 'zona_fin', headerName: 'Ahora', width: 115, cellRenderer: pill, filter: true },
    { field: 'pct_ini', headerName: '% antes', type: 'numericColumn', width: 95, valueFormatter: pctCell },
    { field: 'pct_fin', headerName: '% ahora', type: 'numericColumn', width: 95, valueFormatter: pctCell },
    { field: 'delta', headerName: 'Cambio (pp)', type: 'numericColumn', width: 115, sort: 'asc', valueFormatter: p => p.value == null ? '' : (p.value > 0 ? '+' : '') + Number(p.value).toFixed(0) },
  ]
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
    { field: 'condenado', headerName: 'Condenado', width: 110, cellRenderer: (p: ICellRendererParams) => p.value ? <Chip size="small" label="NxP" sx={{ height: 20, fontSize: 11, bgcolor: '#424242', color: '#fff' }} /> : '' },
  ]

  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', height: '100%', gap: 1.5, minHeight: 600 }}>
      {/* Indicadores del alcance actual: clic en una zona = filtrar por ella */}
      <Typography variant="h6" sx={{ fontWeight: 700 }}>{tendModo ? 'Control DDMRP · tendencia en el tiempo' : cambiosModo ? 'Control DDMRP · cambios en un periodo' : 'Control DDMRP · foto actual'}</Typography>
      {!tendModo && <Box sx={{ display: 'grid', flexShrink: 0, gridTemplateColumns: { xs: 'repeat(2, 1fr)', md: 'repeat(5, 1fr)' }, gap: 1.5 }}>
        <Card variant="outlined" sx={{ borderLeft: '6px solid #6e8a37', flexShrink: 0 }}>
          <Box sx={{ p: 1.25 }}>
            <Typography variant="caption" color="text.secondary">Alcance actual</Typography>
            <Typography variant="h6" sx={{ fontWeight: 700, lineHeight: 1.2 }}>{kpi ? (cambiosModo ? kpi.n_fin : kpi.n).toLocaleString() : '…'}</Typography>
            <Typography variant="caption" color="text.secondary" title="Combinación = un item en una tienda (cada fila de buffer que calcula el motor)">combinaciones (tienda × item) · buffer prom. {cambiosModo ? kpi?.pct_fin : kpi?.pct_prom ?? '–'}%{!cambiosModo && kpi?.inventario != null && <> · inventario {Math.round(kpi.inventario).toLocaleString()} u.</>}</Typography>
          </Box>
        </Card>
        {ZONAS.map(z => {
          const n = kpi?.[KEY[z] + (cambiosModo ? '_fin' : '')] ?? 0, activo = f.zonas.includes(z)
          const n0 = kpi?.[KEY[z] + '_ini'] ?? 0
          return (
            <Tooltip key={z} title={AYUDA[z === 'ROJA' ? 'Rojo' : z === 'AMARILLA' ? 'Amarillo' : z === 'VERDE' ? 'Verde' : 'Exceso']} placement="top"><Card variant="outlined" sx={{ borderLeft: `6px solid ${COLOR[z]}`, outline: activo ? `2px solid ${COLOR[z]}` : 'none' }}>
              <CardActionArea sx={{ p: 1.25 }} onClick={() => setF(x => ({ ...x, zonas: activo ? x.zonas.filter(y => y !== z) : [...x.zonas, z] }))}>
                <Typography variant="caption" color="text.secondary">{z === 'ROJA' ? 'Rojo' : z === 'AMARILLA' ? 'Amarillo' : z === 'VERDE' ? 'Verde' : 'Exceso'}</Typography>
                <Typography variant="h6" sx={{ fontWeight: 700, lineHeight: 1.2 }}>{n.toLocaleString()}</Typography>
                <Typography variant="caption" color="text.secondary">{((n / total) * 100).toFixed(1)}% del alcance
                  {cambiosModo && <> · {delta(n0, n, z === 'VERDE' ? 'baja' : z === 'AMARILLA' ? null : 'sube')}</>}</Typography>
              </CardActionArea>
            </Card></Tooltip>)
        })}
      </Box>}

      {/* Filtros */}
      <Paper variant="outlined" sx={{ flexShrink: 0, p: 1.25, display: 'flex', flexWrap: 'wrap', gap: 1, alignItems: 'center' }}>
        <Autocomplete multiple size="small" limitTags={1} sx={{ minWidth: 200, flex: '1 1 200px' }} options={opc.empresas} value={f.empresa}
          getOptionLabel={(o: string) => o === '05' ? 'Funat (05)' : o === '21' ? 'Stores (21)' : o}
          onChange={(_, v) => setF(x => ({ ...x, empresa: v }))} renderInput={p => <TextField {...p} label="Empresa" />} />
        <Autocomplete multiple size="small" limitTags={2} sx={{ minWidth: 240, flex: '2 1 240px' }} options={opc.tiendas.map((t: any) => t.bodega_id)} value={f.bodegas}
          getOptionLabel={(o: string) => nombreTienda(o) ? `${o} · ${nombreTienda(o)}` : o}
          onChange={(_, v) => setF(x => ({ ...x, bodegas: v }))} renderInput={p => <TextField {...p} label="Tienda" />} />
        <Autocomplete multiple size="small" limitTags={2} sx={{ minWidth: 240, flex: '2 1 240px' }} options={opc.laboratorios.map((l: any) => l.codigo)} value={f.labs}
          getOptionLabel={(o: string) => { const l = opc.laboratorios.find((x: any) => x.codigo === o); return l?.nombre ? `${o} · ${l.nombre}` : o }}
          onChange={(_, v) => setF(x => ({ ...x, labs: v }))} renderInput={p => <TextField {...p} label="Laboratorio" />} />
        {opc.criterios?.length > 0 && <>
          <TextField select size="small" label="Criterio de items" value={f.plan} onChange={e => setF(x => ({ ...x, plan: e.target.value, crit: [] }))} sx={{ minWidth: 190, flex: '1 1 190px' }}
            slotProps={{ select: { displayEmpty: true }, inputLabel: { shrink: true } }}>
            <MenuItem value="">(elige un criterio)</MenuItem>
            {opc.criterios.map((p: any) => <MenuItem key={p.plan_id} value={p.plan_id}>{p.nombre}</MenuItem>)}
          </TextField>
          {f.plan && <Autocomplete multiple size="small" limitTags={2} sx={{ minWidth: 220, flex: '2 1 220px' }}
            options={(opc.criterios.find((p: any) => p.plan_id === f.plan)?.valores ?? []).map((v: any) => v.id)} value={f.crit}
            getOptionLabel={(o: string) => critNombre(f.plan, o)} onChange={(_, v) => setF(x => ({ ...x, crit: v }))}
            renderInput={p => <TextField {...p} label="Valores" />} />}
        </>}
        <TextField size="small" label="Item (código o nombre)" value={qTxt} onChange={e => setQTxt(e.target.value)} sx={{ minWidth: 200, flex: '1 1 200px' }} />
        <TextField select size="small" label="DIA" value={f.dia} onChange={e => setF(x => ({ ...x, dia: e.target.value }))} sx={{ width: 100 }}
          slotProps={{ select: { native: true }, inputLabel: { shrink: true } }}>
          <option value="">Todos</option>{opc.dias.map((d: number) => <option key={d} value={d}>{d}</option>)}
        </TextField>
        {hayFiltros && <Button size="small" onClick={() => { setF(VACIO); setQTxt('') }}>Toda la empresa</Button>}
      </Paper>

      {(cambiosModo || tendModo) && (
        <Paper variant="outlined" sx={{ flexShrink: 0, p: 1.25, display: 'flex', flexWrap: 'wrap', gap: 1, alignItems: 'center' }}>
          <Typography sx={{ fontWeight: 700 }}>Periodo</Typography>
          <TextField size="small" type="date" label="Desde" value={desde} onChange={e => e.target.value && setDesde(e.target.value)} slotProps={{ inputLabel: { shrink: true } }} />
          <TextField size="small" type="date" label="Hasta" value={hasta} onChange={e => e.target.value && setHasta(e.target.value)} slotProps={{ inputLabel: { shrink: true } }} />
          {(tendModo ? [['30 días', 30], ['90 días', 90], ['6 meses', 180], ['12 meses', 365]] : [['Ayer', 1], ['7 días', 7], ['30 días', 30], ['90 días', 90]]).map(([l, d]) =>
            <Button key={l as string} size="small" variant="outlined" onClick={() => { setDesde(hace(d as number)); setHasta(hoy()) }}>{l}</Button>)}
          <Box sx={{ flex: 1 }} />
          {cambiosModo && periodo && <Typography variant="caption" color="text.secondary">Comparando la corrida del {periodo.desde} contra la del {periodo.hasta}
            {periodo.desde === periodo.hasta ? ' (solo hay una corrida guardada en ese rango)' : ''}</Typography>}
        </Paper>)}
      {cambiosModo && matriz.length > 0 && (
        <Paper variant="outlined" sx={{ flexShrink: 0, p: 1.25, overflow: 'auto' }}>
          <Typography variant="caption" color="text.secondary">Movimientos entre zonas (filas = antes, columnas = ahora)</Typography>
          <Box component="table" sx={{ borderCollapse: 'collapse', mt: .5, '& td, & th': { border: '1px solid #e0e0e0', px: 1.5, py: .4, textAlign: 'right', fontSize: 13 } }}>
            <thead><tr><th></th>{ZONAS.map(z => <th key={z} style={{ color: COLOR[z] }}>{z}</th>)}</tr></thead>
            <tbody>{ZONAS.map(a => (
              <tr key={a}><th style={{ color: COLOR[a], textAlign: 'left' }}>{a}</th>
                {ZONAS.map(b => { const n = matriz.find(m => m.de === a && m.a === b)?.n ?? 0
                  return <td key={b} style={{ background: a === b ? '#f5f5f5' : n ? 'rgba(110,138,55,.12)' : undefined, fontWeight: a !== b && n ? 700 : 400 }}>{n ? n.toLocaleString() : '·'}</td> })}
              </tr>))}</tbody>
          </Box>
        </Paper>)}

      {/* Zoom: nivel de agrupación + migas de pan para alejarse */}
      {tendModo && (
        <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 1, alignItems: 'center' }}>
          <Box sx={{ flex: 1 }} />
          {f.empresa.map(v => <Chip key={'e' + v} size="small" color="primary" label={`Empresa ${v}`} onDelete={() => quitar('empresa', v)} />)}
          {f.bodegas.map(v => <Chip key={'b' + v} size="small" color="primary" label={`Tienda ${v}`} onDelete={() => quitar('bodegas', v)} />)}
          {f.labs.map(v => <Chip key={'l' + v} size="small" color="primary" label={`Lab ${v}`} onDelete={() => quitar('labs', v)} />)}
          {f.crit.map(v => <Chip key={'c' + v} size="small" color="primary" label={`${planNombre(f.plan)}: ${critNombre(f.plan, v)}`} onDelete={() => quitar('crit', v)} />)}
        {f.crit.map(v => <Chip key={'c' + v} size="small" color="primary" label={`${planNombre(f.plan)}: ${critNombre(f.plan, v)}`} onDelete={() => quitar('crit', v)} />)}
          {f.q && <Chip size="small" color="primary" label={`Item “${f.q}”`} onDelete={() => quitar('q')} />}
        </Box>)}
      {tendModo && (
        <Paper variant="outlined" sx={{ p: 1.5, flexShrink: 0 }}>
          <Typography variant="subtitle2" sx={{ fontWeight: 700 }}>Buffer en el tiempo{serie.length ? ` · ${serie[serie.length - 1].n.toLocaleString()} combinación(es)` : ''}</Typography>
          <Typography variant="caption" color="text.secondary">Para la curva de un solo item en una sola tienda, elige esa tienda y escribe el código del item. Si no, las unidades de todo lo filtrado se suman.</Typography>
          <BufferTrend serie={serie} />
          {serie.some(p => p.n > 1) && <><Typography variant="subtitle2" sx={{ fontWeight: 700, mt: 2 }}>Semáforo en el tiempo (% de combinaciones por zona)</Typography><ZonaShare serie={serie} /></>}
        </Paper>)}
      {!tendModo && <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 1, alignItems: 'center' }}>
        <Tabs value={nivel} onChange={(_, v) => setNivel(v)} variant="scrollable" sx={{ minHeight: 36, '& .MuiTab-root': { minHeight: 36, textTransform: 'none' } }}>
          {NIVELES.map(n => <Tab key={n.k} value={n.k} label={<Tooltip title={AYUDA[n.label] ?? ''} placement="top"><span>{n.label}</span></Tooltip>} />)}
        </Tabs>
        <Box sx={{ flex: 1 }} />
        {f.empresa.map(v => <Chip key={'e' + v} size="small" color="primary" label={`Empresa ${v}`} onDelete={() => quitar('empresa', v)} />)}
        {f.bodegas.map(v => <Chip key={'b' + v} size="small" color="primary" label={`Tienda ${v}`} onDelete={() => quitar('bodegas', v)} />)}
        {f.labs.map(v => <Chip key={'l' + v} size="small" color="primary" label={`Lab ${v}`} onDelete={() => quitar('labs', v)} />)}
        {f.crit.map(v => <Chip key={'c' + v} size="small" color="primary" label={`${planNombre(f.plan)}: ${critNombre(f.plan, v)}`} onDelete={() => quitar('crit', v)} />)}
        {f.zonas.map(v => <Chip key={'z' + v} size="small" sx={{ bgcolor: COLOR[v], color: '#fff' }} label={v} onDelete={() => quitar('zonas', v)} />)}
        {f.q && <Chip size="small" color="primary" label={`Item “${f.q}”`} onDelete={() => quitar('q')} />}
        {f.dia && <Chip size="small" color="primary" label={`DIA ${f.dia}`} onDelete={() => quitar('dia')} />}
      </Box>}
      {cambiosModo && !tendModo && nivel === 'detalle' && (
        <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap' }}>
          {MOVS.map(m => <Chip key={m.k} size="small" label={m.label} color={mov === m.k ? 'primary' : 'default'} variant={mov === m.k ? 'filled' : 'outlined'} onClick={() => setMov(m.k)} />)}
        </Box>)}
      {err && <Typography color="error" variant="body2">{err}</Typography>}
      {!tendModo && opc.ejecucion && <Typography variant="caption" color="text.secondary">
        Corte del motor: {String(opc.ejecucion.fecha_calculo).slice(0, 10)}
        {nivel !== 'detalle' ? ' · clic en una fila para acercarte' : det.truncado ? ` · mostrando ${det.filas.length.toLocaleString()} de ${det.total.toLocaleString()} (las más críticas); filtra para ver el resto` : ` · ${det.total.toLocaleString()} filas`}
      </Typography>}

      {!tendModo && <Box className="ag-theme-quartz" sx={{ flex: 1, minHeight: 320 }}>
        {nivel === 'detalle'
          ? <AgGridReact key={'det' + cambiosModo} rowData={det.filas} columnDefs={ayudar(cambiosModo ? colsDetCambios : colsDet)} tooltipShowDelay={300} rowBuffer={20} loading={cargando} defaultColDef={{ resizable: true, sortable: true }} />
          : <AgGridReact key={nivel + cambiosModo} rowData={grupos} columnDefs={ayudar(cambiosModo ? colsCambios : colsGrupo)} tooltipShowDelay={300} rowBuffer={20} loading={cargando} defaultColDef={{ resizable: true, sortable: true }}
              onRowClicked={e => e.data && entrar(String(e.data.clave))} rowStyle={{ cursor: 'pointer' }} rowHeight={40} />}
      </Box>}
    </Box>)
}
