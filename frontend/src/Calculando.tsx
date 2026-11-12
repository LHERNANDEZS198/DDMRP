import { useEffect, useState } from 'react'
import { Alert, CircularProgress, LinearProgress } from '@mui/material'

/** Letrero fijo de «estoy calculando» para pantallas cuyos datos tardan (la tendencia del Control, por ejemplo): no se ve nada hasta que llegan y de repente cambian.
 *  Muestra los segundos transcurridos y una barra; desaparece solo cuando `activo` pasa a false. */
export default function Calculando({ activo, texto = 'Calculando…' }: { activo: boolean; texto?: string }) {
  const [seg, setSeg] = useState(0)
  useEffect(() => {
    if (!activo) return
    setSeg(0); const t0 = Date.now(); const id = setInterval(() => setSeg(Math.floor((Date.now() - t0) / 1000)), 1000)
    return () => clearInterval(id)
  }, [activo])
  if (!activo) return null
  const t = seg >= 60 ? `${Math.floor(seg / 60)} min ${seg % 60} s` : `${seg} s`
  return (
    <Alert severity="info" icon={<CircularProgress size={16} />} sx={{ py: 0, flexShrink: 0, '& .MuiAlert-message': { width: '100%' } }}>
      {texto} · {t}{seg >= 20 && ' (con muchos datos puede tardar; los resultados anteriores se muestran atenuados)'}
      <LinearProgress sx={{ mt: .5, borderRadius: 1 }} />
    </Alert>)
}
