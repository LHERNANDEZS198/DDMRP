import { createContext, ReactNode, useCallback, useContext, useEffect, useRef, useState } from 'react'
import { Alert, AlertTitle, Box, Button, CircularProgress } from '@mui/material'
import { Link as RouterLink } from 'react-router-dom'
import { api } from './api'
import { useYo } from './Yo'

type Problema = { tipo: 'etl' | 'motor'; estado: 'error' | 'interrumpido'; mensaje: string | null; inicio: string; origen: string; usuario: string | null }
export type Salud = {
  en_curso: { tarea: string; mensaje: string; segundos: number } | null
  problemas: Problema[]
  ultimo_motor_ok: { fecha: string; fin: string } | null
  horas_sin_motor: number | null
  sin_corridas: boolean
}
type Ctx = { salud: Salud | null; enCurso: boolean; refrescar: () => void }
const SaludCtx = createContext<Ctx>({ salud: null, enCurso: false, refrescar: () => {} })
export const useSalud = () => useContext(SaludCtx)

/** Consulta al servidor qué está corriendo y si la última corrida quedó a medias: cada 3 s mientras hay algo corriendo, cada 30 s si no. */
export function SaludProvider({ children }: { children: ReactNode }) {
  const [salud, setSalud] = useState<Salud | null>(null)
  const [tic, setTic] = useState(0)
  const timer = useRef<number>()
  const refrescar = useCallback(() => setTic(t => t + 1), [])
  useEffect(() => {
    let vivo = true
    const tomar = async () => {
      let sig = 30000
      try { const s: Salud = await api('/admin/salud'); if (vivo) { setSalud(s); sig = s.en_curso ? 3000 : 30000 } } catch { /* sin conexión: reintenta */ }
      if (vivo) timer.current = window.setTimeout(tomar, sig)
    }
    tomar()
    return () => { vivo = false; window.clearTimeout(timer.current) }
  }, [tic])
  return <SaludCtx.Provider value={{ salud, enCurso: !!salud?.en_curso, refrescar }}>{children}</SaludCtx.Provider>
}

const cuando = (s: string) => new Date(s).toLocaleString('es-CO', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' })
const fechaCorta = (s: string) => new Date(s.length <= 10 ? s + 'T12:00:00' : s).toLocaleDateString('es-CO', { day: '2-digit', month: 'short' })
const NOMBRE = { etl: 'El ETL (traer datos de Siesa)', motor: 'El motor' }

/** Aviso fijo arriba de todas las pantallas: lo que corre ahora, o que la última corrida quedó a medias y hay que repetirla. */
export function BannerSalud() {
  const { salud } = useSalud(); const { puede } = useYo()
  if (!salud) return null
  const opera = puede('correr_motor')
  if (salud.en_curso) {
    const e = salud.en_curso
    return (
      <Alert severity="info" icon={<CircularProgress size={18} />} sx={{ mb: 1.5 }}>
        <b>Corriendo: {e.tarea}</b> — {e.mensaje} ({e.segundos < 60 ? `${e.segundos} s` : `${Math.floor(e.segundos / 60)} min ${e.segundos % 60} s`}).
        {' '}Puedes cambiar de pantalla o cerrar la ventana: sigue corriendo en el servidor.
      </Alert>)
  }
  if (!opera) return null
  const base = salud.ultimo_motor_ok
    ? `Lo que ves es de la última corrida buena del motor (${fechaCorta(salud.ultimo_motor_ok.fecha)}).`
    : 'Todavía no hay ninguna corrida buena del motor, así que no hay datos para mostrar.'
  const accion = (<Button color="inherit" size="small" variant="outlined" component={RouterLink} to="/motor">Correr de nuevo</Button>)
  if (salud.problemas.length) {
    return (
      <Alert severity="warning" action={accion} sx={{ mb: 1.5 }}>
        <AlertTitle>Una corrida no terminó bien</AlertTitle>
        <Box component="ul" sx={{ m: 0, pl: 2.5 }}>
          {salud.problemas.map(p => (
            <li key={p.tipo}>
              {NOMBRE[p.tipo]} {p.estado === 'interrumpido' ? 'se interrumpió (se reinició el servidor o se perdió la conexión)' : 'falló'} el {cuando(p.inicio)}
              {p.origen === 'auto' ? ' (corrida automática)' : p.usuario ? ` (lanzado por ${p.usuario})` : ''}
              {p.estado === 'error' && p.mensaje ? `: ${p.mensaje.slice(0, 180)}` : '.'}
            </li>))}
        </Box>
        {base} Vuelve a correr <b>ETL + motor completo</b> en Motor DDMRP.
      </Alert>)
  }
  if (salud.sin_corridas || (salud.horas_sin_motor ?? 0) > 30) {
    return (
      <Alert severity="info" action={accion} sx={{ mb: 1.5 }}>
        {salud.sin_corridas ? 'Todavía no se ha corrido el motor.' : `El motor no corre hace ${Math.round(salud.horas_sin_motor!)} horas: la corrida automática de la noche no parece haber ocurrido.`}
        {' '}Corre <b>ETL + motor completo</b> en Motor DDMRP.
      </Alert>)
  }
  return null
}
