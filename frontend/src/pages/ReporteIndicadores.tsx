import { useEffect, useMemo, useState } from 'react'
import { Accordion, AccordionDetails, AccordionSummary, Alert, Box, Button, Chip, CircularProgress, MenuItem, TextField, ToggleButton, ToggleButtonGroup, Tooltip, Typography } from '@mui/material'
import ExpandMore from '@mui/icons-material/ExpandMore'
import { ColDef } from 'ag-grid-community'
import Tabla from '../Tabla'
import { api } from '../api'
import { BarraFiltros, COLOR, Kpi, LineasAnio, MM, Panel, SelectorVista, ejeM, ejePct, ent, escala, mesLargo, pct, pesos, useAncho, useFiltros, useModoVista } from '../reportes/comun'

/** Indicadores de compras: por mes, en el periodo elegido, GMROI (cuánto margen deja cada peso invertido en inventario), OTIF del proveedor y % de abastecimiento; y del periodo completo, dónde está el capital y qué productos no lo pagan. El GMROI usa el mismo cálculo de la Clasificación. */
const BANDA: Record<string, { color: string; icono: string }> = {
  bajo: { color: '#c62828', icono: '▼' }, medio: { color: '#f9a825', icono: '●' }, alto: { color: '#2e7d32', icono: '▲' },
  sin_venta: { color: '#6d4c41', icono: '■' }, sin_inv: { color: '#8a8f80', icono: '◆' }, sin_costo: { color: '#8a8f80', icono: '?' },
}
const ETQ: Record<string, string> = { bajo: 'GMROI bajo', medio: 'GMROI medio', alto: 'En meta o más', sin_venta: 'Sin venta con inventario', sin_inv: 'Sin inventario promedio', sin_costo: 'Sin costo' }
const dec = (v: any, d = 2) => v == null ? '—' : Number(v).toLocaleString('es-CO', { minimumFractionDigits: d, maximumFractionDigits: d })
const guardado = <T,>(k: string, def: T): T => { try { const g = localStorage.getItem(k); return g == null ? def : JSON.parse(g) } catch { return def } }
const guardar = (k: string, v: unknown) => { try { localStorage.setItem(k, JSON.stringify(v)) } catch { /* sin almacenamiento */ } }

type Punto = { id: string; d: string; x: number; y: number; inv: number; g: number; b: string }

/** Cada producto es un punto: margen % (vertical) contra rotación = venta anual ÷ inventario a costo (horizontal). GMROI = margen % × rotación, así que el mínimo y la meta son curvas. */
function Dispersion({ puntos, minimo, objetivo, alto = 360 }: { puntos: Punto[]; minimo: number; objetivo: number; alto?: number }) {
  const [ref, W] = useAncho(); const [hover, setHover] = useState<Punto | null>(null)
  const M = { l: 52, r: 16, t: 10, b: 36 }, pw = W - M.l - M.r, ph = alto - M.t - M.b
  const { xe, ye, maxInv } = useMemo(() => {
    const xs = puntos.map(p => p.x).sort((a, b) => a - b), ys = puntos.map(p => p.y)
    const q95 = xs.length ? xs[Math.min(xs.length - 1, Math.floor(xs.length * .95))] : 1
    return { xe: escala([0, Math.max(q95 * 1.1, 0.5)], { piso: 0 }), ye: escala(ys.length ? ys.map(v => Math.max(v, -100)) : [0, 50], { piso: Math.max(-100, Math.min(0, ...ys)) }), maxInv: Math.max(...puntos.map(p => p.inv), 1) }
  }, [puntos])
  if (!puntos.length) return <Typography color="text.secondary" sx={{ p: 3 }}>Sin productos con venta e inventario para ubicar en el gráfico.</Typography>
  const x = (v: number) => M.l + (Math.min(Math.max(v, xe.lo), xe.hi) - xe.lo) / (xe.hi - xe.lo) * pw
  const y = (v: number) => M.t + ph - (Math.min(Math.max(v, ye.lo), ye.hi) - ye.lo) / (ye.hi - ye.lo) * ph
  const r = (p: Punto) => 3 + 9 * Math.sqrt(p.inv / maxInv)
  const curva = (g: number) => { const pts: string[] = []; for (let i = 1; i <= 60; i++) { const xv = xe.lo + (xe.hi - xe.lo) * i / 60; if (xv <= 0) continue; const yv = 100 * g / xv; if (yv >= ye.lo && yv <= ye.hi) pts.push(`${x(xv)},${y(yv)}`) } return pts.length > 1 ? 'M' + pts.join(' L') : '' }
  const cercano = (e: React.MouseEvent<SVGSVGElement>) => {
    const b = e.currentTarget.getBoundingClientRect(), mx = e.clientX - b.left, my = e.clientY - b.top
    let mejor: Punto | null = null, d0 = 18 * 18
    for (const p of puntos) { const d = (x(p.x) - mx) ** 2 + (y(p.y) - my) ** 2; if (d < d0 && d <= (r(p) + 8) ** 2) { d0 = d; mejor = p } }
    setHover(mejor)
  }
  return (
    <Box ref={ref} sx={{ width: '100%', position: 'relative' }}>
      <Box sx={{ display: 'flex', gap: 2, fontSize: 12, mb: .5, flexWrap: 'wrap', color: '#5f6657' }}>
        {['bajo', 'medio', 'alto'].map(b => <span key={b}><span style={{ display: 'inline-block', width: 10, height: 10, borderRadius: 5, background: BANDA[b].color, marginRight: 5 }} />{BANDA[b].icono} {ETQ[b]}</span>)}
        <span>· Tamaño = inventario promedio a costo</span>
      </Box>
      <svg width={W} height={alto} role="img" onMouseMove={cercano} onMouseLeave={() => setHover(null)}>
        {ye.ticks.map(t => <g key={'y' + t}><line x1={M.l} x2={W - M.r} y1={y(t)} y2={y(t)} stroke="#e3e7da" /><text x={M.l - 8} y={y(t) + 4} fontSize="11" textAnchor="end" fill="#5f6657">{dec(t, 0)} %</text></g>)}
        {xe.ticks.map(t => <text key={'x' + t} x={x(t)} y={alto - 16} fontSize="11" textAnchor="middle" fill="#5f6657">{dec(t, t < 10 ? 1 : 0)}×</text>)}
        <text x={M.l + pw / 2} y={alto - 2} fontSize="11" textAnchor="middle" fill="#5f6657">Rotación: venta anual ÷ inventario promedio a costo</text>
        <path d={curva(minimo)} fill="none" stroke={BANDA.bajo.color} strokeWidth="1.5" strokeDasharray="5 4" />
        <path d={curva(objetivo)} fill="none" stroke={BANDA.alto.color} strokeWidth="1.5" strokeDasharray="5 4" />
        {puntos.map(p => <circle key={p.id} cx={x(p.x)} cy={y(p.y)} r={r(p)} fill={BANDA[p.b]?.color ?? '#8a8f80'} fillOpacity=".7" stroke="#fff" strokeWidth="1.5" />)}
        {hover && <circle cx={x(hover.x)} cy={y(hover.y)} r={r(hover) + 2} fill="none" stroke="#2b2f26" strokeWidth="2" />}
      </svg>
      <Box sx={{ fontSize: 11, color: '#5f6657', mt: -.5 }}>Línea roja punteada: GMROI mínimo ({dec(minimo, 1)}) · línea verde punteada: meta ({dec(objetivo, 1)}). Por encima de la línea el producto cumple.</Box>
      {hover && (
        <Box sx={{ position: 'absolute', top: 40, left: Math.min(Math.max(x(hover.x) + 14, 8), W - 250), bgcolor: 'rgba(255,255,255,.97)', border: '1px solid #cfd5c4', borderRadius: 1, p: 1, fontSize: 12, pointerEvents: 'none', boxShadow: 2, minWidth: 220, maxWidth: 260 }}>
          <b>{hover.id}</b> · {hover.d}
          <div><span style={{ color: BANDA[hover.b]?.color }}>{BANDA[hover.b]?.icono}</span> GMROI <b>{dec(hover.g)}</b> · margen <b>{dec(hover.y, 1)} %</b></div>
          <div>Rotación <b>{dec(hover.x, 1)}×</b> · inventario <b>{MM(hover.inv)}</b></div>
        </Box>)}
    </Box>)
}

export default function ReporteIndicadores() {
  const { op, f, setF, qs, err } = useFiltros('indicadores')
  const [modo, setModo] = useModoVista()
  const [alcance, setAlcance] = useState<'tiendas' | 'cedi'>(() => guardado('ddmrp_gmroi_alcance', 'tiendas'))
  const [agrupar, setAgrupar] = useState<string>('laboratorio')
  const [banda, setBanda] = useState('')
  const [d, setD] = useState<any>(null)
  const [cargando, setCargando] = useState(false)
  const [e2, setE2] = useState('')
  const [recarga, setRecarga] = useState(0)
  const [calculando, setCalculando] = useState(false)
  const url = useMemo(() => {
    if (!qs) return ''
    const p = new URLSearchParams(qs); p.delete('un')
    p.set('agrupar', agrupar); p.set('solo_cedi', alcance === 'cedi' ? 'true' : 'false')
    return p.toString()
  }, [qs, agrupar, alcance])
  useEffect(() => {
    if (!url) return
    setCargando(true); setE2('')
    api(`/compras/reportes/indicadores?${url}`).then(setD).catch(e => setE2(String(e?.message || e))).finally(() => setCargando(false))
  }, [url, recarga])
  useEffect(() => { guardar('ddmrp_gmroi_alcance', alcance) }, [alcance])
  /** Lanza el cálculo aparte (el mismo de la corrida diaria) y, cuando termina, vuelve a leer el informe. */
  const recalcular = async () => {
    setCalculando(true); setE2('')
    try {
      await api('/compras/reportes/indicadores/recalcular', { method: 'POST' })
      for (let i = 0; i < 150; i++) {
        await new Promise(r => setTimeout(r, 4000))
        const e = await api('/admin/progreso')
        if (e?.estado !== 'corriendo') break
      }
      setRecarga(x => x + 1)
    } catch (e: any) { setE2(String(e?.message || e)) } finally { setCalculando(false) }
  }

  const num = (campo: string, titulo: string, fmt: (v: any) => string, ancho = 120, tip?: string): ColDef => ({ field: campo, headerName: titulo, type: 'numericColumn', width: ancho, filter: 'agNumberColumnFilter', headerTooltip: tip, valueFormatter: (p: any) => p.value == null ? '' : fmt(p.value) })
  const pill = (p: any) => p.value ? <Chip size="small" label={`${BANDA[p.value]?.icono ?? ''} ${ETQ[p.value] ?? p.value}`} sx={{ bgcolor: BANDA[p.value]?.color ?? '#8a8f80', color: '#fff', height: 20, fontSize: 11 }} /> : null
  const p100 = (v: any) => dec(Number(v) * 100, 0) + ' %'
  const colsMes: ColDef[] = useMemo(() => [
    { field: 'periodo', headerName: 'Mes', width: 100, pinned: 'left', valueFormatter: (p: any) => mesLargo(p.value) },
    num('gmroi', 'GMROI', v => dec(v), 95, 'Margen del mes anualizado ÷ inventario promedio a costo del mes'),
    num('margen', 'Margen $', pesos, 130), num('margen_pct', 'Margen %', v => dec(v, 1) + ' %', 100), num('venta', 'Venta neta', pesos, 135),
    num('inv_costo', 'Inv. prom. a costo', pesos, 145), num('meses_inv', 'Meses inv.', v => dec(v, 1), 105),
    num('abast', '% abastecimiento', p100, 140, 'Combinaciones tienda × item que NO estuvieron en zona roja (fuera de riesgo de agotarse), promedio de los días del mes'),
    num('agot', '% agotado', p100, 110, 'Combinaciones tienda × item CON buffer cuyo inventario fue 0 (la línea punteada de la tendencia del Control), promedio de los días del mes'),
    num('otif', 'OTIF', p100, 90, 'Líneas de OC que llegaron a tiempo Y completas, sobre las líneas con última entrada ese mes'), num('infull', '% completo', p100, 110, 'Líneas de OC cuya última entrada fue ese mes y llegaron completas'), num('ontime', '% a tiempo', p100, 110, 'Líneas de OC cuya última entrada fue ese mes y llegó en la fecha pactada'),
    num('lineas_otif', 'Líneas OC', ent, 100),
  ], [])
  const colsFilas: ColDef[] = useMemo(() => [
    { field: 'producto_id', headerName: 'SKU', width: 100, pinned: 'left', filter: true },
    { field: 'descripcion', headerName: 'Producto', width: 280, pinned: 'left', filter: true },
    { field: 'laboratorio', headerName: 'Laboratorio', width: 170, filter: true },
    { field: 'banda', headerName: 'Banda', width: 200, cellRenderer: pill, filter: true, headerTooltip: 'Según el mínimo y la meta de GMROI de Reglas de compras' },
    { field: 'abc', headerName: 'ABC', width: 75, filter: true, headerTooltip: 'Clase ABC de la Clasificación (por margen) dentro de lo filtrado' },
    num('gmroi', 'GMROI', v => dec(v), 95, 'Margen anualizado ÷ inventario promedio a costo'),
    num('margen_pct', 'Margen %', v => dec(v, 1) + ' %', 100),
    { headerName: 'Alerta', width: 250, filter: true, headerTooltip: 'Margen negativo = se vendió por debajo del costo. Casi siempre es un costo mal ingresado en Siesa (compra con valor o unidad equivocada): revísalo en la compra', valueGetter: (p: any) => p.data?.margen != null && p.data.margen < 0 ? '⚠ Margen negativo: revisa el costo en Siesa' : '', cellStyle: { color: '#c62828', fontWeight: 600 } },
    num('rot', 'Rotación', v => dec(v, 1) + '×', 100, 'Venta anual ÷ inventario promedio a costo'),
    num('meses_inv', 'Meses inv.', v => dec(v, 1), 105, 'Meses que dura el inventario promedio al ritmo de venta (a costo)'),
    num('inv_prom_costo', 'Inv. prom. a costo', pesos, 145, 'Promedio del periodo; si no hay historia de inventario, el de hoy'),
    num('inv_costo', 'Inv. hoy a costo', pesos, 135),
    num('capital_exceso', 'Sobra vs meta', pesos, 135, 'Inventario promedio a costo que sobra para llegar al GMROI meta con el mismo margen (referencia, no una orden)'),
    num('valor', 'Venta neta', pesos, 135), num('margen', 'Margen $', pesos, 125), num('cant', 'Uds vendidas', ent, 115),
    num('pct_sin_stock', '% sin stock', v => dec(v, 0) + ' %', 105, 'Días-tienda del periodo con inventario 0. Un GMROI alto con muchos días sin stock suele ser un quiebre, no eficiencia'),
  ], [])
  const colsGrupos: ColDef[] = useMemo(() => [
    { field: 'nombre', headerName: d?.grupo_nombre ?? 'Grupo', width: 240, pinned: 'left', filter: true },
    num('gmroi', 'GMROI', v => dec(v), 95), num('margen_pct', 'Margen %', v => dec(v, 1) + ' %', 100), num('meses_inv', 'Meses inv.', v => dec(v, 1), 105),
    num('inv_prom_costo', 'Inv. prom. a costo', pesos, 145), num('pct_capital', '% del capital', v => dec(v, 1) + ' %', 120, 'Parte del inventario promedio a costo total'),
    num('capital_exceso', 'Sobra vs meta', pesos, 135), num('venta', 'Venta neta', pesos, 135), num('margen', 'Margen $', pesos, 125),
    num('n', 'Productos', ent, 105), num('n_bajo', 'En banda baja', ent, 125),
  ], [d?.grupo_nombre])

  if (err) return <Alert severity="error">{err}</Alert>
  if (!op || !f) return <Box sx={{ display: 'grid', placeItems: 'center', height: '40vh' }}><CircularProgress /></Box>
  const k = d?.kpis, m = d?.meta, s: any[] = d?.serie ?? [], per = s.map(x => x.periodo)
  const filas: any[] = (d?.filas ?? []).filter((r: any) => !banda || r.banda === banda)
  const total = k ? [{ descripcion: 'Total', gmroi: k.gmroi, margen_pct: k.margen_pct, meses_inv: k.meses_inv, inv_prom_costo: k.inv_prom_costo, inv_costo: k.inv_costo, capital_exceso: k.capital_exceso, valor: k.venta, margen: k.margen }] : []
  const colorG = !k || k.gmroi == null ? undefined : k.gmroi < m.minimo ? BANDA.bajo.color : k.gmroi < m.objetivo ? '#b07d00' : BANDA.alto.color
  const maxPct = Math.max(...(d?.bandas ?? []).map((b: any) => b.pct_capital ?? 0), 1)
  const planes = [{ id: 'laboratorio', nombre: 'Laboratorio' }, ...(op.plan_categoria ? [{ id: op.plan_categoria, nombre: 'Categoría' }] : []), ...(op.plan_accion ? [{ id: op.plan_accion, nombre: 'Acción' }] : []),
    ...op.criterios.map(c => ({ id: c.plan_id, nombre: c.nombre }))]
  const recortaGmroi = m && m.desde_gmroi > m.desde
  return (
    <Box sx={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr)', gap: 1.5, pb: 3 }}>
      <Box sx={{ display: 'flex', alignItems: 'baseline', gap: 2, flexWrap: 'wrap' }}>
        <Typography variant="h5" sx={{ fontWeight: 700 }}>Indicadores de compras</Typography>
        <Typography variant="caption" color="text.secondary">{m ? `${mesLargo(m.desde)} a ${mesLargo(m.hasta)} · ${m.alcance === 'cedi' ? 'CEDI' : 'tiendas'} · GMROI con el mismo cálculo de la Clasificación` : ''}</Typography>
        {m?.calculado && <Tooltip title="Los indicadores se calculan aparte del motor y del ETL (corrida automática de reportes o este botón); el informe solo lee lo guardado."><Typography variant="caption" color="text.secondary">Calculado: {new Date(m.calculado).toLocaleString('es-CO', { dateStyle: 'medium', timeStyle: 'short' })}</Typography></Tooltip>}
        <Button size="small" variant="outlined" disabled={calculando} onClick={recalcular}>{calculando ? 'Calculando…' : 'Recalcular'}</Button>
        <Box sx={{ ml: 'auto' }}><SelectorVista modo={modo} setModo={setModo} /></Box>
      </Box>
      <BarraFiltros op={op} f={f} setF={setF} extra={
        <Tooltip placement="top" title="Tiendas: lo que venden las tiendas con su inventario y su abastecimiento (como la Clasificación y el Control). CEDI: lo que rota por el CEDI (su venta directa y lo que sale a las tiendas) con el inventario y el buffer del CEDI. El OTIF es de las órdenes de compra y no cambia.">
          <ToggleButtonGroup size="small" exclusive value={alcance} onChange={(_, v) => v && setAlcance(v)}><ToggleButton value="tiendas">Tiendas</ToggleButton><ToggleButton value="cedi">CEDI</ToggleButton></ToggleButtonGroup>
        </Tooltip>} />
      {e2 && <Alert severity="error">{e2}</Alert>}
      {m && !m.calculado && !cargando && <Alert severity="info" action={<Button color="inherit" size="small" disabled={calculando} onClick={recalcular}>{calculando ? 'Calculando…' : 'Calcular ahora'}</Button>}>Los indicadores aún no se han calculado. Se calculan solos con la corrida automática de reportes (Reglas de compras); también puedes lanzarlos ahora.</Alert>}
      {!!m?.avisos?.length && <Alert severity="warning" sx={{ py: 0 }}>No alcanzó el tiempo para calcular: {m.avisos.join(', ')}. Lo demás sí se muestra; acorta el periodo o acota con un laboratorio.</Alert>}
      {recortaGmroi && <Alert severity="info" sx={{ py: 0 }}>El GMROI y el abastecimiento solo tienen historia de inventario desde {mesLargo(m.desde_gmroi)}: los meses anteriores salen vacíos y el análisis del periodo (bandas, grupos y productos) cubre desde ese mes. El OTIF sí cubre todo el periodo.</Alert>}
      {m?.items_sin_historia > 0 && <Alert severity="info" sx={{ py: 0 }}>{ent(m.items_sin_historia)} productos no tienen historia de inventario en el periodo: para ellos el inventario promedio es el de hoy.</Alert>}
      {!!d && !d.filas.length && !cargando && <Alert severity="info">No hay productos con venta o inventario con estos filtros.</Alert>}
      <Box sx={{ display: 'flex', gap: 1.25, flexWrap: 'wrap', opacity: cargando ? .6 : 1 }}>
        <Kpi titulo="GMROI anual" valor={k ? <span style={{ color: colorG }}>{dec(k.gmroi)}</span> : '…'} sub={m ? `mínimo ${dec(m.minimo, 1)} · meta ${dec(m.objetivo, 1)}` : ''} ayuda="Margen anualizado ÷ inventario promedio a costo del periodo, sobre las sumas del filtro. Pesos de margen al año por cada peso invertido en inventario." />
        <Kpi titulo="% Abastecimiento" valor={k ? (k.abast == null ? '—' : p100(k.abast)) : '…'} ayuda="Combinaciones tienda × item que NO estuvieron en zona roja (fuera de riesgo de agotarse), promedio de los días del periodo." />
        <Kpi titulo="% Agotado" valor={k ? (k.agot == null ? '—' : p100(k.agot)) : '…'} ayuda="Combinaciones tienda × item CON buffer cuyo inventario fue 0, promedio de los días del periodo: la línea punteada de la tendencia del Control. Las «No aplica» no cuentan. Menos es mejor." />
        <Kpi titulo="OTIF (a tiempo y completo)" valor={k ? pct(k.otif, 0) : '…'} sub={k ? `${ent(k.lineas_otif)} líneas de OC` : ''} ayuda="Líneas de OC que llegaron a tiempo Y completas a la vez (no es el producto de los dos porcentajes: se mide línea por línea). Umbrales en Reglas de compras." />
        <Kpi titulo="% Completo (infull)" valor={k ? pct(k.infull, 0) : '…'} sub={k ? `${ent(k.lineas_otif)} líneas de OC` : ''} ayuda="Líneas de OC que llegaron completas (umbral en Reglas de compras)" />
        <Kpi titulo="% A tiempo (ontime)" valor={k ? pct(k.ontime, 0) : '…'} ayuda="Líneas de OC cuya última entrada llegó en la fecha pactada (días de gracia en Reglas de compras)" />
        <Kpi titulo="Inventario promedio a costo" valor={k ? MM(k.inv_prom_costo) : '…'} sub={k ? `${ent(k.n)} productos · margen anualizado ${MM(k.margen_anual)}` : ''} />
        <Kpi titulo="Capital en GMROI bajo" valor={k ? MM(k.capital_bajo) : '…'} sub={k ? `${dec(k.pct_capital_bajo, 0)} % del inventario · ${ent(k.n_bajo)} productos` : ''} ayuda="Inventario promedio a costo de los productos cuyo GMROI está por debajo del mínimo" />
        <Kpi titulo="Capital sin venta" valor={k ? MM(k.capital_sin_venta) : '…'} sub="inventario sin ninguna venta en el periodo" />
        <Kpi titulo="Sobra vs la meta" valor={k ? MM(k.capital_exceso) : '…'} sub={m ? `para llegar a GMROI ${dec(m.objetivo, 1)}` : ''} ayuda="Inventario promedio a costo que sobraría para llegar al GMROI meta con el mismo margen. Es una referencia para priorizar, no una orden de compra." />
      </Box>
      <Box sx={{ display: 'grid', gridTemplateColumns: { xs: 'minmax(0, 1fr)', lg: 'minmax(0, 1fr) minmax(0, 1fr)' }, gap: 1.5, opacity: cargando ? .6 : 1 }}>
        <Panel titulo="GMROI por mes" ayuda={m ? `Margen del mes anualizado ÷ inventario promedio a costo del mes. Mínimo ${dec(m.minimo, 1)} · meta ${dec(m.objetivo, 1)}.` : ''}>
          <LineasAnio modo={modo} periodos={per} fmt={v => dec(v)} fmtEje={v => dec(v, 1)} alto={230} series={[{ nombre: 'GMROI', color: COLOR.azul, valores: s.map(x => x.gmroi) }]} />
        </Panel>
        <Panel titulo="% de abastecimiento y % agotado por mes" ayuda="Abastecimiento: combinaciones tienda × item fuera de zona roja. Agotado: combinaciones con buffer e inventario 0 (la línea punteada del Control). Promedio de los días del mes.">
          <LineasAnio modo={modo} periodos={per} fmt={v => pct(v, 1)} fmtEje={ejePct} alto={230} techo={1} spanMin={0.1} series={[{ nombre: '% Abastecimiento', color: COLOR.violeta, valores: s.map(x => x.abast) }, { nombre: '% Agotado', color: COLOR.naranja, valores: s.map(x => x.agot) }]} />
        </Panel>
        <Panel titulo="Cumplimiento del proveedor por mes (OTIF)" ayuda="Mes de la última entrada de cada línea de OC. Completo: llegó lo pedido. A tiempo: llegó en la fecha pactada. OTIF: ambas cosas a la vez en la misma línea.">
          <LineasAnio modo={modo} periodos={per} fmt={v => pct(v, 0)} fmtEje={ejePct} alto={230} techo={1} piso={0}
            series={[{ nombre: '% Completo', color: COLOR.azul, valores: s.map(x => x.infull) }, { nombre: '% A tiempo', color: COLOR.naranja, valores: s.map(x => x.ontime) }, { nombre: 'OTIF (a tiempo y completo)', color: COLOR.aqua, valores: s.map(x => x.otif) }]} />
        </Panel>
        <Panel titulo="Margen e inventario a costo por mes" ayuda="Las dos partes del GMROI, en pesos y en el mismo eje: margen del mes e inventario promedio a costo del mes.">
          <LineasAnio modo={modo} periodos={per} fmt={v => MM(v)} fmtEje={ejeM} alto={230}
            series={[{ nombre: 'Inventario prom. a costo', color: COLOR.azul, valores: s.map(x => x.inv_costo) }, { nombre: 'Margen del mes', color: COLOR.naranja, valores: s.map(x => x.margen) }]} />
        </Panel>
      </Box>
      <Typography sx={{ fontWeight: 700, mt: 1 }}>Resumen por mes</Typography>
      <Box className="ag-theme-quartz">
        <Tabla memoria="rep_ind_mes" cargando={cargando} vacio="Sin datos en el periodo" rowData={[...s].reverse()} columnDefs={colsMes} defaultColDef={{ resizable: true, sortable: true }} domLayout="autoHeight" tooltipShowDelay={300} />
      </Box>
      <Box sx={{ display: 'grid', gridTemplateColumns: { xs: 'minmax(0, 1fr)', lg: 'minmax(0, 2fr) minmax(0, 3fr)' }, gap: 1.5, opacity: cargando ? .6 : 1, mt: 1 }}>
        <Panel titulo="Dónde está el capital" ayuda="Inventario promedio a costo del periodo por banda de GMROI. Clic en una banda para filtrar la tabla de productos.">
          <Box sx={{ display: 'grid', gap: 1 }}>
            {(d?.bandas ?? []).map((b: any) => (
              <Box key={b.banda} onClick={() => setBanda(banda === b.banda ? '' : b.banda)} sx={{ cursor: 'pointer', p: .75, borderRadius: 1, outline: banda === b.banda ? '2px solid #2b2f26' : 'none', '&:hover': { bgcolor: '#f4f6ee' } }}>
                <Box sx={{ display: 'flex', justifyContent: 'space-between', fontSize: 13, gap: 1 }}>
                  <span><span style={{ color: BANDA[b.banda].color }}>{BANDA[b.banda].icono}</span> <b>{ETQ[b.banda]}</b></span>
                  <span>{MM(b.inv_prom_costo)} · {dec(b.pct_capital, 0)} %</span>
                </Box>
                <Box sx={{ height: 10, bgcolor: '#eef1e6', borderRadius: 5, my: .5 }}><Box sx={{ height: 10, borderRadius: 5, bgcolor: BANDA[b.banda].color, width: `${Math.max(2, 100 * (b.pct_capital ?? 0) / maxPct)}%` }} /></Box>
                <Typography variant="caption" color="text.secondary">{ent(b.n)} productos{b.gmroi != null ? ` · GMROI ${dec(b.gmroi)}` : ''} · margen {MM(b.margen_anual)} al año</Typography>
              </Box>))}
          </Box>
        </Panel>
        <Panel titulo="Margen % vs rotación" ayuda="Cada punto es un producto (los 800 con más capital) en el periodo. Pasa el cursor para ver el detalle. Los márgenes por debajo de −100 % (casi siempre un costo mal ingresado en Siesa) se dibujan en el borde inferior; en la tabla de productos salen con la alerta «Margen negativo».">
          <Dispersion puntos={d?.puntos ?? []} minimo={m?.minimo ?? 1} objetivo={m?.objetivo ?? 3.2} />
        </Panel>
      </Box>
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 2, flexWrap: 'wrap', mt: 1 }}>
        <Typography sx={{ fontWeight: 700 }}>GMROI por</Typography>
        <TextField select size="small" value={agrupar} onChange={e => setAgrupar(e.target.value)} sx={{ minWidth: 200 }}>{planes.map(p => <MenuItem key={p.id} value={p.id}>{p.nombre}</MenuItem>)}</TextField>
      </Box>
      <Box className="ag-theme-quartz">
        <Tabla memoria="rep_gmroi_grupos" cargando={cargando} vacio="Sin datos con estos filtros" rowData={d?.grupos || []} columnDefs={colsGrupos} defaultColDef={{ resizable: true, sortable: true }} domLayout="autoHeight"
          pagination paginationPageSize={25} paginationPageSizeSelector={[25, 50, 100]} />
      </Box>
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 2, flexWrap: 'wrap', mt: 1 }}>
        <Typography sx={{ fontWeight: 700 }}>Productos</Typography>
        {banda && <Chip size="small" label={`Solo: ${ETQ[banda]}`} onDelete={() => setBanda('')} />}
        <Typography variant="caption" color="text.secondary">{d ? `${ent(filas.length)} filas${d.recortado ? ` de ${ent(d.total_filas)} (afina los filtros para ver el resto)` : ''} · ordenados por capital · Ctrl+A y Ctrl+C copian a Excel` : ''}</Typography>
      </Box>
      <Box className="ag-theme-quartz">
        <Tabla memoria="rep_gmroi_filas" cargando={cargando} vacio="Sin productos con estos filtros" rowData={filas} columnDefs={colsFilas} pinnedBottomRowData={banda ? [] : total}
          defaultColDef={{ resizable: true, sortable: true }} tooltipShowDelay={300} domLayout="autoHeight" pagination paginationPageSize={50} paginationPageSizeSelector={[25, 50, 100, 200]} />
      </Box>
      <Accordion variant="outlined" disableGutters sx={{ borderRadius: 2 }}>
        <AccordionSummary expandIcon={<ExpandMore />}><Typography sx={{ fontWeight: 600 }}>¿Cómo se calcula?</Typography></AccordionSummary>
        <AccordionDetails>
          <Typography variant="body2" component="div">
            <p><b>GMROI</b> = margen anualizado ÷ inventario promedio a costo = margen % × (venta anual ÷ inventario promedio a costo). Dice cuántos pesos de margen deja cada peso invertido en inventario durante un año. Es el mismo cálculo de la Clasificación (venta neta sin IVA de las tiendas, costo promedio actual, inventario promedio de la foto mensual), así que las cifras coinciden. Por mes: el margen del mes se anualiza (× 365 ÷ días del mes) y se divide por el inventario promedio del mes.</p>
            <p><b>% Abastecimiento</b> = combinaciones tienda × item que no estuvieron en zona roja del buffer, promedio de los días del mes: fuera de riesgo de agotarse. Se guarda por mes desde que existe esta pantalla; los meses anteriores que ya no conservan la foto diaria salen vacíos.</p>
            <p><b>% Agotado</b> = combinaciones tienda × item <i>con buffer</i> cuyo inventario fue 0, promedio de los días del mes (la línea punteada de la tendencia del Control). Va en paralelo al abastecimiento: la zona roja es riesgo de agotarse; agotado es estar en cero. Los meses calculados antes de esta versión salen vacíos hasta que pulses «Recalcular».</p>
            <p><b>OTIF</b> sale de las órdenes de compra: «completo» si lo recibido es al menos el % de lo pedido definido en Reglas de compras y «a tiempo» si la última entrada llegó en la fecha pactada más los días de gracia. Cada línea cuenta en el mes de su última entrada.</p>
            <p><b>Totales, grupos y meses</b> se calculan sobre sumas en pesos, no promediando el GMROI de cada producto.</p>
            <p><b>Bandas:</b> baja (por debajo del mínimo), media (entre el mínimo y la meta) y en meta; aparte, productos sin venta con inventario (capital dormido), sin inventario promedio o sin costo conocido. El mínimo y la meta se cambian en Reglas de compras.</p>
            <p><b>Sobra vs la meta</b> = inventario promedio a costo − margen anual ÷ meta. Es cuánto inventario bastaría para llegar a la meta con el mismo margen; sirve para priorizar dónde frenar compras, no es una orden.</p>
            <p><b>Cuidado:</b> el GMROI favorece a los productos de bajo margen y alta rotación, y un GMROI alto con muchos días sin stock suele ser un quiebre. Léelo junto con el % de abastecimiento y la clase ABC.</p>
          </Typography>
        </AccordionDetails>
      </Accordion>
    </Box>)
}
