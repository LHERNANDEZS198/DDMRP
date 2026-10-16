import { useEffect, useState } from 'react'
import { Box, Button, Card, CardContent, CardHeader, MenuItem, Stack, TextField, Typography } from '@mui/material'
import Calculate from '@mui/icons-material/Calculate'
import PlayCircle from '@mui/icons-material/PlayCircle'
import { api, conProgreso, seguirTarea } from '../api'
import Aviso from '../Aviso'
import { useYo } from '../Yo'

type Regla = { clave: string; titulo: string; ayuda: string; opciones: { valor: number; label: string }[] | null; valor: number | null }

const grupos: [string, string[]][] = [
  ['Decisión de pedido', ['regla_disparo', 'regla_objetivo', 'regla_redondeo', 'cantidad_minima']],
  ['Qué entra al flujo neto y a lo sugerido', ['incluir_transito', 'restar_demanda_calificada', 'sumar_vectorizacion']],
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
      <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1} sx={{ alignItems: { sm: 'center' } }}>
        <Typography variant="h6" sx={{ flex: 1, fontWeight: 700 }}>Reglas de pedido</Typography>
        {motor && <Button variant="outlined" startIcon={<Calculate />} onClick={recalcular}>Recalcular ahora (solo motor)</Button>}
        {motor && <Button variant="contained" startIcon={<PlayCircle />} onClick={pipeline}>Correr ETL + motor completo</Button>}
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
