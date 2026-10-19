import { useEffect, useMemo, useState } from 'react'
import { ColDef, ICellRendererParams } from 'ag-grid-community'
import { Alert, Autocomplete, Box, Button, Chip, MenuItem, Paper, TextField, Tooltip, Typography } from '@mui/material'
import Tabla from '../Tabla'
import { api, bajar } from '../api'

const COLOR_ABC: Record<string, string> = { A: '#2e7d32', B: '#f9a825', C: '#9e9e9e', N: '#1565c0', D: '#6d4c41', S: '#8e24aa' }
const NOMBRE_ABC: Record<string, string> = {
  A: 'Importantes: juntan el primer 80 % del criterio', B: 'Intermedios: hasta el 95 %', C: 'Cola: el resto (incluye margen ≤ 0)',
  N: 'Nuevos: primera venta reciente, aún sin historia', D: 'Sin venta en la ventana (mira su inventario a costo)', S: 'Sin costo en Siesa: no se puede calcular margen',
}
const COP = (v: any) => v == null ? '' : '$' + Math.round(v).toLocaleString('es-CO')
const NUM = (v: any) => v == null ? '' : Math.round(v).toLocaleString('es-CO')
const M = (v: number) => Math.abs(v) >= 1e6 ? (v / 1e6).toLocaleString('es-CO', { maximumFractionDigits: 1 }) + ' M' : NUM(v)
const pill = (p: ICellRendererParams) => p.value == null ? '' :
  <Chip size="small" label={p.value} sx={{ height: 20, fontSize: 11, color: '#fff', bgcolor: COLOR_ABC[String(p.value)[0]] ?? '#999' }} />

export default function Clasificacion() {
  const [nivel, setNivel] = useState('item'); const [criterio, setCriterio] = useState('margen'); const [meses, setMeses] = useState(12)
  const [corteA, setCorteA] = useState(80); const [corteB, setCorteB] = useState(95)
  const [empresa, setEmpresa] = useState<string[]>([]); const [bodegas, setBodegas] = useState<string[]>([]); const [labs, setLabs] = useState<string[]>([])
  const [plan, setPlan] = useState(''); const [crit, setCrit] = useState<string[]>([]); const [q, setQ] = useState(''); const [qd, setQd] = useState('')
  const [abc, setAbc] = useState<string[]>([]); const [xyz, setXyz] = useState<string[]>([])
  const [opc, setOpc] = useState<any>({ tiendas: [], laboratorios: [], empresas: [], criterios: [] })
  const [d, setD] = useState<any>(null)
  const [cargando, setCargando] = useState(false); const [err, setErr] = useState(''); const [bajando, setBajando] = useState(false)

  useEffect(() => { api('/control/filtros').then(setOpc).catch(e => setErr(e.message)) }, [])
  useEffect(() => { const t = setTimeout(() => setQ(qd), 400); return () => clearTimeout(t) }, [qd])
  const base = () => {
    const p = new URLSearchParams({ nivel, criterio, meses: String(meses), corte_a: String(corteA), corte_b: String(corteB) })
    if (empresa.length) p.set('empresa', empresa.join(',')); if (bodegas.length) p.set('bodegas', bodegas.join(',')); if (labs.length) p.set('labs', labs.join(','))
    if (q.trim()) p.set('q', q.trim()); if (plan && crit.length) p.set('crit', crit.map(v => `${plan}:${v}`).join(','))
    return p
  }
  const claveBase = base().toString()
  const salida = () => { const p = new URLSearchParams(); if (abc.length) p.set('abc', abc.join(',')); if (xyz.length) p.set('xyz', xyz.join(',')); return p.toString() }
  const valido = corteA > 0 && corteA < corteB && corteB <= 100
  useEffect(() => {
    if (!valido) return
    let vivo = true; setCargando(true); setErr('')
    api(`/clasificacion?limit=5000&${claveBase}&${salida()}`).then(r => vivo && setD(r)).catch(e => vivo && setErr(e.message)).finally(() => vivo && setCargando(false))
    return () => { vivo = false }
  }, [claveBase, abc.join(), xyz.join()])
  const excel = async () => { setBajando(true); try { await bajar(`/clasificacion/excel?${claveBase}&${salida()}`, 'clasificacion.xlsx') } catch (e: any) { setErr(e.message) } finally { setBajando(false) } }

  const celda = (a: string, x: string) => d?.matriz.celdas.find((c: any) => c.abc === a && c.xyz === x)
  const tot = d?.matriz.total
  const nl = (c: string) => opc.laboratorios.find((l: any) => l.codigo === c)?.nombre
  const nt = (id: string) => opc.tiendas.find((t: any) => t.bodega_id === id)?.nombre
  const valores = opc.criterios.find((p: any) => p.plan_id === plan)?.valores ?? []
  const alternar = (arr: string[], set: (v: string[]) => void, v: string) => set(arr.includes(v) ? arr.filter(x => x !== v) : [...arr, v])

  const cols: ColDef[] = useMemo(() => [
    { field: 'puesto', headerName: '#', width: 75, pinned: 'left', type: 'numericColumn' },
    { field: 'clase', headerName: 'Clase', width: 90, pinned: 'left', cellRenderer: pill, filter: true, headerTooltip: 'ABC por el criterio elegido + XYZ por variabilidad (IV)' },
    { field: 'clase_global', headerName: 'Clase global', width: 115, cellRenderer: pill, filter: true, headerTooltip: 'Clase que tendría con todo lo que puedes ver, sin los filtros de pantalla' },
    ...(nivel === 'tienda_item' ? [{ field: 'bodega_id', headerName: 'Tienda', width: 90, filter: true } as ColDef] : []),
    { field: 'producto_id', headerName: 'Item', width: 100, filter: true },
    { field: 'descripcion', headerName: 'Descripción', width: 280, filter: true },
    { field: 'laboratorio', headerName: 'Lab.', width: 90, filter: true },
    { field: 'valor', headerName: 'Venta neta $', type: 'numericColumn', width: 130, valueFormatter: p => COP(p.value) },
    { field: 'margen', headerName: 'Margen $', type: 'numericColumn', width: 125, valueFormatter: p => COP(p.value), cellStyle: p => (p.value ?? 0) < 0 ? { color: '#c62828' } : null },
    { field: 'margen_pct', headerName: 'Margen %', type: 'numericColumn', width: 105, valueFormatter: p => p.value == null ? '' : Number(p.value).toFixed(1) + '%' },
    { field: 'pct_acum', headerName: '% acum.', type: 'numericColumn', width: 95, valueFormatter: p => p.value == null ? '' : Number(p.value).toFixed(1) + '%' },
    { field: 'cant', headerName: 'Unidades', type: 'numericColumn', width: 100, valueFormatter: p => NUM(p.value) },
    { field: 'inventario', headerName: 'Inventario', type: 'numericColumn', width: 105, valueFormatter: p => NUM(p.value) },
    { field: 'inv_costo', headerName: 'Inv. a costo $', type: 'numericColumn', width: 135, valueFormatter: p => COP(p.value) },
    { field: 'gmroi', headerName: 'GMROI', type: 'numericColumn', width: 95, valueFormatter: p => p.value == null ? '' : Number(p.value).toFixed(2), headerTooltip: 'Margen anualizado / inventario a costo' },
    { field: 'dias_inv', headerName: 'Días inv.', type: 'numericColumn', width: 100, valueFormatter: p => NUM(p.value) },
    { field: 'iv', headerName: 'IV', type: 'numericColumn', width: 80, valueFormatter: p => p.value == null ? '' : Number(p.value).toFixed(2) },
    { field: 'costo', headerName: 'Costo unit.', type: 'numericColumn', width: 115, valueFormatter: p => COP(p.value) },
  ], [nivel])

  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', height: '100%', gap: 1.5, minHeight: 600 }}>
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
        <Typography variant="h6" sx={{ fontWeight: 700, flex: 1 }}>Clasificación de items · ABC × XYZ</Typography>
        <Button size="small" variant="outlined" disabled={bajando || !valido} onClick={excel}>{bajando ? 'Generando…' : 'Descargar Excel'}</Button>
      </Box>
      {d?.meta.sin_valor && <Alert severity="warning" sx={{ flexShrink: 0 }}>Las ventas aún no traen el valor en pesos: actualiza el esquema y corre “Traer ventas por mes” (o el ETL) para llenarlo. Mientras tanto el ABC por margen/venta no es confiable.</Alert>}
      <Paper variant="outlined" sx={{ flexShrink: 0, p: 1.25, display: 'flex', flexWrap: 'wrap', gap: 1, alignItems: 'center' }}>
        <TextField select size="small" label="Clasificar" value={nivel} onChange={e => setNivel(e.target.value)} sx={{ width: 200 }}>
          <MenuItem value="item">Por item (suma de lo filtrado)</MenuItem><MenuItem value="tienda_item">Por tienda × item</MenuItem></TextField>
        <TextField select size="small" label="ABC según" value={criterio} onChange={e => setCriterio(e.target.value)} sx={{ width: 210 }}>
          <MenuItem value="margen">Margen bruto $ (recomendado)</MenuItem><MenuItem value="venta">Venta neta $ (sin IVA)</MenuItem><MenuItem value="costo">Consumo a costo $</MenuItem></TextField>
        <TextField select size="small" label="Ventana" value={meses} onChange={e => setMeses(Number(e.target.value))} sx={{ width: 120 }}>
          {[3, 6, 9, 12].map(m => <MenuItem key={m} value={m}>{m} meses</MenuItem>)}</TextField>
        <Tooltip title="A = lo que junta hasta este % acumulado del criterio"><TextField size="small" type="number" label="Corte A %" value={corteA} onChange={e => setCorteA(Number(e.target.value))} error={!valido} sx={{ width: 100 }} /></Tooltip>
        <Tooltip title="B = hasta este % acumulado; el resto es C"><TextField size="small" type="number" label="Corte B %" value={corteB} onChange={e => setCorteB(Number(e.target.value))} error={!valido} sx={{ width: 100 }} /></Tooltip>
        <Autocomplete multiple size="small" limitTags={1} sx={{ minWidth: 170, flex: '1 1 170px' }} options={opc.empresas} value={empresa}
          getOptionLabel={(o: string) => o === '05' ? 'Funat (05)' : o === '21' ? 'Stores (21)' : o} onChange={(_, v) => setEmpresa(v)} renderInput={p => <TextField {...p} label="Empresa" />} />
        <Autocomplete multiple size="small" limitTags={2} sx={{ minWidth: 230, flex: '2 1 230px' }} options={opc.tiendas.map((t: any) => t.bodega_id)} value={bodegas}
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
      {!valido && <Typography color="error" variant="body2">Los cortes deben cumplir 0 &lt; A &lt; B ≤ 100.</Typography>}
      {err && <Typography color="error" variant="body2">{err}</Typography>}

      {d && <Paper variant="outlined" sx={{ flexShrink: 0, p: 1.25, overflow: 'auto' }}>
        <Typography variant="caption" color="text.secondary">
          {d.meta.criterio_nombre} · ventana {String(d.meta.desde).slice(0, 10)} a {String(d.meta.hasta).slice(0, 10)} · XYZ por IV del motor (X &lt; {d.meta.cortes_iv[0]}, Y hasta {d.meta.cortes_iv[1]}, Z mayor) · clic en una celda o en una clase para filtrar la lista
        </Typography>
        <Box component="table" sx={{ borderCollapse: 'collapse', mt: .5, width: '100%', '& td, & th': { border: '1px solid #e0e0e0', px: 1.25, py: .5, fontSize: 13, textAlign: 'right' } }}>
          <thead><tr><th style={{ textAlign: 'left' }}>Clase</th>
            {['X', 'Y', 'Z'].map(x => <th key={x}>{x} · {x === 'X' ? 'estable' : x === 'Y' ? 'media' : 'variable'}</th>)}
            <th>Items</th><th>Venta neta</th><th>Margen</th><th>Inv. a costo</th></tr></thead>
          <tbody>
            {['A', 'B', 'C', 'N', 'D', 'S'].map(a => {
              const t = d.matriz.por_abc.find((x: any) => x.abc === a); if (!t) return null
              return (<tr key={a}>
                <th style={{ textAlign: 'left' }}><Tooltip title={NOMBRE_ABC[a]}><Chip size="small" clickable label={a} onClick={() => alternar(abc, setAbc, a)} variant={abc.includes(a) ? 'filled' : 'outlined'}
                  sx={{ bgcolor: abc.includes(a) ? COLOR_ABC[a] : undefined, color: abc.includes(a) ? '#fff' : COLOR_ABC[a], borderColor: COLOR_ABC[a], fontWeight: 700 }} /></Tooltip></th>
                {['X', 'Y', 'Z'].map(x => {
                  const c = celda(a, x); const act = abc.includes(a) && xyz.includes(x)
                  return <td key={x} style={{ cursor: c ? 'pointer' : 'default', background: act ? 'rgba(110,138,55,.25)' : c ? 'rgba(110,138,55,.06)' : undefined }}
                    onClick={() => { if (!c) return; setAbc([a]); setXyz([x]) }}>{c ? c.n.toLocaleString() : '·'}</td>
                })}
                <td style={{ fontWeight: 700 }}>{t.n.toLocaleString()}</td><td>{M(t.venta)}</td><td style={{ color: t.margen < 0 ? '#c62828' : undefined }}>{M(t.margen)}</td><td>{M(t.inv_costo)}</td>
              </tr>)
            })}
            <tr><th style={{ textAlign: 'left' }}>Total</th><td colSpan={3}></td><td style={{ fontWeight: 700 }}>{tot.n.toLocaleString()}</td><td>{M(tot.venta)}</td><td>{M(tot.margen)}</td><td>{M(tot.inv_costo)}</td></tr>
          </tbody>
        </Box>
        {(abc.length > 0 || xyz.length > 0) && <Box sx={{ mt: 1, display: 'flex', gap: 1, alignItems: 'center' }}>
          <Typography variant="caption">Lista filtrada a:</Typography>
          {abc.map(a => <Chip key={a} size="small" label={`ABC ${a}`} onDelete={() => setAbc(abc.filter(x => x !== a))} />)}
          {xyz.map(x => <Chip key={x} size="small" label={`XYZ ${x}`} onDelete={() => setXyz(xyz.filter(y => y !== x))} />)}
          <Button size="small" onClick={() => { setAbc([]); setXyz([]) }}>Quitar</Button>
        </Box>}
      </Paper>}

      <Typography variant="caption" color="text.secondary">{d ? (d.truncado ? `Mostrando ${d.filas.length.toLocaleString()} de ${d.total.toLocaleString()}; filtra por clase o baja el Excel` : `${d.total.toLocaleString()} filas`) : ''}</Typography>
      <Box className="ag-theme-quartz" sx={{ flex: 1, minHeight: 320 }}>
        <Tabla textoCargando="Clasificando…" vacio="Sin resultados con estos filtros" key={nivel} rowData={d?.filas ?? []} columnDefs={cols} cargando={cargando} defaultColDef={{ resizable: true, sortable: true }} />
      </Box>
    </Box>)
}
