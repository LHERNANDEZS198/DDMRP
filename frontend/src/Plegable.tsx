import { ReactNode, useState } from 'react'
import { Box, Button, Collapse } from '@mui/material'
import ExpandLess from '@mui/icons-material/ExpandLess'
import ExpandMore from '@mui/icons-material/ExpandMore'

/** Bloque plegable para los filtros y acciones que van arriba de una tabla: al ocultarlo la tabla gana el espacio.
 *  Recuerda (por navegador) si lo dejaste abierto o cerrado. `resumen` se muestra en la barra cuando está plegado (totales, filtros activos…). */
export default function Plegable({ id, titulo = 'filtros y acciones', resumen, inicial = true, children }:
  { id: string; titulo?: string; resumen?: ReactNode; inicial?: boolean; children: ReactNode }) {
  const llave = `plegable:${id}`
  const [abierto, setAbierto] = useState<boolean>(() => {
    try { const v = localStorage.getItem(llave); return v == null ? inicial : v === '1' } catch { return inicial }
  })
  const cambiar = () => setAbierto(a => {
    const n = !a
    try { localStorage.setItem(llave, n ? '1' : '0') } catch { /* sin almacenamiento: solo vale en esta sesión */ }
    return n
  })
  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', gap: 0.5, flexShrink: 0, minWidth: 0 }}>
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, flexWrap: 'wrap' }}>
        <Button size="small" color="inherit" onClick={cambiar} aria-expanded={abierto} startIcon={abierto ? <ExpandLess /> : <ExpandMore />}
          sx={{ textTransform: 'none', color: 'text.secondary' }}>{abierto ? `Ocultar ${titulo}` : `Mostrar ${titulo}`}</Button>
        {!abierto && resumen}
      </Box>
      <Collapse in={abierto}>
        <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1.5 }}>{children}</Box>
      </Collapse>
    </Box>
  )
}
