import { useEffect, useMemo, useState } from 'react'
import { Alert, Autocomplete, Box, Card, Checkbox, Chip, FormControlLabel, Table, TableBody, TableCell, TableHead, TableRow, TextField, Tooltip, Typography } from '@mui/material'
import { api } from '../api'
import { tiendasDeEmpresa } from '../filtros'
import { useEmpresa } from '../Empresa'
import Calculando from '../Calculando'
import { Apilado, Barras, corto } from '../Graficos'

const COP = (v: number | null | undefined) => v == null ? '–' : '$' + Math.round(v).toLocaleString('es-CO')
const NUM = (v: number | null | undefined, d = 0) => v == null ? '–' : Number(v).toLocaleString('es-CO', { maximumFractionDigits: d })
const PCT = (v: number | null | undefined) => v == null ? '–' : v.toLocaleString('es-CO', { maximumFractionDigits: 1 }) + '%'
const mesActual = () => { const d = new Date(); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}` }
const mesAtras = (n: number) => { const d = new Date(); d.setDate(1); d.setMonth(d.getMonth() - n); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}` }
const etq = (m: string) => `${['ene', 'feb', 'mar', 'abr', 'may', 'jun', 'jul', 'ago', 'sep', 'oct', 'nov', 'dic'][Number(m.slice(4)) - 1]} ${m.slice(2, 4)}`
const CLASE_COLOR: Record<string, string> = { A: '#2e7d32', B: '#f9a825', C: '#9e9e9e' }

function Kpi({ titulo, valor, sub, color = '#6e8a37', ayuda }: { titulo: string; valor: string; sub?: string; color?: string; ayuda?: string }) {
  return (
    <Tooltip title={ayuda ?? ''} placement="top"><Card variant="outlined" sx={{ borderLeft: `6px solid ${color}`, p: 1.25 }}>
      <Typography variant="caption" color="text.secondary">{titulo}</Typography>
      <Typography variant="h6" sx={{ fontWeight: 700, lineHeight: 1.2 }}>{valor}</Typography>
      {sub && <Typography variant="caption" color="text.secondary">{sub}</Typography>}
    </Card></Tooltip>)
}

/** Barra del buffer que sugiere el modelo (TOR rojo · hasta TOY amarillo · hasta TOG verde) contra el inventario actual. */
function BufferModelo({ b, inv, costo }: { b: { tor: number; toy: number; tog: number }; inv: number; costo: boolean }) {
  const max = Math.max(b.tog, inv, 1), f = costo ? COP : (v: number) => NUM(v)
  const p = (v: number) => `${Math.max(0, Math.min(100, (v / max) * 100))}%`
  return (
    <Box sx={{ mb: 1.5 }}>
      <Typography variant="caption" sx={{ fontWeight: 700 }}>{costo ? 'En pesos (a costo)' : 'En unidades'}</Typography>
      <Box sx={{ position: 'relative', height: 26, bgcolor: '#eceff1', borderRadius: .5, overflow: 'hidden', mt: .5 }}>
        <Box sx={{ position: 'absolute', left: 0, width: p(b.tor), top: 0, bottom: 0, bgcolor: '#e0584d' }} />
        <Box sx={{ position: 'absolute', left: p(b.tor), width: `calc(${p(b.toy)} - ${p(b.tor)})`, top: 0, bottom: 0, bgcolor: '#f4d03f' }} />
        <Box sx={{ position: 'absolute', left: p(b.toy), width: `calc(${p(b.tog)} - ${p(b.toy)})`, top: 0, bottom: 0, bgcolor: '#7bbf5a' }} />
        <Tooltip title={`Inventario actual: ${f(inv)}`}><Box sx={{ position: 'absolute', left: p(inv), top: -2, bottom: -2, width: 3, bgcolor: '#111' }} /></Tooltip>
      </Box>
      <Box sx={{ display: 'flex', gap: 2, flexWrap: 'wrap', fontSize: 12, mt: .5 }}>
        <span><b style={{ color: '#e0584d' }}>Tope rojo (TOR)</b> {f(b.tor)}</span>
        <span><b style={{ color: '#b8860b' }}>Tope amarillo (TOY aj)</b> {f(b.toy)}</span>
        <span><b style={{ color: '#4a8a2e' }}>Tope verde (TOG aj)</b> {f(b.tog)}</span>
        <span><b>▎Inventario hoy</b> {f(inv)}</span>
      </Box>
    </Box>)
}

export default function Tienda() {
  const { lista: emp } = useEmpresa()
  const [opc, setOpc] = useState<any>({ tiendas: [], laboratorios: [], ejecucion: null })
  const [bodega, setBodega] = useState<string>(() => { try { return localStorage.getItem('tienda_sel') || '' } catch { return '' } })
  const [labs, setLabs] = useState<string[]>([])
  const [desde, setDesde] = useState(mesAtras(11)); const [hasta, setHasta] = useState(mesActual())
  const [comparar, setComparar] = useState(true)
  const [d, setD] = useState<any>(null); const [cargando, setCargando] = useState(false); const [err, setErr] = useState('')
  useEffect(() => { api('/control/filtros').then(setOpc).catch(e => setErr(e.message)) }, [])
  const tiendas = useMemo(() => tiendasDeEmpresa(opc.tiendas, emp), [opc.tiendas, emp.join()])
  const tiendaSel = tiendas.find((t: any) => t.bodega_id === bodega) ?? null
  const empresaT = tiendaSel ? (String(tiendaSel.empresa || '').split(',').find((e: string) => !emp.length || emp.includes(e)) || String(tiendaSel.empresa || '').split(',')[0]) : ''
  const valido = !!tiendaSel && !!empresaT && !!desde && !!hasta && desde <= hasta
  useEffect(() => {
    if (!valido) { setD(null); return }
    let vivo = true; setCargando(true); setErr('')
    const q = new URLSearchParams({ bodega, empresa: empresaT, desde: desde.replace('-', ''), hasta: hasta.replace('-', ''), comparar: String(comparar) })
    if (labs.length) q.set('labs', labs.join(','))
    api('/tienda?' + q.toString()).then(r => vivo && setD(r)).catch(e => vivo && setErr(e.message)).finally(() => vivo && setCargando(false))
    return () => { vivo = false }
  }, [bodega, empresaT, desde, hasta, labs.join(), comparar])
  const elegir = (t: any) => { const b = t?.bodega_id ?? ''; setBodega(b); try { localStorage.setItem('tienda_sel', b) } catch { /* sin almacenamiento */ } }
  const k = d?.kpi, s: any[] = d?.serie ?? [], et = s.map(x => etq(x.mes))
  const hay = (f: string) => s.some(x => x[f] != null)
  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1.5, pb: 3 }}>
      <Calculando activo={cargando} texto="Armando la vista de la tienda" />
      {opc.ejecucion && <Typography variant="caption" color="text.secondary" sx={{ mb: -1 }}>
        Info actualizada: {String(opc.ejecucion.fin ?? opc.ejecucion.fecha_calculo).replace('T', ' ').slice(0, 16)} · corte del motor {String(opc.ejecucion.fecha_calculo).slice(0, 10)}</Typography>}
      <Typography variant="h6" sx={{ fontWeight: 700 }}>Tienda · ventas, margen, inventario y buffer{tiendaSel ? ` · ${tiendaSel.bodega_id} ${tiendaSel.nombre ?? ''}` : ''}</Typography>
      <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap', alignItems: 'center' }}>
        <Autocomplete size="small" sx={{ minWidth: 280, flex: '2 1 280px' }} options={tiendas} value={tiendaSel} onChange={(_, v) => elegir(v)}
          getOptionLabel={(t: any) => `${t.bodega_id} · ${t.nombre ?? ''}${t.clase ? ` [${t.clase}]` : ''}`} isOptionEqualToValue={(a: any, b: any) => a.bodega_id === b.bodega_id}
          renderInput={p => <TextField {...p} label="Tienda" />} />
        <Autocomplete multiple size="small" limitTags={2} sx={{ minWidth: 240, flex: '2 1 240px' }} options={(opc.laboratorios ?? []).map((l: any) => l.codigo)} value={labs} onChange={(_, v) => setLabs(v)}
          getOptionLabel={(c: string) => { const l = (opc.laboratorios ?? []).find((x: any) => x.codigo === c); return l?.nombre ? `${c} · ${l.nombre}` : c }}
          renderInput={p => <TextField {...p} label="Laboratorio" />} />
        <TextField size="small" type="month" label="Desde" value={desde} onChange={e => setDesde(e.target.value)} InputLabelProps={{ shrink: true }} sx={{ width: 160 }} />
        <TextField size="small" type="month" label="Hasta" value={hasta} onChange={e => setHasta(e.target.value)} InputLabelProps={{ shrink: true }} sx={{ width: 160 }} />
        <FormControlLabel control={<Checkbox size="small" checked={comparar} onChange={e => setComparar(e.target.checked)} />} label="Comparar" />
      </Box>
      {err && <Alert severity="error" onClose={() => setErr('')}>{err}</Alert>}
      {!tiendaSel && <Alert severity="info">Elige una tienda para ver sus ventas, margen, inventario y buffer. Las ventas están por mes; el inventario y las zonas tienen historia diaria.</Alert>}
      {d && k && <>
        <Box sx={{ display: 'grid', gridTemplateColumns: { xs: 'repeat(2, 1fr)', md: 'repeat(4, 1fr)', lg: 'repeat(6, 1fr)' }, gap: 1.25 }}>
          <Kpi titulo="Venta neta" valor={COP(k.venta)} sub={comparar && k.var_venta_pct != null ? `${k.var_venta_pct >= 0 ? '▲' : '▼'} ${PCT(Math.abs(k.var_venta_pct))} vs. año anterior` : `${NUM(k.unidades)} unidades`} color={k.var_venta_pct != null && k.var_venta_pct < 0 ? '#c62828' : '#2e7d32'} />
          <Kpi titulo="Margen" valor={COP(k.margen)} sub={`${PCT(k.margen_pct)} de la venta`} ayuda={d.nota} />
          <Kpi titulo="Rot. Promedio" valor={`${NUM(k.rot_promedio, 1)} u/mes`} sub="unidades vendidas por mes en el periodo" color="#00838f" ayuda="Unidades vendidas por mes en promedio durante el periodo elegido (igual que Rot. Promedio de Clasificación)." />
          <Kpi titulo="Inventario hoy (a costo)" valor={COP(k.inv_costo_hoy)} sub={`${NUM(k.inv_unidades_hoy)} u. · ${k.dias_inventario != null ? NUM(k.dias_inventario) + ' días' : '–'}`} color="#1565c0" ayuda="Inventario de la última corrida a costo promedio. Días = inventario ÷ venta diaria del periodo." />
          <Kpi titulo="GMROI" valor={k.gmroi != null ? NUM(k.gmroi, 2) : '–'} sub={`rotación inv. ${k.rotacion_mes != null ? NUM(k.rotacion_mes, 2) : '–'} veces/mes`} color="#6a1b9a" ayuda="Margen anualizado ÷ inventario promedio a costo del periodo." />
          <Kpi titulo="Buffer hoy" valor={`${NUM(k.hoy.roja)} rojo · ${NUM(k.hoy.amarilla)} amarillo`} sub={`${NUM(k.hoy.verde)} verde · ${NUM(k.hoy.exceso)} exceso · ${NUM(k.hoy.agotado)} agotados`} color="#e0584d" />
        </Box>

        <Card variant="outlined" sx={{ p: 1.5 }}>
          <Typography variant="subtitle2" sx={{ fontWeight: 700, mb: .5 }}>Lo que sugiere el modelo para esta tienda hoy: topes del buffer vs. inventario</Typography>
          <BufferModelo b={k.buffer} inv={k.inv_unidades_hoy} costo={false} />
          <BufferModelo b={{ tor: k.buffer.tor_costo, toy: k.buffer.toy_costo, tog: k.buffer.tog_costo }} inv={k.inv_costo_hoy} costo />
          <Typography variant="body2">Para llegar al tope verde el modelo sugiere pedir <b>{NUM(k.sugerido_hoy)} u.</b> ({COP(k.sugerido_costo_hoy)} a costo). Suma de los topes de todos los ítems de la tienda (con el filtro de laboratorio).</Typography>
        </Card>

        <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', lg: '1fr 1fr' }, gap: 2 }}>
          <Card variant="outlined" sx={{ p: 1.5 }}><Barras titulo="Ventas en pesos" etiquetas={et} fmt={corto}
            series={[{ nombre: 'Venta', valores: s.map(x => x.venta), color: '#6e8a37', tipo: 'barra' },
              ...(comparar && hay('venta_ant') ? [{ nombre: 'Mismo mes año anterior', valores: s.map(x => x.venta_ant), color: '#9e9e9e', tipo: 'linea' as const, punteada: true }] : []),
              ...(comparar && hay('venta_clase') ? [{ nombre: `Promedio tiendas clase ${d.comparativo.clase ?? ''}`, valores: s.map(x => x.venta_clase), color: '#1565c0', tipo: 'linea' as const, punteada: true }] : [])]} /></Card>
          <Card variant="outlined" sx={{ p: 1.5 }}><Barras titulo="Ventas en unidades" etiquetas={et} fmt={v => NUM(v)}
            series={[{ nombre: 'Unidades', valores: s.map(x => x.unidades), color: '#00838f', tipo: 'barra' },
              ...(comparar && hay('unidades_ant') ? [{ nombre: 'Mismo mes año anterior', valores: s.map(x => x.unidades_ant), color: '#9e9e9e', tipo: 'linea' as const, punteada: true }] : []),
              ...(comparar && hay('unidades_clase') ? [{ nombre: `Promedio tiendas clase ${d.comparativo.clase ?? ''}`, valores: s.map(x => x.unidades_clase), color: '#1565c0', tipo: 'linea' as const, punteada: true }] : [])]} /></Card>
          <Card variant="outlined" sx={{ p: 1.5 }}><Barras titulo="Margen en pesos y % de margen" etiquetas={et} fmt={corto}
            series={[{ nombre: 'Margen $', valores: s.map(x => x.margen), color: '#2e7d32', tipo: 'barra' },
              ...(comparar && hay('margen_ant') ? [{ nombre: 'Margen año anterior', valores: s.map(x => x.margen_ant), color: '#9e9e9e', tipo: 'linea' as const, punteada: true }] : [])]} />
            <Typography variant="caption" color="text.secondary">Margen % por mes: {s.map(x => `${etq(x.mes)} ${PCT(x.margen_pct)}`).join(' · ')}</Typography></Card>
          <Card variant="outlined" sx={{ p: 1.5 }}><Barras titulo="Inventario promedio del mes (a costo)" etiquetas={et} fmt={corto}
            series={[{ nombre: 'Inventario a costo', valores: s.map(x => x.inv_costo), color: '#1565c0', tipo: 'barra' }]} />
            <Typography variant="caption" color="text.secondary">% de días sin stock por mes: {s.map(x => `${etq(x.mes)} ${PCT(x.pct_sin_stock)}`).join(' · ')}</Typography></Card>
          <Card variant="outlined" sx={{ p: 1.5 }}><Barras titulo="GMROI y rotación del inventario" etiquetas={et} fmt={v => v.toLocaleString('es-CO', { maximumFractionDigits: 2 })}
            series={[{ nombre: 'GMROI (anualizado)', valores: s.map(x => x.gmroi), color: '#6a1b9a', tipo: 'barra' }, { nombre: 'Rotación (veces/mes)', valores: s.map(x => x.rotacion), color: '#ef6c00', tipo: 'linea' }]} /></Card>
          <Card variant="outlined" sx={{ p: 1.5 }}>{d.zonas.length
            ? <Apilado titulo="Zonas del buffer por día (cuántos ítems en cada zona)" fechas={d.zonas.map((z: any) => z.fecha)}
              capas={[{ nombre: 'Rojo', color: '#e0584d', valores: d.zonas.map((z: any) => z.roja) }, { nombre: 'Amarillo', color: '#f4d03f', valores: d.zonas.map((z: any) => z.amarilla) },
                { nombre: 'Verde', color: '#7bbf5a', valores: d.zonas.map((z: any) => z.verde) }, { nombre: 'Exceso', color: '#1565c0', valores: d.zonas.map((z: any) => z.exceso) }]} />
            : <Typography variant="body2" color="text.secondary">Sin historia diaria del buffer en ese periodo para esta tienda.</Typography>}
            {d.zonas.length > 0 && <Typography variant="caption" color="text.secondary">Agotados el último día: {NUM(d.zonas[d.zonas.length - 1].agotado)} de {NUM(d.zonas[d.zonas.length - 1].n - d.zonas[d.zonas.length - 1].no_aplica)} ítems con buffer</Typography>}</Card>
        </Box>

        <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', lg: '1fr 1fr' }, gap: 2 }}>
          <Card variant="outlined" sx={{ p: 1.5, overflow: 'auto' }}>
            <Typography variant="subtitle2" sx={{ fontWeight: 700 }}>Laboratorios (Pareto por margen)</Typography>
            <Table size="small"><TableHead><TableRow>{['Clase', 'Laboratorio', 'Ítems', 'Venta $', 'Margen $', 'Margen %', 'Rot. Prom. (u/mes)', '% acum.'].map(h => <TableCell key={h} sx={{ fontWeight: 700 }} align={h === 'Laboratorio' || h === 'Clase' ? 'left' : 'right'}>{h}</TableCell>)}</TableRow></TableHead>
              <TableBody>{d.labs.map((g: any) => <TableRow key={g.laboratorio}>
                <TableCell><Chip size="small" label={g.clase} sx={{ height: 20, bgcolor: CLASE_COLOR[g.clase], color: '#fff' }} /></TableCell>
                <TableCell>{g.laboratorio}{g.nombre ? ` · ${g.nombre}` : ''}</TableCell><TableCell align="right">{NUM(g.items)}</TableCell><TableCell align="right">{COP(g.venta)}</TableCell>
                <TableCell align="right">{COP(g.margen)}</TableCell><TableCell align="right">{PCT(g.margen_pct)}</TableCell><TableCell align="right">{NUM(g.rot_promedio, 1)}</TableCell><TableCell align="right">{PCT(g.pct_acum)}</TableCell></TableRow>)}</TableBody></Table>
          </Card>
          <Card variant="outlined" sx={{ p: 1.5, overflow: 'auto' }}>
            <Typography variant="subtitle2" sx={{ fontWeight: 700 }}>Top 20 ítems por margen</Typography>
            <Table size="small"><TableHead><TableRow>{['Clase', 'Ítem', 'Descripción', 'Venta $', 'Margen $', 'Margen %', 'Rot. Prom. (u/mes)'].map(h => <TableCell key={h} sx={{ fontWeight: 700 }} align={['Venta $', 'Margen $', 'Margen %', 'Rot. Prom. (u/mes)'].includes(h) ? 'right' : 'left'}>{h}</TableCell>)}</TableRow></TableHead>
              <TableBody>{d.top_items.map((it: any) => <TableRow key={it.producto_id}>
                <TableCell><Chip size="small" label={it.clase} sx={{ height: 20, bgcolor: CLASE_COLOR[it.clase], color: '#fff' }} /></TableCell>
                <TableCell>{it.producto_id}</TableCell><TableCell sx={{ maxWidth: 240 }}>{it.descripcion}</TableCell><TableCell align="right">{COP(it.venta)}</TableCell>
                <TableCell align="right">{COP(it.margen)}</TableCell><TableCell align="right">{PCT(it.margen_pct)}</TableCell><TableCell align="right">{NUM(it.rot_promedio, 1)}</TableCell></TableRow>)}</TableBody></Table>
            {d.peores_items.length > 0 && <>
              <Typography variant="subtitle2" sx={{ fontWeight: 700, mt: 1.5 }}>Ítems que no dejan margen</Typography>
              <Table size="small"><TableBody>{d.peores_items.map((it: any) => <TableRow key={it.producto_id}><TableCell>{it.producto_id}</TableCell><TableCell sx={{ maxWidth: 240 }}>{it.descripcion}</TableCell>
                <TableCell align="right">{COP(it.venta)}</TableCell><TableCell align="right" sx={{ color: '#c62828' }}>{COP(it.margen)}</TableCell></TableRow>)}</TableBody></Table></>}
          </Card>
        </Box>
        <Typography variant="caption" color="text.secondary">{d.nota}</Typography>
      </>}
    </Box>)
}
