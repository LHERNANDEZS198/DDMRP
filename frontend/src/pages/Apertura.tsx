import { useEffect, useMemo, useRef, useState } from 'react'
import Tabla from '../Tabla'
import { ColDef } from 'ag-grid-community'
import { Alert, Autocomplete, Box, Button, Card, Checkbox, Dialog, DialogActions, DialogContent, DialogTitle, FormControlLabel, MenuItem, Stack, Tab, Tabs, TextField, Typography } from '@mui/material'
import HelpOutline from '@mui/icons-material/HelpOutline'
import ArrowBack from '@mui/icons-material/ArrowBack'
import { useNavigate } from 'react-router-dom'
import { api } from '../api'
import { useYo } from '../Yo'
import { useEmpresa } from '../Empresa'
import { GuiaApertura } from '../guias'

const COL_DEF = { resizable: true, sortable: true }
const ent = (p: any) => p.value == null ? '' : Math.round(Number(p.value)).toLocaleString('es-CO')
const num = (p: any) => p.value == null ? '' : Number(p.value).toLocaleString('es-CO', { maximumFractionDigits: 2 })
const hoyISO = () => new Date(Date.now() - 5 * 36e5).toISOString().slice(0, 10)   // fecha de Colombia (UTC-5)

type Tienda = { empresa: string; bodega_id: string; nombre: string | null; leadtime?: number; frecuencia?: number; cedi?: string | null }
type Opciones = { config: { meses_defecto: number; factor_defecto: number; base_meses: number; max_meses: number }; bitacora: Tienda[]; sin_bitacora: Tienda[] }
const etiqueta = (t: Tienda) => `${t.bodega_id} · ${t.nombre ?? 'sin nombre'}`

function Kpi({ t, v }: { t: string; v: string }) {
  return <Box sx={{ border: 1, borderColor: 'divider', borderRadius: 1, px: 1.5, py: .75, minWidth: 120 }}>
    <Typography variant="caption" color="text.secondary">{t}</Typography><Typography sx={{ fontWeight: 700 }}>{v}</Typography></Box>
}

export default function Apertura() {
  const nav = useNavigate()
  const { puede } = useYo(); const edita = puede('cargar_maestros')
  const { una } = useEmpresa()
  const [tab, setTab] = useState(0)
  const [guia, setGuia] = useState(false)
  const [msg, setMsg] = useState<{ t: 'success' | 'error' | 'info'; m: string } | null>(null)
  const [op, setOp] = useState<Opciones | null>(null)
  const cargarOp = () => api('/apertura/opciones').then(setOp).catch(e => setMsg({ t: 'error', m: e.message }))
  useEffect(() => { cargarOp() }, [])

  // ---- formulario
  const [empresa, setEmpresa] = useState(una || '05')
  useEffect(() => { if (una) setEmpresa(una) }, [una])
  const [espejo, setEspejo] = useState<Tienda | null>(null)
  const [destino, setDestino] = useState<Tienda | null>(null)
  const [nombre, setNombre] = useState('')
  const [factor, setFactor] = useState('1')
  const [base, setBase] = useState<'venta' | 'pronostico'>('venta')
  const [baseMeses, setBaseMeses] = useState('6')
  const [meses, setMeses] = useState('4')
  const [fecha, setFecha] = useState(hoyISO())
  const [cotas, setCotas] = useState(true), [nxp, setNxp] = useState(true), [dia, setDia] = useState(true), [bit, setBit] = useState(true)
  const [modo, setModo] = useState<'reemplazar' | 'completar'>('reemplazar')
  const [lleno, setLleno] = useState(false)
  useEffect(() => {
    if (op && !lleno) { setFactor(String(op.config.factor_defecto)); setBaseMeses(String(op.config.base_meses)); setMeses(String(op.config.meses_defecto)); setLleno(true) }
  }, [op, lleno])

  const tiendas = useMemo(() => (op?.bitacora ?? []).filter(t => t.empresa === empresa), [op, empresa])
  const nuevas = useMemo(() => {
    const extra = (op?.sin_bitacora ?? []).filter(t => t.empresa === empresa)
    return [...tiendas, ...extra]
  }, [op, empresa, tiendas])
  const destinoEnBitacora = !!destino && tiendas.some(t => t.bodega_id === destino.bodega_id)

  const plan = () => ({ empresa, espejo: espejo!.bodega_id, destino: destino!.bodega_id, nombre: destinoEnBitacora ? null : (nombre.trim() || destino!.nombre || null),
    factor: Number(factor), base, base_meses: Number(baseMeses), copiar_cotas: cotas, copiar_nxp: nxp, copiar_dia: dia, copiar_bitacora: bit })
  const formOk = !!espejo && !!destino && espejo.bodega_id !== destino.bodega_id && Number(factor) > 0 && Number(meses) >= 1 && Number(meses) <= (op?.config.max_meses ?? 12)

  // ---- vista previa
  const [prev, setPrev] = useState<{ resumen: any; filas: any[] } | null>(null)
  const [cargando, setCargando] = useState(false)
  const [confirmar, setConfirmar] = useState(false)
  const gridApi = useRef<any>(null)
  const verPrevia = async () => {
    setMsg(null); setCargando(true); setPrev(null)
    try {
      const r = await api('/apertura/vista-previa', { method: 'POST', body: JSON.stringify(plan()) })
      setPrev({ resumen: r.resumen, filas: r.filas.map((f: any) => ({ ...f, incluir: true })) })
    } catch (e: any) { setMsg({ t: 'error', m: e.message }) } finally { setCargando(false) }
  }
  const [vers, setVers] = useState(0)   // para refrescar los totales cuando se edita una celda
  const elegidas = useMemo(() => (prev?.filas ?? []).filter(f => f.incluir && Number(f.pronostico) > 0), [prev, vers])
  const totalUn = elegidas.reduce((s, f) => s + Number(f.pronostico), 0)

  const cols = useMemo<ColDef[]>(() => [
    { field: 'incluir', headerName: '✓', width: 70, editable: edita, cellDataType: 'boolean', pinned: 'left',
      headerTooltip: 'Quita la marca de lo que NO quieras cargar en la tienda nueva' },
    { field: 'producto_id', headerName: 'SKU', width: 120, pinned: 'left' },
    { field: 'descripcion', headerName: 'Descripción', width: 320 },
    { field: 'lab', headerName: 'Laboratorio', width: 160 },
    { field: 'base', headerName: 'Base espejo', width: 120, type: 'rightAligned', valueFormatter: num, headerTooltip: 'Venta mensual promedio de la espejo, o el pronóstico que ya tiene' },
    { field: 'pronostico', headerName: 'Pronóstico nuevo', width: 140, type: 'rightAligned', editable: edita, valueFormatter: ent, cellStyle: { background: '#fffde7', fontWeight: 600 },
      valueParser: (p: any) => { const v = Number(p.newValue); return Number.isFinite(v) && v >= 0 ? Math.round(v) : p.oldValue }, headerTooltip: 'Doble clic para ajustarlo. Si lo dejas en 0 o sin marca, ese ítem no se carga' },
    { field: 'cota_max', headerName: 'Cota máx.', width: 110, type: 'rightAligned', valueFormatter: ent },
    { field: 'cota_min', headerName: 'Cota mín.', width: 110, type: 'rightAligned', valueFormatter: ent },
  ], [edita])

  const aplicar = async () => {
    setConfirmar(false); setCargando(true); setMsg(null)
    try {
      const r = await api('/apertura/aplicar', { method: 'POST', body: JSON.stringify({ ...plan(), meses_espejo: Number(meses), fecha_apertura: fecha || null, modo,
        filas: elegidas.map(f => ({ producto_id: f.producto_id, pronostico: Number(f.pronostico) })) }) })
      setMsg({ t: 'success', m: r.aviso || 'Listo' }); setPrev(null); cargarOp(); cargarLista(); setTab(1)
    } catch (e: any) { setMsg({ t: 'error', m: e.message }) } finally { setCargando(false) }
  }

  // ---- aperturas en curso
  const [lista, setLista] = useState<any[]>([])
  const cargarLista = () => api('/apertura').then(setLista).catch(e => setMsg({ t: 'error', m: e.message }))
  useEffect(() => { cargarLista() }, [])
  const cambiar = async (a: any, cuerpo: { meses_espejo?: number; activa?: boolean }) => {
    try { const r = await api(`/apertura/${a.empresa}/${a.bodega_id}`, { method: 'PUT', body: JSON.stringify(cuerpo) }); setMsg({ t: 'success', m: r.aviso || 'Guardado' }); cargarLista() }
    catch (e: any) { setMsg({ t: 'error', m: e.message }); cargarLista() }
  }
  const colsLista = useMemo<ColDef[]>(() => [
    { field: 'empresa', headerName: 'Emp.', width: 80 },
    { field: 'bodega_id', headerName: 'Tienda', width: 100 },
    { field: 'nombre', headerName: 'Nombre', width: 200 },
    { field: 'espejo', headerName: 'Espejo', width: 200, valueGetter: (p: any) => `${p.data.espejo}${p.data.espejo_nombre ? ' · ' + p.data.espejo_nombre : ''}` },
    { field: 'estado', headerName: 'Estado', width: 190, cellStyle: (p: any) => ({ fontWeight: 600, color: p.value === 'En espejo' ? '#1565c0' : p.value?.startsWith('Terminado') ? '#2e7d32' : p.value === 'Cerrada' ? '#757575' : '#b45309' }) },
    { field: 'meses_venta', headerName: 'Meses de venta', width: 130, type: 'rightAligned', headerTooltip: 'Meses desde la primera venta de la tienda, contando el mes en curso (así los cuenta el motor)' },
    { field: 'meses_espejo', headerName: 'Dura (meses)', width: 120, type: 'rightAligned', editable: edita, cellStyle: { background: '#fffde7', fontWeight: 600 },
      valueParser: (p: any) => { const v = Math.round(Number(p.newValue)); return v >= 1 && v <= (op?.config.max_meses ?? 12) ? v : p.oldValue }, headerTooltip: 'Doble clic para alargar o acortar el espejo' },
    { field: 'restan', headerName: 'Restan', width: 90, type: 'rightAligned' },
    { field: 'items', headerName: 'Ítems', width: 90, type: 'rightAligned', valueFormatter: ent },
    { field: 'pronostico_total', headerName: 'Pronóstico (u/mes)', width: 150, type: 'rightAligned', valueFormatter: ent },
    { field: 'venta_prom_mes', headerName: 'Venta real prom. (u/mes)', width: 170, type: 'rightAligned', valueFormatter: ent, headerTooltip: 'Promedio de los meses cerrados, solo de los ítems con pronóstico' },
    { field: 'venta_ultimo_mes', headerName: 'Venta mes anterior', width: 150, type: 'rightAligned', valueFormatter: ent },
    { field: 'desvio_pct', headerName: 'Real vs pron.', width: 120, type: 'rightAligned', valueFormatter: (p: any) => p.value == null ? '' : (p.value > 0 ? '+' : '') + Number(p.value).toFixed(0) + '%',
      cellStyle: (p: any) => p.value == null ? null : Math.abs(p.value) > 30 ? { color: '#c62828', fontWeight: 600 } : null, headerTooltip: 'Si se aleja mucho, ajusta el pronóstico en el maestro o acorta/alarga el espejo' },
    { field: 'fecha_apertura', headerName: 'Apertura', width: 120 },
    { field: 'creado_por', headerName: 'Creó', width: 130 },
    { headerName: '', width: 130, pinned: 'right', sortable: false, cellRenderer: (p: any) => !edita ? null :
      <Button size="small" color={p.data.activa ? 'warning' : 'primary'} onClick={() => cambiar(p.data, { activa: !p.data.activa })}>{p.data.activa ? 'Cerrar espejo' : 'Reactivar'}</Button> },
  ], [edita, op])

  const r = prev?.resumen
  return (
    <Box sx={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr)', gap: 1.5 }}>
      <Stack direction="row" sx={{ alignItems: 'center', gap: 1 }}>
        <Button size="small" startIcon={<ArrowBack />} onClick={() => nav('/config')}>Maestros</Button>
        <Typography variant="h6" sx={{ fontWeight: 700 }}>Apertura de tienda</Typography>
        <Button size="small" startIcon={<HelpOutline />} onClick={() => setGuia(true)}>¿Cómo funciona? · Paso a paso</Button>
      </Stack>
      {msg && <Alert severity={msg.t} onClose={() => setMsg(null)}>{msg.m}</Alert>}
      <Tabs value={tab} onChange={(_, v) => setTab(v)}>
        <Tab label="Nueva apertura" /><Tab label={`Aperturas en curso (${lista.filter(a => a.activa).length})`} />
      </Tabs>

      {tab === 0 && (<>
        {!edita && <Alert severity="info">Tu perfil puede ver esta pantalla pero no crear aperturas (requiere cargar maestros).</Alert>}
        <Card variant="outlined" sx={{ p: 2, display: 'grid', gap: 1.5, gridTemplateColumns: { xs: 'minmax(0, 1fr)', md: 'repeat(3, minmax(0, 1fr))' } }}>
          {(op?.config && true) && <TextField select size="small" label="Empresa" value={empresa} onChange={e => { setEmpresa(e.target.value); setEspejo(null); setDestino(null) }}>
            {[...new Set((op?.bitacora ?? []).map(t => t.empresa))].map(e => <MenuItem key={e} value={e}>{e}</MenuItem>)}</TextField>}
          <Autocomplete size="small" options={tiendas} value={espejo} onChange={(_, v) => setEspejo(v)} getOptionLabel={etiqueta} isOptionEqualToValue={(a, b) => a.bodega_id === b.bodega_id}
            renderInput={p => <TextField {...p} label="Tienda espejo (la que se parece)" />} />
          <Autocomplete size="small" options={nuevas} value={destino} onChange={(_, v) => { setDestino(v); setNombre(v?.nombre ?? '') }} getOptionLabel={etiqueta} isOptionEqualToValue={(a, b) => a.bodega_id === b.bodega_id}
            freeSolo={false} renderInput={p => <TextField {...p} label="Tienda nueva" helperText={destino ? (destinoEnBitacora ? 'Ya está en la Bitácora' : 'Se dará de alta en la Bitácora') : 'Elígela de la lista (debe existir la bodega en Siesa)'} />} />
          {destino && !destinoEnBitacora && <TextField size="small" label="Nombre de la tienda" value={nombre} onChange={e => setNombre(e.target.value)} />}
          <TextField size="small" label="Factor" type="number" value={factor} onChange={e => setFactor(e.target.value)} slotProps={{ htmlInput: { step: 0.1, min: 0.1, max: 10 } }}
            helperText="1 = igual que la espejo; 0,8 = 20% menos" />
          <TextField select size="small" label="Base del pronóstico" value={base} onChange={e => setBase(e.target.value as any)}>
            <MenuItem value="venta">Venta mensual promedio de la espejo</MenuItem><MenuItem value="pronostico">Pronóstico que ya tiene la espejo</MenuItem></TextField>
          {base === 'venta' && <TextField size="small" label="Meses de venta a promediar" type="number" value={baseMeses} onChange={e => setBaseMeses(e.target.value)} slotProps={{ htmlInput: { min: 1, max: 12 } }} />}
          <TextField size="small" label="Meses que dura el espejo" type="number" value={meses} onChange={e => setMeses(e.target.value)} slotProps={{ htmlInput: { min: 1, max: op?.config.max_meses ?? 12 } }}
            helperText="Mientras la tienda tenga menos meses de venta que esto, manda el pronóstico; después, su propio historial. El mes de apertura cuenta." />
          <TextField size="small" label="Fecha de apertura" type="date" value={fecha} onChange={e => setFecha(e.target.value)} slotProps={{ inputLabel: { shrink: true } }} helperText="Solo informativa" />
          <TextField select size="small" label="Si la tienda nueva ya tiene pronósticos" value={modo} onChange={e => setModo(e.target.value as any)}>
            <MenuItem value="reemplazar">Reemplazar: dejarla como la espejo</MenuItem><MenuItem value="completar">Completar: solo agregar lo que le falte</MenuItem></TextField>
          <Box sx={{ gridColumn: { md: '1 / -1' }, display: 'flex', flexWrap: 'wrap', columnGap: 2 }}>
            <FormControlLabel control={<Checkbox checked={cotas} onChange={e => setCotas(e.target.checked)} />} label="Copiar cotas" />
            <FormControlLabel control={<Checkbox checked={nxp} onChange={e => setNxp(e.target.checked)} />} label="Copiar NxP (y no cargarlos)" />
            <FormControlLabel control={<Checkbox checked={dia} onChange={e => setDia(e.target.checked)} />} label="Copiar día de abastecimiento" />
            <FormControlLabel control={<Checkbox checked={bit} onChange={e => setBit(e.target.checked)} />} label="Copiar lead time y frecuencia" />
          </Box>
          <Box><Button variant="contained" disabled={!formOk || cargando || !edita} onClick={verPrevia}>{cargando && !prev ? 'Calculando…' : 'Ver vista previa'}</Button></Box>
        </Card>

        {prev && r && (<>
          <Stack direction="row" sx={{ gap: 1, flexWrap: 'wrap' }}>
            <Kpi t="Ítems a cargar" v={elegidas.length.toLocaleString('es-CO') + ' de ' + prev.filas.length.toLocaleString('es-CO')} />
            <Kpi t="Unidades / mes" v={Math.round(totalUn).toLocaleString('es-CO')} />
            <Kpi t="Con cotas" v={String(r.con_cotas)} />
            <Kpi t="NxP excluidos" v={String(r.nxp_excluidos)} />
            {r.meses_base && <Kpi t="Base" v={`${r.meses_base} meses (${r.desde}–${r.hasta})`} />}
            <Kpi t="Espejo dura" v={`${meses} meses`} />
          </Stack>
          {(r.avisos ?? []).map((a: string, i: number) => <Alert key={i} severity="warning">{a}</Alert>)}
          {r.destino_pronosticos > 0 && <Alert severity="info">La tienda nueva ya tiene {r.destino_pronosticos} pronósticos. Con «{modo === 'reemplazar' ? 'Reemplazar' : 'Completar'}» {modo === 'reemplazar' ? 'quedará igual que la espejo' : 'solo se agregan los que le faltan'}.</Alert>}
          {r.apertura_previa && <Alert severity="warning">Esta tienda ya tiene una apertura activa: al aplicar se reemplaza por esta.</Alert>}
          <Box sx={{ height: '55vh', minHeight: 320 }}>
            <Tabla memoria="apertura_previa" rowData={prev.filas} columnDefs={cols} defaultColDef={COL_DEF} getRowId={(p: any) => p.data.producto_id} stopEditingWhenCellsLoseFocus
              onGridReady={(e: any) => { gridApi.current = e.api }} onCellValueChanged={() => setVers(v => v + 1)} vacio="La espejo no tiene ítems para copiar" />
          </Box>
          <Stack direction="row" sx={{ gap: 1 }}>
            <Button variant="contained" color="success" disabled={!edita || !elegidas.length || cargando} onClick={() => setConfirmar(true)}>Aplicar apertura</Button>
            <Button onClick={() => setPrev(null)}>Descartar</Button>
          </Stack>
        </>)}
      </>)}

      {tab === 1 && (
        <Box sx={{ height: '65vh', minHeight: 320 }}>
          <Tabla memoria="apertura_curso" rowData={lista} columnDefs={colsLista} defaultColDef={COL_DEF} vacio="Aún no hay aperturas" stopEditingWhenCellsLoseFocus
            getRowId={(p: any) => p.data.empresa + '|' + p.data.bodega_id}
            onCellValueChanged={(e: any) => { if (e.colDef.field === 'meses_espejo' && e.newValue !== e.oldValue) cambiar(e.data, { meses_espejo: Number(e.newValue) }) }} />
        </Box>)}

      <Dialog open={confirmar} onClose={() => setConfirmar(false)}>
        <DialogTitle sx={{ fontWeight: 700 }}>¿Aplicar la apertura?</DialogTitle>
        <DialogContent>
          <Typography variant="body2" sx={{ mb: 1 }}>Tienda <b>{destino && etiqueta(destino)}</b> como espejo de <b>{espejo && etiqueta(espejo)}</b>:</Typography>
          <Box component="ul" sx={{ m: 0, pl: 3, '& li': { fontSize: 14 } }}>
            <li>{elegidas.length.toLocaleString('es-CO')} pronósticos ({Math.round(totalUn).toLocaleString('es-CO')} u/mes) — modo {modo}</li>
            <li>El pronóstico manda durante <b>{meses} meses</b> de venta de la tienda; después, su historial</li>
            <li>{[cotas && 'cotas', nxp && 'NxP', dia && 'día de abastecimiento', bit && 'lead time y frecuencia'].filter(Boolean).join(', ') || 'sin copiar nada más'}</li>
          </Box>
          <Typography variant="caption" color="text.secondary">Se aplica en la próxima corrida del motor.</Typography>
        </DialogContent>
        <DialogActions><Button onClick={() => setConfirmar(false)}>Cancelar</Button><Button variant="contained" onClick={aplicar}>Aplicar</Button></DialogActions>
      </Dialog>
      <GuiaApertura abierta={guia} cerrar={() => setGuia(false)} />
    </Box>)
}
