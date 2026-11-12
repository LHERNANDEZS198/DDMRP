import { ReactNode, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Alert, Autocomplete, Box, Button, Chip, CircularProgress, IconButton, MenuItem, Paper, TextField, ToggleButton, ToggleButtonGroup, Tooltip, Typography } from '@mui/material'
import Refresh from '@mui/icons-material/Refresh'
import Close from '@mui/icons-material/Close'
import { api, seguirTarea } from '../api'
import { NOMBRE_EMPRESA, useEmpresa } from '../Empresa'
import { useYo } from '../Yo'

// ---------- formatos ----------
export const ent = (v: any) => v == null ? '' : Math.round(Number(v)).toLocaleString('es-CO')
export const pesos = (v: any) => v == null ? '' : '$' + Math.round(Number(v)).toLocaleString('es-CO')
/** $ en millones con un decimal: «$1.234,5 M» */
export const MM = (v: any) => v == null ? '' : '$' + (Number(v) / 1e6).toLocaleString('es-CO', { maximumFractionDigits: 1 }) + ' M'
export const pct = (v: any, d = 1) => v == null ? '—' : (Number(v) * 100).toLocaleString('es-CO', { maximumFractionDigits: d }) + ' %'
/** Etiquetas de eje: «450 M» y «47,5 %» (nunca «-0 M»). */
export const ejeM = (v: number) => { const r = Math.round(v / 1e6); return (r === 0 ? 0 : r).toLocaleString('es-CO') + ' M' }
export const ejePct = (v: number) => (Math.round(v * 1000) / 10 || 0).toLocaleString('es-CO', { maximumFractionDigits: 1 }) + ' %'
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
export type Serie = { nombre: string; color: string; valores: (number | null)[]; dash?: string }
export function useAncho(): [(el: HTMLDivElement | null) => void, number] {
  const [el, setEl] = useState<HTMLDivElement | null>(null); const [w, setW] = useState(800)
  useEffect(() => {
    if (!el) return
    setW(Math.max(300, el.getBoundingClientRect().width))
    const ro = new ResizeObserver(e => setW(Math.max(300, e[0].contentRect.width))); ro.observe(el); return () => ro.disconnect()
  }, [el])
  return [setEl, w]
}
/** Escala del eje: parte del rango real de los datos (con un poco de aire), lo cierra en pasos redondos y escoge el paso que menos sobra por encima del dato.
 *  piso / techo fijan un extremo (p. ej. 0 y 100 % en el cumplimiento); spanMin evita que una serie casi plana se magnifique (se muestra al menos ese rango). */
export function escala(vals: number[], o: { piso?: number; techo?: number; spanMin?: number }): { lo: number; hi: number; ticks: number[] } {
  let lo = vals.length ? Math.min(...vals) : 0, hi = vals.length ? Math.max(...vals) : 1
  const todoPositivo = lo >= 0
  if (o.spanMin && hi - lo < o.spanMin) { const m = (hi + lo) / 2; lo = m - o.spanMin / 2; hi = m + o.spanMin / 2 }
  if (hi - lo < 1e-12) { const d = Math.abs(hi) * .1 || 1; lo -= d; hi += d }
  const aire = (hi - lo) * .06
  if (o.piso != null) lo = Math.min(o.piso, lo)
  else if (todoPositivo && lo <= hi * .35) lo = 0          // los pesos que arrancan cerca de cero se anclan en cero
  else lo = Math.max(lo - aire, todoPositivo ? 0 : -Infinity)
  hi = o.techo != null ? Math.max(o.techo, hi) : hi + aire
  const e0 = Math.floor(Math.log10((hi - lo) / 6)) - 1
  let mejor: { a: number; b: number; st: number; n: number } | null = null
  for (let e = e0; e <= e0 + 3; e++) for (const m of [1, 1.5, 2, 2.5, 4, 5]) {
    const st = m * Math.pow(10, e), a = Math.floor(lo / st + 1e-9) * st, b = Math.ceil(hi / st - 1e-9) * st, n = Math.round((b - a) / st)
    if (n < 3 || n > 6) continue
    const r = b - a, r0 = mejor ? mejor.b - mejor.a : Infinity
    if (!mejor || r < r0 * (1 - 1e-9) || (Math.abs(r - r0) <= r0 * 1e-9 && n < mejor.n)) mejor = { a, b, st, n }
  }
  if (!mejor) return { lo, hi, ticks: [lo, hi] }
  const { a, b, st, n } = mejor
  return { lo: a, hi: b, ticks: Array.from({ length: n + 1 }, (_, i) => (+(a + i * st).toPrecision(12)) || 0) }
}

type PropsLineas = { periodos: string[]; series: Serie[]; fmt: (v: number) => string; fmtEje?: (v: number) => string; alto?: number; techo?: number; piso?: number; spanMin?: number; etiquetas?: string[]; sinLeyenda?: boolean; leyenda?: ReactNode }
export function Lineas({ periodos, series, fmt, fmtEje, alto = 260, techo, piso, spanMin, etiquetas, sinLeyenda, leyenda }: PropsLineas) {
  const [ref, W] = useAncho(); const [hover, setHover] = useState<number | null>(null)
  const M = { l: 56, r: 16, t: 10, b: 28 }, H = alto, n = periodos.length
  if (!n) return <Typography color="text.secondary" sx={{ p: 3 }}>Sin datos en el rango. Revisa los filtros o actualiza los datos.</Typography>
  const todos = series.flatMap(s => s.valores).filter((v): v is number => v != null)
  const { lo: min, hi: max, ticks } = escala(todos, { piso, techo, spanMin })
  const pw = W - M.l - M.r, ph = H - M.t - M.b
  const x = (i: number) => M.l + (n === 1 ? pw / 2 : (pw * i) / (n - 1)), y = (v: number) => M.t + ph - ((v - min) / ((max - min) || 1)) * ph
  const paso = Math.max(1, Math.ceil(n / Math.max(2, Math.floor(pw / 56))))
  const eje = fmtEje ?? fmt
  const etq = (i: number) => etiquetas?.[i] ?? mesLargo(periodos[i])
  const trazo = (s: Serie) => { let d = '', abierto = false; s.valores.forEach((v, i) => { if (v == null) { abierto = false; return } d += `${abierto ? 'L' : 'M'}${x(i)},${y(v)} `; abierto = true }); return d }
  return (
    <Box ref={ref} sx={{ width: '100%', position: 'relative' }}>
      {leyenda}
      {!leyenda && series.length > 1 && !sinLeyenda && (
        <Box sx={{ display: 'flex', gap: 2, fontSize: 12, mb: .5, flexWrap: 'wrap' }}>
          {series.map(s => <span key={s.nombre} style={{ color: TINTA2 }}><span style={{ display: 'inline-block', width: 10, height: 10, borderRadius: 5, background: s.color, marginRight: 5 }} />{s.nombre}</span>)}
        </Box>)}
      <svg width={W} height={H} role="img" onMouseLeave={() => setHover(null)}
        onMouseMove={e => { const r = (e.currentTarget as SVGElement).getBoundingClientRect(); const i = Math.round(((e.clientX - r.left - M.l) / (pw || 1)) * (n - 1)); setHover(i >= 0 && i < n ? i : null) }}>
        {ticks.map(t => <g key={t}><line x1={M.l} x2={W - M.r} y1={y(t)} y2={y(t)} stroke={REJILLA} /><text x={M.l - 8} y={y(t) + 4} fontSize="11" textAnchor="end" fill={TINTA2}>{eje(t)}</text></g>)}
        {periodos.map((p, i) => i % paso === 0 && <text key={p} x={x(i)} y={H - 8} fontSize="11" textAnchor="middle" fill={TINTA2}>{etq(i)}</text>)}
        {hover != null && <line x1={x(hover)} x2={x(hover)} y1={M.t} y2={H - M.b} stroke="#9aa28f" strokeDasharray="3 3" />}
        {series.map(s => <path key={s.nombre} d={trazo(s)} fill="none" stroke={s.color} strokeWidth="2" strokeDasharray={s.dash} strokeLinejoin="round" strokeLinecap="round" />)}
        {series.map(s => s.valores.map((v, i) => v != null && (n <= 24 || hover === i) && <circle key={s.nombre + i} cx={x(i)} cy={y(v)} r={hover === i ? 5 : 3.5} fill={s.color} stroke="#fff" strokeWidth="2" />))}
      </svg>
      {hover != null && (
        <Box sx={{ position: 'absolute', top: leyenda || (series.length > 1 && !sinLeyenda) ? 28 : 8, left: Math.min(Math.max(x(hover) + 12, 8), W - 200), bgcolor: 'rgba(255,255,255,.97)', border: '1px solid #cfd5c4', borderRadius: 1, p: 1, fontSize: 12, pointerEvents: 'none', boxShadow: 2, minWidth: 170 }}>
          <b>{etq(hover)}</b>
          {series.map(s => <div key={s.nombre}><span style={{ display: 'inline-block', width: 8, height: 8, borderRadius: 4, background: s.color, marginRight: 5 }} />{s.nombre}: <b>{s.valores[hover] == null ? '—' : fmt(s.valores[hover] as number)}</b></div>)}
        </Box>)}
    </Box>)
}

// ---------- vista por año: lineal, años sobrepuestos o un panel por año ----------
export type ModoVista = 'lineal' | 'sobre' | 'separar'
const MES3 = ['ene', 'feb', 'mar', 'abr', 'may', 'jun', 'jul', 'ago', 'sep', 'oct', 'nov', 'dic']
const MESES = MES3.map((_, i) => String(i + 1).padStart(2, '0'))
const COLORES_ANIO = [COLOR.azul, COLOR.naranja, COLOR.violeta, COLOR.aqua]      // el año mas reciente siempre azul, el anterior naranja...
const TRAZO_SERIE = [undefined, '1 5', '8 4', '9 3 2 3']      // 1.ª serie sólida, 2.ª punteada...

/** Modo de vista elegido: se recuerda por navegador y es el mismo para todos los informes. */
export function useModoVista(): [ModoVista, (m: ModoVista) => void] {
  const [m, setM] = useState<ModoVista>(() => { try { const g = localStorage.getItem('ddmrp_rep_vista'); return g === 'sobre' || g === 'separar' ? g : 'lineal' } catch { return 'lineal' } })
  return [m, (v: ModoVista) => { setM(v); try { localStorage.setItem('ddmrp_rep_vista', v) } catch { /* sin almacenamiento */ } }]
}

export function SelectorVista({ modo, setModo }: { modo: ModoVista; setModo: (m: ModoVista) => void }) {
  return (
    <Tooltip placement="top" title="Cómo se dibujan las tendencias: una línea de corrido en el tiempo, un año encima del otro (ene a dic) para comparar la misma época, o un panel por año con el mismo eje vertical.">
      <ToggleButtonGroup size="small" exclusive value={modo} onChange={(_, v) => v && setModo(v)}>
        <ToggleButton value="lineal">Lineal</ToggleButton><ToggleButton value="sobre">Años sobrepuestos</ToggleButton><ToggleButton value="separar">Un panel por año</ToggleButton>
      </ToggleButtonGroup>
    </Tooltip>)
}

/** Las mismas series de `Lineas` en la vista elegida. Sobrepuestos: eje ene–dic, una línea por año (los 4 más recientes); el color es siempre el del año y,
 *  con varias series, cada serie tiene su trazo (la primera sólida, la segunda punteada). Un panel por año: cada año con su propio eje horizontal y el mismo eje vertical. */
export function LineasAnio({ modo, periodos, series, ...r }: { modo: ModoVista } & PropsLineas) {
  const anios = [...new Set(periodos.map(p => p.slice(0, 4)))].sort()
  if (modo === 'lineal' || !anios.length) return <Lineas periodos={periodos} series={series} {...r} />
  const deAnio = (a: string, s: Serie) => MESES.map(m => { const i = periodos.indexOf(a + m); return i >= 0 ? s.valores[i] : null })
  if (modo === 'sobre') {
    const vis = anios.slice(-4).reverse(), una = series.length === 1
    const ss: Serie[] = vis.flatMap((a, k) => series.map((s, j) => ({ nombre: una ? a : `${s.nombre} ${a}`, color: COLORES_ANIO[k], dash: TRAZO_SERIE[j], valores: deAnio(a, s) })))
    const ley = una ? undefined : (
      <Box sx={{ display: 'flex', gap: 2.5, fontSize: 12, mb: .5, flexWrap: 'wrap', color: TINTA2 }}>
        <Box sx={{ display: 'flex', gap: 1.5 }}>{vis.map((a, k) => <span key={a}><span style={{ display: 'inline-block', width: 10, height: 10, borderRadius: 5, background: COLORES_ANIO[k], marginRight: 5 }} />{a}</span>)}</Box>
        <Box sx={{ display: 'flex', gap: 1.5 }}>{series.map((s, j) => <span key={s.nombre}><svg width="26" height="8" style={{ marginRight: 5 }}><line x1="1" x2="25" y1="4" y2="4" stroke={TINTA2} strokeWidth="2" strokeLinecap="round" strokeDasharray={TRAZO_SERIE[j]} /></svg>{s.nombre}</span>)}</Box>
      </Box>)
    return <Lineas periodos={MESES} etiquetas={MES3} series={ss} leyenda={ley} {...r} />
  }
  const todos = series.flatMap(s => s.valores).filter((v): v is number => v != null)
  const esc = escala(todos, { piso: r.piso, techo: r.techo, spanMin: r.spanMin })
  return (
    <Box>
      {[...anios].reverse().map((a, k) => (
        <Box key={a} sx={{ mt: k ? 1 : 0 }}>
          <Typography variant="caption" sx={{ fontWeight: 700, color: TINTA }}>{a}</Typography>
          <Lineas {...r} periodos={MESES} etiquetas={MES3} series={series.map(s => ({ ...s, valores: deAnio(a, s) }))} piso={esc.lo} techo={esc.hi} alto={Math.round((r.alto ?? 260) * .62)} sinLeyenda={k > 0} />
        </Box>))}
    </Box>)
}

// ---------- filtros ----------
export type CritSel = { plan: string; vals: string[] }
export type Filtro = { desde: string; hasta: string; labs: string[]; cats: string[]; accs: string[]; un: string[]; q: string; crit: CritSel[]; skus?: string[] }
type Op = { id: string; nombre: string; se_compra?: boolean }
export type Criterio = { plan_id: string; nombre: string; valores: { id: string; nombre: string; items: number }[] }
export type Opciones = { plan_categoria?: string; plan_accion?: string; labs: Op[]; categorias: Op[]; acciones: Op[]; unidades: string[]; periodo_min: string | null; periodo_max: string | null; actualizacion: any[]; criterios: Criterio[]; empresas_con_datos: string[] }

const restar = (p: string, m: number) => { const t = Number(p.slice(0, 4)) * 12 + Number(p.slice(4)) - 1 - m; return `${Math.floor(t / 12)}${String((t % 12) + 1).padStart(2, '0')}` }
const rango = (a: string, b: string) => { const r: string[] = []; for (let p = a; p <= b && r.length < 400; p = restar(p, -1)) r.push(p); return r }

/** Filtros del reporte: se recuerdan por navegador y por empresa (la de la barra: Funat, Stores o ambas). La primera vez en cada empresa: ultimos 12 meses y las
 *  categorias que esa empresa compra. Al cambiar de empresa la pantalla vuelve a pedir las listas y los datos de la elegida. */
export function useFiltros(clave: string) {
  const { lista: empresa } = useEmpresa()
  const empKey = empresa.join(',') || '*'
  const [op, setOp] = useState<Opciones | null>(null)
  const [f, setF] = useState<Filtro | null>(null)
  const [err, setErr] = useState('')
  const dueno = useRef('')       // de que empresa son los filtros que hay en pantalla
  const LSK = `ddmrp_rep_${clave}_${empKey}`
  const cargarOpciones = useCallback(() => {
    if (dueno.current !== empKey) setF(null)
    api(`/compras/reportes/opciones${empresa.length ? '?empresa=' + empresa.join(',') : ''}`).then((o: Opciones) => {
      setOp(o)
      setF(prev => {
        if (prev && dueno.current === empKey) return prev
        dueno.current = empKey
        try { const g = localStorage.getItem(LSK); if (g) return { crit: [], skus: [], ...JSON.parse(g), q: '' } } catch { /* sin almacenamiento */ }
        const hasta = o.periodo_max || ''
        return { desde: hasta ? restar(hasta, 11) : '', hasta, labs: [], cats: o.categorias.filter(c => c.se_compra).map(c => c.id), accs: [], un: [], q: '', crit: [], skus: [] }
      })
    }).catch(e => setErr(String(e?.message || e)))
  }, [empKey, LSK])
  useEffect(cargarOpciones, [cargarOpciones])
  useEffect(() => { if (f && dueno.current === empKey) try { localStorage.setItem(LSK, JSON.stringify(f)) } catch { /* sin almacenamiento */ } }, [f, LSK, empKey])
  const qs = useMemo(() => {
    if (!f) return ''
    const p = new URLSearchParams()
    if (empresa.length) p.set('empresa', empresa.join(','))
    if (f.desde) p.set('desde', f.desde); if (f.hasta) p.set('hasta', f.hasta)
    if (f.labs.length) p.set('labs', f.labs.join(',')); if (f.cats.length) p.set('categorias', f.cats.join(','))
    if (f.accs.length) p.set('acciones', f.accs.join(',')); if (f.un.length) p.set('un', f.un.join(','))
    const crit = (f.crit ?? []).filter(c => c.plan && c.vals.length).flatMap(c => c.vals.map(v => `${c.plan}:${v}`))
    if (crit.length) p.set('crit', crit.join(','))
    if (f.q.trim()) p.set('q', f.q.trim())
    if (f.skus?.length) p.set('skus', f.skus.join(','))
    return p.toString()
  }, [f, empKey])
  return { op, f, setF, qs, err, recargarOpciones: cargarOpciones }
}

/** Selector de SKU exactos (uno o varios): escribe el código o parte de la descripción, elige de la lista y queda el SKU completo como un chip (como laboratorio o categoría).
 *  También acepta pegar varios códigos separados por coma, espacio o salto de línea. Filtra por igualdad: elegir 192970 no trae el 2192970. */
function SkuPicker({ valor, onChange }: { valor: string[]; onChange: (v: string[]) => void }) {
  const { lista: empresa } = useEmpresa()
  const [texto, setTexto] = useState(''); const [sug, setSug] = useState<{ id: string; descripcion: string }[]>([]); const [busca, setBusca] = useState(false)
  const nombres = useRef<Record<string, string>>({})
  useEffect(() => {
    const t = texto.trim()
    if (t.length < 2) { setSug([]); return }
    let vivo = true; setBusca(true)
    const h = setTimeout(() => api(`/compras/reportes/skus?buscar=${encodeURIComponent(t)}${empresa.length ? '&empresa=' + empresa.join(',') : ''}`)
      .then((r: any[]) => { if (!vivo) return; r.forEach(x => { nombres.current[x.id] = x.descripcion }); setSug(r) }).catch(() => vivo && setSug([])).finally(() => vivo && setBusca(false)), 300)
    return () => { vivo = false; clearTimeout(h) }
  }, [texto, empresa.join(',')])
  const agregar = (ids: string[]) => { const nuevos = ids.map(x => x.trim()).filter(Boolean); if (nuevos.length) onChange(Array.from(new Set([...valor, ...nuevos]))) }
  return (
    <Autocomplete multiple freeSolo size="small" limitTags={2} sx={{ width: 260 }} options={sug.map(s => s.id)} value={valor} inputValue={texto} loading={busca} disableCloseOnSelect filterOptions={x => x}
      getOptionLabel={(o: string) => o} noOptionsText="Escribe al menos 2 letras o dígitos"
      renderOption={(props, o: string) => <li {...props} key={o}><b>{o}</b>&nbsp;<span style={{ color: '#666', fontSize: 12 }}>{nombres.current[o] ?? ''}</span></li>}
      onInputChange={(_, v, motivo) => {
        if (motivo === 'reset') return              // al elegir una opción el texto se limpia solo
        const t = v.trim(), solo = /^\d+(\s+\d+)+$/.test(t)      // varios códigos numéricos separados por espacio; con letras el espacio es parte de la descripción
        if (/[,;\n\t]/.test(t) || solo) { agregar(t.split(/[,;\s]+/)); setTexto(''); return }   // pegar varios códigos
        setTexto(v)
      }}
      onChange={(_, v) => { onChange((v as string[]).map(x => x.trim()).filter(Boolean)); setTexto('') }}
      renderInput={p => <TextField {...p} label="SKU (uno o varios)" placeholder={valor.length ? '' : 'código o nombre'} />} />)
}

function Multi({ etiqueta, opciones, valor, onChange, ancho = 220 }: { etiqueta: string; opciones: Op[]; valor: string[]; onChange: (v: string[]) => void; ancho?: number }) {
  const sel = opciones.filter(o => valor.includes(o.id))
  return (
    <Autocomplete multiple size="small" limitTags={1} options={opciones} value={sel} disableCloseOnSelect sx={{ width: ancho }} getOptionLabel={o => o.nombre}
      isOptionEqualToValue={(a, b) => a.id === b.id} onChange={(_, v) => onChange(v.map(x => x.id))}
      renderTags={(v, getProps) => v.length <= 1 ? v.map((o, i) => <Chip size="small" label={o.nombre} {...getProps({ index: i })} key={o.id} />) : [<Chip size="small" label={`${v.length} elegidos`} key="n" onDelete={() => onChange([])} />]}
      renderInput={p => <TextField {...p} label={etiqueta} />} />)
}

export function BarraFiltros({ op, f, setF, conUn, extra, sinPeriodo }: { op: Opciones; f: Filtro; setF: (f: Filtro) => void; conUn?: boolean; extra?: ReactNode; sinPeriodo?: boolean }) {
  const periodos = op.periodo_min && op.periodo_max ? rango(op.periodo_min, op.periodo_max) : []
  const set = (k: Partial<Filtro>) => setF({ ...f, ...k })
  const crit: CritSel[] = f.crit?.length ? f.crit : [{ plan: '', vals: [] }]     // criterios de items elegidos: planes distintos se combinan (Y), valores del mismo plan (O)
  const valoresDe = (plan: string) => op.criterios.find(p => p.plan_id === plan)?.valores ?? []
  const libres = (actual: string) => op.criterios.filter(p => p.plan_id === actual || !crit.some(c => c.plan === p.plan_id))
  const ponerFila = (i: number, c: CritSel) => set({ crit: crit.map((x, j) => j === i ? c : x) })
  return (
    <Paper variant="outlined" sx={{ p: 1.5, borderRadius: 2, display: 'flex', gap: 1.25, flexWrap: 'wrap', alignItems: 'center', bgcolor: '#fff' }}>
      {!sinPeriodo && <>
        <TextField select size="small" label="Desde" value={f.desde} onChange={e => set({ desde: e.target.value })} sx={{ width: 110 }}>
          {periodos.map(p => <MenuItem key={p} value={p}>{mesLargo(p)}</MenuItem>)}</TextField>
        <TextField select size="small" label="Hasta" value={f.hasta} onChange={e => set({ hasta: e.target.value })} sx={{ width: 110 }}>
          {periodos.map(p => <MenuItem key={p} value={p}>{mesLargo(p)}</MenuItem>)}</TextField>
      </>}
      <Multi etiqueta="Laboratorio" opciones={op.labs} valor={f.labs} onChange={labs => set({ labs })} ancho={240} />
      <Multi etiqueta="Categoría" opciones={op.categorias} valor={f.cats} onChange={cats => set({ cats })} />
      <Multi etiqueta="Acción" opciones={op.acciones} valor={f.accs} onChange={accs => set({ accs })} ancho={190} />
      {conUn && <Multi etiqueta="Unidad de negocio" opciones={op.unidades.map(u => ({ id: u, nombre: u }))} valor={f.un} onChange={un => set({ un })} />}
      <SkuPicker valor={f.skus ?? []} onChange={skus => set({ skus })} />
      {op.criterios.length > 0 && <>
        {crit.map((c, i) => <Box key={i} sx={{ display: 'contents' }}>
          <TextField select size="small" label={i === 0 ? 'Criterio de ítems' : 'Y otro criterio'} value={c.plan} sx={{ minWidth: 190 }} slotProps={{ select: { displayEmpty: true }, inputLabel: { shrink: true } }}
            onChange={e => ponerFila(i, { plan: e.target.value, vals: [] })}>
            <MenuItem value="">(elige un criterio)</MenuItem>{libres(c.plan).map(p => <MenuItem key={p.plan_id} value={p.plan_id}>{p.nombre}</MenuItem>)}</TextField>
          {c.plan && <Autocomplete multiple size="small" limitTags={2} sx={{ minWidth: 220, flex: '1 1 220px', maxWidth: 440 }} options={valoresDe(c.plan).map(v => v.id)} value={c.vals} disableCloseOnSelect
            getOptionLabel={(o: string) => valoresDe(c.plan).find(v => v.id === o)?.nombre ?? o} onChange={(_, v) => ponerFila(i, { plan: c.plan, vals: v })} renderInput={p => <TextField {...p} label="Valores" />} />}
          {(crit.length > 1 || c.plan) && <Tooltip placement="top" title="Quitar este criterio"><IconButton size="small" onClick={() => set({ crit: crit.length > 1 ? crit.filter((_, j) => j !== i) : [] })}><Close fontSize="small" /></IconButton></Tooltip>}
        </Box>)}
        {crit[crit.length - 1].plan && libres('').length > 0 && <Tooltip placement="top" title="Combinar con otro criterio: por ejemplo LÍNEA = una línea y además otro criterio de Siesa"><Button size="small" onClick={() => set({ crit: [...crit, { plan: '', vals: [] }] })}>+ Otro criterio</Button></Tooltip>}
      </>}
      {extra}
    </Paper>)
}

/** Avisa cuando la empresa elegida en la barra (Funat, Stores o ambas) todavia no tiene datos traidos de Siesa. */
export function AvisoEmpresa({ op }: { op: Opciones }) {
  const { lista } = useEmpresa()
  const faltan = (lista.length ? lista : ['05', '21']).filter(e => !op.empresas_con_datos.includes(e))
  if (lista.length ? !faltan.length : faltan.length < 2) return null     // ambas: avisa solo si ninguna tiene datos
  const nombre = lista.length ? (NOMBRE_EMPRESA[lista[0]] ?? lista[0]) : 'ninguna empresa'
  return <Alert severity="info" sx={{ py: 0 }}>Aún no hay datos de {nombre} en estos reportes. Un usuario con permiso debe pulsar «Actualizar datos» (para Stores también debe estar configurada su base de Siesa).</Alert>
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
      {fallas.map(a => <Alert key={a.empresa + a.tarea} severity="warning" sx={{ py: 0 }}>«{a.tarea}» de {NOMBRE_EMPRESA[a.empresa] ?? a.empresa} no se pudo actualizar: {a.mensaje}</Alert>)}
    </Box>)
}
