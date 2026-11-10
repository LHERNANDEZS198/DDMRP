import { ReactNode, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Alert, Autocomplete, Box, Button, Chip, CircularProgress, MenuItem, Paper, TextField, Tooltip, Typography } from '@mui/material'
import Refresh from '@mui/icons-material/Refresh'
import { api, seguirTarea } from '../api'
import { useEmpresa } from '../Empresa'
import { useYo } from '../Yo'

// ---------- formatos ----------
export const ent = (v: any) => v == null ? '' : Math.round(Number(v)).toLocaleString('es-CO')
export const pesos = (v: any) => v == null ? '' : '$' + Math.round(Number(v)).toLocaleString('es-CO')
/** $ en millones con un decimal: «$1.234,5 M» */
export const MM = (v: any) => v == null ? '' : '$' + (Number(v) / 1e6).toLocaleString('es-CO', { maximumFractionDigits: 1 }) + ' M'
export const pct = (v: any, d = 1) => v == null ? '—' : (Number(v) * 100).toLocaleString('es-CO', { maximumFractionDigits: d }) + ' %'
export const mesLargo = (p: string) => p ? `${['ene', 'feb', 'mar', 'abr', 'may', 'jun', 'jul', 'ago', 'sep', 'oct', 'nov', 'dic'][Number(p.slice(4)) - 1]} ${p.slice(2, 4)}` : ''
const fechaHora = (iso: string) => new Date(iso).toLocaleString('es-CO', { day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit', hour12: true })

// Paleta categorica validada (slot 1 azul, slot 2 naranja): cada serie lleva su color siempre
export const COLOR = { azul: '#2a78d6', naranja: '#eb6834', violeta: '#6250d6', aqua: '#1baf7a' }
const TINTA = '#2b2f26', TINTA2: string = '#5f6657', REJILLA = '#e3e7da'

// ---------- tarjeta de cifra ----------
export function Kpi({ titulo, valor, sub, ayuda }: { titulo: string; valor: ReactNode; sub?: ReactNode; ayuda?: string }) {
  return (
    <Tooltip title={ayuda || ''} placement="top" arrow disableHoverListener={!ayuda}>
      <Paper variant="outlined" sx={{ p: 1.5, flex: '1 1 150px', minWidth: 150, borderRadius: 2, bgcolor: '#fff' }}>
        <Typography variant="caption" color="text.secondary" sx={{ fontWeight: 600, letterSpacing: .2 }}>{titulo}</Typography>
        <Typography sx={{ fontSize: 26, fontWeight: 700, lineHeight: 1.2, color: TINTA }}>{valor}</Typography>
        {sub && <Typography variant="caption" color="text.secondary">{sub}</Typography>}
      </Paper>
    </Tooltip>)
}

export function Panel({ titulo, ayuda, children }: { titulo: string; ayuda?: string; children: ReactNode }) {
  return (
    <Paper variant="outlined" sx={{ p: 2, borderRadius: 2, bgcolor: '#fff', minWidth: 0 }}>
      <Typography sx={{ fontWeight: 700 }}>{titulo}</Typography>
      {ayuda && <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 1 }}>{ayuda}</Typography>}
      {children}
    </Paper>)
}

// ---------- grafico de lineas por periodo (un solo eje; con 2 o mas series lleva leyenda) ----------
export type Serie = { nombre: string; color: string; valores: (number | null)[] }
function useAncho(): [(el: HTMLDivElement | null) => void, number] {
  const [el, setEl] = useState<HTMLDivElement | null>(null); const [w, setW] = useState(800)
  useEffect(() => {
    if (!el) return
    setW(Math.max(300, el.getBoundingClientRect().width))
    const ro = new ResizeObserver(e => setW(Math.max(300, e[0].contentRect.width))); ro.observe(el); return () => ro.disconnect()
  }, [el])
  return [setEl, w]
}
const bonito = (m: number) => { const e = Math.pow(10, Math.floor(Math.log10(m || 1))); const f = m / e; return (f <= 1 ? 1 : f <= 2 ? 2 : f <= 5 ? 5 : 10) * e }

export function Lineas({ periodos, series, fmt, fmtEje, alto = 260, techo, piso = 0 }: { periodos: string[]; series: Serie[]; fmt: (v: number) => string; fmtEje?: (v: number) => string; alto?: number; techo?: number; piso?: number }) {
  const [ref, W] = useAncho(); const [hover, setHover] = useState<number | null>(null)
  const M = { l: 56, r: 16, t: 10, b: 28 }, H = alto, n = periodos.length
  if (!n) return <Typography color="text.secondary" sx={{ p: 3 }}>Sin datos en el rango. Revisa los filtros o actualiza los datos.</Typography>
  const todos = series.flatMap(s => s.valores).filter((v): v is number => v != null)
  const max = techo ?? bonito(Math.max(...todos, 1) * 1.08), min = Math.min(piso, ...todos, piso)
  const pw = W - M.l - M.r, ph = H - M.t - M.b
  const x = (i: number) => M.l + (n === 1 ? pw / 2 : (pw * i) / (n - 1)), y = (v: number) => M.t + ph - ((v - min) / ((max - min) || 1)) * ph
  const ticks = [0, 1, 2, 3, 4].map(i => min + ((max - min) / 4) * i)
  const paso = Math.max(1, Math.ceil(n / Math.max(2, Math.floor(pw / 56))))
  const eje = fmtEje ?? fmt
  const trazo = (s: Serie) => { let d = '', abierto = false; s.valores.forEach((v, i) => { if (v == null) { abierto = false; return } d += `${abierto ? 'L' : 'M'}${x(i)},${y(v)} `; abierto = true }); return d }
  return (
    <Box ref={ref} sx={{ width: '100%', position: 'relative' }}>
      {series.length > 1 && (
        <Box sx={{ display: 'flex', gap: 2, fontSize: 12, mb: .5, flexWrap: 'wrap' }}>
          {series.map(s => <span key={s.nombre} style={{ color: TINTA2 }}><span style={{ display: 'inline-block', width: 10, height: 10, borderRadius: 5, background: s.color, marginRight: 5 }} />{s.nombre}</span>)}
        </Box>)}
      <svg width={W} height={H} role="img" onMouseLeave={() => setHover(null)}
        onMouseMove={e => { const r = (e.currentTarget as SVGElement).getBoundingClientRect(); const i = Math.round(((e.clientX - r.left - M.l) / (pw || 1)) * (n - 1)); setHover(i >= 0 && i < n ? i : null) }}>
        {ticks.map(t => <g key={t}><line x1={M.l} x2={W - M.r} y1={y(t)} y2={y(t)} stroke={REJILLA} /><text x={M.l - 8} y={y(t) + 4} fontSize="11" textAnchor="end" fill={TINTA2}>{eje(t)}</text></g>)}
        {periodos.map((p, i) => i % paso === 0 && <text key={p} x={x(i)} y={H - 8} fontSize="11" textAnchor="middle" fill={TINTA2}>{mesLargo(p)}</text>)}
        {hover != null && <line x1={x(hover)} x2={x(hover)} y1={M.t} y2={H - M.b} stroke="#9aa28f" strokeDasharray="3 3" />}
        {series.map(s => <path key={s.nombre} d={trazo(s)} fill="none" stroke={s.color} strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" />)}
        {series.map(s => s.valores.map((v, i) => v != null && (n <= 24 || hover === i) && <circle key={s.nombre + i} cx={x(i)} cy={y(v)} r={hover === i ? 5 : 3.5} fill={s.color} stroke="#fff" strokeWidth="2" />))}
      </svg>
      {hover != null && (
        <Box sx={{ position: 'absolute', top: series.length > 1 ? 28 : 8, left: Math.min(Math.max(x(hover) + 12, 8), W - 200), bgcolor: 'rgba(255,255,255,.97)', border: '1px solid #cfd5c4', borderRadius: 1, p: 1, fontSize: 12, pointerEvents: 'none', boxShadow: 2, minWidth: 170 }}>
          <b>{mesLargo(periodos[hover])}</b>
          {series.map(s => <div key={s.nombre}><span style={{ display: 'inline-block', width: 8, height: 8, borderRadius: 4, background: s.color, marginRight: 5 }} />{s.nombre}: <b>{s.valores[hover] == null ? '—' : fmt(s.valores[hover] as number)}</b></div>)}
        </Box>)}
    </Box>)
}

// ---------- filtros ----------
export type Filtro = { desde: string; hasta: string; labs: string[]; cats: string[]; accs: string[]; un: string[]; q: string }
type Op = { id: string; nombre: string; se_compra?: boolean }
export type Opciones = { labs: Op[]; categorias: Op[]; acciones: Op[]; unidades: string[]; periodo_min: string | null; periodo_max: string | null; actualizacion: any[] }

const restar = (p: string, m: number) => { const t = Number(p.slice(0, 4)) * 12 + Number(p.slice(4)) - 1 - m; return `${Math.floor(t / 12)}${String((t % 12) + 1).padStart(2, '0')}` }
const rango = (a: string, b: string) => { const r: string[] = []; for (let p = a; p <= b && r.length < 400; p = restar(p, -1)) r.push(p); return r }

/** Filtros del reporte: se recuerdan por navegador. La primera vez: ultimos 12 meses y las categorias que la empresa compra. */
export function useFiltros(clave: string) {
  const { lista: empresa } = useEmpresa()
  const [op, setOp] = useState<Opciones | null>(null)
  const [f, setF] = useState<Filtro | null>(null)
  const [err, setErr] = useState('')
  const cargarOpciones = useCallback(() => {
    api(`/compras/reportes/opciones${empresa.length ? '?empresa=' + empresa.join(',') : ''}`).then((o: Opciones) => {
      setOp(o)
      setF(prev => {
        if (prev) return prev
        try { const g = localStorage.getItem('ddmrp_rep_' + clave); if (g) return { ...JSON.parse(g), q: '' } } catch { /* sin almacenamiento */ }
        const hasta = o.periodo_max || ''
        return { desde: hasta ? restar(hasta, 11) : '', hasta, labs: [], cats: o.categorias.filter(c => c.se_compra).map(c => c.id), accs: [], un: [], q: '' }
      })
    }).catch(e => setErr(String(e?.message || e)))
  }, [empresa.join(','), clave])
  useEffect(cargarOpciones, [cargarOpciones])
  useEffect(() => { if (f) try { localStorage.setItem('ddmrp_rep_' + clave, JSON.stringify(f)) } catch { /* sin almacenamiento */ } }, [f, clave])
  const qs = useMemo(() => {
    if (!f) return ''
    const p = new URLSearchParams()
    if (empresa.length) p.set('empresa', empresa.join(','))
    if (f.desde) p.set('desde', f.desde); if (f.hasta) p.set('hasta', f.hasta)
    if (f.labs.length) p.set('labs', f.labs.join(',')); if (f.cats.length) p.set('categorias', f.cats.join(','))
    if (f.accs.length) p.set('acciones', f.accs.join(',')); if (f.un.length) p.set('un', f.un.join(','))
    if (f.q.trim()) p.set('q', f.q.trim())
    return p.toString()
  }, [f, empresa.join(',')])
  return { op, f, setF, qs, err, recargarOpciones: cargarOpciones }
}

function Multi({ etiqueta, opciones, valor, onChange, ancho = 220 }: { etiqueta: string; opciones: Op[]; valor: string[]; onChange: (v: string[]) => void; ancho?: number }) {
  const sel = opciones.filter(o => valor.includes(o.id))
  return (
    <Autocomplete multiple size="small" limitTags={1} options={opciones} value={sel} disableCloseOnSelect sx={{ width: ancho }} getOptionLabel={o => o.nombre}
      isOptionEqualToValue={(a, b) => a.id === b.id} onChange={(_, v) => onChange(v.map(x => x.id))}
      renderTags={(v, getProps) => v.length <= 1 ? v.map((o, i) => <Chip size="small" label={o.nombre} {...getProps({ index: i })} key={o.id} />) : [<Chip size="small" label={`${v.length} elegidos`} key="n" onDelete={() => onChange([])} />]}
      renderInput={p => <TextField {...p} label={etiqueta} />} />)
}

export function BarraFiltros({ op, f, setF, conUn, extra }: { op: Opciones; f: Filtro; setF: (f: Filtro) => void; conUn?: boolean; extra?: ReactNode }) {
  const periodos = op.periodo_min && op.periodo_max ? rango(op.periodo_min, op.periodo_max) : []
  const set = (k: Partial<Filtro>) => setF({ ...f, ...k })
  const [q, setQ] = useState(f.q)
  useEffect(() => { const t = setTimeout(() => { if (q !== f.q) set({ q }) }, 450); return () => clearTimeout(t) }, [q])
  return (
    <Paper variant="outlined" sx={{ p: 1.5, borderRadius: 2, display: 'flex', gap: 1.25, flexWrap: 'wrap', alignItems: 'center', bgcolor: '#fff' }}>
      <TextField select size="small" label="Desde" value={f.desde} onChange={e => set({ desde: e.target.value })} sx={{ width: 110 }}>
        {periodos.map(p => <MenuItem key={p} value={p}>{mesLargo(p)}</MenuItem>)}</TextField>
      <TextField select size="small" label="Hasta" value={f.hasta} onChange={e => set({ hasta: e.target.value })} sx={{ width: 110 }}>
        {periodos.map(p => <MenuItem key={p} value={p}>{mesLargo(p)}</MenuItem>)}</TextField>
      <Multi etiqueta="Laboratorio" opciones={op.labs} valor={f.labs} onChange={labs => set({ labs })} ancho={240} />
      <Multi etiqueta="Categoría" opciones={op.categorias} valor={f.cats} onChange={cats => set({ cats })} />
      <Multi etiqueta="Acción" opciones={op.acciones} valor={f.accs} onChange={accs => set({ accs })} ancho={190} />
      {conUn && <Multi etiqueta="Unidad de negocio" opciones={op.unidades.map(u => ({ id: u, nombre: u }))} valor={f.un} onChange={un => set({ un })} />}
      <TextField size="small" label="Buscar SKU o producto" value={q} onChange={e => setQ(e.target.value)} sx={{ width: 210 }} />
      {extra}
    </Paper>)
}

/** Cuando se actualizo cada tarea y el boton para traer los datos de Siesa (con permiso). Avisa de las tareas que fallaron. */
export function Actualizacion({ op, alTerminar }: { op: Opciones; alTerminar: () => void }) {
  const { puede } = useYo(); const [msg, setMsg] = useState(''); const [corre, setCorre] = useState(false)
  const lanzar = async (completo: boolean) => {
    setCorre(true); setMsg('Lanzando la actualización…')
    try {
      const previo = (await api('/admin/progreso')).inicio ?? null
      await api('/compras/reportes/actualizar', { method: 'POST', body: JSON.stringify({ completo }) })
      const fin = await seguirTarea(setMsg, previo)
      setMsg(fin.estado === 'error' ? fin.mensaje : 'Datos actualizados'); alTerminar()
    } catch (e: any) { setMsg('Error: ' + e.message) } finally { setCorre(false) }
  }
  const fallas = op.actualizacion.filter(a => a.mensaje)
  const ult = op.actualizacion.map(a => a.fecha).sort().pop()
  return (
    <Box sx={{ display: 'flex', gap: 1.5, alignItems: 'center', flexWrap: 'wrap' }}>
      <Typography variant="caption" color="text.secondary">{ult ? `Datos de Siesa actualizados el ${fechaHora(ult)}` : 'Aún no se han traído datos de Siesa'}</Typography>
      {puede('gestionar_compras', 'correr_motor') && (<>
        <Button size="small" startIcon={corre ? <CircularProgress size={14} /> : <Refresh />} disabled={corre} onClick={() => lanzar(false)}>Actualizar datos</Button>
        <Tooltip title="Relee toda la historia de Siesa (tarda más). Úsalo si cambiaste los meses de historia o sospechas diferencias con el Power BI."><span><Button size="small" disabled={corre} onClick={() => lanzar(true)}>Recarga completa</Button></span></Tooltip>
      </>)}
      {msg && <Typography variant="caption" color="primary">{msg}</Typography>}
      {fallas.map(a => <Alert key={a.tarea} severity="warning" sx={{ py: 0 }}>«{a.tarea}» no se pudo actualizar: {a.mensaje}</Alert>)}
    </Box>)
}
