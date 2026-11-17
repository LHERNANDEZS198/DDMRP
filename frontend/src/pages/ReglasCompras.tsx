import { useEffect, useState } from 'react'
import { Box, Button, Card, CardContent, CardHeader, Chip, MenuItem, Stack, TextField, Typography } from '@mui/material'
import { api } from '../api'
import Aviso from '../Aviso'
import { useYo } from '../Yo'
import { BarraEmpresaReglas, useEmpresaReglas } from '../SelectorEmpresaReglas'
import { NOMBRE_EMPRESA } from '../Empresa'

type Regla = { grupo: string; clave: string; titulo: string; ayuda: string; opciones: { valor: number; label: string }[] | null; valor: number | null; min?: number; propio?: boolean; global?: boolean }

/** Reglas de compras: pedido mínimo, poca historia, frecuencia por defecto y revisión de las OC. Antes eran el maestro «Configuración de compras». */
export default function ReglasCompras() {
  const { puede } = useYo(); const editar = puede('cargar_maestros_compras', 'editar_reglas_compras')
  const [reglas, setReglas] = useState<Regla[]>([])
  const [msg, setMsg] = useState('')
  // conexión con el BPM (no es por empresa): URL y secreto; lo vacío cae al .env del servidor. El secreto nunca vuelve a la pantalla.
  const [cx, setCx] = useState<any>(null); const [cxUrl, setCxUrl] = useState(''); const [cxSec, setCxSec] = useState('')
  const [ws, setWs] = useState<Record<string, string>>({})     // web service de Siesa de la empresa elegida (envío directo, contingencia)
  const cargarCx = () => api('/reglas/conexiones').then(x => { setCx(x); setCxUrl(x.bpm_url ?? ''); setWs({}) }).catch(() => {})
  useEffect(() => { cargarCx() }, [])
  useEffect(() => { setWs({}) }, [emp])
  const wsE = cx?.ws?.[emp] ?? {}
  const wsVal = (k: string) => ws[k] ?? wsE[k] ?? ''
  const guardarCx = async () => {
    try { await api('/reglas/conexiones', { method: 'PUT', body: JSON.stringify({ bpm_url: cxUrl, bpm_secret: cxSec, ws: Object.keys(ws).length ? { [emp]: ws } : undefined }) }); setCxSec(''); setMsg('Conexión con el BPM guardada.'); cargarCx() }
    catch (e: any) { setMsg('Error: ' + e.message) }
  }
  const er = useEmpresaReglas(); const emp = er.emp
  const cargar = () => api('/reglas/compras?empresa=' + emp).then(setReglas).catch(e => setMsg('Error: ' + e.message))
  useEffect(() => { setReglas([]); cargar() }, [emp])
  const restablecer = async (r: Regla) => {
    try { const x = await api('/reglas/compras/' + r.clave + '?empresa=' + emp, { method: 'DELETE' }); setMsg(`${r.titulo}: ${x.aviso}`); cargar() }
    catch (e: any) { setMsg('Error: ' + e.message) }
  }
  const guardar = async (r: Regla, valor: number) => {
    try { const x = await api('/reglas/compras/' + r.clave, { method: 'PUT', body: JSON.stringify({ valor, empresa: emp }) }); setMsg(`${r.titulo}: guardado. ${x.aviso}`); cargar() }
    catch (e: any) { setMsg('Error: ' + e.message) }
  }
  const grupos = [...new Set(reglas.map(r => r.grupo))]
  return (
    <Box sx={{ maxWidth: 860, mx: 'auto', display: 'grid', gridTemplateColumns: 'minmax(0, 1fr)', gap: 2 }}>
      <Typography variant="h6" sx={{ fontWeight: 700 }}>Reglas de compras</Typography>
      <BarraEmpresaReglas {...er} />
      <Typography variant="body2" color="text.secondary">
        Cada empresa tiene sus reglas (las marcadas «Todas las empresas» son del sistema). Cómo se calculan y se revisan las compras. Los cambios se aplican de inmediato (no hace falta correr el motor).{!editar && ' Tu perfil solo puede verlas.'}
      </Typography>
      {cx && <Card variant="outlined">
        <CardHeader title="Conexión con el BPM" slotProps={{ title: { variant: 'subtitle1', fontWeight: 700 } }} sx={{ bgcolor: '#eef2e3', py: 1 }} />
        <CardContent sx={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr)', gap: 1.5 }}>
          <Typography variant="body2" color="text.secondary">A dónde se entregan las OC cuando el envío es «Al BPM». Lo que dejes vacío usa lo que tenga el servidor en su .env. Aplica a todas las empresas. El secreto debe ser el mismo del BPM (Admin → Conexiones).</Typography>
          <TextField size="small" label="URL del BPM" placeholder="https://bpm.funat.com.co" disabled={!editar} value={cxUrl} onChange={e => setCxUrl(e.target.value)}
            helperText={`Origen: ${cx.bpm_url_origen}`} />
          <TextField size="small" type="password" label="Secreto compartido" autoComplete="new-password" disabled={!editar} value={cxSec} onChange={e => setCxSec(e.target.value)}
            placeholder={cx.bpm_secret_configurado ? '•••••••• (configurado; escribe uno nuevo para cambiarlo)' : 'sin configurar'} helperText={`Origen: ${cx.bpm_secret_origen}`} />
          <Typography variant="subtitle2" sx={{ fontWeight: 700, mt: 1 }}>Envío directo a Siesa (contingencia) · {NOMBRE_EMPRESA[emp] ?? emp} ({emp})</Typography>
          <Typography variant="body2" color="text.secondary">Solo se usa cuando el envío de la empresa es «Directo a Siesa». Si no está completo (aquí o en el .env) no pasa nada: ese envío simplemente no se hace. Stores usa la URL, usuario, clave y compañía de Funat si no tiene los suyos; el nombre de conexión sí es propio.</Typography>
          {(['url', 'usuario', 'conexion', 'cia'] as const).map(k => (
            <TextField key={k} size="small" disabled={!editar} value={wsVal(k)} onChange={e => setWs({ ...ws, [k]: e.target.value })}
              label={{ url: 'URL del web service', usuario: 'Usuario', conexion: 'Nombre de la conexión', cia: 'Compañía (IdCia)' }[k]}
              placeholder={k === 'url' ? 'https://ws.funat.com.co:9160/WSUNOEE/WSUNOEE.asmx' : ''} helperText={`Origen: ${wsE[k + '_origen'] ?? '—'}`} />))}
          <TextField size="small" type="password" label="Clave" autoComplete="new-password" disabled={!editar} value={ws.clave ?? ''} onChange={e => setWs({ ...ws, clave: e.target.value })}
            placeholder={wsE.clave_configurada ? '•••••••• (configurada; escribe una nueva para cambiarla)' : 'sin configurar'} helperText={`Origen: ${wsE.clave_origen ?? '—'}`} />
          <Chip size="small" sx={{ alignSelf: 'start' }} color={wsE.listo ? 'success' : 'default'} label={wsE.listo ? 'Envío directo listo' : 'Envío directo sin configurar (no hace nada)'} />
          <Box><Button variant="contained" disabled={!editar || (cxUrl === (cx.bpm_url ?? '') && !cxSec && !Object.keys(ws).length)} onClick={guardarCx}>Guardar conexión</Button></Box>
        </CardContent>
      </Card>}
      {grupos.map(g => (
        <Card key={g} variant="outlined">
          <CardHeader title={g} slotProps={{ title: { variant: 'subtitle1', fontWeight: 700 } }} sx={{ bgcolor: '#eef2e3', py: 1 }} />
          <CardContent sx={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr)', gap: 2 }}>
            {reglas.filter(r => r.grupo === g).map(r => (
              <Box key={r.clave} sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', sm: '1fr 280px' }, gap: 1, alignItems: 'center' }}>
                <Stack><Typography sx={{ fontWeight: 600 }}>{r.titulo}{r.global && <Chip size="small" label="Todas las empresas" sx={{ ml: 1 }} />}{r.propio && <Chip size="small" color="warning" label={`Propia de ${NOMBRE_EMPRESA[emp] ?? emp}`} sx={{ ml: 1 }} onDelete={editar ? () => restablecer(r) : undefined} />}</Typography><Typography variant="caption" color="text.secondary">{r.ayuda}</Typography></Stack>
                {r.opciones
                  ? <TextField select size="small" disabled={!editar} value={r.valor ?? ''} onChange={e => guardar(r, Number(e.target.value))}>
                      {r.opciones.map(o => <MenuItem key={o.valor} value={o.valor}>{o.label}</MenuItem>)}</TextField>
                  : <TextField type="number" size="small" disabled={!editar} defaultValue={r.valor ?? ''} key={r.valor} slotProps={{ htmlInput: { step: 'any', min: r.min ?? 0 } }}
                      onBlur={e => { if (e.target.value === '') return; const v = Number(e.target.value); if (v !== r.valor) guardar(r, v) }} />}
              </Box>))}
          </CardContent>
        </Card>))}
      <Aviso msg={msg} onClose={() => setMsg('')} />
    </Box>)
}
