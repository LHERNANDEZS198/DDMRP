import { ReactNode, useState } from 'react'
import { IconButton, Popover, Tooltip, Typography } from '@mui/material'
import InfoOutlined from '@mui/icons-material/InfoOutlined'

/** Reemplaza un recuadro azul informativo por una «i» pequeña: el mensaje se ve al hacer clic (o al pasar el mouse, en el tooltip corto). */
export default function AvisoInfo({ children, titulo = 'Más información' }: { children: ReactNode; titulo?: string }) {
  const [ancla, setAncla] = useState<HTMLElement | null>(null)
  return (
    <>
      <Tooltip title={titulo} placement="top">
        <IconButton size="small" color="info" aria-label={titulo} onClick={e => setAncla(e.currentTarget)}>
          <InfoOutlined fontSize="small" />
        </IconButton>
      </Tooltip>
      <Popover open={!!ancla} anchorEl={ancla} onClose={() => setAncla(null)} anchorOrigin={{ vertical: 'bottom', horizontal: 'left' }}>
        <Typography component="div" variant="body2" sx={{ p: 1.5, maxWidth: 520, whiteSpace: 'normal' }}>{children}</Typography>
      </Popover>
    </>)
}
