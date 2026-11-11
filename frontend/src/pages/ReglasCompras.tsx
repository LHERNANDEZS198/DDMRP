import { useEffect, useState } from 'react'
import { Box, Card, CardContent, CardHeader, Chip, MenuItem, Stack, TextField, Typography } from '@mui/material'
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
