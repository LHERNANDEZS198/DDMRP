import { useEffect, useState } from 'react'
import { AgGridReact } from 'ag-grid-react'
import { CellValueChangedEvent, ColDef } from 'ag-grid-community'
import { api } from '../api'

const ed = (field: string, extra: ColDef = {}): ColDef => ({ field, editable: true, type: 'numericColumn', ...extra })
const cols: ColDef[] = [
  { field: 'producto_id', headerName: 'Producto', filter: true, pinned: 'left' },
  { field: 'descripcion', filter: true, width: 220 },
  { field: 'bodega_id', headerName: 'Bodega', filter: true },
  ed('lead_time_dias'), ed('factor_lead_time'), ed('factor_variabilidad'),
  ed('factor_zona_roja'), ed('factor_zona_amarilla'), ed('factor_zona_verde'),
  ed('ciclo_pedido_dias'), ed('cantidad_minima'), ed('multiplo_empaque'), ed('ventana_adu_dias'),
  { field: 'clase_abc', editable: true, cellEditor: 'agSelectCellEditor', cellEditorParams: { values: ['A', 'B', 'C'] } },
  { field: 'clase_xyz', editable: true, cellEditor: 'agSelectCellEditor', cellEditorParams: { values: ['X', 'Y', 'Z'] } },
]

export default function Config() {
  const [rows, setRows] = useState<any[]>([])
  const [msg, setMsg] = useState('')
  useEffect(() => { api('/config/items').then(setRows) }, [])
  const onChange = async (e: CellValueChangedEvent) => {
    try {
      await api('/config/items', { method: 'PATCH', body: JSON.stringify([{
        producto_id: e.data.producto_id, bodega_id: e.data.bodega_id, campo: e.colDef.field, valor: e.newValue }]) })
      setMsg('Guardado')
    } catch (x: any) { e.node.setDataValue(e.colDef.field!, e.oldValue); setMsg('Error: ' + x.message) }
  }
  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      <small>{msg}</small>
      <div className="ag-theme-quartz" style={{ flex: 1 }}>
        <AgGridReact rowData={rows} columnDefs={cols} onCellValueChanged={onChange} rowBuffer={20}
          defaultColDef={{ resizable: true, sortable: true }} />
      </div>
    </div>)
}
