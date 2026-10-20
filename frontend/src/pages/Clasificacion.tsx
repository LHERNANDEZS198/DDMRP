import { useEffect, useMemo, useState } from 'react'
import { ColDef, ICellRendererParams } from 'ag-grid-community'
import { Alert, Autocomplete, Box, Button, Checkbox, Chip, Collapse, Dialog, DialogActions, DialogContent, DialogTitle, FormControlLabel, IconButton, MenuItem, Paper, Snackbar, TextField, Tooltip, Typography } from '@mui/material'
import Close from '@mui/icons-material/Close'
import ExpandLess from '@mui/icons-material/ExpandLess'
import ExpandMore from '@mui/icons-material/ExpandMore'
import SaveOutlined from '@mui/icons-material/SaveOutlined'
import DeleteOutline from '@mui/icons-material/DeleteOutline'
import Tabla from '../Tabla'
import { CampoSelect } from '../Campos'
import HelpOutline from '@mui/icons-material/HelpOutline'
import { api, bajar } from '../api'
import { confirmar } from '../alertas'
import { GuiaClasificacion } from '../guias'

const COLOR_ABC: Record<string, string> = { A: '#2e7d32', B: '#f9a825', C: '#9e9e9e', N: '#1565c0', D: '#6d4c41', S: '#8e24aa' }
const NOMBRE_ABC: Record<string, string> = {
  A: 'Importantes: juntan el primer 80 % del criterio', B: 'Intermedios: hasta el 95 %', C: 'Cola: el resto (incluye margen ≤ 0)',
  N: 'Nuevos: primera venta reciente, aún sin historia', D: 'Sin venta en las tiendas en la ventana (lo que el CEDI vende a wholesale o canales digitales no cuenta aquí). Mira su inventario a costo', S: 'Sin costo en Siesa: no se puede calcular margen',
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
  const [fc, setFc] = useState<{ plan: string; vals: string[] }[]>([{ plan: '', vals: [] }])   // filtros por criterio de items: planes distintos se combinan (Y), valores del mismo plan (O)
  const [agrupar, setAgrupar] = useState(''); const [dentro, setDentro] = useState(false); const [soloCon, setSoloCon] = useState(false)   // soloCon: excluir items sin valor en los criterios elegidos
     // vista por dentro de un criterio; dentro = ABC recalculado en cada grupo
  const [q, setQ] = useState(''); const [qd, setQd] = useState('')
  const [abc, setAbc] = useState<string[]>([]); const [xyz, setXyz] = useState<string[]>([])
  const [opc, setOpc] = useState<any>({ tiendas: [], laboratorios: [], empresas: [], criterios: [] })
  const [d, setD] = useState<any>(null)
  const [cargando, setCargando] = useState(false); const [err, setErr] = useState(''); const [bajando, setBajando] = useState(false)
  const [guia, setGuia] = useState(false)
  const [verFiltros, setVerFiltros] = useState(() => { try { return localStorage.getItem('clas_filtros') !== '0' } catch { return true } })
  const cambiarFiltros = (v: boolean) => { setVerFiltros(v); try { localStorage.setItem('clas_filtros', v ? '1' : '0') } catch { /* sin almacenamiento */ } }
  const nActivos = [soloCon && (agrupar || fc.some(f => f.plan)) ? 1 : 0, empresa.length, bodegas.length, labs.length, q.trim() ? 1 : 0, agrupar ? 1 : 0].filter(Boolean).length + fc.filter(f => f.plan && f.vals.length).length

  useEffect(() => { api('/control/filtros').then(setOpc).catch(e => setErr(e.message)) }, [])
  useEffect(() => { const t = setTimeout(() => setQ(qd), 400); return () => clearTimeout(t) }, [qd])
  // ---- vistas guardadas: la configuración completa del informe, con nombre, por usuario ----
  type Vista = { nombre: string; config: any; compartida: boolean; mia: boolean; dueno: string | null }
  const [vistas, setVistas] = useState<Vista[]>([])
  const [sel, setSel] = useState('')                       // clave de la vista abierta ('' = ninguna)
  const [dlg, setDlg] = useState<{ nombre: string; compartida: boolean } | null>(null)
  const [aviso, setAviso] = useState('')
  const claveV = (v: Vista) => `${v.mia ? 'm' : 'o'}|${v.dueno ?? ''}|${v.nombre}`
  const cargarVistas = () => api('/vistas/clasificacion').then(setVistas).catch(() => {})
  useEffect(() => { cargarVistas() }, [])
  const instantanea = () => ({ nivel, criterio, meses, corteA, corteB, empresa, bodegas, labs, fc, agrupar, dentro, soloCon, abc, xyz, q: qd })
  const aplicar = (c: any) => {
    setNivel(c.nivel ?? 'item'); setCriterio(c.criterio ?? 'margen'); setMeses(c.meses ?? 12); setCorteA(c.corteA ?? 80); setCorteB(c.corteB ?? 95)
    setEmpresa(c.empresa ?? []); setBodegas(c.bodegas ?? []); setLabs(c.labs ?? [])
    setFc(c.fc?.length ? c.fc : [{ plan: '', vals: [] }]); setAgrupar(c.agrupar ?? ''); setDentro(!!c.dentro); setSoloCon(!!c.soloCon)
    setAbc(c.abc ?? []); setXyz(c.xyz ?? []); setQd(c.q ?? ''); setQ(c.q ?? '')
  }
  const vistaSel = vistas.find(v => claveV(v) === sel)
  const modificada = !!vistaSel && JSON.stringify(instantanea()) !== JSON.stringify({ ...instantanea(), ...vistaSel.config, fc: vistaSel.config.fc?.length ? vistaSel.config.fc : [{ plan: '', vals: [] }] })
  const abrir = (k: string) => { setSel(k); const v = vistas.find(x => claveV(x) === k); if (v) aplicar(v.config) }
  const guardarVista = async () => {
    if (!dlg?.nombre.trim()) return
    try {
      await api(`/vistas/clasificacion?nombre=${encodeURIComponent(dlg.nombre.trim())}`, { method: 'PUT', body: JSON.stringify({ config: instantanea(), compartida: dlg.compartida }) })
      await cargarVistas(); setSel(`m||${dlg.nombre.trim()}`); setAviso(`Vista “${dlg.nombre.trim()}” guardada`); setDlg(null)
    } catch (e: any) { setErr(e.message) }
  }
  const borrarVista = async () => {
    if (!vistaSel?.mia || !(await confirmar(`Borrar la vista “${vistaSel.nombre}”`, 'Solo se borra la configuración guardada; los datos no cambian.', { peligro: true, si: 'Sí, borrar' }))) return
    try { await api(`/vistas/clasificacion?nombre=${encodeURIComponent(vistaSel.nombre)}`, { method: 'DELETE' }); setSel(''); cargarVistas() } catch (e: any) { setErr(e.message) }
  }

  const crit = fc.filter(f => f.plan && f.vals.length).flatMap(f => f.vals.map(v => `${f.plan}:${v}`))
  const planes = [...new Set([...fc.map(f => f.plan), agrupar].filter(Boolean))]   // criterios elegidos en pantalla (filtro o agrupar): salen como columnas en el Excel
  const base = () => {
    const p = new URLSearchParams({ nivel, criterio, meses: String(meses), corte_a: String(corteA), corte_b: String(corteB) })
    if (empresa.length) p.set('empresa', empresa.join(',')); if (bodegas.length) p.set('bodegas', bodegas.join(',')); if (labs.length) p.set('labs', labs.join(','))
    if (q.trim()) p.set('q', q.trim()); if (crit.length) p.set('crit', crit.join(','))
    if (planes.length) { p.set('planes', planes.join(',')); if (soloCon) p.set('solo_con', '1') }
    if (agrupar) { p.set('agrupar', agrupar); if (dentro) p.set('dentro', '1') }   // vista por dentro del criterio elegido (categoría, línea…)
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
  const valoresDe = (plan: string) => opc.criterios.find((p: any) => p.plan_id === plan)?.valores ?? []
  const libres = (actual: string) => opc.criterios.filter((p: any) => p.plan_id === actual || !fc.some(f => f.plan === p.plan_id))
  const ponerFila = (i: number, f: { plan: string; vals: string[] }) => setFc(fc.map((x, j) => j === i ? f : x))
  // clic en una fila de la vista por criterio: suma/quita ese valor en el filtro de ese criterio (lo crea si no existe)
  const alternarValor = (id: string) => {
    const i = fc.findIndex(f => f.plan === agrupar)
    if (i < 0) { setFc([...fc.filter(f => f.plan), { plan: agrupar, vals: [id] }]); return }
    ponerFila(i, { plan: agrupar, vals: fc[i].vals.includes(id) ? fc[i].vals.filter(v => v !== id) : [...fc[i].vals, id] })
  }
  const valsAgrupar = fc.find(f => f.plan === agrupar)?.vals ?? []
  const alternar = (arr: string[], set: (v: string[]) => void, v: string) => set(arr.includes(v) ? arr.filter(x => x !== v) : [...arr, v])

  const [cx, cy] = d?.meta.cortes_iv ?? [0.5, 0.8]
  const cols: ColDef[] = useMemo(() => [
    { field: 'puesto', headerName: '#', width: 75, pinned: 'left', type: 'numericColumn', headerTooltip: 'Puesto en el ranking ABC según el criterio elegido (1 = el que más aporta). Los apartes D, N y S no tienen puesto.' },
    { field: 'clase', headerName: 'Clase', width: 90, pinned: 'left', cellRenderer: pill, filter: true, headerTooltip: 'ABC (cuánto aporta, según el criterio elegido) + XYZ (qué tan predecible es su venta). Ej.: AX = importante y estable. Sin letra XYZ = aún sin IV. Apartes: N nuevo, D sin venta en tiendas (no cuenta lo que vende el CEDI a wholesale/digital), S sin costo.' },
    { field: 'clase_global', headerName: 'Clase global', width: 115, cellRenderer: pill, filter: true, headerTooltip: 'La clase que tendría con todo lo que puedes ver, sin los filtros de pantalla (tienda, laboratorio, criterio…). “Clase” es el ABC dentro de lo filtrado; esta es la importancia real del item.' },
    ...(nivel === 'tienda_item' ? [{ field: 'empresa', headerName: 'Empresa', width: 80, filter: true, headerTooltip: 'Empresa de la tienda (05 Funat, 21 Stores): un mismo código de tienda puede existir en las dos.' } as ColDef, { field: 'bodega_id', headerName: 'Tienda', width: 90, filter: true, headerTooltip: 'Tienda (código de Siesa). Solo aparece al clasificar por tienda × item.' } as ColDef] : []),
    { field: 'producto_id', headerName: 'Item', width: 100, filter: true, headerTooltip: 'Referencia del producto. Un item REC se suma a su original.' },
    { field: 'descripcion', headerName: 'Descripción', width: 280, filter: true, headerTooltip: 'Nombre del producto en Siesa.' },
    { field: 'laboratorio', headerName: 'Lab.', width: 90, filter: true, headerTooltip: 'Código del laboratorio (plan 006 de Siesa).' },
    { field: 'valor', headerName: 'Venta neta $', type: 'numericColumn', width: 130, valueFormatter: p => COP(p.value), headerTooltip: 'Venta de la ventana sin IVA: valor bruto − descuentos de línea − descuentos globales. Las devoluciones restan.' },
    { field: 'margen', headerName: 'Margen $', type: 'numericColumn', width: 125, valueFormatter: p => COP(p.value), cellStyle: p => (p.value ?? 0) < 0 ? { color: '#c62828' } : null, headerTooltip: 'Venta neta − (unidades × costo promedio actual). Es el criterio ABC por defecto. En rojo: se vendió por debajo del costo.' },
    { field: 'margen_pct', headerName: 'Margen %', type: 'numericColumn', width: 105, valueFormatter: p => p.value == null ? '' : Number(p.value).toFixed(1) + '%', headerTooltip: 'Margen $ ÷ venta neta × 100.' },
    { field: 'pct_acum', headerName: '% acum.', type: 'numericColumn', width: 95, valueFormatter: p => p.value == null ? '' : Number(p.value).toFixed(1) + '%', headerTooltip: 'Porcentaje acumulado del criterio hasta este item, de mayor a menor. A = hasta el corte A, B = hasta el corte B, C = el resto.' },
    { field: 'cant', headerName: 'Unidades', type: 'numericColumn', width: 100, valueFormatter: p => NUM(p.value), headerTooltip: 'Unidades vendidas en la ventana.' },
    { field: 'inventario', headerName: 'Inventario', type: 'numericColumn', width: 105, valueFormatter: p => NUM(p.value), headerTooltip: 'Unidades disponibles hoy en las tiendas filtradas (último corte de Siesa). Los negativos cuentan como 0.' },
    { field: 'inv_costo', headerName: 'Inv. a costo $', type: 'numericColumn', width: 135, valueFormatter: p => COP(p.value), headerTooltip: 'Inventario de hoy × costo promedio actual: el dinero parado en stock hoy.' },
    { field: 'inv_prom', headerName: 'Inv. promedio', type: 'numericColumn', width: 120, valueFormatter: p => p.value == null ? '' : Number(p.value).toLocaleString('es-CO', { maximumFractionDigits: 1 }), headerTooltip: 'Inventario promedio en unidades de los días de la ventana (foto diaria de las tiendas filtradas). Donde no hay historia se usa el inventario de hoy: mira “Días con historia”.' },
    { field: 'dias_hist', headerName: 'Días hist.', type: 'numericColumn', width: 95, valueFormatter: p => NUM(p.value), cellStyle: p => p.value ? null : { color: '#c62828' }, headerTooltip: 'Días de historia de inventario que respaldan el promedio (el de la tienda con más días). 0 = no hay historia y el GMROI usa el inventario de hoy. Si es mucho menor que la ventana, el promedio cubre solo parte de ella.' },
    { field: 'gmroi', headerName: 'GMROI', type: 'numericColumn', width: 95, valueFormatter: p => p.value == null ? '' : Number(p.value).toFixed(2), headerTooltip: 'Margen anualizado ÷ inventario PROMEDIO a costo: pesos de margen por cada peso invertido en stock en un año. Más alto es mejor; bajo 1 el margen anual no cubre lo invertido.' },
    { field: 'rotacion', headerName: 'Rotación (uds/mes)', type: 'numericColumn', width: 150, valueFormatter: p => p.value == null ? '' : Number(p.value).toLocaleString('es-CO', { maximumFractionDigits: 2 }), headerTooltip: 'Unidades vendidas por mes en promedio durante la ventana (unidades ÷ meses de la ventana). Con el inventario promedio da la cobertura: inventario promedio ÷ rotación = meses de stock.' },
    { field: 'dias_inv', headerName: 'Días inv.', type: 'numericColumn', width: 100, valueFormatter: p => NUM(p.value), headerTooltip: 'Inventario promedio ÷ venta diaria promedio de la ventana: para cuántos días alcanza el stock.' },
    { field: 'pct_sin_stock', headerName: '% sin stock', type: 'numericColumn', width: 110, valueFormatter: p => p.value == null ? '' : Number(p.value).toFixed(1) + '%', cellStyle: p => (p.value ?? 0) >= 20 ? { color: '#c62828' } : null, headerTooltip: 'Días-tienda de la ventana con inventario 0 ÷ días-tienda con historia. Un GMROI alto con muchos días sin stock suele ser quiebre, no eficiencia. Rojo desde 20 %.' },
    { field: 'cob_x_margen', headerName: 'Cobertura×margen % (anterior)', type: 'numericColumn', width: 215, valueFormatter: p => p.value == null ? '' : Number(p.value).toLocaleString('es-CO', { maximumFractionDigits: 1 }) + '%', headerTooltip: 'Indicador anterior: (inventario promedio en unidades ÷ venta mensual en unidades) × margen %. Son meses de stock ponderados por margen: NO es un retorno y no se compara con el GMROI.' },
    { field: 'iv', headerName: 'IV', type: 'numericColumn', width: 80, valueFormatter: p => p.value == null ? '' : Number(p.value).toFixed(2), headerTooltip: `Índice de variabilidad del motor (desviación ÷ promedio de la venta mensual). Define XYZ: X si es menor que ${cx}, Y hasta ${cy}, Z si es mayor. A nivel item pondera por la venta diaria de cada tienda.` },
    { field: 'costo', headerName: 'Costo unit.', type: 'numericColumn', width: 115, valueFormatter: p => COP(p.value), headerTooltip: 'Costo promedio actual por unidad (Siesa, por instalación). Si falta, el item queda como S (sin costo).' },
  ], [nivel, cx, cy])

  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', height: '100%', gap: 1.5, minHeight: 600 }}>
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, flexWrap: 'wrap' }}>
        <Typography variant="h6" sx={{ fontWeight: 700 }}>Clasificación de items · ABC × XYZ</Typography>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, flexWrap: 'wrap', flex: 1, ml: 1 }}>
        <CampoSelect tip="Abre una configuración que guardaste (o que otro compartió): filtros, criterios, agrupación y clases." size="small" label="Vista guardada" value={sel} sx={{ width: 280 }}
          onChange={e => abrir(e.target.value as string)} slotProps={{ inputLabel: { shrink: true }, select: { displayEmpty: true, renderValue: (k: any) => vistaSel ? vistaSel.nombre + (modificada ? ' · modificada' : '') : <em>(sin vista guardada)</em> } }}>
          {vistas.length === 0 && <MenuItem disabled value="">Aún no tienes vistas guardadas</MenuItem>}
          {vistas.map(v => <MenuItem key={claveV(v)} value={claveV(v)}>{v.nombre}{v.compartida && <Chip size="small" label={v.mia ? 'compartida' : `de ${v.dueno}`} sx={{ ml: 1, height: 18, fontSize: 10 }} />}</MenuItem>)}
        </CampoSelect>
        {vistaSel?.mia && <Button size="small" variant="outlined" disabled={!modificada} onClick={() => setDlg({ nombre: vistaSel.nombre, compartida: vistaSel.compartida })}>Actualizar</Button>}
        <Button size="small" variant="outlined" startIcon={<SaveOutlined />} onClick={() => setDlg({ nombre: '', compartida: false })}>Guardar como…</Button>
        {vistaSel?.mia && <Tooltip placement="top" title="Borrar esta vista"><IconButton size="small" onClick={borrarVista}><DeleteOutline fontSize="small" /></IconButton></Tooltip>}
        {sel && <Button size="small" onClick={() => { setSel(''); aplicar({}) }}>Restablecer</Button>}
        </Box>
        <Tooltip placement="top" title={verFiltros ? 'Ocultar los filtros para ver más tabla' : 'Mostrar los filtros'}>
          <Button size="small" variant={verFiltros ? 'text' : 'outlined'} startIcon={verFiltros ? <ExpandLess /> : <ExpandMore />} onClick={() => cambiarFiltros(!verFiltros)}>
            {verFiltros ? 'Ocultar filtros' : `Filtros${nActivos ? ` (${nActivos} activos)` : ''}`}</Button></Tooltip>
        <Button size="small" startIcon={<HelpOutline />} onClick={() => setGuia(true)}>¿Cómo se calcula?</Button>
        <Button size="small" variant="outlined" disabled={bajando || !valido} onClick={excel}>{bajando ? 'Generando…' : 'Descargar Excel'}</Button>
      </Box>
      {d?.meta.sin_valor && <Alert severity="warning" sx={{ flexShrink: 0 }}>Las ventas aún no traen el valor en pesos: actualiza el esquema y corre “Traer ventas por mes” (o el ETL) para llenarlo. Mientras tanto el ABC por margen/venta no es confiable.</Alert>}
      <Collapse in={verFiltros} unmountOnExit={false} sx={{ flexShrink: 0 }}><Paper variant="outlined" sx={{ p: 1.25, display: 'flex', flexWrap: 'wrap', gap: 1, alignItems: 'center' }}>
        <CampoSelect tip="Por item: una clase por item sumando las tiendas filtradas. Por tienda × item: una clase por cada item dentro de cada tienda." size="small" label="Clasificar" value={nivel} onChange={e => setNivel(e.target.value)} sx={{ width: 200 }}>
          <MenuItem value="item">Por item (suma de lo filtrado)</MenuItem><MenuItem value="tienda_item">Por tienda × item</MenuItem></CampoSelect>
        <CampoSelect tip="Con qué se ordena y acumula el ABC: el margen mide lo que realmente deja el item (recomendado); la venta solo lo facturado; el consumo a costo, el capital que mueve." size="small" label="ABC según" value={criterio} onChange={e => setCriterio(e.target.value)} sx={{ width: 210 }}>
          <MenuItem value="margen">Margen bruto $ (recomendado)</MenuItem><MenuItem value="venta">Venta neta $ (sin IVA)</MenuItem><MenuItem value="costo">Consumo a costo $</MenuItem></CampoSelect>
        <CampoSelect tip="Meses de venta que se miran, terminando en el mes actual. Con menos de 6 no se detectan items nuevos (N)." size="small" label="Ventana" value={meses} onChange={e => setMeses(Number(e.target.value))} sx={{ width: 120 }}>
          {[3, 6, 9, 12].map(m => <MenuItem key={m} value={m}>{m} meses</MenuItem>)}</CampoSelect>
        <Tooltip placement="top" title="A = lo que junta hasta este % acumulado del criterio"><TextField size="small" type="number" label="Corte A %" value={corteA} onChange={e => setCorteA(Number(e.target.value))} error={!valido} sx={{ width: 100 }} /></Tooltip>
        <Tooltip placement="top" title="B = hasta este % acumulado; el resto es C"><TextField size="small" type="number" label="Corte B %" value={corteB} onChange={e => setCorteB(Number(e.target.value))} error={!valido} sx={{ width: 100 }} /></Tooltip>
        <Autocomplete multiple size="small" limitTags={1} sx={{ minWidth: 170, flex: '1 1 170px' }} options={opc.empresas} value={empresa}
          getOptionLabel={(o: string) => o === '05' ? 'Funat (05)' : o === '21' ? 'Stores (21)' : o} onChange={(_, v) => setEmpresa(v)} renderInput={p => <TextField {...p} label="Empresa" />} />
        <Autocomplete multiple size="small" limitTags={2} sx={{ minWidth: 230, flex: '2 1 230px' }} options={opc.tiendas.map((t: any) => t.bodega_id)} value={bodegas}
          getOptionLabel={(o: string) => nt(o) ? `${o} · ${nt(o)}` : o} onChange={(_, v) => setBodegas(v)} renderInput={p => <TextField {...p} label="Tienda" />} />
        <Autocomplete multiple size="small" limitTags={2} sx={{ minWidth: 230, flex: '2 1 230px' }} options={opc.laboratorios.map((l: any) => l.codigo)} value={labs}
          getOptionLabel={(o: string) => nl(o) ? `${o} · ${nl(o)}` : o} onChange={(_, v) => setLabs(v)} renderInput={p => <TextField {...p} label="Laboratorio" />} />
        {opc.criterios.length > 0 && <>
          {fc.map((f, i) => <Box key={i} sx={{ display: 'contents' }}>
            <TextField select size="small" label={i === 0 ? 'Criterio de items' : 'Y otro criterio'} value={f.plan} onChange={e => { const pl = e.target.value; ponerFila(i, { plan: pl, vals: [] }); if (pl && !agrupar) setAgrupar(pl) }} sx={{ minWidth: 190 }} slotProps={{ select: { displayEmpty: true }, inputLabel: { shrink: true } }}>
              <MenuItem value="">(elige un criterio)</MenuItem>{libres(f.plan).map((p: any) => <MenuItem key={p.plan_id} value={p.plan_id}>{p.nombre}</MenuItem>)}</TextField>
            {f.plan && <Autocomplete multiple size="small" limitTags={2} sx={{ minWidth: 220, flex: '2 1 220px' }} options={valoresDe(f.plan).map((v: any) => v.id)} value={f.vals}
              getOptionLabel={(o: string) => valoresDe(f.plan).find((v: any) => v.id === o)?.nombre ?? o} onChange={(_, v) => ponerFila(i, { plan: f.plan, vals: v })} renderInput={p => <TextField {...p} label="Valores" />} />}
            {(fc.length > 1 || f.plan) && <Tooltip placement="top" title="Quitar este criterio"><IconButton size="small" onClick={() => { if (f.plan === agrupar && fc.length === 1) setAgrupar(''); setFc(fc.length > 1 ? fc.filter((_, j) => j !== i) : [{ plan: '', vals: [] }]) }}><Close fontSize="small" /></IconButton></Tooltip>}
          </Box>)}
          {fc[fc.length - 1].plan && libres('').length > 0 && <Tooltip placement="top" title="Combinar con otro criterio: por ejemplo CATEGORIA = TERCEROS y además LINEA = una línea"><Button size="small" onClick={() => setFc([...fc, { plan: '', vals: [] }])}>+ Otro criterio</Button></Tooltip>}
          <CampoSelect tip="Muestra una fila por cada valor de este criterio (categoría, línea…) con cuántos items hay de cada clase. Se combina con los filtros: con CATEGORIA = TERCEROS arriba y LINEA aquí ves las líneas de Terceros." size="small" label="Agrupar por" value={agrupar} onChange={e => setAgrupar(e.target.value)} sx={{ minWidth: 170 }} slotProps={{ select: { displayEmpty: true }, inputLabel: { shrink: true } }}>
            <MenuItem value="">(sin agrupar)</MenuItem>{opc.criterios.map((p: any) => <MenuItem key={p.plan_id} value={p.plan_id}>{p.nombre}</MenuItem>)}</CampoSelect>
          {agrupar && <Tooltip placement="top" title="Apagado: cada item conserva su clase de la lista. Encendido: el ABC se recalcula dentro de cada grupo (cada item contra los de su mismo valor)."><FormControlLabel sx={{ mr: 0 }} control={<Checkbox size="small" checked={dentro} onChange={e => setDentro(e.target.checked)} />} label="ABC dentro de cada grupo" /></Tooltip>}
        </>}
        {planes.length > 0 && <Tooltip placement="top" title="Deja fuera los items que no tienen valor en los criterios elegidos (los que salen como (sin valor)). El Excel también trae una columna por cada criterio elegido."><FormControlLabel sx={{ mr: 0 }} control={<Checkbox size="small" checked={soloCon} onChange={e => setSoloCon(e.target.checked)} />} label="Excluir items sin esa clasificación" /></Tooltip>}
        <TextField size="small" label="Item (código o nombre)" value={qd} onChange={e => setQd(e.target.value)} sx={{ minWidth: 190, flex: '1 1 190px' }} />
      </Paper></Collapse>
      {!valido && <Typography color="error" variant="body2">Los cortes deben cumplir 0 &lt; A &lt; B ≤ 100.</Typography>}
      {err && <Typography color="error" variant="body2">{err}</Typography>}

      {d && <Paper variant="outlined" sx={{ flexShrink: 0, p: 1.25, overflow: 'auto' }}>
        <Typography variant="caption" color="text.secondary">
          {d.meta.criterio_nombre} · ventana {String(d.meta.desde).slice(0, 10)} a {String(d.meta.hasta).slice(0, 10)} · XYZ por IV del motor (X &lt; {d.meta.cortes_iv[0]}, Y hasta {d.meta.cortes_iv[1]}, Z mayor) · clic en una celda o en una clase para filtrar la lista
        </Typography>
        <Box component="table" sx={{ borderCollapse: 'collapse', mt: .5, width: '100%', '& td, & th': { border: '1px solid #e0e0e0', px: 1.25, py: .5, fontSize: 13, textAlign: 'right' } }}>
          <thead><tr><th style={{ textAlign: 'left' }}>Clase</th>
            {['X', 'Y', 'Z'].map(x => <Tooltip key={x} title={`${x === 'X' ? `Estable: IV menor que ${cx}` : x === 'Y' ? `Variación media: IV entre ${cx} y ${cy}` : `Variable: IV mayor que ${cy}`}. IV = desviación ÷ promedio de la venta mensual.`}><th>{x} · {x === 'X' ? 'estable' : x === 'Y' ? 'media' : 'variable'}</th></Tooltip>)}
            <Tooltip title="Cuántos items hay en esa clase."><th>Items</th></Tooltip><Tooltip title="Venta neta (sin IVA) de la clase en la ventana."><th>Venta neta</th></Tooltip>
            <Tooltip title="Venta neta − costo de lo vendido. Rojo = pierde plata."><th>Margen</th></Tooltip><Tooltip title="Inventario de hoy a costo promedio: dinero parado en stock."><th>Inv. a costo</th></Tooltip>
            <Tooltip title="Margen anualizado ÷ inventario promedio a costo de la clase (sumas en pesos)."><th>GMROI</th></Tooltip><Tooltip title="Meses que dura el inventario promedio al ritmo de venta, todo a costo (sumas en pesos)."><th>Meses inv.</th></Tooltip></tr></thead>
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
                <td style={{ fontWeight: 700 }}>{t.n.toLocaleString()}</td><td>{M(t.venta)}</td><td style={{ color: t.margen < 0 ? '#c62828' : undefined }}>{M(t.margen)}</td><td>{M(t.inv_costo)}</td><td>{t.gmroi == null ? '' : t.gmroi.toFixed(2)}</td><td>{t.meses_inv == null ? '' : t.meses_inv.toFixed(1)}</td>
              </tr>)
            })}
            <tr><th style={{ textAlign: 'left' }}>Total</th><td colSpan={3}></td><td style={{ fontWeight: 700 }}>{tot.n.toLocaleString()}</td><td>{M(tot.venta)}</td><td>{M(tot.margen)}</td><td>{M(tot.inv_costo)}</td><td>{tot.gmroi == null ? '' : tot.gmroi.toFixed(2)}</td><td>{tot.meses_inv == null ? '' : tot.meses_inv.toFixed(1)}</td></tr>
          </tbody>
        </Box>
        {(abc.length > 0 || xyz.length > 0) && <Box sx={{ mt: 1, display: 'flex', gap: 1, alignItems: 'center' }}>
          <Typography variant="caption">Lista filtrada a:</Typography>
          {abc.map(a => <Chip key={a} size="small" label={`ABC ${a}`} onDelete={() => setAbc(abc.filter(x => x !== a))} />)}
          {xyz.map(x => <Chip key={x} size="small" label={`XYZ ${x}`} onDelete={() => setXyz(xyz.filter(y => y !== x))} />)}
          <Button size="small" onClick={() => { setAbc([]); setXyz([]) }}>Quitar</Button>
        </Box>}
      </Paper>}

      {d?.por_criterio && <Paper variant="outlined" sx={{ flexShrink: 0, p: 1.25, overflow: 'auto', maxHeight: 280 }}>
        <Typography variant="caption" color="text.secondary">
          Por {d.por_criterio.plan_nombre} · {crit.length ? 'con los filtros de criterio elegidos' : 'todos los valores'} · cuántos {nivel === 'item' ? 'items' : 'tienda × item'} hay de cada clase{dentro ? ' (ABC recalculado dentro de cada grupo)' : ''} · clic en una fila para filtrar todo el informe a ese valor (la clase se recalcula dentro de lo filtrado)
        </Typography>
        <Box component="table" sx={{ borderCollapse: 'collapse', mt: .5, width: '100%', '& td, & th': { border: '1px solid #e0e0e0', px: 1.25, py: .4, fontSize: 13, textAlign: 'right' } }}>
          <thead><tr><th style={{ textAlign: 'left' }}>{d.por_criterio.plan_nombre}</th><th>{nivel === 'item' ? 'Items' : 'Filas'}</th>
            {['A', 'B', 'C', 'N', 'D', 'S'].map(a => <Tooltip key={a} placement="top" title={NOMBRE_ABC[a]}><th style={{ color: COLOR_ABC[a] }}>{a}</th></Tooltip>)}
            <th>Venta neta</th><th>Margen</th><th>Margen %</th><th>Inv. a costo</th><Tooltip placement="top" title="Margen anualizado ÷ inventario promedio a costo del grupo (sumas en pesos)"><th>GMROI</th></Tooltip></tr></thead>
          <tbody>
            {d.por_criterio.grupos.map((g: any) => {
              const sel = valsAgrupar.includes(g.id)
              return (<tr key={g.id || 'sin'} onClick={() => g.id && alternarValor(g.id)}
                style={{ cursor: g.id ? 'pointer' : 'default', background: sel ? 'rgba(110,138,55,.25)' : undefined }}>
                <th style={{ textAlign: 'left', fontWeight: sel ? 700 : 500 }}>{g.nombre}</th><td style={{ fontWeight: 700 }}>{g.n.toLocaleString()}</td>
                {['A', 'B', 'C', 'N', 'D', 'S'].map(a => <td key={a} style={{ color: g[a] ? undefined : '#bbb' }}>{g[a] ? g[a].toLocaleString() : '·'}</td>)}
                <td>{M(g.venta)}</td><td style={{ color: g.margen < 0 ? '#c62828' : undefined }}>{M(g.margen)}</td>
                <td>{g.margen_pct == null ? '' : g.margen_pct.toFixed(1) + '%'}</td><td>{M(g.inv_costo)}</td><td>{g.gmroi == null ? '' : g.gmroi.toFixed(2)}</td>
              </tr>)
            })}
          </tbody>
        </Box>
      </Paper>}

      <Typography variant="caption" color="text.secondary">{d ? (d.truncado ? `Mostrando ${d.filas.length.toLocaleString()} de ${d.total.toLocaleString()}; filtra por clase o baja el Excel` : `${d.total.toLocaleString()} filas`) : ''}</Typography>
      <Box className="ag-theme-quartz" sx={{ flex: 1, minHeight: 320 }}>
        <Tabla textoCargando="Clasificando…" vacio="Sin resultados con estos filtros" key={nivel} rowData={d?.filas ?? []} columnDefs={cols} cargando={cargando} defaultColDef={{ resizable: true, sortable: true }} />
      </Box>
      <Dialog open={!!dlg} onClose={() => setDlg(null)} maxWidth="xs" fullWidth>
        <DialogTitle>Guardar vista</DialogTitle>
        <DialogContent>
          <TextField autoFocus fullWidth size="small" label="Nombre de la vista" value={dlg?.nombre ?? ''} sx={{ mt: 1 }} inputProps={{ maxLength: 60 }}
            onChange={e => setDlg(x => ({ ...x!, nombre: e.target.value }))} onKeyDown={e => { if (e.key === 'Enter') guardarVista() }}
            helperText={vistas.some(v => v.mia && v.nombre === dlg?.nombre.trim()) ? 'Ya tienes una vista con ese nombre: se reemplaza' : 'Guarda filtros, criterios, agrupación, clases y búsqueda tal como los ves ahora'} />
          <FormControlLabel sx={{ mt: 1 }} control={<Checkbox checked={dlg?.compartida ?? false} onChange={e => setDlg(x => ({ ...x!, compartida: e.target.checked }))} />}
            label="Compartir con los demás usuarios (ellos la ven con lo que su perfil les permite)" />
        </DialogContent>
        <DialogActions><Button onClick={() => setDlg(null)}>Cancelar</Button><Button variant="contained" disabled={!dlg?.nombre.trim()} onClick={guardarVista}>Guardar</Button></DialogActions>
      </Dialog>
      <Snackbar open={!!aviso} autoHideDuration={3000} onClose={() => setAviso('')} message={aviso} />
      <GuiaClasificacion abierta={guia} cerrar={() => setGuia(false)} meta={d?.meta} />
    </Box>)
}
