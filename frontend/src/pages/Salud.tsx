import { useEffect, useMemo, useState } from 'react'
import { ColDef, ICellRendererParams } from 'ag-grid-community'
import { Alert, Autocomplete, Box, Button, Card, CardActionArea, Chip, MenuItem, Paper, TextField, Tooltip, Typography } from '@mui/material'
import Tabla from '../Tabla'
import { api, bajar } from '../api'
import { bodegasDeEmpresa, colsCobertura, tiendasDeEmpresa } from '../filtros'
import { useEmpresa } from '../Empresa'
import { ayudar } from '../ayuda'

const COLOR_ABC: Record<string, string> = { I: '#1565c0', A: '#2e7d32', B: '#f9a825', C: '#9e9e9e', N: '#00acc1', D: '#6d4c41', S: '#8e24aa' }
const TIPS: Record<string, string> = {
  diag: 'Qué hacer primero con esta tienda × item: cruza la zona del buffer de hoy (rojo, amarillo, verde, sobrestock) con la importancia del item (clase ABC × XYZ). Ya incluye la zona.',
  bodega_id: 'Código de la tienda.', producto_id: 'Referencia del producto.', descripcion: 'Nombre del producto en Siesa.',
  pct_buffer: 'Dónde está el flujo neto dentro del buffer: 0 % = vacío, 100 % = tope verde (TOG). Por encima de 100 % hay sobrestock.',
  clase: 'ABC (cuánto aporta según el criterio elegido) + XYZ (qué tan predecible es su venta, por el IV del motor). Ej.: AY = aporta mucho, venta media.',
  puesto: 'Puesto en el ranking ABC del criterio elegido (1 = el que más aporta).',
  inventario: 'Unidades disponibles hoy en la tienda.',
  sugerido: 'Unidades que sugiere el motor enviar hoy a la tienda (con mínimos, redondeo y el inventario del CEDI).',
  dias_inv: 'Inventario promedio ÷ venta diaria promedio de la ventana: para cuántos días alcanza el stock.',
  inv_costo: 'Inventario de hoy × costo promedio actual: el dinero parado en stock.',
  margen: 'Venta neta − unidades × costo en la ventana elegida.',
  gmroi: 'Margen anualizado ÷ inventario PROMEDIO a costo: pesos de margen por cada peso invertido en stock en un año. Bajo 1 no cubre lo invertido.',
  laboratorio: 'Código del laboratorio (plan 006 de Siesa).',
}
const COP = (v: any) => v == null ? '' : '$' + Math.round(v).toLocaleString('es-CO')
const NUM = (v: any) => v == null ? '' : Math.round(v).toLocaleString('es-CO')
const M = (v: number) => Math.abs(v) >= 1e6 ? (v / 1e6).toLocaleString('es-CO', { maximumFractionDigits: 1 }) + ' M' : NUM(v)

export default function Salud() {
  const [criterio, setCriterio] = useState('margen'); const [meses, setMeses] = useState(12)
  const { lista: empresa } = useEmpresa(); const setEmpresa = (_: string[]) => {}; const [bodegas, setBodegas] = useState<string[]>([]); const [labs, setLabs] = useState<string[]>([])
  const [plan, setPlan] = useState(''); const [crit, setCrit] = useState<string[]>([]); const [q, setQ] = useState(''); const [qd, setQd] = useState('')
  const [zonas, setZonas] = useState<string[]>([]); const [diag, setDiag] = useState<string[]>([])
  const [opc, setOpc] = useState<any>({ tiendas: [], laboratorios: [], empresas: [], criterios: [] })
  const [d, setD] = useState<any>(null)
  const [cargando, setCargando] = useState(false); const [err, setErr] = useState(''); const [bajando, setBajando] = useState(false)

  useEffect(() => { api('/control/filtros').then(setOpc).catch(e => setErr(e.message)) }, [])
  useEffect(() => { const t = setTimeout(() => setQ(qd), 400); return () => clearTimeout(t) }, [qd])
  const qs = () => {
    const p = new URLSearchParams({ criterio, meses: String(meses) })
    if (empresa.length) p.set('empresa', empresa.join(',')); if (bodegas.length) p.set('bodegas', bodegas.join(',')); if (labs.length) p.set('labs', labs.join(','))
    if (q.trim()) p.set('q', q.trim()); if (plan && crit.length) p.set('crit', crit.map(v => `${plan}:${v}`).join(','))
    if (zonas.length) p.set('zonas', zonas.join(',')); if (diag.length) p.set('diag', diag.join(','))
    return p.toString()
  }
  const clave = qs()
  useEffect(() => {
    let vivo = true; setCargando(true); setErr('')
    api(`/salud?limit=5000&${clave}`).then(r => vivo && setD(r)).catch(e => vivo && setErr(e.message)).finally(() => vivo && setCargando(false))
    return () => { vivo = false }
  }, [clave])
  const excel = async () => { setBajando(true); try { await bajar(`/salud/excel?${clave}`, 'salud_inventario.xlsx') } catch (e: any) { setErr(e.message) } finally { setBajando(false) } }
  const nl = (c: string) => opc.laboratorios.find((l: any) => l.codigo === c)?.nombre
  const nt = (id: string) => opc.tiendas.find((t: any) => t.bodega_id === id)?.nombre
  const valores = opc.criterios.find((p: any) => p.plan_id === plan)?.valores ?? []
  const etq = (k: string) => d?.resumen.find((r: any) => r.diag === k)

  const cols: ColDef[] = useMemo(() => ([
    { field: 'diag', headerName: 'Atender', width: 190, pinned: 'left', filter: true, valueGetter: p => etq(p.data?.diag)?.etiqueta ?? p.data?.diag,
      cellRenderer: (p: ICellRendererParams) => p.value == null ? '' : <Chip size="small" label={p.value} sx={{ height: 20, fontSize: 11, color: '#fff', bgcolor: etq(p.data.diag)?.color ?? '#999' }} /> },
    { field: 'empresa', headerName: 'Emp.', width: 70, filter: true, headerTooltip: 'Empresa (05 Funat, 21 Stores): el CEDI PT001 existe en las dos, y cada una tiene su propia fila.' },
    { field: 'bodega_id', headerName: 'Tienda', width: 90, filter: true },
    { field: 'producto_id', headerName: 'Item', width: 100, filter: true },
    { field: 'descripcion', headerName: 'Descripción', width: 260, filter: true },
    { field: 'pct_buffer', headerName: '% buffer', type: 'numericColumn', width: 95, valueFormatter: p => p.value == null ? '' : Number(p.value).toFixed(0) + '%' },
    { field: 'clase', headerName: 'Clase', width: 80, filter: true, cellRenderer: (p: ICellRendererParams) => p.value == null ? '' :
      <Chip size="small" label={p.value} sx={{ height: 20, fontSize: 11, color: '#fff', bgcolor: COLOR_ABC[String(p.value)[0]] ?? '#999' }} /> },
    { field: 'puesto', headerName: 'Ranking', type: 'numericColumn', width: 90 },
    { field: 'inventario', headerName: 'Inventario', type: 'numericColumn', width: 105, valueFormatter: p => NUM(p.value) },
    { field: 'sobran', headerName: 'Sobran (u.)', type: 'numericColumn', width: 105, valueFormatter: p => p.value ? NUM(p.value) : '', cellStyle: { color: '#1565c0', fontWeight: 600 }, headerTooltip: 'Unidades por encima del tope verde ajustado (TOG aj.) en las tiendas en sobrestock.' },
    { field: 'faltan', headerName: 'Faltan (u.)', type: 'numericColumn', width: 105, valueFormatter: p => p.value ? NUM(p.value) : '', cellStyle: { color: '#c62828', fontWeight: 600 }, headerTooltip: 'Unidades que separan el flujo neto del tope verde ajustado (TOG aj.) cuando NO hay sobrestock. Es la distancia al tope, no el sugerido del motor (que además aplica mínimos, redondeo y el inventario del CEDI).' },
    { field: 'rotacion', headerName: 'Rotación (uds/mes)', type: 'numericColumn', width: 150, valueFormatter: p => p.value == null ? '' : Number(p.value).toLocaleString('es-CO', { maximumFractionDigits: 1 }), headerTooltip: 'Unidades vendidas por mes en promedio en la ventana.' },
    ...colsCobertura(),
    { field: 'sugerido', headerName: 'Sugerido', type: 'numericColumn', width: 100, valueFormatter: p => NUM(p.value) },
    { field: 'dias_inv', headerName: 'Días inv.', type: 'numericColumn', width: 100, valueFormatter: p => NUM(p.value) },
    { field: 'inv_costo', headerName: 'Inv. a costo $', type: 'numericColumn', width: 135, valueFormatter: p => COP(p.value) },
    { field: 'margen', headerName: 'Margen $', type: 'numericColumn', width: 120, valueFormatter: p => COP(p.value), cellStyle: p => (p.value ?? 0) < 0 ? { color: '#c62828' } : null },
    { field: 'gmroi', headerName: 'GMROI', type: 'numericColumn', width: 90, valueFormatter: p => p.value == null ? '' : Number(p.value).toFixed(2) },
    { field: 'laboratorio', headerName: 'Lab.', width: 90, filter: true },
  ] as ColDef[]).map(c => c.headerTooltip || !TIPS[c.field as string] ? c : { ...c, headerTooltip: TIPS[c.field as string] }), [d?.resumen])

  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', height: '100%', gap: 1.5, minHeight: 600 }}>
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
        <Typography variant="h6" sx={{ fontWeight: 700, flex: 1 }}>Salud del inventario</Typography>
        <Button size="small" variant="outlined" disabled={bajando} onClick={excel}>{bajando ? 'Generando…' : 'Descargar Excel'}</Button>
      </Box>
      <Typography variant="caption" color="text.secondary" sx={{ mt: -1 }}>Cruza la zona del buffer de hoy con la importancia del item (clase ABC × XYZ): qué reponer primero, dónde sobra y dónde hay capital dormido.</Typography>
      {d?.meta.sin_valor && <Alert severity="warning" sx={{ flexShrink: 0 }}>Las ventas aún no traen el valor en pesos: corre “Traer ventas por mes” para que el ABC por margen sea confiable.</Alert>}

      <Box sx={{ display: 'grid', flexShrink: 0, gridTemplateColumns: { xs: 'repeat(2, 1fr)', md: 'repeat(4, 1fr)', xl: 'repeat(7, 1fr)' }, gap: 1 }}>
        {(d?.resumen ?? []).map((r: any) => {
          const act = diag.includes(r.diag)
          return (
            <Tooltip key={r.diag} title={r.ayuda} placement="top">
              <Card variant="outlined" sx={{ borderLeft: `6px solid ${r.color}`, outline: act ? `2px solid ${r.color}` : 'none' }}>
                <CardActionArea sx={{ p: 1.25 }} onClick={() => setDiag(a => act ? a.filter(x => x !== r.diag) : [...a, r.diag])}>
                  <Typography variant="caption" color="text.secondary">{r.etiqueta}</Typography>
                  <Typography variant="h6" sx={{ fontWeight: 700, lineHeight: 1.2 }}>{r.n.toLocaleString()}</Typography>
                  <Typography variant="caption" color="text.secondary">inv. a costo {M(r.inv_costo)}</Typography>
                </CardActionArea>
              </Card>
            </Tooltip>)
        })}
      </Box>

      <Paper variant="outlined" sx={{ flexShrink: 0, p: 1.25, display: 'flex', flexWrap: 'wrap', gap: 1, alignItems: 'center' }}>
        <TextField select size="small" label="ABC según" value={criterio} onChange={e => setCriterio(e.target.value)} sx={{ width: 210 }}>
          <MenuItem value="margen">Margen bruto $ (recomendado)</MenuItem><MenuItem value="venta">Venta neta $ (sin IVA)</MenuItem><MenuItem value="costo">Consumo a costo $</MenuItem></TextField>
        <TextField select size="small" label="Ventana" value={meses} onChange={e => setMeses(Number(e.target.value))} sx={{ width: 120 }}>
          {[3, 6, 9, 12].map(m => <MenuItem key={m} value={m}>{m} meses</MenuItem>)}</TextField>
        <TextField select size="small" label="Zona hoy" value={zonas} onChange={e => setZonas(typeof e.target.value === 'string' ? e.target.value.split(',').filter(Boolean) : e.target.value)}
          slotProps={{ select: { multiple: true } }} sx={{ width: 150 }}>
          {['ROJA', 'AMARILLA', 'VERDE', 'EXCESO'].map(z => <MenuItem key={z} value={z}>{z}</MenuItem>)}</TextField>
        <Autocomplete multiple size="small" limitTags={2} sx={{ minWidth: 230, flex: '2 1 230px' }} options={tiendasDeEmpresa(opc.tiendas, empresa).map((t: any) => t.bodega_id)} value={bodegas}
          getOptionLabel={(o: string) => nt(o) ? `${o} · ${nt(o)}` : o} onChange={(_, v) => setBodegas(v)} renderInput={p => <TextField {...p} label="Tienda" />} />
        <Autocomplete multiple size="small" limitTags={2} sx={{ minWidth: 230, flex: '2 1 230px' }} options={opc.laboratorios.map((l: any) => l.codigo)} value={labs}
          getOptionLabel={(o: string) => nl(o) ? `${o} · ${nl(o)}` : o} onChange={(_, v) => setLabs(v)} renderInput={p => <TextField {...p} label="Laboratorio" />} />
        {opc.criterios.length > 0 && <>
          <TextField select size="small" label="Criterio de items" value={plan} onChange={e => { setPlan(e.target.value); setCrit([]) }} sx={{ minWidth: 190 }} slotProps={{ select: { displayEmpty: true }, inputLabel: { shrink: true } }}>
            <MenuItem value="">(elige un criterio)</MenuItem>{opc.criterios.map((p: any) => <MenuItem key={p.plan_id} value={p.plan_id}>{p.nombre}</MenuItem>)}</TextField>
          {plan && <Autocomplete multiple size="small" limitTags={2} sx={{ minWidth: 220, flex: '2 1 220px' }} options={valores.map((v: any) => v.id)} value={crit}
            getOptionLabel={(o: string) => valores.find((v: any) => v.id === o)?.nombre ?? o} onChange={(_, v) => setCrit(v)} renderInput={p => <TextField {...p} label="Valores" />} />}
        </>}
        <TextField size="small" label="Item (código o nombre)" value={qd} onChange={e => setQd(e.target.value)} sx={{ minWidth: 190, flex: '1 1 190px' }} />
      </Paper>
      {err && <Typography color="error" variant="body2">{err}</Typography>}
      <Typography variant="caption" color="text.secondary">{d ? (d.truncado ? `Mostrando ${d.filas.length.toLocaleString()} de ${d.total.toLocaleString()} (en orden de atención); filtra o baja el Excel` : `${d.total.toLocaleString()} tienda × item`) : ''}</Typography>
      <Box className="ag-theme-quartz" sx={{ flex: 1, minHeight: 320 }}>
        <Tabla textoCargando="Calculando…" vacio="Sin resultados con estos filtros" rowData={d?.filas ?? []} columnDefs={ayudar(cols)} tooltipShowDelay={300} cargando={cargando} defaultColDef={{ resizable: true, sortable: true }} />
      </Box>
    </Box>)
}
