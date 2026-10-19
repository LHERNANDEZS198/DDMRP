import { useEffect, useRef, useState } from 'react'
import { Box, Typography } from '@mui/material'

export type Punto = { fecha: string; n: number; tor: number; toy_aj: number; tog_aj: number; inventario: number; flujo_neto: number
  roja: number; amarilla: number; verde: number; exceso: number; con_stock?: number }
const C = { roja: '#e0584d', amarilla: '#f4d03f', verde: '#7bbf5a', exceso: '#1565c0', inv: '#111', nfp: '#d500f9' }
const fmt = (v: number) => Math.abs(v) >= 1000 ? (v / 1000).toLocaleString(undefined, { maximumFractionDigits: 1 }) + 'k' : String(Math.round(v))
const dm = (s: string) => `${s.slice(8, 10)}/${s.slice(5, 7)}`
const nice = (m: number) => { const e = Math.pow(10, Math.floor(Math.log10(m || 1))); const f = m / e; return (f <= 1 ? 1 : f <= 2 ? 2 : f <= 5 ? 5 : 10) * e }

function useAncho(): [(el: HTMLDivElement | null) => void, number] {
  const [el, setEl] = useState<HTMLDivElement | null>(null); const [w, setW] = useState(900)
  useEffect(() => {
    if (!el) return
    setW(Math.max(320, el.getBoundingClientRect().width))
    const ro = new ResizeObserver(e => setW(Math.max(320, e[0].contentRect.width))); ro.observe(el); return () => ro.disconnect()
  }, [el])
  return [setEl, w]
}

function Ejes({ n, pts, x, W, H, M, ticksY, maxY }: any) {
  const paso = Math.max(1, Math.ceil(n / Math.max(2, Math.floor((W - M.l - M.r) / 70))))
  return (<>
    {ticksY.map((t: number) => { const y = H - M.b - (t / maxY) * (H - M.t - M.b)
      return <g key={t}><line x1={M.l} x2={W - M.r} y1={y} y2={y} stroke="#e0e0e0" /><text x={M.l - 6} y={y + 4} fontSize="11" textAnchor="end" fill="#555">{t === 0 ? 0 : fmt(t)}</text></g> })}
    {pts.map((p: Punto, i: number) => i % paso === 0 && (
      <text key={p.fecha} transform={`translate(${x(i)},${H - M.b + 12}) rotate(-45)`} fontSize="11" textAnchor="end" fill="#555">{dm(p.fecha)}</text>))}
  </>)
}

/** Curva de buffer estilo DDMRP: zonas apiladas por dia (rojo/amarillo/verde) + inventario y flujo neto. */
export function BufferTrend({ serie }: { serie: Punto[] }) {
  const [ref, W] = useAncho(); const [hover, setHover] = useState<number | null>(null)
  const H = 380, M = { l: 52, r: 14, t: 12, b: 52 }
  if (!serie.length) return <Typography color="text.secondary" sx={{ p: 3 }}>Sin historia en ese rango. La historia se va guardando con cada corrida del motor.</Typography>
  const n = serie.length
  const maxY = nice(Math.max(...serie.map(p => Math.max(p.tog_aj, p.inventario, p.flujo_neto)), 1) * 1.05)
  const pw = W - M.l - M.r, ph = H - M.t - M.b
  const bw = pw / n, x = (i: number) => M.l + bw * (i + .5), y = (v: number) => H - M.b - (Math.max(v, 0) / maxY) * ph
  const ticksY = [0, 1, 2, 3, 4, 5].map(i => (maxY / 5) * i)
  const linea = (k: 'inventario' | 'flujo_neto') => serie.map((p, i) => `${x(i)},${y(p[k])}`).join(' ')
  const h = hover != null ? serie[hover] : null
  return (
    <Box ref={ref} sx={{ width: '100%', position: 'relative' }}>
      <svg width={W} height={H} onMouseLeave={() => setHover(null)}
        onMouseMove={e => { const r = (e.currentTarget as SVGElement).getBoundingClientRect(); const i = Math.floor((e.clientX - r.left - M.l) / bw); setHover(i >= 0 && i < n ? i : null) }}>
        <Ejes n={n} pts={serie} x={x} W={W} H={H} M={M} ticksY={ticksY} maxY={maxY} />
        {serie.map((p, i) => { const g = Math.max(bw * .08, .5), w = Math.max(bw - g, 1)
          return <g key={p.fecha}>
            <rect x={x(i) - w / 2} width={w} y={y(p.tor)} height={H - M.b - y(p.tor)} fill={C.roja} />
            <rect x={x(i) - w / 2} width={w} y={y(p.toy_aj)} height={Math.max(y(p.tor) - y(p.toy_aj), 0)} fill={C.amarilla} />
            <rect x={x(i) - w / 2} width={w} y={y(p.tog_aj)} height={Math.max(y(p.toy_aj) - y(p.tog_aj), 0)} fill={C.verde} />
          </g> })}
        <polyline points={linea('inventario')} fill="none" stroke={C.inv} strokeWidth="1.8" />
        <polyline points={linea('flujo_neto')} fill="none" stroke={C.nfp} strokeWidth="1.8" />
        {n <= 60 && serie.map((p, i) => <circle key={i} cx={x(i)} cy={y(p.flujo_neto)} r="2.5" fill={C.nfp} />)}
        {hover != null && <line x1={x(hover)} x2={x(hover)} y1={M.t} y2={H - M.b} stroke="#000" strokeDasharray="3 3" />}
      </svg>
      {h && (
        <Box sx={{ position: 'absolute', top: 8, left: Math.min(Math.max(x(hover!) + 10, 8), W - 210), bgcolor: 'rgba(255,255,255,.96)', border: '1px solid #bbb',
          borderRadius: 1, p: 1, fontSize: 12, pointerEvents: 'none', boxShadow: 2, minWidth: 190 }}>
          <b>{h.fecha}</b>{h.n > 1 && <span> · {h.n.toLocaleString()} combinaciones</span>}
          <div style={{ color: '#c62828' }}>Rojo (TOR): {h.tor.toLocaleString()}</div>
          <div style={{ color: '#b8860b' }}>Amarillo (TOY aj.): {h.toy_aj.toLocaleString()}</div>
          <div style={{ color: '#2e7d32' }}>Verde (TOG aj.): {h.tog_aj.toLocaleString()}</div>
          <div><b>Inventario:</b> {h.inventario.toLocaleString()}</div>
          <div style={{ color: C.nfp }}><b>Flujo neto:</b> {h.flujo_neto.toLocaleString()}</div>
        </Box>)}
      <Box sx={{ display: 'flex', gap: 2, justifyContent: 'center', flexWrap: 'wrap', fontSize: 12, mt: .5 }}>
        {[['Zona verde', C.verde], ['Zona amarilla', C.amarilla], ['Zona roja', C.roja]].map(([l, c]) => <span key={l}><span style={{ display: 'inline-block', width: 10, height: 10, borderRadius: 5, background: c, marginRight: 4 }} />{l}</span>)}
        <span><span style={{ display: 'inline-block', width: 16, height: 3, background: C.inv, marginRight: 4, verticalAlign: 'middle' }} />Inventario</span>
        <span><span style={{ display: 'inline-block', width: 16, height: 3, background: C.nfp, marginRight: 4, verticalAlign: 'middle' }} />Flujo neto</span>
      </Box>
    </Box>)
}

/** Semáforo en el tiempo: % de combinaciones en cada zona por día, como áreas apiladas al 100% (rojo abajo, azul/exceso arriba),
 *  y la línea punteada "Disponible" = % de combinaciones con inventario > 0. */
export function ZonaShare({ serie }: { serie: Punto[] }) {
  const [ref, W] = useAncho(); const [hover, setHover] = useState<number | null>(null); const [modo, setModo] = useState<'apilado' | 'cambio'>('apilado')
  const H = 300, M = { l: 52, r: 14, t: 8, b: 48 }
  if (serie.length < 1) return null
  const n = serie.length, pw = W - M.l - M.r, ph = H - M.t - M.b
  const bw = pw / n, x = (i: number) => (n === 1 ? M.l + pw / 2 : M.l + (pw * i) / (n - 1)), ypc = (f: number) => H - M.b - f * ph
  const zonas = ['roja', 'amarilla', 'verde', 'exceso'] as const
  const paso = Math.max(1, Math.ceil(n / Math.max(2, Math.floor(pw / 70))))
  const h = hover != null ? serie[hover] : null
  // frontera acumulada de cada zona por dia (0..1)
  const acum = serie.map(p => { let a = 0; return zonas.map(z => (a += p[z] / (p.n || 1))) })
  const area = (k: number) => {
    const sup = serie.map((_, i) => `${x(i)},${ypc(acum[i][k])}`)
    const inf = serie.map((_, i) => `${x(i)},${ypc(k === 0 ? 0 : acum[i][k - 1])}`).reverse()
    return [...sup, ...inf].join(' ')
  }
  const hayDisp = serie.length > 0   // Disponible = todas las zonas menos la roja
  // modo "cambio": puntos porcentuales de cada zona frente al primer dia, con el eje ajustado a lo que realmente se mueve
  const pc = (p: Punto, z: typeof zonas[number] | 'disp') => ((z === 'disp' ? p.n - p.roja : p[z]) / (p.n || 1)) * 100
  const ser = [...zonas, ...(hayDisp ? ['disp' as const] : [])]
  const delta = ser.map(z => serie.map(p => pc(p, z) - pc(serie[0], z)))
  const dmax = Math.max(0.5, ...delta.flat().map(Math.abs)), lim = Math.ceil(dmax * 1.15 * 2) / 2
  const yd = (v: number) => M.t + ph / 2 - (v / lim) * (ph / 2)
  const colS = (z: string) => (z === 'disp' ? '#000' : C[z as keyof typeof C])
  const disp = serie.map((p, i) => `${x(i)},${ypc((p.n - p.roja) / (p.n || 1))}`).join(' ')
  return (
    <Box ref={ref} sx={{ width: '100%', position: 'relative' }}>
      <Box sx={{ display: 'flex', gap: 1, fontSize: 12, mb: .5, alignItems: 'center' }}>Vista:
        {([['apilado', 'Participación (100%)'], ['cambio', 'Cambio vs. primer día (puntos %)']] as const).map(([m, l]) =>
          <span key={m} onClick={() => setModo(m)} style={{ cursor: 'pointer', padding: '2px 8px', borderRadius: 10, border: '1px solid #999', background: modo === m ? '#2e7d32' : '#fff', color: modo === m ? '#fff' : '#333' }}>{l}</span>)}
      </Box>
      <svg width={W} height={H} onMouseLeave={() => setHover(null)}
        onMouseMove={e => { const r = (e.currentTarget as SVGElement).getBoundingClientRect(); const f = (e.clientX - r.left - M.l) / (n === 1 ? pw : pw / (n - 1)); const i = Math.round(f); setHover(i >= 0 && i < n && e.clientX - r.left > M.l - 6 ? i : null) }}>
        {modo === 'cambio' && [-lim, -lim / 2, 0, lim / 2, lim].map(t => <g key={t}><line x1={M.l} x2={W - M.r} y1={yd(t)} y2={yd(t)} stroke={t === 0 ? '#888' : '#e0e0e0'} /><text x={M.l - 6} y={yd(t) + 4} fontSize="11" textAnchor="end" fill="#555">{t > 0 ? '+' : ''}{t.toFixed(1)}</text></g>)}
        {modo === 'cambio' && ser.map((z, k) => <polyline key={z} points={serie.map((_, i) => `${x(i)},${yd(delta[k][i])}`).join(' ')} fill="none" stroke={colS(z)} strokeWidth="2.2" strokeDasharray={z === 'disp' ? '6 4' : undefined} />)}
        {modo === 'cambio' && ser.map((z, k) => serie.map((_, i) => <circle key={z + i} cx={x(i)} cy={yd(delta[k][i])} r="3" fill={colS(z)} />))}
        {modo === 'apilado' && [0, 20, 40, 60, 80, 100].map(t => { const y = ypc(t / 100)
          return <g key={t}><line x1={M.l} x2={W - M.r} y1={y} y2={y} stroke="#e0e0e0" /><text x={M.l - 6} y={y + 4} fontSize="11" textAnchor="end" fill="#555">{t}%</text></g> })}
        {modo === 'apilado' && (n === 1
          ? zonas.map((z, k) => { const lo = k === 0 ? 0 : acum[0][k - 1], hi = acum[0][k]
              return <rect key={z} x={M.l} width={pw} y={ypc(hi)} height={Math.max(ypc(lo) - ypc(hi), 0)} fill={C[z]} /> })
          : zonas.map((z, k) => <polygon key={z} points={area(k)} fill={C[z]} />))}
        {modo === 'apilado' && hayDisp && n > 1 && <polyline points={disp} fill="none" stroke="#000" strokeWidth="2" strokeDasharray="6 4" />}
        {modo === 'apilado' && hayDisp && n === 1 && <line x1={M.l} x2={W - M.r} y1={ypc((serie[0].n - serie[0].roja) / (serie[0].n || 1))} y2={ypc((serie[0].n - serie[0].roja) / (serie[0].n || 1))} stroke="#000" strokeWidth="2" strokeDasharray="6 4" />}
        {serie.map((p, i) => i % paso === 0 && <text key={p.fecha} transform={`translate(${x(i)},${H - M.b + 12}) rotate(-45)`} fontSize="11" textAnchor="end" fill="#555">{dm(p.fecha)}</text>)}
        {hover != null && <line x1={x(hover)} x2={x(hover)} y1={M.t} y2={H - M.b} stroke="#000" strokeDasharray="3 3" />}
      </svg>
      {h && <Box sx={{ position: 'absolute', top: 4, left: Math.min(Math.max(x(hover!) + 10, 8), W - 210), bgcolor: 'rgba(255,255,255,.96)', border: '1px solid #bbb', borderRadius: 1, p: 1, fontSize: 12, pointerEvents: 'none', boxShadow: 2, minWidth: 190 }}>
        <b>{h.fecha}</b> · {h.n.toLocaleString()} combinaciones
        {(['exceso', 'verde', 'amarilla', 'roja'] as const).map(z => <div key={z} style={{ color: z === 'amarilla' ? '#b8860b' : C[z] }}>{z === 'exceso' ? 'AZUL (exceso)' : z.toUpperCase()}: {h[z].toLocaleString()} ({((h[z] / (h.n || 1)) * 100).toFixed(1)}%)</div>)}
        <div><b>Disponible:</b> {(((h.n - h.roja) / (h.n || 1)) * 100).toFixed(1)}% (todo menos zona roja)</div>
      </Box>}
      <Box sx={{ display: 'flex', gap: 2, justifyContent: 'center', flexWrap: 'wrap', fontSize: 12, mt: .5 }}>
        {[['Rojo', C.roja], ['Amarillo', C.amarilla], ['Verde', C.verde], ['Azul (exceso)', C.exceso]].map(([l, c]) => <span key={l}><span style={{ display: 'inline-block', width: 10, height: 10, borderRadius: 2, background: c, marginRight: 4 }} />{l}</span>)}
        {hayDisp && <span><span style={{ display: 'inline-block', width: 18, borderTop: '2px dashed #000', marginRight: 4, verticalAlign: 'middle' }} />Disponible (% fuera de zona roja)</span>}
      </Box>
    </Box>)
}
