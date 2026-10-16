import { useEffect, useState } from 'react'
import { AgGridReact } from 'ag-grid-react'
import { ColDef, GridApi } from 'ag-grid-community'
import { api, descargar } from '../api'

const cols: ColDef[] = [
  { checkboxSelection: true, headerCheckboxSelection: true, width: 50, pinned: 'left' },
  { field: 'bodega_id', headerName: 'Bodega', filter: true },
  { field: 'producto_id', headerName: 'Producto', filter: true },
  { field: 'descripcion', flex: 1, filter: true },
  { field: 'zona', filter: true },
  { field: 'inventario', type: 'numericColumn' },
  { field: 'en_transito', headerName: 'Transito', type: 'numericColumn' },
  { field: 'tog_aj', headerName: 'TOG aj.', type: 'numericColumn' },
  { field: 'unidad_despacho', headerName: 'Und. desp.', type: 'numericColumn' },
  { field: 'vectorizacion', headerName: 'Derrame', type: 'numericColumn' },
  { field: 'cantidad_sugerida', headerName: 'Sugerido', type: 'numericColumn' },
  { field: 'cantidad_aprobada', headerName: 'A enviar', editable: true, type: 'numericColumn',
    valueGetter: p => p.data.cantidad_aprobada ?? p.data.cantidad_sugerida,
    valueSetter: p => { p.data.cantidad_aprobada = Number(p.newValue); return true } },
]

export default function Despacho() {
  const [rows, setRows] = useState<any[]>([])
  const [grid, setGrid] = useState<GridApi | null>(null)
  const [msg, setMsg] = useState('')
  const [notas, setNotas] = useState('')
  const [consec, setConsec] = useState(1)
  const [marcar, setMarcar] = useState(false)
  const cargar = () => api('/despacho/matriz').then(setRows)
  useEffect(() => { cargar() }, [])
  const aprobar = async () => {
    const sel = grid?.getSelectedRows() ?? []
    if (!sel.length) { setMsg('Selecciona filas'); return }
    try {
      await api('/despacho/aprobar', { method: 'POST', body: JSON.stringify(sel.map((r: any) => ({
        ejecucion_id: r.ejecucion_id, producto_id: r.producto_id, bodega_id: r.bodega_id,
        cantidad_aprobada: r.cantidad_aprobada ?? r.cantidad_sugerida, aprobar: true }))) })
      setMsg(`Aprobadas ${sel.length}`); cargar()
    } catch (x: any) { setMsg('Error: ' + x.message) }
  }
  const plano = async () => {
    try {
      const r = await descargar('/despacho/exportar-plano', { notas: notas || null, consec_inicial: consec, marcar_enviadas: marcar })
      setMsg(`Descargado ${r.nombre}` + (r.derivado ? ` · centro de operacion deducido para: ${r.derivado}` : ''))
      if (marcar) cargar()
    } catch (x: any) { setMsg('Error: ' + x.message) }
  }
  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', gap: 8 }}>
      <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
        <button onClick={aprobar}>Aprobar seleccionados</button>
        <input style={{ width: 300 }} placeholder="Nota (ej. ABASTECIMIENTO DEL 15 DE OCTUBRE DÍA 4)" value={notas} onChange={e => setNotas(e.target.value)} />
        <label>Consecutivo inicial <input type="number" style={{ width: 70 }} min={1} value={consec} onChange={e => setConsec(Number(e.target.value))} /></label>
        <label><input type="checkbox" checked={marcar} onChange={e => setMarcar(e.target.checked)} /> marcar como enviadas</label>
        <button onClick={plano}>Generar archivo plano Siesa</button>
        <button disabled title="Fase 3">Enviar a Siesa (web service)</button> <small>{msg}</small></div>
      <div className="ag-theme-quartz" style={{ flex: 1 }}>
        <AgGridReact rowData={rows} columnDefs={cols} rowSelection="multiple" rowBuffer={20}
          onGridReady={e => setGrid(e.api)} defaultColDef={{ resizable: true, sortable: true }} />
      </div>
    </div>)
}
