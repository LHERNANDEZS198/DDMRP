import { useEffect, useMemo, useRef, useState } from 'react'
import Tabla from '../Tabla'
import AvisoInfo from '../AvisoInfo'
import { ColDef, GridApi, ICellRendererParams } from 'ag-grid-community'
import { Alert, Autocomplete, Box, Button, Checkbox, Chip, Collapse, FormControlLabel, IconButton, MenuItem, Paper, Stack, Table, TableBody, TableCell, TableHead, TableRow, TextField, Tooltip, Typography } from '@mui/material'
import Insights from '@mui/icons-material/Insights'
import Check from '@mui/icons-material/Check'
import Download from '@mui/icons-material/Download'
import Undo from '@mui/icons-material/Undo'
import LocalShipping from '@mui/icons-material/LocalShipping'
import ExpandMore from '@mui/icons-material/ExpandMore'
import { api, descargar } from '../api'
import Aviso from '../Aviso'
import { ayudar } from '../ayuda'
import { useYo } from '../Yo'
import { confirmar } from '../alertas'
import { GuiaDespacho } from '../guias'
import HelpOutline from '@mui/icons-material/HelpOutline'
import { useEmpresa } from '../Empresa'

const cop = (v: number) => '$' + Math.round(v).toLocaleString('es-CO')
const unidades = (r: any) => Number(r.cantidad_aprobada ?? r.cantidad_sugerida) || 0
const valorDe = (r: any) => unidades(r) * (r.costo ?? 0)

const verEnControl = (p: ICellRendererParams) => (
  <Tooltip title="Ver esta tienda y este item en Control DDMRP (foto actual), en una pestaña nueva">
    <IconButton size="small" component="a" target="_blank" rel="noopener" href={`/control?tienda=${encodeURIComponent(p.data.bodega_id)}&item=${encodeURIComponent(p.data.producto_id)}`}>
      <Insights fontSize="small" /></IconButton></Tooltip>)
const cols: ColDef[] = [
  { checkboxSelection: true, headerCheckboxSelection: true, width: 50, pinned: 'left' },
  { headerName: 'Control', width: 80, cellRenderer: verEnControl, sortable: false, pinned: 'left' },
  { field: 'bodega_id', headerName: 'Bodega', filter: true },
  { field: 'producto_id', headerName: 'Producto', filter: true },
  { field: 'descripcion', flex: 1, minWidth: 220, filter: true },
  { field: 'zona', filter: true },
  { field: 'estado', filter: true, width: 115 },
  { field: 'inventario', type: 'numericColumn' },
  { field: 'en_transito', headerName: 'Transito', type: 'numericColumn' },
  { field: 'tog_aj', headerName: 'TOG aj.', type: 'numericColumn' },
  { field: 'unidad_despacho', headerName: 'Und. desp.', type: 'numericColumn' },
  { field: 'vectorizacion', headerName: 'Derrame', type: 'numericColumn' },
  { field: 'cantidad_necesaria', headerName: 'Necesario', type: 'numericColumn' },
  { field: 'stock_cedi', headerName: 'CEDI antes', type: 'numericColumn', headerTooltip: 'Stock del CEDI de la empresa para este ítem (menos la reserva), antes de repartir', valueFormatter: p => p.value == null ? '' : Math.round(p.value).toLocaleString() },
  { field: 'cantidad_sugerida', headerName: 'Asignado', type: 'numericColumn',
    cellStyle: p => p.data?.limitado ? { color: '#c62828', fontWeight: 700 } : null },
  { field: 'cedi_despues', headerName: 'CEDI después', type: 'numericColumn', headerTooltip: 'Lo que queda en el CEDI de este ítem después de enviar lo asignado a las tiendas que compiten por ese stock en el reparto (los DIAs elegidos en la corrida; si no se eligió ninguno, todas). Las tiendas de otros DIAs no cuentan aquí',
    valueFormatter: p => p.value == null ? '' : Math.round(p.value).toLocaleString() },
  { field: 'cantidad_aprobada', headerName: 'A enviar', editable: (p: any) => !!p.context?.aprobar, type: 'numericColumn',
    valueGetter: p => p.data.cantidad_aprobada ?? p.data.cantidad_sugerida,
    valueSetter: p => { p.data.cantidad_aprobada = Number(p.newValue); return true } },
  { field: 'costo', headerName: 'Costo prom.', type: 'numericColumn', width: 115, valueFormatter: p => p.value == null ? 'sin costo' : cop(p.value),
    cellStyle: p => p.value == null ? { color: '#c62828' } : null },
  { colId: 'valor', headerName: 'Valor a enviar', type: 'numericColumn', width: 130, valueGetter: p => valorDe(p.data), valueFormatter: p => cop(p.value ?? 0) },
]

export default function Despacho() {
  const { puede } = useYo(); const pAprobar = puede('aprobar_despacho'); const pPlano = puede('descargar_planos'); const pAudit = puede('ver_auditoria')
  const [rows, setRows] = useState<any[]>([])
  const [cargando, setCargando] = useState(true)
  const [grid, setGrid] = useState<GridApi | null>(null)
  const [msg, setMsg] = useState('')
  const [notas, setNotas] = useState('')
  const [consec, setConsec] = useState(1)
  const [marcar, setMarcar] = useState(false)
  const [cedi, setCedi] = useState<any>(null)
  const [guia, setGuia] = useState(false)
  // empresa obligatoria (05 Funat / 21 Stores): cada una tiene su CEDI, su matriz y su plano
  const { una: empresa } = useEmpresa()
  // filtros de la lista (en pantalla): texto, laboratorio, zona, solo lo limitado por el CEDI
  const [fTexto, setFTexto] = useState(''); const [fLab, setFLab] = useState(''); const [fZona, setFZona] = useState(''); const [fLim, setFLim] = useState(true)   // por defecto solo lo que el CEDI no alcanzó a cubrir
  const [fTienda, setFTienda] = useState<string | null>(null)   // ver el detalle de los items de una sola tienda
  const [fCero, setFCero] = useState(false)   // filas con 0 a enviar: ocultas por defecto (a la tienda no le llega nada)
  const [porTienda, setPorTienda] = useState(false)
  const [bajandoAud, setBajandoAud] = useState(false)
  const [ediciones, setEdiciones] = useState(0)   // al cambiar "A enviar" a mano se recalculan los totales
  useEffect(() => { api('/despacho/cedi').then(setCedi).catch(() => {}) }, [])
  const [ver, setVer] = useState<'pendiente' | 'aprobada' | 'enviada'>('pendiente')
  // Corrida del dia: DIA de abastecimiento + tiendas elegidas (se pueden poner o quitar antes de generar)
  const [dias, setDias] = useState<{ dia: number; bodegas: string[] }[]>([])
  const [todasBod, setTodas] = useState<string[]>([])
  const [empDe, setEmpDe] = useState<Record<string, string>>({})
  const [dia, setDia] = useState('')            // '' = sin DIA
  const [filtrar, setFiltrar] = useState(false) // false = todas las tiendas
  const [tiendas, setTiendas] = useState<string[]>([])
  const [nueva, setNueva] = useState('')
  useEffect(() => { api('/despacho/dias?empresa=' + empresa).then(x => { setDias(x.dias); setTodas(x.bodegas); setEmpDe(x.empresa_de ?? {}) }) }, [empresa])
  const diasEmp = useMemo(() => dias.map(d => ({ ...d, bodegas: d.bodegas.filter(b => empDe[b] === empresa) })).filter(d => d.bodegas.length), [dias, empDe, empresa])
  const todas = useMemo(() => todasBod.filter(b => empDe[b] === empresa), [todasBod, empDe, empresa])
  const elegirDia = (v: string) => {
    setDia(v)
    if (v === '') { setFiltrar(false); setTiendas([]); return }
    setFiltrar(true); setTiendas(diasEmp.find(d => String(d.dia) === v)?.bodegas ?? [])
  }
  const quitar = (b: string) => { setFiltrar(true); setTiendas(t => t.filter(x => x !== b)) }
  const poner = (b: string) => { if (!b) return; setFiltrar(true); setTiendas(t => t.includes(b) ? t : [...t, b].sort()); setNueva('') }
  // Solo vale la respuesta de la última petición: si cambias de "Ver" mientras llega una lista grande, la vieja no debe pisar la nueva
  const peticion = useRef(0)
  const cargar = () => {
    const n = ++peticion.current
    if (!empresa) { setRows([]); setCargando(false); return Promise.resolve() }
    return api('/despacho/matriz?empresa=' + empresa + '&estado=' + ver + (filtrar ? '&bodegas=' + encodeURIComponent(tiendas.join(',') || '-') : ''))
      .then(r => { if (n === peticion.current) setRows(r) })
      .finally(() => { if (n === peticion.current) setCargando(false) })
  }
  useEffect(() => { setDia(''); setFiltrar(false); setTiendas([]) }, [empresa])
  useEffect(() => { setRows([]); setCargando(true); cargar() }, [filtrar, tiendas.join(','), ver, empresa])
  const [nombres, setNombres] = useState<Record<string, string>>({})   // código de tienda -> nombre (Éxito Envigado…)
  useEffect(() => { api('/control/filtros').then(r => setNombres(Object.fromEntries((r.tiendas ?? []).map((t: any) => [t.bodega_id, t.nombre ?? ''])))).catch(() => {}) }, [])
  const tiendasEnFilas = useMemo(() => [...new Set(rows.map(r => r.bodega_id).filter(Boolean))].sort() as string[], [rows])
  useEffect(() => { if (fTienda && !tiendasEnFilas.includes(fTienda)) setFTienda(null) }, [tiendasEnFilas])   // cambió la corrida o la empresa
  const labs = useMemo(() => [...new Set(rows.map(r => r.categoria).filter(Boolean))].sort() as string[], [rows])
  const vista = useMemo(() => {
    const t = fTexto.trim().toLowerCase()
    return rows.filter(r => (!t || `${r.producto_id} ${r.descripcion ?? ''} ${r.bodega_id}`.toLowerCase().includes(t)) && (!fLab || r.categoria === fLab) && (!fTienda || r.bodega_id === fTienda)
      && (!fZona || r.zona === fZona) && (!fLim || r.limitado) && (fCero || fLim || unidades(r) > 0))   // 'solo limitadas' muestra tambien las de 0: son justo las que el CEDI no alcanzo a cubrir
  }, [rows, fTexto, fLab, fTienda, fZona, fLim, fCero])
  const hayFiltro = !!(fTexto || fLab || fTienda || fZona || fLim)
  // totales de lo que se ve: unidades y costo, en total y por tienda
  const tot = useMemo(() => {
    const por = new Map<string, { filas: number; uds: number; valor: number; sinCosto: number }>()
    for (const r of vista) {
      const x = por.get(r.bodega_id) ?? { filas: 0, uds: 0, valor: 0, sinCosto: 0 }
      x.filas++; x.uds += unidades(r); x.valor += valorDe(r); if (r.costo == null) x.sinCosto++
      por.set(r.bodega_id, x)
    }
    const lista = [...por.entries()].sort((a, b) => a[0].localeCompare(b[0]))
    return { lista, uds: lista.reduce((s, [, x]) => s + x.uds, 0), valor: lista.reduce((s, [, x]) => s + x.valor, 0), sinCosto: lista.reduce((s, [, x]) => s + x.sinCosto, 0) }
  }, [vista, ediciones])
  const minimo: number = cedi?.minimo_envio ?? 0; const regla = minimo > 0 && (cedi?.con_costos ?? 0) > 0
  // tiendas bajo el mínimo según TODAS sus filas (no solo las filtradas): se pintan en gris en la matriz
  const bajoMin = useMemo(() => {
    const v = new Map<string, number>(); for (const r of rows) v.set(r.bodega_id, (v.get(r.bodega_id) ?? 0) + valorDe(r))
    return new Set(regla ? [...v.entries()].filter(([, x]) => x < minimo).map(([b]) => b) : [])
  }, [rows, ediciones, regla, minimo])
  // Excel de auditoría (con fórmulas) de lo que se ve ahora mismo: mismas filas, con todos los filtros de la pantalla
  const TOPE_AUD = 10000
  const auditoria = async () => {
    if (!vista.length) return
    const filas = vista.slice(0, TOPE_AUD).map((r: any) => ({ b: r.bodega_id, p: r.producto_id }))
    setBajandoAud(true); setMsg('Armando el Excel de auditoría con las fórmulas… puede tardar si son muchas filas')
    try {
      await descargar('/auditoria/excel', { empresa, filas, limite: TOPE_AUD })
      setMsg(`Excel de auditoría descargado: ${filas.length.toLocaleString('es-CO')} filas`
        + (vista.length > TOPE_AUD ? ` (de ${vista.length.toLocaleString('es-CO')}: el Excel lleva las primeras ${TOPE_AUD.toLocaleString('es-CO')}, filtra más para el resto)` : ''))
    } catch (x: any) { setMsg('Error: ' + x.message) } finally { setBajandoAud(false) }
  }
  const textoCedi: string = !cedi ? '' : (
    cedi.regla === 0 ? 'El reparto del inventario del CEDI está apagado: se sugiere todo lo que pide el buffer.'
            : cedi.productos === 0 ? `Sin inventario del CEDI (${cedi.bodega}): corre el ETL para traerlo. Mientras tanto no se limita lo sugerido.`
            : `CEDI ${cedi.bodega}${empresa ? ` (empresa ${empresa})` : ''}: ${(cedi.por_empresa?.find((x: any) => x.empresa === empresa)?.con_stock ?? cedi.con_stock).toLocaleString()} items con stock (corte ${cedi.por_empresa?.find((x: any) => x.empresa === empresa)?.corte ?? cedi.corte}) · si no alcanza se reparte solo entre las tiendas de esa empresa: ${cedi.regla_nombre.toLowerCase()}`
              + (cedi.limitadas ? ` · ${cedi.limitadas.toLocaleString()} combinaciones con menos de lo necesario` : '')
              + (cedi.items_con_reserva ? ` · ${cedi.items_con_reserva} items con reserva` : ''))
  const aprobar = async () => {
    const sel = grid?.getSelectedRows() ?? []
    if (!sel.length) { setMsg('Selecciona filas'); return }
    try {
      await api('/despacho/aprobar', { method: 'POST', body: JSON.stringify(sel.map((r: any) => ({
        ejecucion_id: r.ejecucion_id, producto_id: r.producto_id, bodega_id: r.bodega_id, empresa: r.empresa,
        cantidad_aprobada: r.cantidad_aprobada ?? r.cantidad_sugerida, aprobar: true }))) })
      setMsg(`Aprobadas ${sel.length}. Las ves en “Aprobadas”, desde donde puedes devolverlas a pendiente.`); cargar()
    } catch (x: any) { setMsg('Error: ' + x.message) }
  }
  const devolver = async () => {
    const sel = grid?.getSelectedRows() ?? []
    if (!sel.length) { setMsg('Selecciona filas aprobadas'); return }
    try {
      const r = await api('/despacho/desaprobar', { method: 'POST', body: JSON.stringify(sel.map((x: any) => ({ ejecucion_id: x.ejecucion_id, producto_id: x.producto_id, bodega_id: x.bodega_id, empresa: x.empresa }))) })
      setMsg(r.devueltas ? `Devueltas a pendiente: ${r.devueltas}` + (r.omitidas ? ` (${r.omitidas} no estaban aprobadas)` : '')
        : 'Ninguna se devolvió: las filas elegidas no están aprobadas en la corrida actual.'); grid?.deselectAll(); cargar()
    } catch (x: any) { setMsg('Error: ' + x.message) }
  }
  const plano = async () => {
    try {
      setMsg('Generando el archivo plano de Siesa…')
      const r = await descargar('/despacho/exportar-plano', { notas: notas || null, consec_inicial: consec, marcar_enviadas: marcar,
        bodegas: filtrar ? tiendas : null, dia: dia ? Number(dia) : null, empresa })
      setMsg(`Descargado ${r.nombre}` + (r.derivado ? ` · centro de operacion deducido para: ${r.derivado}` : '')
        + (r.bajoMinimo ? ` · NO se incluyeron por estar bajo el mínimo de ${cop(minimo)}: ${r.bajoMinimo.split(',').map((x: string) => { const [b, v] = x.split(':'); return `${b} (${cop(Number(v))})` }).join(', ')}` : ''))
      if (marcar) cargar()
    } catch (x: any) { setMsg('Error: ' + x.message) }
  }
  const enviar = async () => {
    const sel = grid?.getSelectedRows() ?? []
    const bodegas = sel.length ? [...new Set<string>(sel.map((x: any) => x.bodega_id))] : (filtrar ? tiendas : null)
    const n = bodegas ? bodegas.length : tot.lista.length
    if (!(await confirmar('Marcar como enviadas', `Se marcan como ENVIADAS las aprobadas de ${bodegas ? n : 'todas las'} tienda(s).` + (regla ? ` Las que valgan menos de ${cop(minimo)} no se envían.` : '') + ' Quedan fuera de Aprobadas y ya no se pueden devolver.', { si: 'Sí, marcar como enviadas' }))) return
    try {
      const r = await api('/despacho/marcar-enviadas', { method: 'POST', body: JSON.stringify({ bodegas, empresa }) })
      setMsg(`Marcadas como enviadas: ${r.enviadas} filas de ${r.tiendas} tienda(s)`
        + (r.bloqueadas?.length ? ` · NO se enviaron por estar bajo el mínimo de ${cop(r.minimo)}: ${r.bloqueadas.map((b: any) => `${b.bodega_id} (${cop(b.valor)})`).join(', ')}` : ''))
      grid?.deselectAll(); cargar()
    } catch (x: any) { setMsg('Error: ' + x.message) }
  }
  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', height: '100%', gap: 1.5, minHeight: 500 }}>
      <Paper variant="outlined" sx={{ p: 1.5, display: 'flex', flexWrap: 'wrap', gap: 1, alignItems: 'center' }}>
        <Typography sx={{ fontWeight: 700 }}>Corrida</Typography>
        <TextField select size="small" value={dia} onChange={e => elegirDia(e.target.value)} sx={{ minWidth: 220 }} slotProps={{ select: { displayEmpty: true } }}>
          <MenuItem value="">Todas las tiendas</MenuItem>
          {diasEmp.map(d => <MenuItem key={d.dia} value={String(d.dia)}>DIA {d.dia} ({d.bodegas.length} tiendas)</MenuItem>)}
        </TextField>
        {filtrar && tiendas.map(b => <Chip key={b} label={b} size="small" color="primary" variant="outlined" onDelete={() => quitar(b)} />)}
        <TextField select size="small" value={nueva} onChange={e => poner(e.target.value)} sx={{ minWidth: 170 }} label="+ agregar tienda">
          {todas.filter(b => !tiendas.includes(b)).map(b => <MenuItem key={b} value={b}>{b}</MenuItem>)}
        </TextField>
        {filtrar && <Button size="small" onClick={() => { setDia(''); setFiltrar(false); setTiendas([]) }}>Ver todas</Button>}
        <Box sx={{ flex: 1 }} />
        {cedi?.activo && <AvisoInfo titulo="Estado del inventario del CEDI y regla de reparto">{textoCedi}</AvisoInfo>}
        {cedi && cedi.dias_reparto?.length > 0 && <AvisoInfo titulo="Reparto del CEDI por DIAs">El inventario del CEDI se repartió solo entre las tiendas de los DIAs {cedi.dias_reparto.join(' + ')}; las demás tiendas muestran lo que pide su buffer sin limitar.</AvisoInfo>}
      </Paper>
      {cedi && !cedi.activo && (
        <Alert severity="warning" sx={{ py: 0 }}>
          {textoCedi}
        </Alert>)}
      {cedi && cedi.con_costos === 0 && <Alert severity="warning" sx={{ py: 0 }}>Aún no hay costos de Siesa: corre el ETL (o el pipeline) para traerlos. Mientras tanto el valor del despacho queda en $0 y no se aplica el mínimo por tienda.</Alert>}
      <Paper variant="outlined" sx={{ p: 1.5, display: 'flex', flexWrap: 'wrap', gap: 1.5, alignItems: 'center' }}>
        <TextField select size="small" label="Ver" value={ver} onChange={e => setVer(e.target.value as any)} sx={{ minWidth: 130 }}>
          <MenuItem value="pendiente">Pendientes</MenuItem><MenuItem value="aprobada">Aprobadas</MenuItem><MenuItem value="enviada">Enviadas</MenuItem>
        </TextField>
        <Tooltip title="Pendiente → Aprobada → Enviada. Los estados viven en la corrida del motor: al correrlo de nuevo el mismo día se conservan las Enviadas y lo demás vuelve a Pendiente. Clic para ver cómo funciona.">
          <Button size="small" color="warning" startIcon={<HelpOutline />} onClick={() => setGuia(true)}>Estados: qué pasa al correr el motor</Button></Tooltip>
        {pAprobar && ver === 'pendiente' && <Button variant="contained" startIcon={<Check />} onClick={aprobar}>Aprobar seleccionados</Button>}
        {pAprobar && ver === 'aprobada' && <Button variant="outlined" color="warning" startIcon={<Undo />} onClick={devolver}>Devolver a pendiente</Button>}
        {(pAprobar || pPlano) && ver === 'aprobada' && <Tooltip title="Pasa las aprobadas (las seleccionadas, o las de las tiendas de la corrida) a ENVIADAS sin bajar el plano. Las tiendas bajo el valor mínimo no se envían.">
          <Button variant="contained" color="success" startIcon={<LocalShipping />} onClick={enviar}>Marcar como enviadas</Button></Tooltip>}
        {pPlano && <><TextField size="small" sx={{ width: 320 }} label="Nota del documento" value={notas} onChange={e => setNotas(e.target.value)}
          placeholder={`ABASTECIMIENTO DEL <dia> DE <MES>${dia ? ` DÍA ${dia}` : ''}`} />
        <TextField size="small" type="number" label="Consecutivo inicial" sx={{ width: 150 }} value={consec}
          slotProps={{ htmlInput: { min: 1 } }} onChange={e => setConsec(Number(e.target.value))} />
        <FormControlLabel control={<Checkbox size="small" checked={marcar} onChange={e => setMarcar(e.target.checked)} />} label="Marcar como enviadas" />
        <Button variant="outlined" startIcon={<Download />} onClick={plano}>Generar archivo plano Siesa</Button>
        <Button disabled title="Fase 3">Enviar a Siesa (web service)</Button></>}
      </Paper>
      <Paper variant="outlined" sx={{ p: 1, display: 'flex', flexWrap: 'wrap', gap: 1, alignItems: 'center' }}>
        <TextField size="small" label="Buscar item, descripción o tienda" value={fTexto} onChange={e => setFTexto(e.target.value)} sx={{ width: 260 }} />
        <Autocomplete size="small" sx={{ width: 260 }} options={tiendasEnFilas} value={fTienda} onChange={(_, v) => setFTienda(v)} noOptionsText="Sin tiendas"
          getOptionLabel={(o: string) => nombres[o] ? `${o} · ${nombres[o]}` : o}
          renderInput={p => <TextField {...p} label="Tienda (detalle)" placeholder="Todas" />} />
        <TextField select size="small" label="Laboratorio" value={fLab} onChange={e => setFLab(e.target.value)} sx={{ minWidth: 160 }}>
          <MenuItem value="">Todos</MenuItem>{labs.map(l => <MenuItem key={l} value={l}>{l}</MenuItem>)}</TextField>
        <TextField select size="small" label="Zona" value={fZona} onChange={e => setFZona(e.target.value)} sx={{ minWidth: 130 }}>
          <MenuItem value="">Todas</MenuItem>{['ROJA', 'AMARILLA', 'VERDE', 'EXCESO'].map(z => <MenuItem key={z} value={z}>{z}</MenuItem>)}</TextField>
        <FormControlLabel control={<Checkbox size="small" checked={fLim} onChange={e => setFLim(e.target.checked)} />} label="Solo limitadas por el CEDI" />
        <Tooltip placement="top" title={fLim ? 'Con “Solo limitadas por el CEDI” se ven también las que quedaron en 0' : 'Filas en las que no se le enviará nada a la tienda (A enviar = 0). Ocultas por defecto.'}><span>
          <FormControlLabel control={<Checkbox size="small" checked={fCero || fLim} disabled={fLim} onChange={e => setFCero(e.target.checked)} />} label="Mostrar items con enviar en 0" /></span></Tooltip>
        {hayFiltro && <Button size="small" onClick={() => { setFTexto(''); setFLab(''); setFTienda(null); setFZona(''); setFLim(false) }}>Quitar filtros</Button>}
        <Box sx={{ flex: 1 }} />
        <Chip label={`${vista.length.toLocaleString()}${vista.length !== rows.length ? ` de ${rows.length.toLocaleString()}` : ''} filas`} size="small" />
        <Chip label={`${Math.round(tot.uds).toLocaleString('es-CO')} uds a enviar`} size="small" color="primary" />
        <Chip label={`Costo total ${cop(tot.valor)}`} size="small" color="primary" />
        <Chip label={`${tot.lista.length} tiendas`} size="small" />
        {bajoMin.size > 0 && <Tooltip title={`En gris: ${[...bajoMin].join(', ')}. No salen en el plano ni se marcan como enviadas.`}><Chip label={`${bajoMin.size} tiendas bajo el mínimo`} size="small" /></Tooltip>}
        {tot.sinCosto > 0 && <Chip label={`${tot.sinCosto} filas sin costo`} size="small" color="warning" />}
        {pAudit && <Tooltip title="Descarga a Excel, con todas las fórmulas del cálculo, exactamente las filas que ves ahora (con los filtros de la pantalla)">
          <span><Button size="small" variant="outlined" startIcon={<Download />} onClick={auditoria} disabled={bajandoAud || !vista.length || !empresa}>Excel auditoría</Button></span></Tooltip>}
        <Button size="small" variant={porTienda ? 'contained' : 'outlined'} endIcon={<ExpandMore sx={{ transform: porTienda ? 'rotate(180deg)' : 'none' }} />} onClick={() => setPorTienda(!porTienda)}>{porTienda ? 'Volver a la vista por ítem' : 'Por tienda'}</Button>
      </Paper>
      {porTienda && (
        <Paper variant="outlined" sx={{ flex: 1, minHeight: 300, overflow: 'auto' }}>
          <Table size="small" stickyHeader>
            <TableHead><TableRow><TableCell>Tienda</TableCell><TableCell align="right">Filas</TableCell><TableCell align="right">Unidades</TableCell>
              <TableCell align="right">Costo</TableCell><TableCell>{regla ? `Mínimo ${cop(minimo)}` : 'Mínimo'}</TableCell></TableRow></TableHead>
            <TableBody>
              {tot.lista.map(([b, x]) => { const bajo = regla && x.valor < minimo
                return (<TableRow key={b} hover>
                  <TableCell>{b}</TableCell><TableCell align="right">{x.filas}</TableCell>
                  <TableCell align="right">{Math.round(x.uds).toLocaleString('es-CO')}</TableCell>
                  <TableCell align="right" sx={{ color: bajo ? 'error.main' : undefined, fontWeight: bajo ? 700 : 400 }}>{cop(x.valor)}</TableCell>
                  <TableCell>{!regla ? '' : bajo ? <Chip size="small" color="error" label={`Falta ${cop(minimo - x.valor)} · no se puede enviar`} /> : <Chip size="small" color="success" variant="outlined" label="Cumple" />}</TableCell>
                </TableRow>) })}
              {!tot.lista.length && <TableRow><TableCell colSpan={5} align="center" sx={{ color: 'text.secondary' }}>Sin filas</TableCell></TableRow>}
            </TableBody>
          </Table>
        </Paper>)}
      <Box className="ag-theme-quartz" sx={{ flex: 1, minHeight: 300, display: porTienda ? 'none' : 'block' }}>
        {!empresa && <Alert severity="warning" sx={{ mb: 1 }}>El despacho se trabaja de a una empresa: elige Funat o Stores en la barra de arriba (cada una tiene su CEDI y su plano).</Alert>}
        <Tabla cargando={cargando} textoCargando="Cargando la matriz…" vacio="No hay filas con este filtro" rowData={vista} columnDefs={ayudar(cols)} tooltipShowDelay={300} rowSelection="multiple" rowBuffer={20}
          getRowStyle={(p: any) => bajoMin.has(p.data?.bodega_id) ? { color: '#9e9e9e', background: 'rgba(158,158,158,0.12)' } : undefined}
          context={{ aprobar: pAprobar }} onCellValueChanged={() => setEdiciones(n => n + 1)} onGridReady={e => setGrid(e.api)} defaultColDef={{ resizable: true, sortable: true }} />
      </Box>
      <GuiaDespacho abierta={guia} cerrar={() => setGuia(false)} />
      <Aviso msg={msg} onClose={() => setMsg('')} />
    </Box>)
}
