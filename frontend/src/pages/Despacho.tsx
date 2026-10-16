import { useEffect, useState } from 'react'
import { AgGridReact } from 'ag-grid-react'
import { ColDef } from 'ag-grid-community'
import { api } from '../api'

const cols: ColDef[] = [
  { checkboxSelection: true, headerCheckboxSelection: true, width: 50, pinned: 'left' },
  { field: 'bodega_id', headerName: 'Bodega', filter: true },
  { field: 'producto_id', headerName: 'Producto', filter: true },
  { field: 'descripcion', flex: 1, filter: true },
  { field: 'zona', filter: true },
  { field: 'inventario', type: 'numericColumn' },
  { field: 'en_transito', type: 'numericColumn' },
  { field: 'tog', type: 'numericColumn' },
  { field: 'cantidad_sugerida', headerName: 'Sugerido', type: 'numericColumn' },
  { field: 'cantidad_aprobada', headerName: 'A enviar', editable: true, type: 'numericColumn',
    valueGetter: p => p.data.cantidad_aprobada ?? p.data.cantidad_sugerida,
    valueSetter: p => { p.data.cantidad_aprobada = Number(p.newValue); return true } },
]

export default function Despacho() {
  const [rows, setRows] = useState<any[]>([])
  const [api_, setApi] = useState<any>(null)
  const cargar = () => api('/despacho/matriz').then(setRows)
  useEffect(() => { cargar() }, [])
  const aprobar = async () => {
    const sel = api_.getSelectedRows()
    await api('/despacho/aprobar', { method: 'POST', body: JSON.stringify(sel.map((r: any) => ({
      ejecucion_id: r.ejecucion_id, producto_id: r.producto_id, bodega_id: r.bodega_id,
      cantidad_aprobada: r.cantidad_aprobada ?? r.cantidad_sugerida, aprobar: true }))) })
    cargar()
  }
  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', gap: 8 }}>
      <div><button onClick={aprobar}>Aprobar seleccionados</button>{' '}
        <button disabled title="Fase 2">Generar archivo plano Siesa</button>{' '}
        <button disabled title="Fase 3">Enviar a Siesa (web service)</button></div>
      <div className="ag-theme-quartz" style={{ flex: 1 }}>
        <AgGridReact rowData={rows} columnDefs={cols} rowSelection="multiple" rowBuffer={20}
          onGridReady={e => setApi(e.api)} defaultColDef={{ resizable: true, sortable: true }} />
      </div>
    </div>)
}
