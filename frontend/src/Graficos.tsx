import { useEffect, useState } from 'react'
import { Box, Typography } from '@mui/material'

/** Gráficos SVG livianos (sin librerías) para la vista por tienda: barras agrupadas con líneas encima, y áreas apiladas en el tiempo. */

function useAncho(): [(el: HTMLDivElement | null) => void, number] {
  const [el, setEl] = useState<HTMLDivElement | null>(null); const [w, setW] = useState(600)
  useEffect(() => {
    if (!el) return
    const ro = new ResizeObserver(e => setW(Math.max(280, Math.floor(e[0].contentRect.width))))
    ro.observe(el); setW(Math.max(280, Math.floor(el.clientWidth)))
    return () => ro.disconnect()
  }, [el])
  return [setEl, w]
}

const nice = (m: number) => { if (m <= 0) return 1; const e = Math.pow(10, Math.floor(Math.log10(m))); const f = m / e; return (f <= 1 ? 1 : f <= 2 ? 2 : f <= 5 ? 5 : 10) * e }
export const corto = (v: number) => { const a = Math.abs(v); const s = v < 0 ? '-' : ''
  return a >= 1e9 ? s + (a / 1e9).toLocaleString('es-CO', { maximumFractionDigits: 1 }) + ' MM' : a >= 1e6 ? s + (a / 1e6).toLocaleString('es-CO', { maximumFractionDigits: 1 }) + ' M' : a >= 1e3 ? s + (a / 1e3).toLocaleString('es-CO', { maximumFractionDigits: 1 }) + ' k' : s + Math.round(a).toLocaleString('es-CO') }

function Globo({ x, w, titulo, filas }: { x: number; w: number; titulo: string; filas: { nombre: string; color: string; valor: string }[] }) {
  const izq = x > w / 2
  return <div style={{ position: 'absolute', top: 4, left: izq ? undefined : x + 12, right: izq ? w - x + 12 : undefined, pointerEvents: 'none', zIndex: 5, background: 'rgba(33,33,33,.93)', color: '#fff', borderRadius: 6, padding: '6px 9px', fontSize: 12, lineHeight: 1.45, boxShadow: '0 2px 8px rgba(0,0,0,.3)', whiteSpace: 'nowrap' }}>
    <div style={{ fontWeight: 700, marginBottom: 2 }}>{titulo}</div>
    {filas.map(f => <div key={f.nombre}><span style={{ display: 'inline-block', width: 9, height: 9, borderRadius: 2, background: f.color, marginRight: 6 }} />{f.nombre}: <b>{f.valor}</b></div>)}
  </div>
}

export type Serie = { nombre: string; valores: (number | null | undefined)[]; color: string; tipo: 'barra' | 'linea'; punteada?: boolean }

function Leyenda({ items }: { items: { nombre: string; color: string; punteada?: boolean }[] }) {
  return <Box sx={{ display: 'flex', gap: 1.5, flexWrap: 'wrap', mb: .5 }}>{items.map(i => (
    <Box key={i.nombre} sx={{ display: 'flex', alignItems: 'center', gap: .5, fontSize: 12 }}>
      <Box sx={{ width: 14, height: i.punteada ? 0 : 8, borderRadius: .5, bgcolor: i.punteada ? 'transparent' : i.color, borderTop: i.punteada ? `2px dashed ${i.color}` : undefined }} />{i.nombre}</Box>))}</Box>
}

export function Barras({ titulo, etiquetas, series, fmt = corto, alto = 230 }: { titulo: string; etiquetas: string[]; series: Serie[]; fmt?: (v: number) => string; alto?: number }) {
  const [ref, w] = useAncho(); const [hv, setHv] = useState<number | null>(null)
  const L = 54, R = 10, T = 8, B = 26, W = w - L - R, H = alto - T - B
  const vals = series.flatMap(s => s.valores.map(v => v ?? 0))
  const max = nice(Math.max(...vals, 0)), min = Math.min(...vals, 0) < 0 ? -nice(-Math.min(...vals)) : 0
  const y = (v: number) => T + H - ((v - min) / (max - min || 1)) * H
  const barras = series.filter(s => s.tipo === 'barra'), n = etiquetas.length, paso = W / Math.max(n, 1)
  const bw = Math.max(2, Math.min(28, (paso * 0.8) / Math.max(barras.length, 1)))
  const cada = Math.max(1, Math.ceil(n / Math.max(2, Math.floor(W / 44))))
  return (
    <Box><Typography variant="subtitle2" sx={{ fontWeight: 700 }}>{titulo}</Typography>
      <Leyenda items={series} />
      <div ref={ref} style={{ width: '100%', position: 'relative' }}>
        {hv != null && <Globo x={L + paso * hv + paso / 2} w={w} titulo={etiquetas[hv]} filas={series.map(s => ({ nombre: s.nombre, color: s.color, valor: s.valores[hv] == null ? '–' : fmt(s.valores[hv] as number) }))} />}
        <svg width={w} height={alto} role="img" aria-label={titulo} onMouseLeave={() => setHv(null)}
          onMouseMove={e => { const r = e.currentTarget.getBoundingClientRect(); const i = Math.floor((e.clientX - r.left - L) / paso); setHv(i >= 0 && i < n ? i : null) }}>
          {hv != null && <rect x={L + paso * hv} y={T} width={paso} height={H} fill="#000" opacity={.07} />}
          {[0, 1, 2, 3, 4].map(i => { const v = min + (max - min) * i / 4; return <g key={i}><line x1={L} x2={w - R} y1={y(v)} y2={y(v)} stroke="#e0e0e0" /><text x={L - 6} y={y(v) + 4} fontSize={11} textAnchor="end" fill="#666">{fmt(v)}</text></g> })}
          {etiquetas.map((e, i) => i % cada === 0 && <text key={i} x={L + paso * i + paso / 2} y={alto - 8} fontSize={11} textAnchor="middle" fill="#666">{e}</text>)}
          {barras.map((s, k) => s.valores.map((v, i) => v == null ? null :
            <rect key={s.nombre + i} x={L + paso * i + (paso - bw * barras.length) / 2 + bw * k} y={Math.min(y(v), y(0))} width={bw - 1} height={Math.abs(y(v) - y(0))} fill={s.color} rx={1}></rect>))}
          {series.filter(s => s.tipo === 'linea').map(s => {
            const pts = s.valores.map((v, i) => v == null ? null : [L + paso * i + paso / 2, y(v)] as [number, number])
            const d = pts.map((p, i) => p ? `${pts[i - 1] ? 'L' : 'M'}${p[0]},${p[1]}` : '').join(' ')
            return <g key={s.nombre}><path d={d} fill="none" stroke={s.color} strokeWidth={2} strokeDasharray={s.punteada ? '5 4' : undefined} />
              {pts.map((p, i) => p && <circle key={i} cx={p[0]} cy={p[1]} r={3} fill={s.color}></circle>)}</g>
          })}
        </svg>
      </div>
    </Box>)
}

export type Capa = { nombre: string; valores: number[]; color: string }

export function Apilado({ titulo, fechas, capas, alto = 230 }: { titulo: string; fechas: string[]; capas: Capa[]; alto?: number }) {
  const [ref, w] = useAncho(); const [hv, setHv] = useState<number | null>(null)
  const L = 44, R = 10, T = 8, B = 26, W = w - L - R, H = alto - T - B, n = fechas.length
  const tot = fechas.map((_, i) => capas.reduce((a, c) => a + (c.valores[i] || 0), 0))
  const max = nice(Math.max(...tot, 1))
  const x = (i: number) => L + (n > 1 ? (W * i) / (n - 1) : W / 2), y = (v: number) => T + H - (v / max) * H
  const base = fechas.map(() => 0)
  const areas = capas.map(c => {
    const arriba = c.valores.map((v, i) => base[i] + (v || 0))
    const d = `M${x(0)},${y(base[0])} ` + arriba.map((v, i) => `L${x(i)},${y(v)}`).join(' ') + ' ' + base.map((_, i) => `L${x(n - 1 - i)},${y(base[n - 1 - i])}`).join(' ') + 'Z'
    arriba.forEach((v, i) => { base[i] = v })
    return { c, d }
  })
  const marcas = Array.from({ length: Math.min(6, n) }, (_, k) => Math.round((k * (n - 1)) / Math.max(1, Math.min(6, n) - 1)))
  return (
    <Box><Typography variant="subtitle2" sx={{ fontWeight: 700 }}>{titulo}</Typography>
      <Leyenda items={capas} />
      <div ref={ref} style={{ width: '100%', position: 'relative' }}>
        {hv != null && <Globo x={x(hv)} w={w} titulo={`${fechas[hv]} · total ${tot[hv].toLocaleString('es-CO')}`} filas={[...capas].reverse().map(c => ({ nombre: c.nombre, color: c.color, valor: (c.valores[hv] || 0).toLocaleString('es-CO') }))} />}
        <svg width={w} height={alto} role="img" aria-label={titulo} onMouseLeave={() => setHv(null)}
          onMouseMove={e => { const r = e.currentTarget.getBoundingClientRect(); const i = n > 1 ? Math.round(((e.clientX - r.left - L) / W) * (n - 1)) : 0; setHv(i >= 0 && i < n ? i : null) }}>
          {[0, 1, 2, 3, 4].map(i => { const v = (max * i) / 4; return <g key={i}><line x1={L} x2={w - R} y1={y(v)} y2={y(v)} stroke="#e0e0e0" /><text x={L - 6} y={y(v) + 4} fontSize={11} textAnchor="end" fill="#666">{Math.round(v).toLocaleString('es-CO')}</text></g> })}
          {areas.map(a => <path key={a.c.nombre} d={a.d} fill={a.c.color} opacity={.9} />)}
          {hv != null && <line x1={x(hv)} x2={x(hv)} y1={T} y2={T + H} stroke="#111" strokeDasharray="3 3" />}
          {marcas.map(i => <text key={i} x={x(i)} y={alto - 8} fontSize={11} textAnchor="middle" fill="#666">{fechas[i]?.slice(5)}</text>)}
        </svg>
      </div>
    </Box>)
}
