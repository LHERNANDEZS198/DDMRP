import { useState } from 'react'
import { Alert, Chip, Stack, Typography } from '@mui/material'
import { NOMBRE_EMPRESA, useEmpresa } from './Empresa'

/** Las reglas se configuran por empresa. Con una sola elegida en la barra se usa esa; con «Ambas» se pide elegir aquí cuál se está editando. */
export function useEmpresaReglas() {
  const { una, opciones } = useEmpresa()
  const posibles = opciones.filter(o => o !== '*')
  const [loc, setLoc] = useState<string>(posibles.includes('05') ? '05' : (posibles[0] ?? '05'))
  const emp = una || (posibles.includes(loc) ? loc : (posibles[0] ?? '05'))
  return { emp, ambas: !una && posibles.length > 1, posibles, setLoc }
}

export function BarraEmpresaReglas({ emp, ambas, posibles, setLoc }: ReturnType<typeof useEmpresaReglas>) {
  return (
    <Stack spacing={1}>
      {ambas && <Alert severity="info" sx={{ py: 0 }}>Tienes «Ambas» elegida arriba, pero las reglas se configuran de a una empresa. Elige cuál vas a ver y cambiar:</Alert>}
      <Stack direction="row" sx={{ gap: 1, alignItems: 'center', flexWrap: 'wrap' }}>
        <Typography variant="body2" sx={{ fontWeight: 600 }}>Reglas de:</Typography>
        {ambas
          ? posibles.map(e => <Chip key={e} label={`${NOMBRE_EMPRESA[e] ?? e} (${e})`} color={e === emp ? 'primary' : 'default'} variant={e === emp ? 'filled' : 'outlined'} onClick={() => setLoc(e)} />)
          : <Chip label={`${NOMBRE_EMPRESA[emp] ?? emp} (${emp})`} color="primary" />}
      </Stack>
    </Stack>)
}
