import { AgGridReact, AgGridReactProps } from 'ag-grid-react'

const cargandoHtml = (txt: string) =>
  `<span class="ag-overlay-loading-center" style="padding:14px 22px;font-size:14px;display:flex;align-items:center;gap:10px">` +
  `<span style="width:16px;height:16px;border:2px solid #c5d3b0;border-top-color:#6b8e23;border-radius:50%;display:inline-block;animation:tgiro 0.8s linear infinite"></span>${txt}</span>` +
  `<style>@keyframes tgiro{to{transform:rotate(360deg)}}</style>`

/** AG Grid con mensaje mientras llegan los datos y texto propio cuando de verdad no hay filas. */
export default function Tabla({ cargando, textoCargando = 'Cargando datos…', vacio = 'Sin resultados', ...p }:
  AgGridReactProps & { cargando?: boolean; textoCargando?: string; vacio?: string }) {
  return <AgGridReact {...p} loading={!!cargando}
    overlayLoadingTemplate={cargandoHtml(textoCargando)}
    overlayNoRowsTemplate={`<span style="padding:10px;font-size:14px;color:#666">${vacio}</span>`} />
}
