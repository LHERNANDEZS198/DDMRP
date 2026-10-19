import { useEffect, useMemo, useRef } from 'react'
import { AgGridReact, AgGridReactProps } from 'ag-grid-react'
import type { CellMouseDownEvent, CellMouseOverEvent, Column, GridApi, GridReadyEvent } from 'ag-grid-community'

const cargandoHtml = (txt: string) =>
  `<span class="ag-overlay-loading-center" style="padding:14px 22px;font-size:14px;display:flex;align-items:center;gap:10px">` +
  `<span style="width:16px;height:16px;border:2px solid #c5d3b0;border-top-color:#6b8e23;border-radius:50%;display:inline-block;animation:tgiro 0.8s linear infinite"></span>${txt}</span>` +
  `<style>@keyframes tgiro{to{transform:rotate(360deg)}}</style>`

type Pos = { r: number; c: number }

/** Una celda al formato del portapapeles de Excel: decimales con coma (Excel en español), y entre comillas lo que lleve tab, salto o comillas. */
const celdaTsv = (v: unknown): string => {
  if (v == null) return ''
  if (typeof v === 'number') return Number.isInteger(v) ? String(v) : String(v).replace('.', ',')
  const s = v instanceof Date ? v.toISOString().slice(0, 10) : String(v)
  return /[\t\n\r"]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s
}

/** AG Grid con mensaje mientras llegan los datos, texto propio cuando de verdad no hay filas y selección de celdas como en Excel:
 *  clic y arrastre (o Mayús+clic) para marcar un bloque, Ctrl+A para todo y Ctrl+C para copiarlo (se pega en Excel con sus columnas y filas).
 *  Si se selecciona todo con Ctrl+A, la copia incluye los encabezados. La selección por rangos de AG Grid es de pago, por eso se hace aquí. */
export default function Tabla({ cargando, textoCargando = 'Cargando datos…', vacio = 'Sin resultados', onGridReady, onCellMouseDown, onCellMouseOver, onRowDataUpdated, defaultColDef, ...p }:
  AgGridReactProps & { cargando?: boolean; textoCargando?: string; vacio?: string }) {
  const api = useRef<GridApi | null>(null)
  const raiz = useRef<HTMLDivElement>(null)
  const ancla = useRef<Pos | null>(null)
  const fin = useRef<Pos | null>(null)
  const arrastrando = useRef(false)
  const todo = useRef(false)

  const columnas = (): Column[] => api.current?.getAllDisplayedColumns() ?? []
  const refrescar = () => api.current?.refreshCells({ force: true, suppressFlash: true })
  const limpiar = () => { if (ancla.current) { ancla.current = fin.current = null; todo.current = false; refrescar() } }

  // el resaltado va como regla de clase de cada columna (la que defina una columna propia la reemplaza: no pasa en estas pantallas)
  const colDefBase = useMemo(() => ({
    ...defaultColDef,
    cellClassRules: {
      ...defaultColDef?.cellClassRules,
      'celda-rango': (q: { node: { rowIndex: number | null }; column: Column }) => {
        const a = ancla.current, f = fin.current
        if (!a || !f || q.node.rowIndex == null) return false
        const c = columnas().indexOf(q.column), r = q.node.rowIndex
        return r >= Math.min(a.r, f.r) && r <= Math.max(a.r, f.r) && c >= Math.min(a.c, f.c) && c <= Math.max(a.c, f.c)
      },
    },
  }), [defaultColDef])

  const posDe = (e: CellMouseDownEvent | CellMouseOverEvent): Pos | null => {
    const c = columnas().indexOf(e.column as Column)
    return e.rowIndex == null || c < 0 ? null : { r: e.rowIndex, c }
  }

  const alBajar = (e: CellMouseDownEvent) => {
    onCellMouseDown?.(e)
    const ev = e.event as MouseEvent | null
    if (!ev || ev.button !== 0 || (ev.target as HTMLElement | null)?.closest('input, button, a, .ag-checkbox')) return
    const pos = posDe(e); if (!pos) return
    todo.current = false
    ancla.current = ev.shiftKey && ancla.current ? ancla.current : pos
    fin.current = pos
    arrastrando.current = true
    refrescar()
  }
  const alPasar = (e: CellMouseOverEvent) => {
    onCellMouseOver?.(e)
    if (!arrastrando.current) return
    const pos = posDe(e); if (!pos || (fin.current?.r === pos.r && fin.current?.c === pos.c)) return
    fin.current = pos; refrescar()
  }

  /** Texto TSV de lo seleccionado (o undefined si no hay selección). */
  const texto = (): string | undefined => {
    const g = api.current, a = ancla.current, f = fin.current
    if (!g || !a || !f) return
    const cols = columnas().slice(Math.min(a.c, f.c), Math.max(a.c, f.c) + 1).filter(c => c.getColDef().field || c.getColDef().valueGetter)
    const lineas: string[] = []
    if (todo.current) lineas.push(cols.map(c => celdaTsv(c.getColDef().headerName ?? c.getColDef().field ?? '')).join('\t'))
    for (let r = Math.min(a.r, f.r); r <= Math.max(a.r, f.r); r++) {
      const nodo = g.getDisplayedRowAtIndex(r); if (!nodo) continue
      lineas.push(cols.map(c => celdaTsv(g.getCellValue({ rowNode: nodo, colKey: c }))).join('\t'))
    }
    return lineas.join('\n')
  }

  useEffect(() => {
    const el = raiz.current?.firstElementChild as HTMLElement | null
    if (!el) return
    const copiar = (e: ClipboardEvent) => {
      if (api.current?.getEditingCells().length) return          // editando una celda: el Ctrl+C normal del texto
      const t = texto(); if (t === undefined) return
      e.clipboardData?.setData('text/plain', t); e.preventDefault()
    }
    const teclas = (e: KeyboardEvent) => {
      if (!(e.ctrlKey || e.metaKey) || e.key.toLowerCase() !== 'a' || api.current?.getEditingCells().length) return
      const filas = api.current?.getDisplayedRowCount() ?? 0, cols = columnas().length
      if (!filas || !cols) return
      e.preventDefault()
      ancla.current = { r: 0, c: 0 }; fin.current = { r: filas - 1, c: cols - 1 }; todo.current = true; refrescar()
    }
    const soltar = () => { arrastrando.current = false }
    const fuera = (e: MouseEvent) => { if (!el.contains(e.target as Node)) limpiar() }
    el.addEventListener('copy', copiar); el.addEventListener('keydown', teclas)
    document.addEventListener('mouseup', soltar); document.addEventListener('mousedown', fuera)
    return () => { el.removeEventListener('copy', copiar); el.removeEventListener('keydown', teclas); document.removeEventListener('mouseup', soltar); document.removeEventListener('mousedown', fuera) }
  }, [])

  return (
    <div ref={raiz} style={{ display: 'contents' }}>
      <AgGridReact {...p} defaultColDef={colDefBase} loading={!!cargando}
        onGridReady={(e: GridReadyEvent) => { api.current = e.api; onGridReady?.(e) }}
        onCellMouseDown={alBajar} onCellMouseOver={alPasar}
        onRowDataUpdated={e => { limpiar(); onRowDataUpdated?.(e) }}
        overlayLoadingTemplate={cargandoHtml(textoCargando)}
        overlayNoRowsTemplate={`<span style="padding:10px;font-size:14px;color:#666">${vacio}</span>`} />
    </div>)
}
