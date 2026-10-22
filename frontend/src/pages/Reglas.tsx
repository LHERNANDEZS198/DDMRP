import { useEffect, useState } from 'react'
import { Alert, Box, Button, Card, CardContent, CardHeader, Chip, MenuItem, Stack, Table, TableBody, TableCell, TableRow, TextField, Typography } from '@mui/material'
import { Link as RouterLink } from 'react-router-dom'
import { api } from '../api'
import Aviso from '../Aviso'
import { useYo } from '../Yo'

type Regla = { clave: string; titulo: string; ayuda: string; opciones: { valor: number; label: string }[] | null; valor: number | null }

const grupos: [string, string[]][] = [
  ['Decisión de pedido', ['regla_disparo', 'regla_objetivo', 'regla_redondeo', 'cantidad_minima']],
  ['Qué entra al flujo neto y a lo sugerido', ['incluir_transito', 'restar_demanda_calificada', 'sumar_vectorizacion', 'vectorizacion_un_solo_uso']],
  ['Inventario del CEDI (cuando no alcanza)', ['cedi_regla_reparto']],
  ['Envío a las tiendas (Matriz de despacho)', ['valor_minimo_envio']],
  ['Qué items entran al modelo', ['solo_items_activos', 'rec_suma_original']],
  ['Datos de Siesa', ['etl_traer_ventas', 'inv_tiendas_resta_comprometido', 'inv_tiendas_resta_sin_acumular']],
  ['Parámetros del modelo (hoja Modelo)', ['meses_historia', 'meses_adu', 'pron_meses_minimos', 'mult_cota_max_promo', 'mult_cota_min_promo', 'adu_bajo_min', 'adu_bajo_max']],
  ['Historial (vistas de cambios y tendencia)', ['retener_dias']],
]

/** A que tiendas se reparte el inventario del CEDI cuando no alcanza: todas, o solo las de los DIAs elegidos. */
export function RepartoDias({ editar, onCambio, compacto, onElegidos }: { editar: boolean; onCambio: (m: string) => void; compacto?: boolean; onElegidos?: (e: number[]) => void }) {
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
    <Box sx={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr)', gap: 1 }}>
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
    <Box sx={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr)', gap: 1.5 }}>
      <Typography variant="body2" color="text.secondary">
        Escribe la tienda y la referencia (ej. SV021 y 190240): se consulta Siesa en vivo (existencia, comprometida y costos) y se compara con el inventario que tiene este sistema.
      </Typography>
      <Stack direction="row" sx={{ gap: 1, flexWrap: 'wrap' }}>
        <TextField size="small" label="Tienda" value={bodega} onChange={e => setBodega(e.target.value)} sx={{ width: 130 }} />
        <TextField size="small" label="Referencia" value={prod} onChange={e => setProd(e.target.value)} sx={{ width: 150 }} />
        <Button variant="outlined" disabled={!bodega.trim() || !prod.trim() || cargando} onClick={consultar}>{cargando ? 'Consultando…' : 'Consultar'}</Button>
      </Stack>
      {err && <Alert severity="error">{err}</Alert>}
      {res && (<Box sx={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr)', gap: 1 }}>
        <Alert severity={res.local.en_bitacora.length ? 'success' : 'warning'} sx={{ py: 0 }}>
          {res.local.en_bitacora.length ? `La tienda ${res.bodega} está en la bitácora (empresa ${res.local.en_bitacora[0].empresa}): el ETL trae su inventario.`
            : `La tienda ${res.bodega} NO está en la bitácora: el ETL no trae su inventario y el motor la ignora. Cárgala en Maestros → Bitácora.`}
        </Alert>
        <Alert severity="info" sx={{ py: 0 }}>
          Inventario que tiene el sistema: <b>{inv ? Number(inv.disponible).toLocaleString('es-CO') : 'sin fila (cuenta como 0)'}</b>{inv ? ` (corte ${inv.fecha_corte})` : ''}
          {' · '}{(res.local.resta_comprometido ? 'se calcula como existencia − comprometida' : 'se calcula como la existencia (sin restar lo comprometido)') + (res.local.resta_sin_acumular ? ' − ventas sin acumular' : '')}
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
        {res.etl?.map((e: any) => (
          <Alert key={e.empresa} severity={e.error ? 'error' : /NO pasa|inactiva/.test(e.causa || '') ? 'warning' : 'info'} sx={{ py: 0.5, '& .MuiAlert-message': { width: '100%' } }}>
            <b>Por qué el ETL {inv ? 'trae ese valor' : 'no lo trae'} · empresa {e.empresa}</b>
            {e.error ? <div>{e.error}</div> : <>
              <div>{e.causa}</div>
              <Table size="small"><TableBody>
                {e.pasos.map((p: any) => <TableRow key={p.filtro}><TableCell sx={{ py: 0.2 }}>{p.filtro}</TableCell><TableCell sx={{ py: 0.2 }} align="right"><b>{typeof p.valor === 'number' ? p.valor.toLocaleString('es-CO') : p.valor}</b></TableCell></TableRow>)}
              </TableBody></Table>
              <div style={{ fontSize: 12 }}>Extensiones del item en Siesa ({e.extensiones_nota}): {e.extensiones.map((x: any) => `#${x.rowid} → ${x.estado}`).join(' · ') || 'ninguna'}
                {' · '}En el maestro: {res.local.en_maestro ? 'sí' : 'NO'}{' · '}Estado guardado: {res.local.estado?.map((x: any) => `${x.empresa}=${x.estado}`).join(', ') || 'sin fila'}
                {' · '}Filas de la tienda en el sistema: {res.local.filas_bodega} (corte {res.local.ultimo_etl_inventario})</div>
            </>}
          </Alert>))}
        {!res.siesa.length && !res.aviso && <Alert severity="warning" sx={{ py: 0 }}>Siesa no devolvió filas de existencia para esa tienda y referencia.</Alert>}
      </Box>)}
    </Box>)
}

export default function Reglas() {
  const { puede } = useYo(); const editar = puede('editar_reglas'); const motor = puede('correr_motor')
  const [reglas, setReglas] = useState<Regla[]>([])
  const [msg, setMsg] = useState('')
  const cargar = () => api('/reglas').then(setReglas).catch(e => setMsg('Error: ' + e.message))
  useEffect(() => { cargar() }, [])
  const guardar = async (r: Regla, valor: number) => {
    try { const x = await api('/reglas/' + r.clave, { method: 'PUT', body: JSON.stringify({ valor }) }); setMsg(`${r.titulo}: guardado. ${x.aviso}`); cargar() }
    catch (e: any) { setMsg('Error: ' + e.message) }
  }
  return (
    <Box sx={{ maxWidth: 860, mx: 'auto', display: 'grid', gridTemplateColumns: 'minmax(0, 1fr)', gap: 2 }}>
      <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1} sx={{ alignItems: { sm: 'center' } }}>
        <Typography variant="h6" sx={{ flex: 1, fontWeight: 700 }}>Reglas de pedido</Typography>
        {motor && <Button variant="outlined" component={RouterLink} to="/motor">Ir a Motor DDMRP (recalcular / ETL)</Button>}
      </Stack>
      <Typography variant="body2" color="text.secondary">
        Los cambios se aplican en la siguiente corrida del motor (cada noche, o cuando recalcules en Motor DDMRP). Flujo neto = inventario + tránsito − demanda calificada.
      </Typography>
      {grupos.map(([titulo, claves]) => (
        <Card key={titulo} variant="outlined">
          <CardHeader title={titulo} slotProps={{ title: { variant: 'subtitle1', fontWeight: 700 } }} sx={{ bgcolor: '#eef2e3', py: 1 }} />
          <CardContent sx={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr)', gap: 2 }}>
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
