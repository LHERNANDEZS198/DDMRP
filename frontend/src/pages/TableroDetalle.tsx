import { useEffect, useMemo, useState } from 'react'
import { Alert, Box, Button, ToggleButton, ToggleButtonGroup, Typography } from '@mui/material'
import ArrowBack from '@mui/icons-material/ArrowBack'
import Refresh from '@mui/icons-material/Refresh'
import { ColDef } from 'ag-grid-community'
import { useNavigate, useParams } from 'react-router-dom'
import Tabla from '../Tabla'
import { api } from '../api'
import { useEmpresa } from '../Empresa'

/** Detalle completo (sin tope) de una tarjeta del Control compras: la tabla se filtra, se ordena y se copia a Excel con Ctrl+A / Ctrl+C. */
export default function TableroDetalle() {
  const { tipo } = useParams()
  const nav = useNavigate()
  const [d, setD] = useState<any>(null)
  const [err, setErr] = useState('')
  const [cargando, setCargando] = useState(false)
  const { lista: empresa } = useEmpresa()
  const [vista, setVista] = useState<'item' | 'encabezado'>('item')      // OC abiertas: una fila por línea (item) o una por OC (encabezado, sin items)
  const cargar = () => {
    setCargando(true); setErr('')
    api(`/compras/tablero/detalle/${tipo}?vista=${tipo === 'oc_abiertas' ? vista : 'item'}${empresa.length ? '&empresa=' + empresa.join(',') : ''}`).then(setD).catch(e => { setD(null); setErr(String(e?.message || e)) }).finally(() => setCargando(false))
  }
  useEffect(cargar, [tipo, empresa.join(','), vista])
  const cols: ColDef[] = useMemo(() => (d?.columnas || []).map((c: any): ColDef => c.tipo === 'num'
    ? { field: c.field, headerName: c.headerName, type: 'numericColumn', filter: 'agNumberColumnFilter', width: 140, valueFormatter: (p: any) => p.value == null ? '' : Number(p.value).toLocaleString('es-CO', { maximumFractionDigits: 1 }) }
    : { field: c.field, headerName: c.headerName, filter: true, width: c.field === 'descripcion' || c.field === 'proveedor_nombre' || c.field === 'mensaje' ? 280 : 130 }), [d])

  return (
    <Box sx={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr)', gap: 1 }}>
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 2, flexWrap: 'wrap' }}>
        <Button size="small" startIcon={<ArrowBack />} onClick={() => nav('/compras/tablero')}>Control compras</Button>
        <Typography variant="h6" sx={{ fontWeight: 700 }}>{d?.titulo || 'Detalle'}</Typography>
        {d && <Typography variant="body2" color="text.secondary">{d.filas.length.toLocaleString('es-CO')} filas</Typography>}
        <Button size="small" startIcon={<Refresh />} onClick={cargar} disabled={cargando}>Actualizar</Button>
        {tipo === 'oc_abiertas' && <ToggleButtonGroup size="small" exclusive value={vista} onChange={(_, v) => v && setVista(v)}>
          <ToggleButton value="item">Por ítem (líneas)</ToggleButton><ToggleButton value="encabezado">Por OC (encabezado)</ToggleButton>
        </ToggleButtonGroup>}
      </Box>
      {d?.ayuda && <Typography variant="body2" color="text.secondary">{d.ayuda} Selecciona la tabla (Ctrl+A) y cópiala (Ctrl+C) para pegarla en Excel.</Typography>}
      {err && <Alert severity="error">{err}</Alert>}
      <Box className="ag-theme-quartz" sx={{ height: 'calc(100vh - 220px)', minHeight: 360 }}>
        <Tabla textoCargando="Cargando…" vacio="Nada que mostrar" rowData={d?.filas || []} columnDefs={cols} cargando={cargando} rowBuffer={20} tooltipShowDelay={300}
          defaultColDef={{ resizable: true, sortable: true }} />
      </Box>
    </Box>)
}
