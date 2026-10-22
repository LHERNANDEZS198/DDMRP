import { Fragment, useCallback, useEffect, useState } from 'react'
import { Alert, Box, Button, Chip, Collapse, IconButton, MenuItem, Paper, Stack, Tab, Table, TableBody, TableCell, TableHead, TableRow, Tabs, TextField, Tooltip, Typography } from '@mui/material'
import KeyboardArrowDown from '@mui/icons-material/KeyboardArrowDown'
import KeyboardArrowRight from '@mui/icons-material/KeyboardArrowRight'
import Refresh from '@mui/icons-material/Refresh'
import Cancel from '@mui/icons-material/Cancel'
import { api } from '../api'
import Aviso from '../Aviso'
import { confirmar } from '../alertas'

/** Pantalla de diagnóstico (solo administradores): consultas hechas, tiempos, consultas en curso y estado de la base. */
type Consulta = { id: number; ts: string; usuario: string | null; metodo: string; ruta: string; params: Record<string, string>; http: number; estado: string
  ms: number | null; ms_sql: number | null; ms_calc: number | null; filas: number | null; bytes: number | null; error: string | null; extra: Record<string, any> }

const ESTADO: Record<string, 'success' | 'error' | 'warning' | 'default'> = { ok: 'success', timeout: 'error', error: 'error', rechazado: 'warning' }
const ESTADO_TXT: Record<string, string> = { ok: 'Cargó', timeout: 'Se pasó de tiempo', error: 'Falló', rechazado: 'Rechazada' }
const hora = (s: string | null) => s ? new Date(s).toLocaleString('es-CO', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit', second: '2-digit' }) : '—'
const seg = (ms: number | null) => ms == null ? '—' : ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1)} s`
const colorMs = (ms: number | null) => ms == null ? undefined : ms >= 10000 ? '#c62828' : ms >= 3000 ? '#b45309' : undefined
const mb = (b: number | null) => b == null ? '—' : b < 1024 * 1024 ? `${(b / 1024).toFixed(0)} KB` : b < 1024 ** 3 ? `${(b / 1024 / 1024).toFixed(0)} MB` : `${(b / 1024 ** 3).toFixed(1)} GB`
const corta = (r: string) => r.replace(/^\/api/, '')
const contenedor = { overflow: 'auto', maxWidth: '100%' } as const

function Consultas({ setMsg }: { setMsg: (s: string) => void }) {
  const [d, setD] = useState<{ filas: Consulta[]; rutas: string[]; usuarios: string[] }>({ filas: [], rutas: [], usuarios: [] })
  const [f, setF] = useState({ horas: '24', ruta: '', usuario: '', estado: '', min_ms: '', q: '' })
  const [abiertas, setAbiertas] = useState<Set<number>>(new Set())
  const cargar = useCallback(() => api('/diagnostico/consultas?' + new URLSearchParams(Object.entries(f).filter(([, v]) => v))).then(setD).catch(e => setMsg('Error: ' + e.message)), [f])
  useEffect(() => { cargar() }, [cargar])
  const alternar = (id: number) => setAbiertas(s => { const n = new Set(s); n.has(id) ? n.delete(id) : n.add(id); return n })
  return (
    <Stack spacing={1.5}>
      <Paper variant="outlined" sx={{ p: 1.25, display: 'flex', flexWrap: 'wrap', gap: 1, alignItems: 'center' }}>
        <TextField select size="small" label="Periodo" value={f.horas} onChange={e => setF({ ...f, horas: e.target.value })} sx={{ width: 130 }}>
          {[['1', 'Última hora'], ['6', '6 horas'], ['24', '24 horas'], ['72', '3 días'], ['168', '7 días'], ['720', '30 días']].map(([v, l]) => <MenuItem key={v} value={v}>{l}</MenuItem>)}</TextField>
        <TextField select size="small" label="Consulta" value={f.ruta} onChange={e => setF({ ...f, ruta: e.target.value })} sx={{ minWidth: 190, flex: '1 1 190px' }}>
          <MenuItem value="">Todas</MenuItem>{d.rutas.map(r => <MenuItem key={r} value={r}>{corta(r)}</MenuItem>)}</TextField>
        <TextField select size="small" label="Usuario" value={f.usuario} onChange={e => setF({ ...f, usuario: e.target.value })} sx={{ minWidth: 140, flex: '1 1 140px' }}>
          <MenuItem value="">Todos</MenuItem>{d.usuarios.map(r => <MenuItem key={r} value={r}>{r}</MenuItem>)}</TextField>
        <TextField select size="small" label="Resultado" value={f.estado} onChange={e => setF({ ...f, estado: e.target.value })} sx={{ width: 160 }}>
          <MenuItem value="">Todos</MenuItem>{Object.entries(ESTADO_TXT).map(([k, v]) => <MenuItem key={k} value={k}>{v}</MenuItem>)}</TextField>
        <TextField select size="small" label="Tardó más de" value={f.min_ms} onChange={e => setF({ ...f, min_ms: e.target.value })} sx={{ width: 140 }}>
          <MenuItem value="">Cualquier tiempo</MenuItem>{[['1000', '1 s'], ['3000', '3 s'], ['10000', '10 s'], ['30000', '30 s']].map(([v, l]) => <MenuItem key={v} value={v}>{l}</MenuItem>)}</TextField>
        <TextField size="small" label="Buscar en filtros / error" value={f.q} onChange={e => setF({ ...f, q: e.target.value })} sx={{ minWidth: 180, flex: '1 1 180px' }} />
        <Tooltip title="Actualizar"><IconButton onClick={cargar}><Refresh /></IconButton></Tooltip>
      </Paper>
      <Typography variant="caption" color="text.secondary">{d.filas.length} consultas{d.filas.length >= 300 ? ' (las 300 más recientes: acota con los filtros)' : ''} · se guardan 30 días · no incluye login, salud ni esta pantalla</Typography>
      <Paper variant="outlined" sx={contenedor}>
        <Table size="small">
          <TableHead><TableRow sx={{ bgcolor: '#eef2e3' }}>
            <TableCell /><TableCell sx={{ fontWeight: 700 }}>Cuándo</TableCell><TableCell sx={{ fontWeight: 700 }}>Quién</TableCell><TableCell sx={{ fontWeight: 700 }}>Consulta</TableCell>
            <TableCell sx={{ fontWeight: 700 }} align="right">Tiempo</TableCell><TableCell sx={{ fontWeight: 700 }} align="right">SQL</TableCell><TableCell sx={{ fontWeight: 700 }} align="right">Cálculo</TableCell>
            <TableCell sx={{ fontWeight: 700 }} align="right">Filas</TableCell><TableCell sx={{ fontWeight: 700 }}>Resultado</TableCell></TableRow></TableHead>
          <TableBody>
            {d.filas.map(x => (
              <Fragment key={x.id}>
                <TableRow hover sx={{ cursor: 'pointer', '& td': { whiteSpace: 'nowrap' } }} onClick={() => alternar(x.id)}>
                  <TableCell padding="checkbox">{abiertas.has(x.id) ? <KeyboardArrowDown fontSize="small" /> : <KeyboardArrowRight fontSize="small" />}</TableCell>
                  <TableCell>{hora(x.ts)}</TableCell><TableCell>{x.usuario ?? '—'}</TableCell>
                  <TableCell><b>{x.metodo}</b> {corta(x.ruta)}{Object.keys(x.params).length > 0 && <Typography component="span" variant="caption" color="text.secondary"> · {Object.keys(x.params).length} filtros</Typography>}</TableCell>
                  <TableCell align="right" sx={{ fontWeight: 700, color: colorMs(x.ms) }}>{seg(x.ms)}</TableCell>
                  <TableCell align="right">{seg(x.ms_sql)}</TableCell><TableCell align="right">{seg(x.ms_calc)}</TableCell>
                  <TableCell align="right">{x.filas?.toLocaleString('es-CO') ?? '—'}</TableCell>
                  <TableCell><Chip size="small" color={ESTADO[x.estado] ?? 'default'} label={ESTADO_TXT[x.estado] ?? x.estado} variant={x.estado === 'ok' ? 'outlined' : 'filled'} /></TableCell>
                </TableRow>
                <TableRow><TableCell colSpan={9} sx={{ p: 0, border: abiertas.has(x.id) ? undefined : 0 }}>
                  <Collapse in={abiertas.has(x.id)} unmountOnExit>
                    <Box sx={{ p: 1.5, bgcolor: '#fafaf5', fontSize: 13, display: 'grid', gridTemplateColumns: 'minmax(0, 1fr)', gap: .75 }}>
                      {x.error && <Alert severity="error" sx={{ py: 0 }}>{x.error}</Alert>}
                      <Box><b>Filtros usados</b>{Object.keys(x.params).length ? (
                        <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: .5, mt: .5 }}>{Object.entries(x.params).map(([k, v]) => <Chip key={k} size="small" variant="outlined" label={`${k}: ${v}`} sx={{ maxWidth: '100%' }} />)}</Box>) : ' ninguno'}</Box>
                      <Box><b>Detalle</b> · HTTP {x.http} · respuesta {mb(x.bytes)} · {Object.entries(x.extra ?? {}).map(([k, v]) => `${k.replace(/_/g, ' ')}: ${String(v)}`).join(' · ') || 'sin más datos'}</Box>
                    </Box>
                  </Collapse></TableCell></TableRow>
              </Fragment>))}
            {!d.filas.length && <TableRow><TableCell colSpan={9} align="center" sx={{ color: 'text.secondary', py: 3 }}>Sin consultas en este periodo</TableCell></TableRow>}
          </TableBody>
        </Table>
      </Paper>
    </Stack>)
}

function Resumen({ setMsg }: { setMsg: (s: string) => void }) {
  const [horas, setHoras] = useState('24'); const [r, setR] = useState<any[]>([])
  useEffect(() => { api('/diagnostico/resumen?horas=' + horas).then(x => setR(x.rutas)).catch(e => setMsg('Error: ' + e.message)) }, [horas])
  return (
    <Stack spacing={1.5}>
      <Stack direction="row" spacing={1} alignItems="center">
        <TextField select size="small" label="Periodo" value={horas} onChange={e => setHoras(e.target.value)} sx={{ width: 140 }}>
          {[['1', 'Última hora'], ['24', '24 horas'], ['168', '7 días'], ['720', '30 días']].map(([v, l]) => <MenuItem key={v} value={v}>{l}</MenuItem>)}</TextField>
        <Typography variant="caption" color="text.secondary">Ordenado por el tiempo total que consumió cada consulta. p95 = el 95 % de las veces tardó menos que esto.</Typography>
      </Stack>
      <Paper variant="outlined" sx={contenedor}>
        <Table size="small">
          <TableHead><TableRow sx={{ bgcolor: '#eef2e3' }}>{['Consulta', 'Veces', 'Se pasó de tiempo', 'Fallas', 'Promedio', 'Mediana', 'p95', 'Máximo', 'SQL prom.', 'Cálculo prom.', 'Última'].map((h, i) => <TableCell key={h} align={i && i < 10 ? 'right' : 'left'} sx={{ fontWeight: 700, whiteSpace: 'nowrap' }}>{h}</TableCell>)}</TableRow></TableHead>
          <TableBody>
            {r.map(x => (
              <TableRow key={x.ruta} hover sx={{ '& td': { whiteSpace: 'nowrap' } }}>
                <TableCell><b>{corta(x.ruta)}</b></TableCell><TableCell align="right">{x.n.toLocaleString('es-CO')}</TableCell>
                <TableCell align="right" sx={{ color: x.timeouts ? '#c62828' : undefined, fontWeight: x.timeouts ? 700 : undefined }}>{x.timeouts}</TableCell>
                <TableCell align="right" sx={{ color: x.fallas ? '#b45309' : undefined }}>{x.fallas}</TableCell>
                <TableCell align="right" sx={{ color: colorMs(x.ms_prom) }}>{seg(x.ms_prom)}</TableCell><TableCell align="right">{seg(x.ms_p50)}</TableCell>
                <TableCell align="right" sx={{ color: colorMs(x.ms_p95), fontWeight: 700 }}>{seg(x.ms_p95)}</TableCell><TableCell align="right" sx={{ color: colorMs(x.ms_max) }}>{seg(x.ms_max)}</TableCell>
                <TableCell align="right">{seg(x.sql_prom)}</TableCell><TableCell align="right">{seg(x.calc_prom)}</TableCell><TableCell>{hora(x.ultima)}</TableCell>
              </TableRow>))}
            {!r.length && <TableRow><TableCell colSpan={11} align="center" sx={{ color: 'text.secondary', py: 3 }}>Sin consultas en este periodo</TableCell></TableRow>}
          </TableBody>
        </Table>
      </Paper>
    </Stack>)
}

function EnCurso({ setMsg }: { setMsg: (s: string) => void }) {
  const [filas, setFilas] = useState<any[]>([])
  const cargar = useCallback(() => api('/diagnostico/activas').then(x => setFilas(x.filas)).catch(e => setMsg('Error: ' + e.message)), [])
  useEffect(() => { cargar(); const t = setInterval(cargar, 4000); return () => clearInterval(t) }, [cargar])
  const cancelar = async (x: any) => {
    if (!(await confirmar('Cancelar la consulta', `Se cancela la consulta del proceso ${x.pid} (lleva ${x.segundos} s). Quien la pidió verá un error; la conexión no se cierra.`, { peligro: true, si: 'Sí, cancelar' }))) return
    try { const r = await api('/diagnostico/cancelar/' + x.pid, { method: 'POST' }); setMsg(r.cancelada ? 'Consulta cancelada' : 'No se pudo cancelar'); cargar() } catch (e: any) { setMsg('Error: ' + e.message) }
  }
  return (
    <Stack spacing={1.5}>
      <Typography variant="caption" color="text.secondary">Lo que Postgres está ejecutando ahora (se actualiza cada 4 s). Una consulta de pantalla que lleve más de ~50 s ya debería haberse cortado sola: si la ves aquí, algo anda mal.</Typography>
      <Paper variant="outlined" sx={contenedor}>
        <Table size="small">
          <TableHead><TableRow sx={{ bgcolor: '#eef2e3' }}>{['', 'Proceso', 'Lleva', 'Estado', 'Espera', 'Consulta'].map(h => <TableCell key={h} sx={{ fontWeight: 700 }}>{h}</TableCell>)}</TableRow></TableHead>
          <TableBody>
            {filas.map(x => (
              <TableRow key={x.pid} hover>
                <TableCell padding="checkbox"><Tooltip title="Cancelar esta consulta"><IconButton size="small" color="error" onClick={() => cancelar(x)}><Cancel fontSize="small" /></IconButton></Tooltip></TableCell>
                <TableCell>{x.pid}</TableCell>
                <TableCell sx={{ fontWeight: 700, color: x.segundos >= 50 ? '#c62828' : x.segundos >= 10 ? '#b45309' : undefined, whiteSpace: 'nowrap' }}>{x.segundos == null ? '—' : `${x.segundos} s`}</TableCell>
                <TableCell>{x.estado}</TableCell><TableCell sx={{ whiteSpace: 'nowrap' }}>{x.espera ?? '—'}</TableCell>
                <TableCell sx={{ fontFamily: 'monospace', fontSize: 12, minWidth: 320, wordBreak: 'break-word' }}>{x.consulta}</TableCell>
              </TableRow>))}
            {!filas.length && <TableRow><TableCell colSpan={6} align="center" sx={{ color: 'text.secondary', py: 3 }}>No hay consultas corriendo en este momento</TableCell></TableRow>}
          </TableBody>
        </Table>
      </Paper>
    </Stack>)
}

function Base({ setMsg }: { setMsg: (s: string) => void }) {
  const [d, setD] = useState<any>(null)
  useEffect(() => { api('/diagnostico/base').then(setD).catch(e => setMsg('Error: ' + e.message)) }, [])
  if (!d) return <Typography color="text.secondary">Cargando…</Typography>
  const viejas = d.tablas.filter((t: any) => t.filas > 1000 && (!t.analizada || t.cambios_desde_analyze > t.filas * 0.2))
  const ventasMeses = d.ventas_por_mes.length
  return (
    <Stack spacing={1.5}>
      <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 1 }}>
        {[['Tamaño de la base', mb(d.bytes_base)], ['Conexiones', `${d.conexiones_activas} activas de ${d.conexiones}`], ['Tiempo máximo por consulta', d.statement_timeout === '0' ? 'sin límite' : d.statement_timeout], ['Meses de ventas cargados', String(ventasMeses)]].map(([k, v]) => (
          <Paper key={k} variant="outlined" sx={{ p: 1.25, flex: '1 1 150px' }}><Typography variant="caption" color="text.secondary">{k}</Typography><Typography sx={{ fontWeight: 700 }}>{v}</Typography></Paper>))}
      </Box>
      {viejas.length > 0 && <Alert severity="warning" sx={{ py: 0 }}>Estas tablas tienen estadísticas viejas o con muchos cambios desde el último análisis: {viejas.map((t: any) => t.tabla).join(', ')}. Corre Log → «Actualizar estadísticas».</Alert>}
      <Typography variant="subtitle2" sx={{ fontWeight: 700 }}>Tablas más grandes</Typography>
      <Paper variant="outlined" sx={contenedor}>
        <Table size="small">
          <TableHead><TableRow sx={{ bgcolor: '#eef2e3' }}>{['Tabla', 'Filas (aprox.)', 'Muertas', 'Tamaño', 'Cambios desde el análisis', 'Estadísticas al día desde', 'Limpieza'].map((h, i) => <TableCell key={h} align={i && i < 5 ? 'right' : 'left'} sx={{ fontWeight: 700, whiteSpace: 'nowrap' }}>{h}</TableCell>)}</TableRow></TableHead>
          <TableBody>
            {d.tablas.map((t: any) => (
              <TableRow key={t.tabla} hover sx={{ '& td': { whiteSpace: 'nowrap' } }}>
                <TableCell><b>{t.tabla}</b></TableCell><TableCell align="right">{t.filas.toLocaleString('es-CO')}</TableCell>
                <TableCell align="right" sx={{ color: t.muertas > t.filas * 0.3 && t.muertas > 10000 ? '#b45309' : undefined }}>{t.muertas.toLocaleString('es-CO')}</TableCell>
                <TableCell align="right">{mb(t.bytes)}</TableCell><TableCell align="right">{t.cambios_desde_analyze.toLocaleString('es-CO')}</TableCell>
                <TableCell sx={{ color: !t.analizada && t.filas > 1000 ? '#c62828' : undefined }}>{t.analizada ? hora(t.analizada) : 'nunca'}</TableCell><TableCell>{t.vaciada ? hora(t.vaciada) : '—'}</TableCell>
              </TableRow>))}
          </TableBody>
        </Table>
      </Paper>
      <Typography variant="subtitle2" sx={{ fontWeight: 700 }}>Ventas por mes cargadas <Typography component="span" variant="caption" color="text.secondary">· si falta un mes o una tienda aquí, falta en los informes</Typography></Typography>
      <Paper variant="outlined" sx={contenedor}>
        <Table size="small">
          <TableHead><TableRow sx={{ bgcolor: '#eef2e3' }}>{['Mes', 'Tiendas', 'Items', 'Venta neta (millones $)'].map((h, i) => <TableCell key={h} align={i ? 'right' : 'left'} sx={{ fontWeight: 700 }}>{h}</TableCell>)}</TableRow></TableHead>
          <TableBody>
            {d.ventas_por_mes.map((v: any) => (
              <TableRow key={v.mes} hover><TableCell>{String(v.mes).slice(0, 4)}-{String(v.mes).slice(4)}</TableCell><TableCell align="right">{v.tiendas}</TableCell><TableCell align="right">{v.items.toLocaleString('es-CO')}</TableCell><TableCell align="right">{Number(v.venta_millones).toLocaleString('es-CO')}</TableCell></TableRow>))}
            {!d.ventas_por_mes.length && <TableRow><TableCell colSpan={4} align="center" sx={{ color: 'text.secondary', py: 3 }}>No hay ventas cargadas</TableCell></TableRow>}
          </TableBody>
        </Table>
      </Paper>
    </Stack>)
}

export default function Diagnostico() {
  const [tab, setTab] = useState(0); const [msg, setMsg] = useState('')
  return (
    <Box sx={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr)', gap: 1.5, maxWidth: 1400, mx: 'auto' }}>
      <Typography variant="h6" sx={{ fontWeight: 700 }}>Diagnóstico</Typography>
      <Tabs value={tab} onChange={(_, v) => setTab(v)} variant="scrollable" scrollButtons="auto">
        <Tab label="Consultas" /><Tab label="Resumen por consulta" /><Tab label="En ejecución" /><Tab label="Base de datos" /></Tabs>
      {tab === 0 && <Consultas setMsg={setMsg} />}{tab === 1 && <Resumen setMsg={setMsg} />}{tab === 2 && <EnCurso setMsg={setMsg} />}{tab === 3 && <Base setMsg={setMsg} />}
      <Aviso msg={msg} onClose={() => setMsg('')} />
    </Box>)
}
