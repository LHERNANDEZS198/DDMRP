import { Alert, Snackbar } from '@mui/material'
/** Mensaje simple: "Error: ..." sale en rojo, el resto en verde. Vacio = oculto. */
export default function Aviso({ msg, onClose }: { msg: string; onClose: () => void }) {
  const err = msg.startsWith('Error')
  return (
    <Snackbar open={!!msg} autoHideDuration={err ? 10000 : 5000} onClose={onClose} anchorOrigin={{ vertical: 'bottom', horizontal: 'center' }}>
      <Alert severity={err ? 'error' : 'success'} variant="filled" onClose={onClose} sx={{ maxWidth: 700 }}>{msg}</Alert>
    </Snackbar>)
}
