import { useEffect, useState } from 'react'
import { AgGridReact } from 'ag-grid-react'
import { ColDef } from 'ag-grid-community'
import { api } from '../api'

const cols: ColDef[] = [
  { field: 'bodega_id', headerName: 'Bodega', filter: true },
  { field: 'producto_id', headerName: 'Producto', filter: true },
  { field: 'descripcion', headerName: 'Descripcion', filter: true, flex: 1 },
  { field: 'inventario', type: 'numericColumn' },
  { field: 'en_transito', headerName: 'Transito', type: 'numericColumn' },
  { field: 'flujo_neto', headerName: 'Flujo neto', type: 'numericColumn' },
  { field: 'tor', headerName: 'TOR', type: 'numericColumn' },
  { field: 'tog_aj', headerName: 'TOG aj.', type: 'numericColumn' },
  { field: 'pct_buffer', headerName: '% buffer', type: 'numericColumn', sort: 'asc' },
  { field: 'cantidad_sugerida', headerName: 'Sugerido', type: 'numericColumn' },
]

export default function Dashboard() {
  const [res, setRes] = useState<{ zona: string; n: number }[]>([])
  const [rows, setRows] = useState<any[]>([])
  useEffect(() => { api('/alertas/resumen').then(setRes); api('/alertas/zona-roja').then(setRows) }, [])
  const color: Record<string, string> = { ROJA: '#c62828', AMARILLA: '#f9a825', VERDE: '#2e7d32', EXCESO: '#1565c0' }
  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', gap: 8 }}>
      <div style={{ display: 'flex', gap: 12 }}>
        {res.map(r => <div key={r.zona} style={{ borderLeft: `6px solid ${color[r.zona]}`, padding: '4px 12px', background: '#fafafa' }}>
          <div style={{ fontSize: 12 }}>{r.zona}</div><b style={{ fontSize: 22 }}>{r.n.toLocaleString()}</b></div>)}
      </div>
      <div className="ag-theme-quartz" style={{ flex: 1 }}>
        <AgGridReact rowData={rows} columnDefs={cols} rowBuffer={20} animateRows={false} />
      </div>
    </div>)
}
