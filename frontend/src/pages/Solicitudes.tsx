import { useEffect, useMemo, useState } from 'react'
import { ColDef } from 'ag-grid-community'
import { Box, Button, Chip, Tab, Tabs, TextField, Typography, Alert } from '@mui/material'
import Tabla from '../Tabla'
import { api } from '../api'

const COLOR: Record<string, string> = { pendiente: '#f9a825', aprobada: '#2e7d32', rechazada: '#c62828', cancelada: '#9e9e9e' }

/** Solicitudes de NxP / compras: pendientes y resueltas. Quien aprueba selecciona y aprueba o rechaza (al aprobar se aplica solo); quien solicita ve las suyas. */
export default function Solicitudes() {
  const [estado, setEstado] = useState('pendiente')
  const [d, setD] = useState<{ filas: any[]; puede_aprobar: boolean; puede_solicitar: boolean }>({ filas: [], puede_aprobar: false, puede_solicitar: false })
  const [sel, setSel] = useState<any[]>([]); const [nota, setNota] = useState('')
  const [cargando, setCargando] = useState(false); const [err, setErr] = useState(''); const [ok, setOk] = useState('')
  const cargar = () => {
    setCargando(true); setErr('')
    api(`/solicitudes?estado=${estado}`).then((r: any) => { setD(r); setSel([]) }).catch((e: any) => setErr(e.message)).finally(() => setCargando(false))
  }
  useEffect(cargar, [estado])
  useEffect(() => { api('/solicitudes/vistas', { method: 'POST' }).then(() => window.dispatchEvent(new Event('solicitudes-cambio'))).catch(() => {}) }, [])
  const pend = sel.filter(s => s.estado === 'pendiente')
  const accionar = async (accion: 'aprobar' | 'rechazar' | 'cancelar') => {
    setErr(''); setOk('')
    try {
      const r: any = await api(accion === 'cancelar' ? '/solicitudes/cancelar' : '/solicitudes/resolver', { method: 'POST', body: JSON.stringify({ ids: pend.map(s => s.id), accion, nota }) })
      setOk(accion === 'aprobar' ? `${r.resueltas} aprobadas y aplicadas` : accion === 'rechazar' ? `${r.resueltas} rechazadas` : `${r.canceladas} canceladas`)
      setNota(''); cargar(); window.dispatchEvent(new Event('solicitudes-cambio'))
    } catch (e: any) { setErr(e.message) }
  }
  const cols: ColDef[] = useMemo(() => [
    { field: 'id', headerName: '#', width: 80, pinned: 'left', checkboxSelection: true, headerCheckboxSelection: true },
    { field: 'estado', headerName: 'Estado', width: 110, filter: true, cellRenderer: (p: any) => <Chip size="small" label={p.value} sx={{ bgcolor: COLOR[p.value] ?? '#999', color: '#fff', height: 20, fontSize: 11 }} /> },
    { field: 'fecha_solicitud', headerName: 'Solicitada', width: 140 },
    { field: 'solicitante', headerName: 'Solicitante', width: 120, filter: true },
    { field: 'empresa', headerName: 'Empresa', width: 90, filter: true },
    { field: 'tipo', headerName: 'Tipo', width: 95, filter: true, valueFormatter: p => p.value === 'nxp' ? 'NxP' : 'Compras' },
    { field: 'accion', headerName: 'Acción', width: 95, filter: true, valueFormatter: p => p.value === 'agregar' ? 'Agregar' : 'Quitar' },
    { field: 'nivel', headerName: 'Nivel', width: 110, filter: true, valueFormatter: p => ({ laboratorio: 'Laboratorio', item: 'Item', tienda_item: 'Tienda-item' } as any)[p.value] ?? p.value },
    { field: 'laboratorio', headerName: 'Lab.', width: 90, filter: true },
    { field: 'bodega_id', headerName: 'Tienda', width: 90, filter: true },
    { field: 'producto_id', headerName: 'Item', width: 100, filter: true },
    { field: 'descripcion', headerName: 'Descripción', width: 240, filter: true },
    { field: 'motivo', headerName: 'Motivo', width: 220 },
    { field: 'resuelto_por', headerName: 'Resuelta por', width: 120 },
    { field: 'fecha_resuelto', headerName: 'Resuelta', width: 140 },
    { field: 'nota_resolucion', headerName: 'Nota', width: 200 },
    { field: 'aplicado', headerName: 'Qué se aplicó', width: 280 },
  ], [])
  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', height: '100%', gap: 1.5, minHeight: 500 }}>
      <Typography variant="h6" sx={{ fontWeight: 700 }}>Solicitudes de NxP / compras</Typography>
      <Tabs value={estado} onChange={(_, v) => setEstado(v)} sx={{ minHeight: 36 }}>
        <Tab value="pendiente" label="Pendientes" sx={{ minHeight: 36 }} /><Tab value="aprobada" label="Aprobadas" sx={{ minHeight: 36 }} />
        <Tab value="rechazada" label="Rechazadas" sx={{ minHeight: 36 }} /><Tab value="todas" label="Todas" sx={{ minHeight: 36 }} />
      </Tabs>
      {err && <Alert severity="error" onClose={() => setErr('')}>{err}</Alert>}
      {ok && <Alert severity="success" onClose={() => setOk('')}>{ok}</Alert>}
      <Box sx={{ display: 'flex', gap: 1, alignItems: 'center', flexWrap: 'wrap' }}>
        {d.puede_aprobar && <>
          <TextField size="small" label="Nota (opcional)" value={nota} onChange={e => setNota(e.target.value)} sx={{ minWidth: 260 }} />
          <Button size="small" variant="contained" color="success" disabled={!pend.length} onClick={() => accionar('aprobar')}>Aprobar y aplicar ({pend.length})</Button>
          <Button size="small" variant="outlined" color="error" disabled={!pend.length} onClick={() => accionar('rechazar')}>Rechazar ({pend.length})</Button>
        </>}
        {!d.puede_aprobar && d.puede_solicitar && <Button size="small" variant="outlined" disabled={!pend.length} onClick={() => accionar('cancelar')}>Cancelar las marcadas ({pend.length})</Button>}
        <Typography variant="caption" color="text.secondary">{d.filas.length.toLocaleString()} solicitudes{d.puede_aprobar ? '' : ' tuyas'}</Typography>
      </Box>
      <Box sx={{ flex: 1, minHeight: 300 }}>
        <Tabla memoria="solicitudes" cargando={cargando} vacio="No hay solicitudes en esta vista" rowData={d.filas} columnDefs={cols} rowSelection="multiple" suppressRowClickSelection
          onSelectionChanged={e => setSel(e.api.getSelectedRows())} defaultColDef={{ resizable: true, sortable: true }} />
      </Box>
    </Box>)
}
