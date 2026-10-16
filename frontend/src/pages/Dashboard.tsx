import { useEffect, useState } from 'react'
import Tabla from '../Tabla'
import { ColDef } from 'ag-grid-community'
import { Box, Card, CardActionArea, Typography } from '@mui/material'
import { api } from '../api'

const cols: ColDef[] = [
  { field: 'bodega_id', headerName: 'Bodega', filter: true, width: 110 },
  { field: 'producto_id', headerName: 'Producto', filter: true, width: 110 },
  { field: 'descripcion', headerName: 'Descripción', filter: true, flex: 1, minWidth: 200 },
  { field: 'inventario', type: 'numericColumn' },
  { field: 'en_transito', headerName: 'Tránsito', type: 'numericColumn' },
  { field: 'flujo_neto', headerName: 'Flujo neto', type: 'numericColumn' },
  { field: 'tor', headerName: 'TOR', type: 'numericColumn' },
  { field: 'tog_aj', headerName: 'TOG aj.', type: 'numericColumn' },
  { field: 'pct_buffer', headerName: '% buffer', type: 'numericColumn', sort: 'asc' },
  { field: 'cantidad_sugerida', headerName: 'Sugerido', type: 'numericColumn' },
]
const color: Record<string, string> = { ROJA: '#c62828', AMARILLA: '#f9a825', VERDE: '#2e7d32', EXCESO: '#1565c0' }

export default function Dashboard() {
  const [res, setRes] = useState<{ zona: string; n: number }[]>([])
  const [rows, setRows] = useState<any[]>([])
  const [cargando, setCargando] = useState(true)
  useEffect(() => { api('/alertas/resumen').then(setRes).catch(() => {}); api('/alertas/zona-roja').then(setRows).catch(() => {}).finally(() => setCargando(false)) }, [])
  const total = res.reduce((a, r) => a + r.n, 0) || 1
  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', height: '100%', gap: 2 }}>
      <Box sx={{ display: 'grid', gridTemplateColumns: { xs: 'repeat(2, 1fr)', md: 'repeat(4, 1fr)' }, gap: 2 }}>
        {res.map(r => (
          <Card key={r.zona} variant="outlined" sx={{ borderLeft: `6px solid ${color[r.zona] ?? '#999'}` }}>
            <CardActionArea sx={{ p: 1.5 }} disableRipple>
              <Typography variant="caption" color="text.secondary">Zona {r.zona.toLowerCase()}</Typography>
              <Typography variant="h5" sx={{ fontWeight: 700 }}>{r.n.toLocaleString()}</Typography>
              <Typography variant="caption" color="text.secondary">{((r.n / total) * 100).toFixed(1)}% de las combinaciones</Typography>
            </CardActionArea>
          </Card>))}
      </Box>
      <Typography variant="subtitle1" sx={{ fontWeight: 600 }}>Productos en zona roja</Typography>
      <Box className="ag-theme-quartz" sx={{ flex: 1, minHeight: 300 }}>
        <Tabla cargando={cargando} vacio="Sin productos en zona roja" rowData={rows} columnDefs={cols} rowBuffer={20} animateRows={false} defaultColDef={{ resizable: true, sortable: true }} />
      </Box>
    </Box>)
}
