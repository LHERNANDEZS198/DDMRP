import { useEffect, useMemo, useState } from 'react'
import { AgGridReact } from 'ag-grid-react'
import { CellValueChangedEvent, ColDef } from 'ag-grid-community'
import { api } from '../api'

type Def = { clave: string; label: string; llave: string[]; editable: string[] }

// Pega filas desde Excel (con encabezados). Separador: tab, ; o coma.
function parsear(txt: string): Record<string, string>[] {
  const lineas = txt.split(/\r?\n/).map(l => l.trim()).filter(Boolean)
  if (lineas.length < 2) return []
  const sep = lineas[0].includes('\t') ? '\t' : lineas[0].includes(';') ? ';' : ','
  const cab = lineas[0].split(sep).map(c => c.trim())
  return lineas.slice(1).map(l => {
    const v = l.split(sep).map(c => c.trim())
    return Object.fromEntries(cab.map((c, i) => [c, v[i] ?? '']))
  })
}

export default function Config() {
  const [defs, setDefs] = useState<Def[]>([])
  const [sel, setSel] = useState('pronostico')
  const [rows, setRows] = useState<any[]>([])
  const [msg, setMsg] = useState('')
  const [pegar, setPegar] = useState(false)
  const [txt, setTxt] = useState('')
  const def = defs.find(d => d.clave === sel)

  useEffect(() => { api('/maestros').then(setDefs) }, [])
  const cargar = () => api('/maestros/' + sel).then(setRows).catch(e => setMsg('Error: ' + e.message))
  useEffect(() => { setRows([]); setMsg(''); cargar() }, [sel])

  const cols: ColDef[] = useMemo(() => {
    if (!def) return []
    const llave = def.llave.map(k => ({ field: k, filter: true, pinned: k === def.llave[0] ? ('left' as const) : undefined }))
    const desc: ColDef[] = rows[0] && 'descripcion' in rows[0] ? [{ field: 'descripcion', filter: true, width: 240 }] : []
    const ed = def.editable.map(k => ({ field: k, editable: true, type: 'numericColumn', filter: 'agNumberColumnFilter' }))
    return [...llave, ...desc, ...ed]
  }, [def, rows])

  const onChange = async (e: CellValueChangedEvent) => {
    if (!def) return
    try {
      const llave = Object.fromEntries(def.llave.map(k => [k, String(e.data[k])]))
      await api('/maestros/' + sel, { method: 'PATCH', body: JSON.stringify([{ llave, campo: e.colDef.field, valor: e.newValue === '' ? null : Number(e.newValue) }]) })
      setMsg('Guardado')
    } catch (x: any) { e.node.setDataValue(e.colDef.field!, e.oldValue); setMsg('Error: ' + x.message) }
  }

  const enviar = async () => {
    const filas = parsear(txt)
    if (!filas.length) { setMsg('Pega encabezados y al menos una fila'); return }
    try {
      const r = await api('/maestros/' + sel + '/carga', { method: 'POST', body: JSON.stringify({ filas }) })
      setMsg(`Cargadas ${r.filas} filas`); setPegar(false); setTxt(''); cargar()
    } catch (x: any) { setMsg('Error: ' + x.message) }
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', gap: 8 }}>
      <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
        <select value={sel} onChange={e => setSel(e.target.value)}>
          {defs.map(d => <option key={d.clave} value={d.clave}>{d.label}</option>)}
        </select>
        {sel !== 'factores' && sel !== 'parametros' && <button onClick={() => setPegar(!pegar)}>Pegar desde Excel</button>}
        <small>{msg}</small>
      </div>
      {pegar && def && (
        <div>
          <small>Encabezados requeridos: <b>{[...def.llave, ...def.editable].join(' · ')}</b></small>
          <textarea style={{ width: '100%', height: 120 }} value={txt} onChange={e => setTxt(e.target.value)} />
          <button onClick={enviar}>Cargar</button>
        </div>)}
      <div className="ag-theme-quartz" style={{ flex: 1 }}>
        <AgGridReact rowData={rows} columnDefs={cols} onCellValueChanged={onChange} rowBuffer={20}
          defaultColDef={{ resizable: true, sortable: true }} />
      </div>
    </div>)
}
