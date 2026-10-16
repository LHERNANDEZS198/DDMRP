import { useEffect, useState } from 'react'
import { Alert, Box, Button, Card, CardContent, CardHeader, Dialog, DialogActions, DialogContent, DialogTitle, MenuItem, Stack, TextField, Typography } from '@mui/material'
import Calculate from '@mui/icons-material/Calculate'
import PlayCircle from '@mui/icons-material/PlayCircle'
import { api, conProgreso, seguirTarea } from '../api'
import Aviso from '../Aviso'
import { useYo } from '../Yo'

type Regla = { clave: string; titulo: string; ayuda: string; opciones: { valor: number; label: string }[] | null; valor: number | null }

const grupos: [string, string[]][] = [
  ['Decisión de pedido', ['regla_disparo', 'regla_objetivo', 'regla_redondeo', 'cantidad_minima']],
  ['Qué entra al flujo neto y a lo sugerido', ['incluir_transito', 'restar_demanda_calificada', 'sumar_vectorizacion']],
  ['Inventario del CEDI (cuando no alcanza)', ['cedi_regla_reparto']],
  ['Datos de Siesa', ['etl_traer_ventas']],
  ['Parámetros del modelo (hoja Modelo)', ['meses_historia', 'meses_adu', 'mult_cota_max_promo', 'mult_cota_min_promo', 'adu_bajo_min', 'adu_bajo_max']],
  ['Historial (vistas de cambios y tendencia)', ['retener_dias']],
]

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
  // Antes de correr el motor, si ya corrió hoy, avisa qué se pierde de vista y pide confirmar
  const [aviso, setAviso] = useState<{ que: 'motor' | 'pipeline'; d: any } | null>(null)
  const preguntar = async (que: 'motor' | 'pipeline') => {
    try { const d = await api('/admin/motor-hoy'); if (d.corrio_hoy) { setAviso({ que, d }); return } } catch { /* si falla la consulta, no bloquea */ }
    que === 'motor' ? recalcular() : pipeline()
  }
  const recalcular = async () => {
    setMsg('Recalculando con el motor Rust…')
    try { const x = await conProgreso(setMsg, () => api('/admin/correr-motor', { method: 'POST' })); setMsg(`Listo: ${x.filas} combinaciones calculadas`) } catch (e: any) { setMsg('Error: ' + e.message) }
  }
  const pipeline = async () => {
    setMsg('Lanzando ETL + motor…')
    try {
      const previo = (await api('/admin/progreso')).inicio ?? null
      await api('/admin/correr-pipeline', { method: 'POST' })
      const fin = await seguirTarea(setMsg, previo)
      setMsg(fin.estado === 'error' ? fin.mensaje : `Listo: ${fin.mensaje}. Revisa Alertas y Control.`)
    } catch (e: any) { setMsg('Error: ' + e.message) }
  }
  return (
    <Box sx={{ maxWidth: 860, mx: 'auto', display: 'grid', gap: 2 }}>
      <Dialog open={!!aviso} onClose={() => setAviso(null)} maxWidth="sm" fullWidth>
        <DialogTitle>El motor ya corrió hoy</DialogTitle>
        <DialogContent sx={{ display: 'grid', gap: 1.5 }}>
          <Typography>
            Ya hay {aviso?.d.corridas} corrida(s) de hoy (la última a las {aviso?.d.ultima ? new Date(aviso.d.ultima).toLocaleTimeString('es-CO', { hour: '2-digit', minute: '2-digit' }) : ''}).
            Si corres de nuevo:
          </Typography>
          <Box component="ul" sx={{ m: 0, pl: 3, display: 'grid', gap: 0.5 }}>
            <li>La matriz de despacho y el plano pasan a usar <b>solo la corrida nueva</b>.</li>
            <li>Todo vuelve a <b>Pendiente</b>: lo aprobado y las cantidades que hayas editado de la corrida anterior ya no se ven ni se exportan.</li>
            <li>El reparto del inventario del CEDI se recalcula con el stock fresco de PT001, así que las cantidades pueden cambiar.</li>
            {aviso?.que === 'pipeline' && <li>También se vuelve a leer todo Siesa (inventario, tránsitos, items): tarda varios minutos.</li>}
          </Box>
          {(aviso?.d.aprobadas > 0 || aviso?.d.enviadas > 0) && (
            <Alert severity="warning">
              En la corrida actual hay <b>{aviso?.d.aprobadas}</b> fila(s) aprobada(s) y <b>{aviso?.d.enviadas}</b> enviada(s). Si aún no generaste el plano, genéralo antes de recalcular.
            </Alert>)}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setAviso(null)} autoFocus>Cancelar</Button>
          <Button color="warning" variant="contained" onClick={() => { const q = aviso!.que; setAviso(null); q === 'motor' ? recalcular() : pipeline() }}>Correr de todos modos</Button>
        </DialogActions>
      </Dialog>
      <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1} sx={{ alignItems: { sm: 'center' } }}>
        <Typography variant="h6" sx={{ flex: 1, fontWeight: 700 }}>Reglas de pedido</Typography>
        {motor && <Button variant="outlined" startIcon={<Calculate />} onClick={() => preguntar('motor')}>Recalcular ahora (solo motor)</Button>}
        {motor && <Button variant="contained" startIcon={<PlayCircle />} onClick={() => preguntar('pipeline')}>Correr ETL + motor completo</Button>}
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
          </CardContent>
        </Card>))}
      <Aviso msg={msg} onClose={() => setMsg('')} />
    </Box>)
}
