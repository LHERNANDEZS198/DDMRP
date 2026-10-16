import { useEffect, useState } from 'react'
import { Alert, Box, Button, Card, CardContent, CardHeader, Chip, Dialog, DialogActions, DialogContent, DialogTitle, MenuItem, Stack, Table, TableBody, TableCell, TableRow, TextField, Typography } from '@mui/material'
import Calculate from '@mui/icons-material/Calculate'
import PlayCircle from '@mui/icons-material/PlayCircle'
import { api, conProgreso, seguirTarea } from '../api'
import Aviso from '../Aviso'
import { useYo } from '../Yo'
import { useSalud } from '../Salud'

type Regla = { clave: string; titulo: string; ayuda: string; opciones: { valor: number; label: string }[] | null; valor: number | null }

const grupos: [string, string[]][] = [
  ['Decisión de pedido', ['regla_disparo', 'regla_objetivo', 'regla_redondeo', 'cantidad_minima']],
  ['Qué entra al flujo neto y a lo sugerido', ['incluir_transito', 'restar_demanda_calificada', 'sumar_vectorizacion']],
  ['Inventario del CEDI (cuando no alcanza)', ['cedi_regla_reparto']],
  ['Envío a las tiendas (Matriz de despacho)', ['valor_minimo_envio']],
  ['Datos de Siesa', ['etl_traer_ventas', 'inv_tiendas_resta_comprometido']],
  ['Parámetros del modelo (hoja Modelo)', ['meses_historia', 'meses_adu', 'mult_cota_max_promo', 'mult_cota_min_promo', 'adu_bajo_min', 'adu_bajo_max']],
  ['Historial (vistas de cambios y tendencia)', ['retener_dias']],
]

/** A que tiendas se reparte el inventario del CEDI cuando no alcanza: todas, o solo las de los DIAs elegidos. */
function RepartoDias({ editar, onCambio, compacto, onElegidos }: { editar: boolean; onCambio: (m: string) => void; compacto?: boolean; onElegidos?: (e: number[]) => void }) {
  const [d, setD] = useState<{ elegidos: number[]; dias: { dia: number; tiendas: number }[] } | null>(null)
  const cargar = () => api('/reglas/reparto-dias').then(x => { setD(x); onElegidos?.(x.elegidos) }).catch(() => {})
  useEffect(() => { cargar() }, [])
  const guardar = async (dias: number[]) => {
    try { const x = await api('/reglas/reparto-dias', { method: 'PUT', body: JSON.stringify({ dias }) }); onCambio(`Reparto del CEDI: guardado. ${x.aviso}`); cargar() }
    catch (e: any) { onCambio('Error: ' + e.message) }
  }
  if (!d) return null
  const todas = d.elegidos.length === 0
  const alternar = (dia: number) => guardar(d.elegidos.includes(dia) ? d.elegidos.filter(x => x !== dia) : [...d.elegidos, dia].sort((a, b) => a - b))
  return (
    <Box sx={{ display: 'grid', gap: 1 }}>
      <Box><Typography sx={{ fontWeight: 600 }}>{compacto ? '¿Entre qué tiendas se reparte el stock del CEDI en esta corrida?' : 'Entre qué tiendas se reparte el inventario del CEDI'}</Typography>
        {!compacto && <Typography variant="caption" color="text.secondary">
          La necesidad de cada referencia se suma entre las tiendas que entran al reparto; si el CEDI no alcanza, se reparte entre ellas con la regla de arriba.
          <b> Todas</b>: compiten las tiendas de todos los DIAs (cada referencia se reparte entre todas, aunque hoy no se despache a algunas).
          <b> DIAs elegidos</b> (p. ej. DIA 1 + DIA 2): solo compiten las tiendas de esos DIAs; las demás quedan con lo que pide su buffer, sin gastar stock del CEDI.
          Una tienda que esté en varios DIAs entra si alguno de ellos está elegido.</Typography>}</Box>
      <Stack direction="row" sx={{ gap: 1, flexWrap: 'wrap', alignItems: 'center' }}>
        <Chip label="Todas las tiendas" color={todas ? 'primary' : 'default'} variant={todas ? 'filled' : 'outlined'} disabled={!editar} onClick={() => guardar([])} />
        {d.dias.map(x => <Chip key={x.dia} label={`DIA ${x.dia} (${x.tiendas} tiendas)`} disabled={!editar}
          color={d.elegidos.includes(x.dia) ? 'primary' : 'default'} variant={d.elegidos.includes(x.dia) ? 'filled' : 'outlined'} onClick={() => alternar(x.dia)} />)}
        {!d.dias.length && <Typography variant="caption" color="text.secondary">Aún no hay DIAs: cárgalos en Maestros → DIA de abastecimiento por tienda.</Typography>}
      </Stack>
    </Box>)
}

/** Para entender por que un inventario no cuadra: lo que dice Siesa (en vivo) frente a lo que tiene el sistema. */
function Diagnostico() {
  const [bodega, setBodega] = useState(''); const [prod, setProd] = useState('')
  const [res, setRes] = useState<any>(null); const [err, setErr] = useState(''); const [cargando, setCargando] = useState(false)
  const consultar = async () => {
    setErr(''); setRes(null); setCargando(true)
    try { setRes(await api(`/admin/diagnostico-inventario?bodega=${encodeURIComponent(bodega.trim())}&producto=${encodeURIComponent(prod.trim())}`)) }
    catch (e: any) { setErr(e.message) } finally { setCargando(false) }
  }
  const inv = res?.local?.inventario_actual?.[0]
  return (
    <Box sx={{ display: 'grid', gap: 1.5 }}>
      <Typography variant="body2" color="text.secondary">
        Escribe la tienda y la referencia (ej. SV021 y 190240): se consulta Siesa en vivo (existencia, comprometida y costos) y se compara con el inventario que tiene este sistema.
      </Typography>
      <Stack direction="row" sx={{ gap: 1, flexWrap: 'wrap' }}>
        <TextField size="small" label="Tienda" value={bodega} onChange={e => setBodega(e.target.value)} sx={{ width: 130 }} />
        <TextField size="small" label="Referencia" value={prod} onChange={e => setProd(e.target.value)} sx={{ width: 150 }} />
        <Button variant="outlined" disabled={!bodega.trim() || !prod.trim() || cargando} onClick={consultar}>{cargando ? 'Consultando…' : 'Consultar'}</Button>
      </Stack>
      {err && <Alert severity="error">{err}</Alert>}
      {res && (<Box sx={{ display: 'grid', gap: 1 }}>
        <Alert severity={res.local.en_bitacora.length ? 'success' : 'warning'} sx={{ py: 0 }}>
          {res.local.en_bitacora.length ? `La tienda ${res.bodega} está en la bitácora (empresa ${res.local.en_bitacora[0].empresa}): el ETL trae su inventario.`
            : `La tienda ${res.bodega} NO está en la bitácora: el ETL no trae su inventario y el motor la ignora. Cárgala en Maestros → Bitácora.`}
        </Alert>
        <Alert severity="info" sx={{ py: 0 }}>
          Inventario que tiene el sistema: <b>{inv ? Number(inv.disponible).toLocaleString('es-CO') : 'sin fila (cuenta como 0)'}</b>{inv ? ` (corte ${inv.fecha_corte})` : ''}
          {' · '}{res.local.resta_comprometido ? 'se calcula como existencia − comprometida' : 'se calcula como la existencia (sin restar lo comprometido)'}
          {res.local.costo?.length ? ` · costo promedio guardado: $${Math.round(res.local.costo[0]).toLocaleString('es-CO')}` : ' · sin costo guardado'}
        </Alert>
        {res.aviso && <Alert severity="warning" sx={{ py: 0 }}>{res.aviso}</Alert>}
        {res.siesa.map((s: any, i: number) => (
          <Box key={i}>
            <Typography variant="subtitle2">Siesa · empresa {s.empresa} ({s.base})</Typography>
            {s.error ? <Alert severity="error" sx={{ py: 0 }}>{s.error}</Alert>
              : <Table size="small"><TableBody>
                  {Object.entries(s.columnas).map(([k, v]) => (
                    <TableRow key={k} sx={/exist|compr|costo/i.test(k) ? { bgcolor: '#fff8e1' } : undefined}>
                      <TableCell sx={{ fontFamily: 'monospace', py: 0.3 }}>{k}</TableCell><TableCell sx={{ py: 0.3 }}>{String(v)}</TableCell></TableRow>))}
                </TableBody></Table>}
          </Box>))}
        {!res.siesa.length && !res.aviso && <Alert severity="warning" sx={{ py: 0 }}>Siesa no devolvió filas de existencia para esa tienda y referencia.</Alert>}
      </Box>)}
    </Box>)
}

export default function Reglas() {
  const { puede } = useYo(); const editar = puede('editar_reglas'); const motor = puede('correr_motor')
  const { enCurso, refrescar } = useSalud()
  const [reglas, setReglas] = useState<Regla[]>([])
  const [msg, setMsg] = useState('')
  const cargar = () => api('/reglas').then(setReglas).catch(e => setMsg('Error: ' + e.message))
  useEffect(() => { cargar() }, [])
  const guardar = async (r: Regla, valor: number) => {
    try { const x = await api('/reglas/' + r.clave, { method: 'PUT', body: JSON.stringify({ valor }) }); setMsg(`${r.titulo}: guardado. ${x.aviso}`); cargar() }
    catch (e: any) { setMsg('Error: ' + e.message) }
  }
  // Antes de correr el motor, si ya corrió hoy, avisa qué se pierde de vista y pide confirmar
  const [aviso, setAviso] = useState<{ que: 'motor' | 'pipeline'; d: any } | null>(null)
  const preguntar = async (que: 'motor' | 'pipeline') => {
    try { const d = await api('/admin/motor-hoy'); setAviso({ que, d }); return } catch { /* si falla la consulta, no bloquea */ }
    que === 'motor' ? recalcular() : pipeline()
  }
  const recalcular = async () => {
    setMsg('Recalculando con el motor Rust…'); setTimeout(refrescar, 800)
    try { const x = await conProgreso(setMsg, () => api('/admin/correr-motor', { method: 'POST' })); setMsg(`Listo: ${x.filas} combinaciones calculadas`) } catch (e: any) { setMsg('Error: ' + e.message) } finally { refrescar() }
  }
  const pipeline = async () => {
    setMsg('Lanzando ETL + motor…')
    try {
      const previo = (await api('/admin/progreso')).inicio ?? null
      await api('/admin/correr-pipeline', { method: 'POST' }); setTimeout(refrescar, 800)
      const fin = await seguirTarea(setMsg, previo)
      setMsg(fin.estado === 'error' ? fin.mensaje : `Listo: ${fin.mensaje}. Revisa Alertas y Control.`)
    } catch (e: any) { setMsg('Error: ' + e.message) } finally { refrescar() }
  }
  return (
    <Box sx={{ maxWidth: 860, mx: 'auto', display: 'grid', gap: 2 }}>
      <Dialog open={!!aviso} onClose={() => setAviso(null)} maxWidth="sm" fullWidth>
        <DialogTitle>{aviso?.d.corrio_hoy ? 'El motor ya corrió hoy' : (aviso?.que === 'pipeline' ? 'Correr ETL + motor' : 'Recalcular con el motor')}</DialogTitle>
        <DialogContent sx={{ display: 'grid', gap: 1.5 }}>
          <Alert severity="info" sx={{ '& .MuiAlert-message': { width: '100%' } }}>
            <RepartoDias editar={editar} compacto onCambio={m => { if (m.startsWith('Error')) setMsg(m) }}
              onElegidos={e => setAviso(p => p ? { ...p, d: { ...p.d, dias_reparto: e } } : p)} />
            <Typography variant="body2" sx={{ mt: 1 }}>
              {aviso?.d.dias_reparto?.length
                ? <>Solo compiten por la escasez las tiendas de los <b>DIAs {aviso.d.dias_reparto.join(' + ')}</b>; las demás quedan con lo que pide su buffer.</>
                : <>Si el CEDI no alcanza, se reparte entre <b>todas las tiendas</b>.</>}
              {!editar && ' (No tienes permiso para cambiarlo.)'}
            </Typography>
          </Alert>
          {aviso?.d.corrio_hoy && <Typography>
            Ya hay {aviso?.d.corridas} corrida(s) de hoy (la última a las {aviso?.d.ultima ? new Date(aviso.d.ultima).toLocaleTimeString('es-CO', { hour: '2-digit', minute: '2-digit' }) : ''}).
            Si corres de nuevo:
          </Typography>}
          <Box component="ul" sx={{ m: 0, pl: 3, display: 'grid', gap: 0.5 }}>
            {aviso?.d.corrio_hoy && <li>La matriz de despacho y el plano pasan a usar <b>solo la corrida nueva</b>.</li>}
            {aviso?.d.corrio_hoy && <li>Todo vuelve a <b>Pendiente</b>: lo aprobado y las cantidades que hayas editado de la corrida anterior ya no se ven ni se exportan.</li>}
            {aviso?.d.corrio_hoy && <li>Las cantidades pueden cambiar porque el CEDI se reparte con el stock fresco de PT001.</li>}
            {aviso?.que === 'pipeline' && <li>También se vuelve a leer todo Siesa (inventario, tránsitos, items): tarda varios minutos.</li>}
          </Box>
          {(aviso?.d.aprobadas > 0 || aviso?.d.enviadas > 0) && (
            <Alert severity="warning">
              En la corrida actual hay <b>{aviso?.d.aprobadas}</b> fila(s) aprobada(s) y <b>{aviso?.d.enviadas}</b> enviada(s). Si aún no generaste el plano, genéralo antes de recalcular.
            </Alert>)}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setAviso(null)} autoFocus>Cancelar</Button>
          <Button color={aviso?.d.corrio_hoy ? 'warning' : 'primary'} variant="contained" onClick={() => { const q = aviso!.que; setAviso(null); q === 'motor' ? recalcular() : pipeline() }}>{aviso?.d.corrio_hoy ? 'Correr de todos modos' : 'Correr'}</Button>
        </DialogActions>
      </Dialog>
      <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1} sx={{ alignItems: { sm: 'center' } }}>
        <Typography variant="h6" sx={{ flex: 1, fontWeight: 700 }}>Reglas de pedido</Typography>
        {motor && <Button variant="outlined" startIcon={<Calculate />} disabled={enCurso} onClick={() => preguntar('motor')}>Recalcular ahora (solo motor)</Button>}
        {motor && <Button variant="contained" startIcon={<PlayCircle />} disabled={enCurso} onClick={() => preguntar('pipeline')}>Correr ETL + motor completo</Button>}
      </Stack>
      <Typography variant="body2" color="text.secondary">
        Los cambios se aplican en la siguiente corrida del motor (cada noche, o con “Recalcular ahora”). Flujo neto = inventario + tránsito − demanda calificada.
      </Typography>
      {grupos.map(([titulo, claves]) => (
        <Card key={titulo} variant="outlined">
          <CardHeader title={titulo} slotProps={{ title: { variant: 'subtitle1', fontWeight: 700 } }} sx={{ bgcolor: '#eef2e3', py: 1 }} />
          <CardContent sx={{ display: 'grid', gap: 2 }}>
            {claves.map(k => reglas.find(r => r.clave === k)).filter((r): r is Regla => !!r).map(r => (
              <Box key={r.clave} sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', sm: '1fr 280px' }, gap: 1, alignItems: 'center' }}>
                <Box><Typography sx={{ fontWeight: 600 }}>{r.titulo}</Typography><Typography variant="caption" color="text.secondary">{r.ayuda}</Typography></Box>
                {r.opciones
                  ? <TextField select size="small" disabled={!editar} value={r.valor ?? ''} onChange={e => guardar(r, Number(e.target.value))}>
                      {r.opciones.map(o => <MenuItem key={o.valor} value={o.valor}>{o.label}</MenuItem>)}</TextField>
                  : <TextField type="number" size="small" disabled={!editar} defaultValue={r.valor ?? 0} key={r.valor} slotProps={{ htmlInput: { step: 'any', min: 0 } }}
                      onBlur={e => { const v = Number(e.target.value); if (v !== r.valor) guardar(r, v) }} />}
              </Box>))}
            {titulo.startsWith('Inventario del CEDI') && <RepartoDias editar={editar} onCambio={setMsg} />}
          </CardContent>
        </Card>))}
      {(puede('sincronizar_siesa') || motor) && (
        <Card variant="outlined">
          <CardHeader title="Revisar un inventario (Siesa vs este sistema)" slotProps={{ title: { variant: 'subtitle1', fontWeight: 700 } }} sx={{ bgcolor: '#eef2e3', py: 1 }} />
          <CardContent><Diagnostico /></CardContent>
        </Card>)}
      <Aviso msg={msg} onClose={() => setMsg('')} />
    </Box>)
}
