import { Fragment, useCallback, useEffect, useState } from 'react'
import { Box, Button, Chip, Collapse, IconButton, MenuItem, Paper, Stack, Tab, Table, TableBody, TableCell, TableHead, TableRow, Tabs,
  TextField, Tooltip, Typography } from '@mui/material'
import KeyboardArrowDown from '@mui/icons-material/KeyboardArrowDown'
import KeyboardArrowRight from '@mui/icons-material/KeyboardArrowRight'
import Download from '@mui/icons-material/Download'
import Refresh from '@mui/icons-material/Refresh'
import { api, bajar } from '../api'
import Aviso from '../Aviso'

type Fila = { id: number; tipo: string; origen: 'manual' | 'auto'; usuario: string | null; inicio: string; fin: string | null; estado: string
  mensaje: string | null; resumen: Record<string, any> | null; padre_id: number | null; segundos: number | null }
type Cambio = { id: number; tabla: string; llave: string; campo: string; valor_anterior: string | null; valor_nuevo: string | null; usuario: string; fecha: string }
type Ultima = { inicio: string; fin: string | null; estado: string; origen: string; usuario: string | null }

const ESTADO: Record<string, { label: string; color: 'success' | 'error' | 'warning' | 'info' }> = {
  ok: { label: 'Bien', color: 'success' }, error: { label: 'Falló', color: 'error' },
  corriendo: { label: 'Corriendo', color: 'info' }, interrumpido: { label: 'Interrumpida', color: 'warning' },
}
const hoy = () => new Date().toLocaleDateString('sv-SE')
const hace = (d: number) => new Date(Date.now() - d * 864e5).toLocaleDateString('sv-SE')
const fecha = (s: string | null) => s ? new Date(s).toLocaleString('es-CO', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit', second: '2-digit' }) : '—'
const dur = (s: number | null) => s == null ? '—' : s < 60 ? `${s} s` : `${Math.floor(s / 60)} min ${s % 60} s`
const RESUMEN_OCULTO = new Set(['cedi', 'reparto'])

function Origen({ o, u }: { o: string; u: string | null }) {
  return o === 'auto'
    ? <Tooltip title="La lanzó el programador (cron), nadie la pidió a mano"><Chip size="small" label="Automático" color="secondary" variant="outlined" /></Tooltip>
    : <Tooltip title="La lanzó una persona desde la pantalla"><Chip size="small" label={u ?? 'Manual'} variant="outlined" /></Tooltip>
}

function Tarjeta({ titulo, u }: { titulo: string; u?: Ultima }) {
  const e = u ? ESTADO[u.estado] : null
  return (
    <Paper variant="outlined" sx={{ p: 1.5, minWidth: 220, flex: '1 1 220px' }}>
      <Typography variant="caption" color="text.secondary">Última vez · {titulo}</Typography>
      {u ? (<>
        <Typography sx={{ fontWeight: 700 }}>{fecha(u.inicio)}</Typography>
        <Stack direction="row" spacing={0.5} sx={{ mt: 0.5 }}>{e && <Chip size="small" {...e} />}<Origen o={u.origen} u={u.usuario} /></Stack>
      </>) : <Typography color="text.secondary">Aún no registrada</Typography>}
    </Paper>)
}

function Operaciones({ setMsg }: { setMsg: (s: string) => void }) {
  const [d, setD] = useState<{ filas: Fila[]; tipos: Record<string, string>; usuarios: string[]; ultimas: Record<string, Ultima> }>({ filas: [], tipos: {}, usuarios: [], ultimas: {} })
  const [f, setF] = useState({ tipo: '', origen: '', estado: '', usuario: '', desde: hace(30), hasta: '', q: '' })
  const [abiertas, setAbiertas] = useState<Set<number>>(new Set())
  const qs = () => new URLSearchParams(Object.entries(f).filter(([, v]) => v)).toString()
  const cargar = useCallback(() => api('/log?' + qs()).then(setD).catch(e => setMsg('Error: ' + e.message)), [f])
  useEffect(() => { cargar() }, [cargar])
  const hayCorriendo = d.filas.some(x => x.estado === 'corriendo')
  useEffect(() => { if (!hayCorriendo) return; const t = setInterval(cargar, 5000); return () => clearInterval(t) }, [hayCorriendo, cargar])
  const set = (k: string) => (e: React.ChangeEvent<HTMLInputElement>) => setF(p => ({ ...p, [k]: e.target.value }))
  const alternar = (id: number) => setAbiertas(p => { const n = new Set(p); n.has(id) ? n.delete(id) : n.add(id); return n })
  const detalle = (x: Fila) => Object.entries(x.resumen ?? {}).filter(([k]) => !RESUMEN_OCULTO.has(k))
  const hijas = new Set(d.filas.map(x => x.padre_id).filter(Boolean))

  return (<Stack spacing={1.5}>
    <Stack direction="row" spacing={1.5} useFlexGap flexWrap="wrap">
      <Tarjeta titulo="Pipeline completo" u={d.ultimas.pipeline} />
      <Tarjeta titulo="ETL de Siesa" u={d.ultimas.etl} />
      <Tarjeta titulo="Motor DDMRP" u={d.ultimas.motor} />
    </Stack>
    <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap" alignItems="center">
      <TextField select size="small" label="Operación" value={f.tipo} onChange={set('tipo')} sx={{ minWidth: 200 }}>
        <MenuItem value="">Todas</MenuItem>{Object.entries(d.tipos).map(([k, v]) => <MenuItem key={k} value={k}>{v}</MenuItem>)}
      </TextField>
      <TextField select size="small" label="Origen" value={f.origen} onChange={set('origen')} sx={{ minWidth: 130 }}>
        <MenuItem value="">Todos</MenuItem><MenuItem value="auto">Automático</MenuItem><MenuItem value="manual">Manual</MenuItem>
      </TextField>
      <TextField select size="small" label="Estado" value={f.estado} onChange={set('estado')} sx={{ minWidth: 130 }}>
        <MenuItem value="">Todos</MenuItem>{Object.entries(ESTADO).map(([k, v]) => <MenuItem key={k} value={k}>{v.label}</MenuItem>)}
      </TextField>
      <TextField select size="small" label="Usuario" value={f.usuario} onChange={set('usuario')} sx={{ minWidth: 150 }}>
        <MenuItem value="">Todos</MenuItem>{d.usuarios.map(u => <MenuItem key={u} value={u}>{u}</MenuItem>)}
      </TextField>
      <TextField size="small" type="date" label="Desde" value={f.desde} onChange={set('desde')} InputLabelProps={{ shrink: true }} />
      <TextField size="small" type="date" label="Hasta" value={f.hasta} onChange={set('hasta')} InputLabelProps={{ shrink: true }} />
      <TextField size="small" label="Buscar" value={f.q} onChange={set('q')} />
      <Tooltip title="Actualizar"><IconButton onClick={cargar}><Refresh /></IconButton></Tooltip>
      <Button startIcon={<Download />} onClick={() => bajar('/log/csv?' + qs(), 'log_ddmrp.csv').catch(e => setMsg('Error: ' + e.message))}>Descargar CSV</Button>
    </Stack>
    <Paper variant="outlined" sx={{ overflow: 'auto' }}>
      <Table size="small">
        <TableHead><TableRow>
          <TableCell width={40} /><TableCell>Inicio</TableCell><TableCell>Operación</TableCell><TableCell>Origen</TableCell>
          <TableCell>Estado</TableCell><TableCell align="right">Duración</TableCell><TableCell>Detalle</TableCell>
        </TableRow></TableHead>
        <TableBody>
          {d.filas.map(x => {
            const det = detalle(x); const hay = det.length > 0 || !!x.mensaje; const ab = abiertas.has(x.id); const e = ESTADO[x.estado]
            return (<Fragment key={x.id}>
              <TableRow hover sx={{ '& > td': { borderBottom: ab ? 'unset' : undefined } }}>
                <TableCell>{hay && <IconButton size="small" onClick={() => alternar(x.id)}>{ab ? <KeyboardArrowDown /> : <KeyboardArrowRight />}</IconButton>}</TableCell>
                <TableCell sx={{ whiteSpace: 'nowrap' }}>{fecha(x.inicio)}</TableCell>
                <TableCell sx={{ fontWeight: hijas.has(x.id) ? 700 : 400, pl: x.padre_id ? 4 : 2 }}>{x.padre_id ? '↳ ' : ''}{d.tipos[x.tipo] ?? x.tipo}</TableCell>
                <TableCell><Origen o={x.origen} u={x.usuario} /></TableCell>
                <TableCell>{e && <Chip size="small" {...e} />}</TableCell>
                <TableCell align="right" sx={{ whiteSpace: 'nowrap' }}>{dur(x.segundos)}</TableCell>
                <TableCell sx={{ maxWidth: 420, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{x.mensaje ?? ''}</TableCell>
              </TableRow>
              <TableRow><TableCell colSpan={7} sx={{ py: 0, borderBottom: ab ? undefined : 'unset' }}>
                <Collapse in={ab} unmountOnExit>
                  <Box sx={{ p: 1.5 }}>
                    {x.mensaje && <Typography variant="body2" sx={{ mb: 1, color: x.estado === 'error' ? 'error.main' : undefined, whiteSpace: 'pre-wrap' }}>{x.mensaje}</Typography>}
                    <Box sx={{ display: 'grid', gridTemplateColumns: 'max-content 1fr', columnGap: 2, rowGap: 0.25 }}>
                      {det.map(([k, v]) => (<Fragment key={k}>
                        <Typography variant="caption" color="text.secondary">{k.replace(/_/g, ' ')}</Typography>
                        <Typography variant="caption">{typeof v === 'object' ? JSON.stringify(v) : String(v)}</Typography>
                      </Fragment>))}
                      <Typography variant="caption" color="text.secondary">terminó</Typography><Typography variant="caption">{fecha(x.fin)}</Typography>
                    </Box>
                  </Box>
                </Collapse>
              </TableCell></TableRow>
            </Fragment>)
          })}
          {!d.filas.length && <TableRow><TableCell colSpan={7} align="center" sx={{ py: 4, color: 'text.secondary' }}>Nada registrado en este rango</TableCell></TableRow>}
        </TableBody>
      </Table>
    </Paper>
  </Stack>)
}

function Cambios({ setMsg }: { setMsg: (s: string) => void }) {
  const [d, setD] = useState<{ filas: Cambio[]; tablas: string[] }>({ filas: [], tablas: [] })
  const [f, setF] = useState({ tabla: '', desde: hace(30), hasta: '', q: '' })
  const qs = () => new URLSearchParams(Object.entries(f).filter(([, v]) => v)).toString()
  const cargar = useCallback(() => api('/log/cambios?' + qs()).then(setD).catch(e => setMsg('Error: ' + e.message)), [f])
  useEffect(() => { cargar() }, [cargar])
  const set = (k: string) => (e: React.ChangeEvent<HTMLInputElement>) => setF(p => ({ ...p, [k]: e.target.value }))
  return (<Stack spacing={1.5}>
    <Typography variant="body2" color="text.secondary">Quién cambió qué en las reglas, los maestros, los usuarios y los perfiles, con el valor anterior y el nuevo.</Typography>
    <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap">
      <TextField select size="small" label="Qué se cambió" value={f.tabla} onChange={set('tabla')} sx={{ minWidth: 220 }}>
        <MenuItem value="">Todo</MenuItem>{d.tablas.map(t => <MenuItem key={t} value={t}>{t}</MenuItem>)}
      </TextField>
      <TextField size="small" type="date" label="Desde" value={f.desde} onChange={set('desde')} InputLabelProps={{ shrink: true }} />
      <TextField size="small" type="date" label="Hasta" value={f.hasta} onChange={set('hasta')} InputLabelProps={{ shrink: true }} />
      <TextField size="small" label="Buscar" value={f.q} onChange={set('q')} />
    </Stack>
    <Paper variant="outlined" sx={{ overflow: 'auto' }}>
      <Table size="small">
        <TableHead><TableRow><TableCell>Fecha</TableCell><TableCell>Usuario</TableCell><TableCell>Qué</TableCell><TableCell>Llave</TableCell><TableCell>Campo</TableCell><TableCell>Antes</TableCell><TableCell>Después</TableCell></TableRow></TableHead>
        <TableBody>
          {d.filas.map(x => (<TableRow key={x.id} hover>
            <TableCell sx={{ whiteSpace: 'nowrap' }}>{fecha(x.fecha)}</TableCell><TableCell>{x.usuario}</TableCell><TableCell>{x.tabla}</TableCell>
            <TableCell>{x.llave}</TableCell><TableCell>{x.campo}</TableCell><TableCell>{x.valor_anterior ?? '—'}</TableCell><TableCell>{x.valor_nuevo ?? '—'}</TableCell>
          </TableRow>))}
          {!d.filas.length && <TableRow><TableCell colSpan={7} align="center" sx={{ py: 4, color: 'text.secondary' }}>Sin cambios en este rango</TableCell></TableRow>}
        </TableBody>
      </Table>
    </Paper>
  </Stack>)
}

export default function Log() {
  const [tab, setTab] = useState(0); const [msg, setMsg] = useState('')
  return (<Box sx={{ p: 2, overflow: 'auto', height: '100%' }}>
    <Typography variant="h6" sx={{ fontWeight: 700 }}>Log de operaciones</Typography>
    <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>Cuándo corrió cada cosa, quién la lanzó (o si fue automática), cuánto tardó y cómo terminó.</Typography>
    <Tabs value={tab} onChange={(_, v) => setTab(v)} sx={{ mb: 1.5 }}><Tab label="Operaciones" /><Tab label="Cambios de configuración" /></Tabs>
    {tab === 0 ? <Operaciones setMsg={setMsg} /> : <Cambios setMsg={setMsg} />}
    <Aviso msg={msg} onClose={() => setMsg('')} />
  </Box>)
}
