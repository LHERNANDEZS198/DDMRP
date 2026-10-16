import { useEffect, useState } from 'react'
import { Alert, Box, CircularProgress, LinearProgress, Snackbar } from '@mui/material'

/** Mensaje flotante. Si termina en "…" o "..." es una tarea en curso: no se oculta, muestra los segundos transcurridos
 *  y una barra de progreso hasta que el mensaje cambie. "Error..." sale en rojo; el resto en verde y se oculta solo. */
export default function Aviso({ msg, onClose }: { msg: string; onClose: () => void }) {
  const err0 = msg.startsWith('Error')
  const enCurso = !err0 && (msg.includes('…') || /\.\.\.\s*$/.test(msg))
  const err = msg.startsWith('Error')
  const [seg, setSeg] = useState(0)
  useEffect(() => {
    if (!enCurso) return
    setSeg(0); const t0 = Date.now(); const id = setInterval(() => setSeg(Math.floor((Date.now() - t0) / 1000)), 1000)
    return () => clearInterval(id)
  }, [enCurso, msg])
  const tiempo = seg >= 60 ? `${Math.floor(seg / 60)} min ${seg % 60} s` : `${seg} s`
  return (
    <Snackbar open={!!msg} autoHideDuration={enCurso ? null : err ? 15000 : 6000}
      onClose={(_, r) => { if (r !== 'clickaway') onClose() }} anchorOrigin={{ vertical: 'bottom', horizontal: 'center' }}>
      <Alert severity={enCurso ? 'info' : err ? 'error' : 'success'} variant="filled" onClose={enCurso ? undefined : onClose}
        icon={enCurso ? <CircularProgress size={18} color="inherit" /> : undefined} sx={{ maxWidth: 720, minWidth: 320 }}>
        {msg}{enCurso && <> · {tiempo}</>}
        {enCurso && <LinearProgress color="inherit" sx={{ mt: 1, borderRadius: 1, opacity: .7 }} />}
      </Alert>
    </Snackbar>)
}
