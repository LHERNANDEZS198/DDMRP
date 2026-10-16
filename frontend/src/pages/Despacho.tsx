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
  // Corrida del dia: DIA de abastecimiento + tiendas elegidas (se pueden poner o quitar antes de generar)
  const [dias, setDias] = useState<{ dia: number; bodegas: string[] }[]>([])
  const [todas, setTodas] = useState<string[]>([])
  const [dia, setDia] = useState('')            // '' = sin DIA
  const [filtrar, setFiltrar] = useState(false) // false = todas las tiendas
  const [tiendas, setTiendas] = useState<string[]>([])
  const [nueva, setNueva] = useState('')
  useEffect(() => { api('/despacho/dias').then(x => { setDias(x.dias); setTodas(x.bodegas) }) }, [])
  const elegirDia = (v: string) => {
    setDia(v)
    if (v === '') { setFiltrar(false); setTiendas([]); return }
    setFiltrar(true); setTiendas(dias.find(d => String(d.dia) === v)?.bodegas ?? [])
  }
  const quitar = (b: string) => { setFiltrar(true); setTiendas(t => t.filter(x => x !== b)) }
  const poner = (b: string) => { if (!b) return; setFiltrar(true); setTiendas(t => t.includes(b) ? t : [...t, b].sort()); setNueva('') }
  const cargar = () => api('/despacho/matriz' + (filtrar ? '?bodegas=' + encodeURIComponent(tiendas.join(',') || '-') : '')).then(setRows)
  useEffect(() => { cargar() }, [filtrar, tiendas.join(',')])
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
      const r = await descargar('/despacho/exportar-plano', { notas: notas || null, consec_inicial: consec, marcar_enviadas: marcar,
        bodegas: filtrar ? tiendas : null, dia: dia ? Number(dia) : null })
      setMsg(`Descargado ${r.nombre}` + (r.derivado ? ` · centro de operacion deducido para: ${r.derivado}` : ''))
      if (marcar) cargar()
    } catch (x: any) { setMsg('Error: ' + x.message) }
  }
  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', gap: 8 }}>
      <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
        <b>Corrida:</b>
        <select value={dia} onChange={e => elegirDia(e.target.value)}>
          <option value="">Todas las tiendas</option>
          {dias.map(d => <option key={d.dia} value={d.dia}>DIA {d.dia} ({d.bodegas.length} tiendas)</option>)}
        </select>
        {filtrar && tiendas.map(b => (
          <span key={b} style={{ background: '#e8f0fe', borderRadius: 10, padding: '1px 8px' }}>
            {b} <a href="#" style={{ textDecoration: 'none' }} title="Quitar de esta corrida" onClick={e => { e.preventDefault(); quitar(b) }}>×</a>
          </span>))}
        <select value={nueva} onChange={e => poner(e.target.value)}>
          <option value="">+ agregar tienda…</option>
          {todas.filter(b => !tiendas.includes(b)).map(b => <option key={b} value={b}>{b}</option>)}
        </select>
        {filtrar && <button onClick={() => { setDia(''); setFiltrar(false); setTiendas([]) }}>Ver todas</button>}
      </div>
      <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
        <button onClick={aprobar}>Aprobar seleccionados</button>
        <input style={{ width: 300 }} placeholder={`Nota (por defecto: ABASTECIMIENTO DEL <dia> DE <MES>${dia ? ` DÍA ${dia}` : ''})`} value={notas} onChange={e => setNotas(e.target.value)} />
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
