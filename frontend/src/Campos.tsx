import { useState } from 'react'
import { TextField, TextFieldProps, Tooltip } from '@mui/material'

/** Campo de selección con tooltip que no estorba: sale ARRIBA y se esconde mientras la lista está abierta
 *  (si no, el globo quedaba pegado al campo y tapaba la primera opción del menú). */
export function CampoSelect({ tip, slotProps, ...p }: TextFieldProps & { tip: string }) {
  const [encima, setEncima] = useState(false)
  const [abierto, setAbierto] = useState(false)
  const sel = (slotProps as any)?.select
  return (
    <Tooltip title={tip} placement="top" open={encima && !abierto} onOpen={() => setEncima(true)} onClose={() => setEncima(false)}>
      <TextField select {...p} slotProps={{ ...slotProps, select: { ...sel, onOpen: () => setAbierto(true), onClose: () => setAbierto(false) } } as any} />
    </Tooltip>)
}
